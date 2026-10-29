"""Perfil de energía automático: con batería, ahorro; enchufado, rendimiento.

aios-power.service lo aplica al arrancar y udev lo relanza cuando cambia la
alimentación (90-aios-power.rules). Solo actúa si el perfil cambia, así que
los avisos periódicos de la batería no hacen nada. Con batería:

- CPU: preferencia de energía (EPP) "balance_power" si el controlador la
  admite (intel_pstate, amd-pstate-epp); enchufado, "balance_performance".
  Sin EPP no se toca el gobernador: los genéricos ahorran poco o frenan mucho.
- Pantalla: el brillo baja a BATTERY_BRIGHTNESS si estaba por encima, y al
  enchufar vuelve al de antes, salvo que el usuario lo haya cambiado.
- Modelo: menos hilos (BATTERY_LLAMA_THREADS). llama-server no los cambia en
  marcha: se reinicia, pero solo si no está respondiendo; si lo está, se
  reintenta al minuto (systemd-run). Mientras recarga, la barra dice AI LOADING.

Configuración en /etc/aios/power.conf. Estado en /run/aios/power.json.
"""
import argparse
import glob
import json
import os
import subprocess
import urllib.error
import urllib.request

from . import notify, ui
from .result import Result, fail

SYSFS = os.environ.get("AIOS_SYSFS", "/sys")
CONF = os.environ.get("AIOS_POWER_CONF", "/etc/aios/power.conf")
RUN = os.environ.get("AIOS_POWER_RUN", "/run/aios")
STATE = os.path.join(RUN, "power.json")
LLAMA_OVERRIDE = os.path.join(RUN, "llama-power.conf")  # lo lee aios-llama
LLAMA_PORT = os.environ.get("AIOS_LLAMA_PORT", "8083")
EPP = {"battery": "balance_power", "ac": "balance_performance"}
DEFAULTS = {"ENABLED": "yes", "BATTERY_BRIGHTNESS": "60", "BATTERY_LLAMA_THREADS": "auto"}


def _read(path):
    try:
        with open(path) as f:
            return f.read().strip()
    except OSError:
        return None


def _write(path, value):
    try:
        with open(path, "w") as f:
            f.write(value)
        return True
    except OSError:
        return False


def config():
    c = dict(DEFAULTS)
    for line in (_read(CONF) or "").splitlines():
        line = line.split("#", 1)[0].strip()
        if "=" in line:
            k, v = line.split("=", 1)
            c[k.strip()] = v.strip().strip('"')
    return c


def on_ac():
    """True enchufado (o sin batería), False con batería."""
    supplies = glob.glob(os.path.join(SYSFS, "class", "power_supply", "*"))
    mains = [s for s in supplies if _read(os.path.join(s, "type")) in ("Mains", "USB")
             and _read(os.path.join(s, "online")) is not None]
    if any(_read(os.path.join(s, "online")) == "1" for s in mains):
        return True
    bats = [s for s in supplies if _read(os.path.join(s, "type")) == "Battery"]
    if not bats:
        return True  # sobremesa o VM
    if mains:
        return False
    # Sin cargador visible: lo dice el estado de la batería
    return not any(_read(os.path.join(b, "status")) == "Discharging" for b in bats)


def load_state():
    try:
        with open(STATE) as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def save_state(st):
    os.makedirs(RUN, exist_ok=True)
    tmp = STATE + ".tmp"
    with open(tmp, "w") as f:
        json.dump(st, f)
    os.replace(tmp, STATE)


# --- CPU ---------------------------------------------------------------------------------

def set_epp(profile):
    """Pone la preferencia de energía en todas las políticas; devuelve la puesta o None."""
    want, done = EPP[profile], None
    for pol in glob.glob(os.path.join(SYSFS, "devices", "system", "cpu", "cpufreq", "policy*")):
        avail = (_read(os.path.join(pol, "energy_performance_available_preferences")) or "").split()
        if want in avail and _write(os.path.join(pol, "energy_performance_preference"), want):
            done = want
    return done


# --- Pantalla ------------------------------------------------------------------------------

def set_brightness(profile, st, cfg):
    dev = ui.backlight()
    if dev is None:
        return None
    try:
        target = max(ui.MIN_PERCENT, min(100, int(cfg["BATTERY_BRIGHTNESS"])))
    except ValueError:
        return None
    if profile == "battery":
        if dev["percent"] <= target:
            return None
        st["brightness_before"], st["brightness_set"] = dev["percent"], target
        ui.set_value(dev, max(1, round(target * dev["max"] / 100)))
        return target
    before, mine = st.pop("brightness_before", None), st.pop("brightness_set", None)
    if before is None or dev["percent"] != mine:
        return None  # el usuario lo cambió con batería: se respeta
    ui.set_value(dev, max(1, round(before * dev["max"] / 100)))
    return before


# --- Modelo --------------------------------------------------------------------------------

def physical_cores():
    cores = set()
    for cpu in glob.glob(os.path.join(SYSFS, "devices", "system", "cpu", "cpu[0-9]*", "topology")):
        cores.add((_read(os.path.join(cpu, "physical_package_id")), _read(os.path.join(cpu, "core_id"))))
    return len(cores) or os.cpu_count() or 1


