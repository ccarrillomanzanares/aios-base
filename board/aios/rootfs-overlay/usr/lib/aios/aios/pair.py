"""aios ai pair — añadir un proveedor tecleando la clave en otro dispositivo.

En AIOS aún no hay navegador y copiar a mano una clave de 100 caracteres es
un suplicio. El portátil enseña un código (y un QR); en el móvil o el PC se
abre la página, se elige el proveedor y se pega la clave. El navegador la
cifra con la clave pública RSA que acaba de generar el portátil: el servidor
de emparejamiento (scripts/diag-server.py en el VPS) solo guarda texto
cifrado, unos minutos, y lo borra al entregarlo. La clave privada vive en
XDG_RUNTIME_DIR (memoria) y se borra al terminar.
"""
import argparse
import base64
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request

from . import ai
from .result import Result, fail

SERVER = os.environ.get("AIOS_PAIR_SERVER", "https://ccmai.org/aios-diag/pair")
WAIT = 600  # segundos que vale el código


def _post(url, body, token=None):
    h = {"Content-Type": "application/json", "User-Agent": ai.USER_AGENT}
    if token:
        h["Authorization"] = "Bearer " + token
    req = urllib.request.Request(url, data=json.dumps(body).encode(), headers=h)
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.load(r)


def _poll(url, token):
    req = urllib.request.Request(url, headers={"Authorization": "Bearer " + token,
                                               "User-Agent": ai.USER_AGENT})
    with urllib.request.urlopen(req, timeout=15) as r:
        if r.status == 204:
            return None
        return json.load(r)


def _openssl(*args, data=None):
    p = subprocess.run(["openssl", *args], input=data, capture_output=True, timeout=60)
    if p.returncode != 0:
        raise RuntimeError(p.stderr.decode("utf-8", "replace").strip()[-300:])
    return p.stdout


def _ask(question, default=""):
    try:
        ans = input(question).strip()
    except EOFError:
        return default
    return ans or default


def _pick_model(p):
    ids = ai.model_ids(p)
    if not ids or len(ids) == 1:
        return ids[0] if ids else p.get("model", "")
    default = p.get("model") if p.get("model") in ids else ids[0]
    shown = ids[:30]
    print("Models on this provider:")
    for i, m in enumerate(shown, 1):
        print(f"  {i:2}. {m}{'  (suggested)' if m == default else ''}")
    if len(ids) > len(shown):
        print(f"  ... and {len(ids) - len(shown)} more (type the name)")
    while True:
        ans = _ask(f"Model [{default}]: ", default)
        if ans.isdigit() and 1 <= int(ans) <= len(shown):
            return shown[int(ans) - 1]
        if ans in ids:
            return ans
        print("Type a number from the list or a model name.")


def pair(args):
    if args.json or not sys.stdin.isatty():
        return fail("AI_PAIR_INTERACTIVE", "Run 'aios ai pair' in a terminal.",
                    text="Pairing shows a code and waits: run it in a terminal.")
    if not shutil.which("openssl"):
        return fail("AI_PAIR_NO_OPENSSL", "Run: aios ai add <name> --url <url>",
                    text="openssl is missing on this system.")
    server = (args.server or SERVER).rstrip("/")
    tmp = tempfile.mkdtemp(prefix="aios-pair-", dir=os.environ.get("XDG_RUNTIME_DIR"))
    try:
        key = os.path.join(tmp, "key.pem")
        _openssl("genpkey", "-algorithm", "RSA", "-pkeyopt", "rsa_keygen_bits:3072", "-out", key)
        pub = _openssl("pkey", "-in", key, "-pubout").decode()
        try:
            s = _post(server + "/new", {"pubkey": pub})
        except (urllib.error.URLError, OSError, ValueError) as e:
            return fail("AI_PAIR_SERVER", "Check the Internet connection: aios net status",
                        {"server": server, "error": str(getattr(e, "reason", e))},
                        text=f"Cannot reach the pairing server: {getattr(e, 'reason', e)}")
        print("On your phone or another computer, open:\n")
        print(f"    {s['url']}\n")
        if shutil.which("qrencode"):
            subprocess.run(["qrencode", "-t", "ANSIUTF8", "-m", "1", s["url"]])
        print(f"and type the code  {s['code']}  if it asks for it.")
        print("Waiting... (Ctrl+C to cancel)")
        end = time.monotonic() + min(int(s.get("expires", WAIT)), WAIT)
        got = None
        try:
            while time.monotonic() < end:
                try:
                    got = _poll(server + "/poll", s["poll"])
                except urllib.error.HTTPError as e:
                    if e.code == 404:
                        break  # caducado
                    raise
                except (urllib.error.URLError, OSError):
                    got = None  # un corte de red momentáneo: se sigue esperando
                if got:
                    break
                time.sleep(2)
        except KeyboardInterrupt:
            print()
            return Result(True, "AI_CANCELLED", text="Pairing cancelled.")
        if not got:
            return fail("AI_PAIR_EXPIRED", "Run: aios ai pair", text="The code expired. Try again.")

        prov = got.get("provider") or {}
        url = str(prov.get("url", "")).strip()
        if not url.startswith("https://") and not url.startswith("http://"):
            return fail("AI_PAIR_BAD_DATA", "Run: aios ai pair", text="The pairing data is not valid.")
        api_key = ""
        if got.get("key_enc"):
            try:
                api_key = _openssl("pkeyutl", "-decrypt", "-inkey", key,
                                   "-pkeyopt", "rsa_padding_mode:oaep",
                                   "-pkeyopt", "rsa_oaep_md:sha256", "-pkeyopt", "rsa_mgf1_md:sha256",
                                   data=base64.b64decode(got["key_enc"])).decode().strip()
            except (RuntimeError, ValueError, UnicodeDecodeError):
                return fail("AI_PAIR_BAD_DATA", "Run: aios ai pair",
                            text="Could not decrypt the API key. Try again.")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    # Lo que llega se enseña y se confirma: el servidor no decide por el usuario
    label = prov.get("label") or url
    print(f'\nReceived: {label}\n  URL: {url}\n  API key: {"yes" if api_key else "none"}')
    name = "".join(ch for ch in str(prov.get("name") or "remote").lower() if ch.isalnum() or ch in "-_")
    name = _ask(f"Name for this provider [{name}]: ", name)
    p = {"url": url.rstrip("/"), "key_header": prov.get("key_header") or "Authorization",
         "model": prov.get("model") or ""}
    if api_key:
        p["api_key"] = api_key
    ok, err = ai.reachable(p)
    if not ok:
        return fail("AI_UNREACHABLE", "Check the API key and run: aios ai pair", {"url": url, "error": err},
                    text=f"Cannot use {url}: {err}")
    p["model"] = _pick_model(p)
    res = ai.add(argparse.Namespace(name=name, url=p["url"], model=p["model"], api_key=api_key or None,
                                    no_key=not api_key, key_header=p["key_header"], context=None,
                                    insecure=False, json=False))
    if not res.ok:
        return res
    print(res.text)
    if _ask("Use it now? [Y/n] ", "y").lower() in ("y", "yes", "s", "si", "sí"):
        return ai.use(argparse.Namespace(name=name, model=None, confirm=None, json=False))
    return Result(True, "OK", res.data, f"Run: aios ai use {name}", text=f'Saved "{name}".')
