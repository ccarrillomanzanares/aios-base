"""look — mira la pantalla: captura con grim y pregunta al modelo (local, con
el proyector de visión de Qwen3.5, sin red).

La captura se reduce a MAX_WIDTH de ancho: menos tokens de imagen, que en CPU
es lo que cuesta. Se usa desde el chat (/look y la herramienta del agente)
y desde 'aios ai look'.
"""
import base64
import json
import os
import subprocess
import urllib.error
import urllib.request

from . import ai as aiconf
from .result import Result, fail

MAX_WIDTH = 1024


def wayland_env():
    env = dict(os.environ)
    env.setdefault("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}")
    env.setdefault("WAYLAND_DISPLAY", "wayland-1")  # desde tty o consola serie
    return env


def screen_width(env):
    try:
        out = subprocess.run(["swaymsg", "-t", "get_outputs", "-r"], capture_output=True,
                             text=True, timeout=5, env=env).stdout
        widths = [o["current_mode"]["width"] for o in json.loads(out) if o.get("active")]
        return max(widths) if widths else None
    except (OSError, ValueError, KeyError, subprocess.TimeoutExpired):
        return None


def capture(path=None):
    """PNG de la pantalla (bytes), reducido a MAX_WIDTH. path: usar ese fichero."""
    if path:
        with open(path, "rb") as f:
            return f.read()
    env = wayland_env()
    width = screen_width(env)
    scale = min(1.0, MAX_WIDTH / width) if width else 0.75
    p = subprocess.run(["grim", "-s", f"{scale:.3f}", "-"], capture_output=True,
                       timeout=20, env=env)
    if p.returncode != 0 or not p.stdout:
        raise RuntimeError(p.stderr.decode(errors="replace").strip() or "grim failed")
    return p.stdout


def describe(question, png, provider=None):
    """Pregunta al modelo por la imagen; devuelve el texto de la respuesta."""
    p = provider or aiconf.provider()
    url = "data:image/png;base64," + base64.b64encode(png).decode()
    body = {"messages": [{"role": "user", "content": [
        {"type": "text", "text": question},
        {"type": "image_url", "image_url": {"url": url}}]}],
        "max_tokens": 512}
    if p["local"]:
        body["chat_template_kwargs"] = {"enable_thinking": False}
    elif p.get("model"):
        body["model"] = p["model"]
    req = urllib.request.Request(p["url"].rstrip("/") + "/chat/completions",
                                 data=json.dumps(body).encode(), headers=aiconf.headers(p))
    with urllib.request.urlopen(req, timeout=600, context=aiconf.ssl_context(p)) as r:
        return json.load(r)["choices"][0]["message"]["content"].strip()


def look(args):
    question = args.question or "Describe what is on the screen."
    try:
        png = capture(args.file)
    except (OSError, RuntimeError, subprocess.TimeoutExpired) as e:
        return fail("LOOK_NO_SCREEN", "Run it inside the graphical session.", {"error": str(e)},
                    text=f"Could not capture the screen: {e}")
    try:
        answer = describe(question, png)
    except urllib.error.HTTPError as e:
        body = e.read().decode(errors="replace")[:300]
        hint = "The model in use may not support images." if e.code in (400, 500) else "Run: aios ai status"
        return fail("LOOK_MODEL_FAILED", hint, {"error": f"HTTP {e.code}: {body}"},
                    text=f"The model could not look at the screen: HTTP {e.code}")
    except (urllib.error.URLError, OSError, ValueError, KeyError) as e:
        return fail("AI_UNREACHABLE", "Run: aios ai status", {"error": str(e)})
    return Result(True, "OK", {"question": question, "answer": answer}, text=answer)