def llama_threads(cfg):
    v = cfg["BATTERY_LLAMA_THREADS"]
    if v in ("", "keep", "no"):
        return None
    if v == "auto":
        return max(1, physical_cores() // 2)
    try:
        return max(1, int(v))
    except ValueError:
        return None


def llama_busy():
    """True si está respondiendo o no se sabe; False si está ocioso; None si no corre."""
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{LLAMA_PORT}/slots", timeout=3) as r:
            slots = json.load(r)
    except urllib.error.HTTPError:
        return True
    except (OSError, ValueError):
        return None
    return any(s.get("is_processing") for s in slots if isinstance(s, dict))


def set_llama(profile, cfg):
    """Escribe los hilos para aios-llama; devuelve ('restarted'|'later'|'next-start'|None, hilos)."""
    n = llama_threads(cfg) if profile == "battery" else None
    old = _read(LLAMA_OVERRIDE)
    new = f"THREADS={n}\nTHREADS_BATCH={n}\n" if n else None
    if (old or None) == new:
        return None, n
    os.makedirs(RUN, exist_ok=True)
    if new:
        _write(LLAMA_OVERRIDE, new)
    else:
        try:
            os.unlink(LLAMA_OVERRIDE)
        except OSError:
            pass
    return restart_llama_when_idle(), n


def restart_llama_when_idle():
    busy = llama_busy()
    if busy is None:
        return "next-start"  # no está corriendo: lo leerá al arrancar
    if busy:
        # Respondiendo: otro intento en un minuto, sin cortar la respuesta
        subprocess.run(["systemd-run", "--quiet", "--on-active=60", "--unit=aios-power-retry",
                        "/usr/bin/aios", "sys", "power", "llama-restart"], capture_output=True)
        return "later"
    subprocess.run(["systemctl", "restart", "--no-block", "aios-llama.service"], capture_output=True)
    return "restarted"


# --- Órdenes -------------------------------------------------------------------------------

def apply(args):
    if os.geteuid() != 0 and "AIOS_POWER_RUN" not in os.environ:
        return fail("NEEDS_ROOT", "Run: sudo aios sys power apply", text="Needs administrator rights.")
    cfg = config()
    if cfg["ENABLED"] != "yes":
        return Result(True, "POWER_DISABLED", text="Automatic power profile disabled in " + CONF)
    profile = args.profile if getattr(args, "profile", None) in ("battery", "ac") else \
        ("ac" if on_ac() else "battery")
    st = load_state()
    if st.get("profile") == profile and not getattr(args, "force", False):
        return Result(True, "OK", st, text=f"Already on the {profile} profile.")
    first = "profile" not in st
    st["profile"] = profile
    done = {"profile": profile, "epp": set_epp(profile)}
    done["brightness"] = set_brightness(profile, st, cfg)
    done["llama"], done["llama_threads"] = set_llama(profile, cfg)
    save_state(st)
    if not first:  # al arrancar no se avisa: nada ha cambiado para el usuario
        what = []
        if done["epp"]:
            what.append("CPU " + ("power saving" if profile == "battery" else "full speed"))
        if done["brightness"]:
            what.append(f'brightness {done["brightness"]}%')
        if done["llama"] in ("restarted", "later"):
            what.append("AI with " + (f'{done["llama_threads"]} threads' if done["llama_threads"] else "all threads")
                        + (" (reloading)" if done["llama"] == "restarted" else " (after this answer)"))
        notify.send_to_user("On battery: saving power" if profile == "battery" else "Plugged in: full power",
                            ", ".join(what) or "")
    return Result(True, "OK", done, text=f"{profile} profile: " + json.dumps(done))


def llama_restart(args):
    """Reintento de systemd-run: reinicia el modelo si ya está ocioso."""
    r = restart_llama_when_idle()
    return Result(True, "OK", {"llama": r}, text=f"llama: {r}")


def show(args):
    st = load_state()
    data = {"on_ac": on_ac(), "profile": st.get("profile"), "config": config(),
            "llama_override": _read(LLAMA_OVERRIDE)}
    epp = _read(os.path.join(SYSFS, "devices", "system", "cpu", "cpufreq", "policy0",
                             "energy_performance_preference"))
    data["epp"] = epp
    text = (f'{"Plugged in" if data["on_ac"] else "On battery"}; profile {data["profile"] or "not applied"}'
            + (f"; CPU preference {epp}" if epp else ""))
    return Result(True, "OK", data, text=text)


def register(s):
    p = s.add_parser("power", help="automatic power profile (battery / plugged in)")
    ps = p.add_subparsers(dest="power_action")
    p.set_defaults(func=show)
    a = ps.add_parser("apply", help="apply the profile for the current power source (root)")
    a.add_argument("--profile", choices=("auto", "battery", "ac"), default="auto")
    a.add_argument("--force", action="store_true", help="apply even if it did not change")
    a.set_defaults(func=apply)
    ps.add_parser("llama-restart", help=argparse.SUPPRESS).set_defaults(func=llama_restart)
