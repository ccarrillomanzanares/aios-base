#!/usr/bin/env python3
"""AIOS — rellena las plantillas de web/ con lo que hay publicado en releases/.

Uso: scripts/render-web.py RELEASES SALIDA
Lee aios.img.xz y aios.ova con sus .sha256 e .info (los deja scripts/publish.sh)
y escribe en SALIDA index.html, changelog.html, changelog-lfs.html y
releases/index.html. La versión es la última etiqueta v* del repositorio.
Si el .ova aún es de otra versión que la imagen (se publica después), se dice.
"""
import html
import os
import re
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PAGES = ["index.html", "about.html", "help.html", "changelog.html", "changelog-lfs.html", "releases/index.html"]


def info(path):
    try:
        return dict(l.strip().split("=", 1) for l in open(path) if "=" in l)
    except OSError:
        return {}


def md_html(md):
    """help.md (títulos, listas, tablas, `código`) -> HTML; la misma ayuda que aios-help."""
    def inline(t):
        return re.sub(r"`([^`]*)`", r"<code>\1</code>", html.escape(t, quote=False))
    out, rows, items = [], [], []

    def flush():
        if rows:
            cells = [[c.strip() for c in r.strip().strip("|").split("|")] for r in rows]
            cells = [r for r in cells if not all(set(c) <= set("-: ") for c in r)]
            out.append("<table>" + "".join(
                "<tr>" + "".join(f"<{'th' if i == 0 else 'td'}>{inline(c)}</{'th' if i == 0 else 'td'}>" for c in r) + "</tr>"
                for i, r in enumerate(cells)) + "</table>")
            rows.clear()
        if items:
            out.append('<ul class="what">' + "".join(f"<li>{inline(x)}</li>" for x in items) + "</ul>")
            items.clear()

    for line in md.splitlines():
        if line.startswith("|"):
            rows.append(line)
            continue
        if line.startswith("- "):
            items.append(line[2:])
            continue
        flush()
        if line.startswith("# "):
            out.append(f"<h1>&gt; {inline(line[2:])}</h1>")
        elif line.startswith("## "):
            anchor = re.sub(r"[^a-z0-9]+", "-", line[3:].lower()).strip("-")
            out.append(f'<h2 id="{anchor}">{inline(line[3:])}</h2>')
        elif line.strip():
            out.append(f"<p>{inline(line)}</p>")
    flush()
    return "\n".join(out)


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
    values["@HELP_BODY@"] = md_html(open(os.path.join(ROOT, "board/aios/rootfs-overlay/usr/share/aios/help.md")).read())
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
