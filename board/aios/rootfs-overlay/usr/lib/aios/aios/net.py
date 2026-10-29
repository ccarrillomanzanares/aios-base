"""aios net — red cableada y wifi.

El wifi es de iwd: el estado y el escaneo se leen por D-Bus con busctl
(salida JSON, sin interpretar texto); para conectar se usa iwctl, que lleva
el agente que entrega la contraseña a iwd. aios está en wheel, que la
política D-Bus de iwd deja hablar con él.
"""
import getpass
import json
import os
import re
import socket
import subprocess
import sys
import time

from .result import Result, fail

IWD = "net.connman.iwd"


# --- utilidades ----------------------------------------------------------------

def run(args, timeout=15):
    try:
        # Sin entrada: iwctl no debe quedarse esperando una contraseña tecleada
        p = subprocess.run(args, capture_output=True, text=True, timeout=timeout,
                           stdin=subprocess.DEVNULL)
        return p.returncode, p.stdout, p.stderr
    except (OSError, subprocess.TimeoutExpired) as e:
        return 1, "", str(e)


def ip_json(*args):
    rc, out, _ = run(["ip", "-j", *args])
    try:
        return json.loads(out) if rc == 0 and out.strip() else []
    except ValueError:
        return []


def unwrap(v):
    """Quita las capas {"type", "data"} de la salida JSON de busctl."""
    if isinstance(v, dict) and set(v) == {"type", "data"}:
        return unwrap(v["data"])
    if isinstance(v, dict):
        return {k: unwrap(x) for k, x in v.items()}
    if isinstance(v, list):
        return [unwrap(x) for x in v]
    return v


def busctl(*args, timeout=15):
    rc, out, err = run(["busctl", "--system", "--json=short", *args], timeout=timeout)
    if rc != 0:
        return None
    try:
        return unwrap(json.loads(out)) if out.strip() else {}
    except ValueError:
        return None


# --- iwd -------------------------------------------------------------------------

def iwd_objects():
    """{ruta: {interfaz: {propiedad: valor}}} o None si iwd no responde."""
    r = busctl("call", IWD, "/", "org.freedesktop.DBus.ObjectManager", "GetManagedObjects")
    if r is None:
        return None
    # "call" devuelve la lista de valores de retorno; aquí, uno: el diccionario
    return r[0] if isinstance(r, list) and r and isinstance(r[0], dict) else {}


def wifi_devices(objs):
    devs = []
    for path, ifaces in sorted(objs.items()):
        dev = ifaces.get(IWD + ".Device")
        if not dev:
            continue
        st = ifaces.get(IWD + ".Station") or {}
        net = objs.get(st.get("ConnectedNetwork", ""), {}).get(IWD + ".Network", {})
        devs.append({"path": path, "name": dev.get("Name"), "powered": dev.get("Powered"),
                     "mode": dev.get("Mode"), "state": st.get("State"),
                     "scanning": st.get("Scanning", False), "ssid": net.get("Name"),
                     "station": bool(st)})
    return devs


def pick_device(objs, name=None):
    devs = wifi_devices(objs)
    if name:
        devs = [d for d in devs if d["name"] == name]
    else:  # la de modo estación antes que una en modo punto de acceso
        devs.sort(key=lambda d: d["mode"] != "station")
    return devs[0] if devs else None


def ensure_powered(dev):
    if dev["powered"]:
        return True
    busctl("set-property", IWD, dev["path"], IWD + ".Device", "Powered", "b", "true")
    for _ in range(20):
        objs = iwd_objects() or {}
        d = pick_device(objs, dev["name"])
        if d and d["powered"] and d["station"]:
            dev.update(d)
            return True
        time.sleep(0.25)
    return False


def no_wifi():
    if iwd_objects() is None:
        return fail("WIFI_NO_SERVICE", "Run: systemctl status iwd",
                    text="Wifi service (iwd) is not responding.")
    return fail("WIFI_NO_DEVICE", "Check the wifi card with: aios-diag",
                text="No wifi device found.")


# --- estado ------------------------------------------------------------------------

def internet_check():
    """DNS y salida a Internet, con tiempos cortos (no debe colgar la barra)."""
    dns = inet = False
    try:
        socket.setdefaulttimeout(3)
        addr = socket.getaddrinfo("ccmai.org", 443, proto=socket.IPPROTO_TCP)[0][4]
        dns = True
        with socket.create_connection(addr[:2], timeout=3):
            inet = True
    except OSError:
        pass
    finally:
        socket.setdefaulttimeout(None)
    return dns, inet


