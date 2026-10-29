"""Notificaciones de escritorio (mako) por D-Bus estándar, sin libnotify."""
import os
import subprocess

URGENCY = {"low": "0", "normal": "1", "critical": "2"}


def send(title, body="", urgency="normal", timeout_ms=8000):
    env = dict(os.environ)
    env.setdefault("DBUS_SESSION_BUS_ADDRESS", f"unix:path=/run/user/{os.getuid()}/bus")
    p = subprocess.run(
        ["busctl", "--user", "call", "org.freedesktop.Notifications",
         "/org/freedesktop/Notifications", "org.freedesktop.Notifications", "Notify",
         "susssasa{sv}i", "AIOS", "0", "", title, body, "0",
         "1", "urgency", "y", URGENCY.get(urgency, "1"), str(timeout_ms)],
        capture_output=True, env=env, timeout=10)
    return p.returncode == 0
