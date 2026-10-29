"""aios ui — interfaz: brillo de la pantalla (de momento).

El brillo se cambia con logind (Session.SetBrightness), que lo permite al
usuario de la sesión activa sin root ni reglas de udev. AIOS_SYSFS cambia la
raíz de /sys para las pruebas.
"""
import os
import subprocess

from .result import Result, fail

SYSFS = os.environ.get("AIOS_SYSFS", "/sys")
MIN_PERCENT = 5  # nunca a 0: pantalla negra sin forma fácil de volver
STEP = 10
# Como systemd-backlight: firmware (ACPI) antes que platform y que raw
PREFERENCE = {"firmware": 0, "platform": 1, "raw": 2}


def read_int(path):
    with open(path) as f:
        return int(f.read().strip())


def backlight():
    base = os.path.join(SYSFS, "class", "backlight")
    try:
        names = os.listdir(base)
    except OSError:
        return None
    devs = []
    for name in names:
        d = os.path.join(base, name)
        try:
            kind = open(os.path.join(d, "type")).read().strip()
            mx = read_int(os.path.join(d, "max_brightness"))
            cur = read_int(os.path.join(d, "brightness"))
        except (OSError, ValueError):
            continue
        if mx > 0:
            devs.append((PREFERENCE.get(kind, 3), name, cur, mx))
    if not devs:
        return None
    _, name, cur, mx = sorted(devs)[0]
    return {"device": name, "value": cur, "max": mx, "percent": round(cur * 100 / mx)}


def set_value(dev, value):
    rc = subprocess.run(
        ["busctl", "--system", "call", "org.freedesktop.login1",
         "/org/freedesktop/login1/session/auto", "org.freedesktop.login1.Session",
         "SetBrightness", "ssu", "backlight", dev["device"], str(value)],
        capture_output=True).returncode
    if rc == 0:
        return True
    try:  # sin sesión de logind (p. ej. root por ssh): escritura directa
        with open(os.path.join(SYSFS, "class", "backlight", dev["device"], "brightness"), "w") as f:
            f.write(str(value))
        return True
    except OSError:
        return False


def brightness(args):
    dev = backlight()
    if dev is None:
        return fail("UI_NO_BACKLIGHT", "This screen has no adjustable backlight.",
                    text="No adjustable backlight found.")
    if args.level is None:
        return Result(True, "OK", dev, text=f'Brightness: {dev["percent"]}%')
    lvl = args.level.strip()
    try:
        if lvl == "up":
            pct = dev["percent"] + STEP
        elif lvl == "down":
            pct = dev["percent"] - STEP
        else:
            pct = int(lvl.rstrip("%"))
    except ValueError:
        return fail("UI_BAD_LEVEL", "Use: aios ui brightness [up|down|0-100]", {"level": lvl})
    pct = max(MIN_PERCENT, min(100, pct))
    value = max(1, round(pct * dev["max"] / 100))
    if not set_value(dev, value):
        return fail("UI_BRIGHTNESS_DENIED", "Run it from the graphical session.", dev)
    dev.update(value=value, percent=pct)
    return Result(True, "OK", dev, text=f"Brightness: {pct}%")


def register(sub):
    p = sub.add_parser("ui", help="interface: screen brightness")
    s = p.add_subparsers(dest="action", required=True)
    b = s.add_parser("brightness", help="show or set the screen brightness")
    b.add_argument("level", nargs="?", help="up, down or a percentage (5-100)")
    b.set_defaults(func=brightness)
