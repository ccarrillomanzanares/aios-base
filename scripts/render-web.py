#!/usr/bin/env python3
"""AIOS — rellena las plantillas de web/ con lo que hay publicado en releases/.

Uso: scripts/render-web.py RELEASES SALIDA
Lee aios.img.xz y aios.ova con sus .sha256 e .info (los deja scripts/publish.sh)
y escribe en SALIDA index.html, changelog.html, changelog-lfs.html y
releases/index.html. La versión es la última etiqueta v* del repositorio.
Si el .ova aún es de otra versión que la imagen (se publica después), se dice.
"""
import os
import re
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PAGES = ["index.html", "changelog.html", "changelog-lfs.html", "releases/index.html"]


def info(path):
    try:
        return dict(l.strip().split("=", 1) for l in open(path) if "=" in l)
    except OSError:
        return {}


def human(n):
    return f"{n / 1e9:.1f} GB"


def main():
    rel, out = sys.argv[1], sys.argv[2]
    version = subprocess.run(["git", "-C", ROOT, "describe", "--tags", "--abbrev=0", "--match", "v*"],
                             capture_output=True, text=True).stdout.strip() or "dev"
    img_info, ova_info = info(f"{rel}/aios.img.xz.info"), info(f"{rel}/aios.ova.info")
    commit = img_info.get("COMMIT", "unknown")[:7]
    values = {
        "@VERSION@": version,
        "@COMMIT@": commit,
        "@DATE@": img_info.get("DATE", "")[:10],
    }
    for key, name in (("IMG", "aios.img.xz"), ("OVA", "aios.ova")):
        path = f"{rel}/{name}"
        size = os.path.getsize(path) if os.path.exists(path) else 0
        sha = open(f"{path}.sha256").read().split()[0] if os.path.exists(f"{path}.sha256") else "not available yet"
        values[f"@{key}_SIZE@"] = human(size) if size else "not available yet"
        values[f"@{key}_SHA@"] = sha
    if ova_info.get("COMMIT", "")[:7] != commit:
        values["@OVA_SIZE@"] += " · previous version, the new one is on its way"
    # tamaño en el USB: el de la imagen sin comprimir (xz lo guarda en el índice)
    p = subprocess.run(["xz", "--robot", "--list", f"{rel}/aios.img.xz"], capture_output=True, text=True)
    m = re.search(r"^totals\t\d+\t\d+\t\d+\t(\d+)", p.stdout, re.M)
    values["@IMG_FULL@"] = human(int(m.group(1))) if m else "?"

    for page in PAGES:
        text = open(os.path.join(ROOT, "web", page)).read()
        for k, v in values.items():
            text = text.replace(k, v)
        left = re.findall(r"@[A-Z_]+@", text)
        if left:
            sys.exit(f"{page}: sin rellenar {left}")
        dst = os.path.join(out, page)
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        with open(dst, "w") as f:
            f.write(text)
    print(f"web {version} (imagen {commit}) en {out}")


if __name__ == "__main__":
    main()