def iface_list():
    out = []
    for a in ip_json("addr", "show"):
        name = a.get("ifname", "")
        if name == "lo" or not os.path.exists(f"/sys/class/net/{name}/device"):
            continue  # solo interfaces físicas
        kind = "wifi" if os.path.exists(f"/sys/class/net/{name}/wireless") else "ethernet"
        ipv4 = [f'{i["local"]}/{i["prefixlen"]}' for i in a.get("addr_info", [])
                if i.get("family") == "inet"]
        out.append({"name": name, "type": kind, "state": a.get("operstate", "").lower(),
                    "mac": a.get("address"), "ipv4": ipv4})
    return out


def status(check_internet=True):
    ifaces = iface_list()
    objs = iwd_objects() or {}
    for d in wifi_devices(objs):
        for i in ifaces:
            if i["name"] == d["name"]:
                i.update({"ssid": d["ssid"], "wifi_state": d["state"], "powered": d["powered"]})
    route = ip_json("route", "show", "default")
    default = {"iface": route[0].get("dev"), "gateway": route[0].get("gateway")} if route else None
    data = {"interfaces": ifaces, "default_route": default}
    if check_internet:
        data["dns"], data["internet"] = internet_check() if default else (False, False)

    if not ifaces:
        return fail("NET_NO_DEVICE", "Check the network hardware with: aios-diag", data,
                    text="No network devices found.")
    lines = []
    for i in ifaces:
        extra = ""
        if i["type"] == "wifi":
            extra = f' "{i["ssid"]}"' if i.get("ssid") else f' ({i.get("wifi_state") or "off"})'
        lines.append(f'{i["name"]:<10} {i["type"]:<9} {i["state"]:<6} '
                     f'{", ".join(i["ipv4"]) or "-"}{extra}')
    if default is None:
        wifi = [i for i in ifaces if i["type"] == "wifi"]
        hint = "Run: aios net wifi scan" if wifi else "Plug in a network cable."
        return Result(False, "NET_NO_LINK", data, hint, text="\n".join(lines + ["Not connected."]))
    if check_internet and not data["internet"]:
        code = "NET_NO_DNS" if not data["dns"] else "NET_NO_INTERNET"
        return Result(False, code, data, "Run: aios-diag",
                      text="\n".join(lines + ["Connected, but no Internet access."]))
    tail = ["Internet: OK"] if check_internet else []
    return Result(True, "OK", data, text="\n".join(lines + tail))


# --- wifi ----------------------------------------------------------------------------

def networks(objs, dev):
    r = busctl("call", IWD, dev["path"], IWD + ".Station", "GetOrderedNetworks")
    nets = []
    for path, signal in (r[0] if isinstance(r, list) and r else []):
        n = objs.get(path, {}).get(IWD + ".Network")
        if not n:
            continue
        nets.append({"ssid": n.get("Name"), "security": n.get("Type"),
                     "signal_dbm": round(signal / 100), "known": "KnownNetwork" in n,
                     "connected": bool(n.get("Connected"))})
    return nets


