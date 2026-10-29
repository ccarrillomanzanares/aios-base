#!/usr/bin/env python3
"""Receptor de diagnósticos de AIOS (corre en el VPS, detrás de Apache).

aios-diag sube un .tar.gz con POST a https://ccmai.org/aios-diag/upload;
Apache lo pasa a 127.0.0.1:8091. Solo biblioteca estándar.

Uso: diag-server.py [--port 8091] [--dir ~/aios-diag] [--token-file ~/.config/aios-diag/token]
"""
import argparse
import hmac
import os
import re
import secrets
import shutil
import sys
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

MAX_UPLOAD = 64 * 1024 * 1024    # por subida
MAX_TOTAL = 2 * 1024 ** 3        # en disco; por encima se rechazan subidas
MIN_INTERVAL = 10                # segundos entre subidas desde la misma IP

args = None
token = b""
last_by_ip = {}


def dir_size(path):
    return sum(e.stat().st_size for e in os.scandir(path) if e.is_file())


class Handler(BaseHTTPRequestHandler):
    server_version = "aios-diag"

    def reply(self, code, text):
        body = (text + "\n").encode()
        self.send_response(code)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path.rstrip("/") == "/aios-diag":
            self.reply(200, "aios-diag receiver OK")
        else:
            self.reply(404, "not found")

    def do_POST(self):
        if self.path != "/aios-diag/upload":
            return self.reply(404, "not found")
        auth = self.headers.get("Authorization", "").encode()
        if not hmac.compare_digest(auth, b"Bearer " + token):
            return self.reply(403, "bad token")
        ip = self.headers.get("X-Forwarded-For", self.client_address[0]).split(",")[0].strip()
        now = time.monotonic()
        if now - last_by_ip.get(ip, -MIN_INTERVAL) < MIN_INTERVAL:
            return self.reply(429, "too many uploads, wait a few seconds")
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            length = 0
        if length <= 0:
            return self.reply(411, "Content-Length required")
        if length > MAX_UPLOAD:
            return self.reply(413, f"too large (max {MAX_UPLOAD // 2**20} MB)")
        if dir_size(args.dir) + length > MAX_TOTAL:
            return self.reply(507, "receiver full")
        last_by_ip[ip] = now

        # Nombre: fecha + host que declara el cliente (saneado) + sufijo aleatorio
        host = re.sub(r"[^A-Za-z0-9_-]", "", self.headers.get("X-AIOS-Host", ""))[:32] or "unknown"
        name = f"{time.strftime('%Y%m%d-%H%M%S')}-{host}-{secrets.token_hex(3)}.tar.gz"
        tmp = os.path.join(args.dir, "." + name + ".part")
        with open(tmp, "wb") as f:
            left = length
            while left:
                chunk = self.rfile.read(min(left, 1 << 16))
                if not chunk:
                    break
                f.write(chunk)
                left -= len(chunk)
        if left:
            os.unlink(tmp)
            return self.reply(400, "upload truncated")
        os.rename(tmp, os.path.join(args.dir, name))
        print(f"recibido {name} ({length} bytes) desde {ip}", flush=True)
        self.reply(200, name)

    def log_message(self, fmt, *a):
        pass   # las subidas ya se registran arriba; sin ruido de cada petición


def main():
    global args, token
    p = argparse.ArgumentParser(description="AIOS diagnostics receiver")
    p.add_argument("--port", type=int, default=8091)
    p.add_argument("--dir", default=os.path.expanduser("~/aios-diag"))
    p.add_argument("--token-file", default=os.path.expanduser("~/.config/aios-diag/token"))
    args = p.parse_args()
    try:
        token = open(args.token_file, "rb").read().strip()
    except OSError as e:
        sys.exit(f"diag-server: cannot read token: {e}")
    if len(token) < 16:
        sys.exit("diag-server: token too short (min 16 chars)")
    os.makedirs(args.dir, exist_ok=True)
    print(f"diag-server en 127.0.0.1:{args.port}, guarda en {args.dir}", flush=True)
    ThreadingHTTPServer(("127.0.0.1", args.port), Handler).serve_forever()


if __name__ == "__main__":
    main()