def bars(dbm):
    return "▂▄▆█"[:max(1, min(4, (dbm + 90) // 10))]


def scan(dev):
    busctl("call", IWD, dev["path"], IWD + ".Station", "Scan")
    time.sleep(0.5)
    for _ in range(40):  # hasta 10 s
        d = pick_device(iwd_objects() or {}, dev["name"])
        if d and not d["scanning"]:
            break
        time.sleep(0.25)
    return networks(iwd_objects() or {}, dev)


def wifi_scan(args):
    objs = iwd_objects()
    dev = pick_device(objs or {}, args.device)
    if not dev:
        return no_wifi()
    if not ensure_powered(dev):
        return fail("WIFI_BLOCKED", "Check the wifi switch or airplane mode key.",
                    text="The wifi device cannot be turned on.")
    nets = scan(dev)
    data = {"device": dev["name"], "networks": nets}
    if not nets:
        return Result(True, "WIFI_NONE_FOUND", data, "Move closer to the router and scan again.",
                      text="No wifi networks found.")
    lines = [f'{"*" if n["connected"] else " "} {bars(n["signal_dbm"]):<4} '
             f'{n["security"]:<6} {n["ssid"]}' for n in nets]
    return Result(True, "OK", data, "Run: aios net wifi connect <ssid>", text="\n".join(lines))


def wait_state(name, want, seconds):
    end = time.time() + seconds
    while time.time() < end:
        d = pick_device(iwd_objects() or {}, name)
        if d and d["state"] in want:
            return d
        time.sleep(0.5)
    return pick_device(iwd_objects() or {}, name)


def wait_ipv4(name, seconds):
    end = time.time() + seconds
    while time.time() < end:
        for a in ip_json("addr", "show", "dev", name):
            for i in a.get("addr_info", []):
                if i.get("family") == "inet":
                    return i["local"]
        time.sleep(0.5)
    return None


def auth_problem(reason):
    r = reason.lower()
    return "passphrase" in r or "auth" in r or "operation failed" in r


def attempt(dev, ssid, password):
    """Un intento con iwctl; devuelve (dispositivo conectado o None, motivo)."""
    cmd = ["iwctl", "--dont-ask"]  # si faltan credenciales, falla en vez de esperar
    if password is not None:
        cmd += ["--passphrase", password]
    cmd += ["station", dev["name"], "connect", ssid]
    rc, out, err = run(cmd, timeout=45)
    d = wait_state(dev["name"], ("connected",), 5 if rc else 20)
    if d and d["state"] == "connected" and d["ssid"] == ssid:
        return d, ""
    # iwctl colorea su salida: sin códigos ANSI, la última línea con texto
    plain = re.sub(r"\x1b\[[0-9;?]*[A-Za-z]", "", out + err)
    msg = [m.strip() for m in plain.splitlines() if m.strip()]
    return None, msg[-1] if msg else "connection failed"


def wifi_connect(args):
    objs = iwd_objects()
    dev = pick_device(objs or {}, args.device)
    if not dev:
        return no_wifi()
    if not ensure_powered(dev):
        return fail("WIFI_BLOCKED", "Check the wifi switch or airplane mode key.",
                    text="The wifi device cannot be turned on.")
    nets = networks(iwd_objects() or {}, dev)
    if not any(n["ssid"] == args.ssid for n in nets):
        nets = scan(dev)  # sin escaneo reciente, iwd aún no la conoce
    target = next((n for n in nets if n["ssid"] == args.ssid), None)
    if target is None:
        return fail("WIFI_NOT_FOUND", "Run: aios net wifi scan", {"ssid": args.ssid},
                    text=f'Network "{args.ssid}" not found.')
    if target["connected"]:
        ip = wait_ipv4(dev["name"], 1)
        return Result(True, "OK", {"ssid": args.ssid, "device": dev["name"], "ipv4": ip},
                      text=f'Already connected to "{args.ssid}".')

    password = args.password
    needs = target["security"] in ("psk", "wep") and not target["known"]
    if needs and password is None:
        if args.json or not sys.stdin.isatty():
            return fail("WIFI_NEEDS_PASSWORD",
                        f"Run: aios net wifi connect '{args.ssid}' --password <password>",
                        {"ssid": args.ssid}, text=f'"{args.ssid}" needs a password.')
        password = getpass.getpass(f'Password for "{args.ssid}": ')
    if target["security"] == "8021x":
        return fail("WIFI_UNSUPPORTED", "Enterprise (802.1X) networks are not supported yet.",
                    {"ssid": args.ssid})

    # Con contraseña dada, siempre se entrega: si la guardada ya no vale (cambió
    # la del router), iwd la pide al agente, usa esta y la guarda.
    d, reason = attempt(dev, args.ssid, password)
    if d is None:
        if needs or auth_problem(reason):
            code, hint = "WIFI_AUTH_FAILED", "Check the password and try again."
            if target["known"] and not needs:
                hint = f"Run: aios net wifi connect '{args.ssid}' --password <new password>"
        else:
            code, hint = "WIFI_CONNECT_FAILED", "Run: aios-diag"
        return fail(code, hint, {"ssid": args.ssid, "reason": reason},
                    text=f'Could not connect to "{args.ssid}": {reason}')
    ip = wait_ipv4(dev["name"], 15)
    data = {"ssid": args.ssid, "device": dev["name"], "ipv4": ip}
    if not ip:
        return Result(False, "NET_NO_IP", data, "Run: aios-diag",
                      text=f'Connected to "{args.ssid}" but got no IP address.')
    return Result(True, "OK", data, text=f'Connected to "{args.ssid}" ({ip}).')


def wifi_disconnect(args):
    dev = pick_device(iwd_objects() or {}, args.device)
    if not dev:
        return no_wifi()
    if dev["state"] != "connected":
        return Result(True, "OK", {"device": dev["name"]}, text="Not connected.")
    busctl("call", IWD, dev["path"], IWD + ".Station", "Disconnect")
    wait_state(dev["name"], ("disconnected",), 5)
    return Result(True, "OK", {"device": dev["name"], "ssid": dev["ssid"]},
                  text=f'Disconnected from "{dev["ssid"]}".')


def register(sub):
    p = sub.add_parser("net", help="network: status and wifi")
    s = p.add_subparsers(dest="action", required=True)
    s.add_parser("status", help="interfaces, addresses and Internet access").set_defaults(
        func=lambda a: status())
    w = s.add_parser("wifi", help="wifi networks").add_subparsers(dest="wifi_action", required=True)
    sc = w.add_parser("scan", help="list nearby networks")
    sc.add_argument("--device")
    sc.set_defaults(func=wifi_scan)
    c = w.add_parser("connect", help="connect to a network")
    c.add_argument("ssid")
    c.add_argument("--password")
    c.add_argument("--device")
    c.set_defaults(func=wifi_connect)
    d = w.add_parser("disconnect", help="disconnect from the current network")
    d.add_argument("--device")
    d.set_defaults(func=wifi_disconnect)
