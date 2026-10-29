"""aios update code — actualiza scripts y configuración de AIOS desde git.

Solo cubre lo que va en el overlay de la imagen (board/aios/rootfs-overlay):
scripts, la CLI, configuración. Paquetes, kernel o defconfig necesitan una
imagen nueva; 'check' lo avisa. (La actualización A/B de imágenes completas,
con RAUC, llega en el hito 4 como 'aios update check/apply/rollback'.)

Fusión a tres bandas por fichero, para no pisar cambios locales:
  base   = versión del commit instalado (/etc/aios/build-info o la última
           actualización), nueva = la del repositorio, actual = la del sistema.
  - solo cambió el repositorio   -> se instala la nueva
  - solo cambió el sistema       -> se respeta
  - cambiaron los dos            -> se conserva la local; la nueva queda al
                                    lado como <fichero>.aios-new
Antes de tocar nada se copia lo que había a /var/lib/aios/updates/<fecha>/,
y 'rollback' lo deja como estaba.
"""
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time

from .result import Result, fail

ROOT = os.environ.get("AIOS_UPDATE_ROOT", "/")  # raíz del sistema (pruebas)
CONF = os.path.join(ROOT, "etc/aios/update.conf")
SIGNERS = os.path.join(ROOT, "etc/aios/update-signers")
BUILD_INFO = os.path.join(ROOT, "etc/aios/build-info")
STATE = os.environ.get("AIOS_UPDATE_STATE", "/var/lib/aios")
SRC = os.path.join(STATE, "src")
CURRENT = os.path.join(STATE, "code-commit")
UPDATES = os.path.join(STATE, "updates")
OVERLAY = "board/aios/rootfs-overlay"
# Cambios fuera del overlay que solo llegan con una imagen nueva
IMAGE_PATHS = ("configs/", "board/aios/kernel/", "board/aios/post-build.sh",
               "board/aios/post-image.sh", "board/aios/users.txt", "board/aios/genimage.cfg",
               "board/aios/grub", "external.mk", "Config.in", "package/")


def read_kv(path):
    out = {}
    try:
        for line in open(path):
            if "=" in line and not line.lstrip().startswith("#"):
                k, v = line.split("=", 1)
                out[k.strip()] = v.strip()
    except OSError:
        pass
    return out


def git(*args, check=True, binary=False):
    p = subprocess.run(["git", "-C", SRC, *args], capture_output=True,
                       stdin=subprocess.DEVNULL, timeout=300)
    if check and p.returncode != 0:
        raise RuntimeError(p.stderr.decode(errors="replace").strip() or "git failed")
    return p.stdout if binary else p.stdout.decode(errors="replace")


def blob(commit, path):
    """Contenido de path en commit, o None si no existe allí."""
    if not commit:
        return None
    p = subprocess.run(["git", "-C", SRC, "show", f"{commit}:{path}"],
                       capture_output=True, stdin=subprocess.DEVNULL)
    return p.stdout if p.returncode == 0 else None


def live(path):
    try:
        with open(os.path.join(ROOT, path), "rb") as f:
            return f.read()
    except OSError:
        return None


def overlay_files(commit):
    out = git("ls-tree", "-r", "--full-tree", commit, OVERLAY)
    files = {}
    for line in out.splitlines():
        meta, path = line.split("\t", 1)
        mode = meta.split()[0]
        if mode in ("100644", "100755"):
            files[path[len(OVERLAY) + 1:]] = mode
    return files


def installed_commit():
    try:
        c = open(CURRENT).read().strip()
        if c:
            return c
    except OSError:
        pass
    c = read_kv(BUILD_INFO).get("COMMIT", "")
    return c if c and c != "unknown" else None


def need_root(action):
    if os.geteuid() != 0 and "AIOS_UPDATE_ROOT" not in os.environ:
        return fail("NEEDS_ROOT", f"Run: sudo aios update code {action}",
                    text="Updating AIOS code needs administrator rights.")
    return None


class NoRelease(Exception):
    """No hay ninguna versión firmada por una clave de update-signers."""


def verified_tag():
    """La etiqueta v* más alta con firma válida (clave de update-signers)."""
    tags = git("tag", "-l", "v*", "--sort=-v:refname").split()
    for tag in tags:
        p = subprocess.run(["git", "-C", SRC, "-c", "gpg.format=ssh",
                            "-c", f"gpg.ssh.allowedSignersFile={SIGNERS}", "verify-tag", tag],
                           capture_output=True, stdin=subprocess.DEVNULL, timeout=60)
        if p.returncode == 0:
            return tag
    raise NoRelease(f"none of {len(tags)} tag(s) is signed by a key in {SIGNERS}")


def fetch():
    """Descarga y devuelve (commit, repo, origen). Canal 'release' (por defecto):
    la versión firmada más reciente; 'main': lo último de la rama, sin firma."""
    conf = read_kv(CONF)
    repo = conf.get("REPO", "https://github.com/ccarrillomanzanares/aios-base")
    branch = conf.get("BRANCH", "main")
    channel = conf.get("CHANNEL", "release")
    if not os.path.isdir(os.path.join(SRC, ".git")):
        os.makedirs(STATE, exist_ok=True)
        p = subprocess.run(["git", "clone", "--quiet", "--branch", branch, repo, SRC],
                           capture_output=True, stdin=subprocess.DEVNULL, timeout=600)
        if p.returncode != 0:
            shutil.rmtree(SRC, ignore_errors=True)
            raise RuntimeError(p.stderr.decode(errors="replace").strip())
    git("remote", "set-url", "origin", repo)
    git("fetch", "--quiet", "--tags", "--force", "origin", branch)
    if channel == "main":
        return git("rev-parse", "FETCH_HEAD").strip(), repo, f"{branch} (unsigned)"
    tag = verified_tag()
    return git("rev-parse", f"{tag}^{{commit}}").strip(), repo, f"{tag} (signed)"


def is_older(new, base):
    """¿new es anterior a lo instalado? (nunca se baja de versión)"""
    if not base or new == base:
        return False
    return subprocess.run(["git", "-C", SRC, "merge-base", "--is-ancestor", new, base],
                          capture_output=True).returncode == 0


def plan(base, new):
    """Qué hacer con cada fichero del overlay al pasar de base a new."""
    base_ok = bool(base) and subprocess.run(
        ["git", "-C", SRC, "cat-file", "-e", f"{base}^{{commit}}"],
        capture_output=True).returncode == 0
    new_files = overlay_files(new)
    old_files = overlay_files(base) if base_ok else {}
    steps = {"update": [], "add": [], "remove": [], "conflict": [], "kept": []}
    for path, mode in sorted(new_files.items()):
        b = blob(base, f"{OVERLAY}/{path}") if base_ok else None
        n = blob(new, f"{OVERLAY}/{path}")
        cur = live(path)
        if cur == n:
            continue
        if cur is None:
            steps["add"].append({"path": path, "mode": mode})
        elif not base_ok or cur == b:  # sin base conocida, se actualiza (con copia)
            steps["update"].append({"path": path, "mode": mode})
        elif n == b:
            continue  # solo lo cambió el usuario: se respeta
        else:
            steps["conflict"].append({"path": path, "mode": mode})
    for path in sorted(set(old_files) - set(new_files)):
        cur = live(path)
        if cur is None:
            continue
        if cur == blob(base, f"{OVERLAY}/{path}"):
            steps["remove"].append({"path": path})
        else:
            steps["kept"].append({"path": path})
    image = []
    if base_ok:
        changed = git("diff", "--name-only", base, new).splitlines()
        image = [p for p in changed if p.startswith(IMAGE_PATHS)]
    commits = []
    if base_ok:
        commits = git("log", "--format=%h %s", f"{base}..{new}").splitlines()
    return steps, image, commits, base_ok


def token_for(new, steps):
    raw = json.dumps([new, steps], sort_keys=True).encode()
    return hashlib.sha256(raw).hexdigest()[:8]


def summary(new, steps, image, commits, base_ok):
    lines = [f"Latest: {new[:10]}"]  # el origen (etiqueta firmada o rama) lo añade quien llama
    if commits:
        lines += ["Commits:"] + [f"  {c}" for c in commits[:15]]
        if len(commits) > 15:
            lines.append(f"  ... and {len(commits) - 15} more")
    if not base_ok:
        lines.append("Installed version unknown: every file that differs will be replaced (with backup).")
    labels = {"update": "update", "add": "new", "remove": "remove",
              "conflict": "local changes kept, new version saved as .aios-new",
              "kept": "removed upstream but changed locally, kept"}
    for k, label in labels.items():
        for s in steps[k]:
            lines.append(f"  [{label}] /{s['path']}")
    if image:
        lines.append("These changes need a new image (not applied here):")
        lines += [f"  {p}" for p in image]
    return lines


def mode_for(path, git_mode):
    if path.startswith("etc/sudoers.d/"):
        return 0o440
    return 0o755 if git_mode == "100755" else 0o644


def owner_for(path):
    return (1000, 1000) if path.startswith("home/aios/") else (0, 0)


def write_file(path, data, git_mode):
    dest = os.path.join(ROOT, path)
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    tmp = dest + ".aios-tmp"
    with open(tmp, "wb") as f:
        f.write(data)
    os.chmod(tmp, mode_for(path, git_mode))
    if os.geteuid() == 0:
        os.chown(tmp, *owner_for(path))
    os.replace(tmp, dest)  # atómico: un script nunca queda a medias


def code_check(args):
    r = need_root("check")
    if r:
        return r
    try:
        new, repo, branch = fetch()
    except NoRelease as e:
        return Result(True, "UPDATE_NO_RELEASE", {"error": str(e)},
                      "There is no signed AIOS release yet.", text=f"No signed release: {e}")
    except (RuntimeError, OSError, subprocess.TimeoutExpired) as e:
        return fail("UPDATE_FETCH_FAILED", "Check the network with: aios net status",
                    {"error": str(e)}, text=f"Could not download the AIOS code: {e}")
    base = installed_commit()
    if is_older(new, base):
        return Result(True, "UPDATE_NONE", {"installed": base, "latest": new, "source": branch},
                      text=f"Installed code is newer than {branch}: nothing to do.")
    steps, image, commits, base_ok = plan(base, new)
    n = sum(len(v) for k, v in steps.items() if k != "kept")
    data = {"installed": base, "latest": new, "repo": repo, "source": branch,
            "changes": steps, "needs_image": image, "commits": commits}
    if n == 0:
        return Result(True, "UPDATE_NONE", data,
                      "A new image is needed for the remaining changes." if image else None,
                      text="\n".join(["AIOS code is up to date."] +
                                     summary(new, steps, image, [], base_ok)[1:]))
    return Result(True, "UPDATE_AVAILABLE", data, "Run: sudo aios update code apply",
                  text="\n".join([f"Source: {branch}"] + summary(new, steps, image, commits, base_ok)))


NOTIFIED = os.path.join(STATE, "update-notified")


def code_notify(args):
    """Para aios-update-check.timer: comprueba y, si hay algo nuevo que aún no
    se ha avisado, lo dice en el escritorio. Una vez por versión."""
    if read_kv(CONF).get("AUTO_CHECK", "yes") != "yes":
        return Result(True, "UPDATE_CHECK_DISABLED", text="Automatic update check disabled in " + CONF)
    res = code_check(args)
    latest = (res.data or {}).get("latest")
    if res.code not in ("UPDATE_AVAILABLE", "UPDATE_NONE") or not latest:
        return res
    image = bool((res.data or {}).get("needs_image"))
    if res.code == "UPDATE_NONE" and not image:
        return res
    try:
        with open(NOTIFIED) as f:
            if f.read().strip() == latest:
                return res  # ya avisado de esta versión
    except OSError:
        pass
    from . import notify
    if res.code == "UPDATE_AVAILABLE":
        n = sum(len(v) for k, v in res.data["changes"].items() if k != "kept")
        sent = notify.send_to_user(
            "AIOS update available",
            f"{n} file(s) to update. Ask the assistant, or run in a terminal: sudo aios update code apply")
    else:
        sent = notify.send_to_user("New AIOS image available",
                                   "Some changes need a new image: download it from ccmai.org/aios")
    if sent:  # sin sesión gráfica no cuenta como avisado: se repite la próxima vez
        os.makedirs(STATE, exist_ok=True)
        with open(NOTIFIED, "w") as f:
            f.write(latest + "\n")
    res.data["notified"] = sent
    return res


def code_apply(args):
    r = need_root("apply")
    if r:
        return r
    try:
        new, _, branch = fetch()
    except NoRelease as e:
        return Result(True, "UPDATE_NO_RELEASE", {"error": str(e)},
                      "There is no signed AIOS release yet.", text=f"No signed release: {e}")
    except (RuntimeError, OSError, subprocess.TimeoutExpired) as e:
        return fail("UPDATE_FETCH_FAILED", "Check the network with: aios net status",
                    {"error": str(e)}, text=f"Could not download the AIOS code: {e}")
    base = installed_commit()
    if is_older(new, base):
        return Result(True, "UPDATE_NONE", {"installed": base, "latest": new},
                      text=f"Installed code is newer than {branch}: nothing to do.")
    steps, image, commits, base_ok = plan(base, new)
    if not any(steps[k] for k in ("update", "add", "remove", "conflict")):
        return Result(True, "UPDATE_NONE", {"latest": new}, text="AIOS code is up to date.")

    # Confirmación: el contrato pide token; en un terminal basta con un sí
    token = token_for(new, steps)
    if args.confirm != token:
        lines = summary(new, steps, image, commits, base_ok)
        if not args.json and sys.stdin.isatty() and args.confirm is None:
            print("\n".join(lines))
            if input("Apply these changes? [y/N] ").strip().lower() not in ("y", "yes", "s", "si", "sí"):
                return Result(True, "UPDATE_CANCELLED", text="Nothing changed.")
        else:
            return Result(False, "CONFIRM_REQUIRED", {"latest": new, "changes": steps},
                          f"Run: sudo aios update code apply --confirm {token}",
                          confirm=token, text="\n".join(lines))

    # Copia de seguridad de todo lo que se va a tocar
    stamp = time.strftime("%Y%m%d-%H%M%S")
    bdir = os.path.join(UPDATES, stamp)
    os.makedirs(os.path.join(bdir, "files"), exist_ok=True)
    manifest = {"from": base, "to": new, "date": stamp, "saved": [], "added": []}
    for k in ("update", "remove"):
        for s in steps[k]:
            src = os.path.join(ROOT, s["path"])
            dst = os.path.join(bdir, "files", s["path"])
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            shutil.copy2(src, dst)
            st = os.stat(src)
            manifest["saved"].append({"path": s["path"], "mode": st.st_mode & 0o7777,
                                      "uid": st.st_uid, "gid": st.st_gid})
    manifest["added"] = [s["path"] for s in steps["add"]] + \
                        [s["path"] + ".aios-new" for s in steps["conflict"]]
    with open(os.path.join(bdir, "manifest.json"), "w") as f:
        json.dump(manifest, f, indent=1)

    for s in steps["update"] + steps["add"]:
        write_file(s["path"], blob(new, f"{OVERLAY}/{s['path']}"), s["mode"])
    for s in steps["conflict"]:
        write_file(s["path"] + ".aios-new", blob(new, f"{OVERLAY}/{s['path']}"), s["mode"])
    for s in steps["remove"]:
        os.unlink(os.path.join(ROOT, s["path"]))
    with open(CURRENT, "w") as f:
        f.write(new + "\n")

    touched = [s["path"] for k in ("update", "add", "remove") for s in steps[k]]
    hint = "Log out and back in (or reboot) to load every change."
    if any(p.startswith("etc/systemd/") for p in touched):
        subprocess.run(["systemctl", "daemon-reload"], capture_output=True)
    if "etc/aios/llama.conf" in touched or "usr/bin/aios-llama" in touched:
        hint = "Run: sudo systemctl restart aios-llama, then log out and back in."
    data = {"from": base, "to": new, "changes": steps, "backup": bdir, "needs_image": image}
    lines = [f"Updated to {new[:10]}: {len(touched)} files."]
    if steps["conflict"]:
        lines.append("Local changes kept; compare with the .aios-new files:")
        lines += [f"  /{s['path']}" for s in steps["conflict"]]
    lines.append("Undo with: sudo aios update code rollback")
    return Result(True, "OK", data, hint, text="\n".join(lines))


def code_rollback(args):
    r = need_root("rollback")
    if r:
        return r
    try:
        last = sorted(d for d in os.listdir(UPDATES) if not d.endswith(".undone"))[-1]
    except (OSError, IndexError):
        return fail("UPDATE_NO_BACKUP", text="There is no update to undo.")
    bdir = os.path.join(UPDATES, last)
    with open(os.path.join(bdir, "manifest.json")) as f:
        m = json.load(f)
    for path in m["added"]:
        try:
            os.unlink(os.path.join(ROOT, path))
        except FileNotFoundError:
            pass
    for s in m["saved"]:
        dest = os.path.join(ROOT, s["path"])
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        shutil.copy2(os.path.join(bdir, "files", s["path"]), dest)
        os.chmod(dest, s["mode"])
        if os.geteuid() == 0:
            os.chown(dest, s["uid"], s["gid"])
    if m.get("from"):
        with open(CURRENT, "w") as f:
            f.write(m["from"] + "\n")
    else:
        try:
            os.unlink(CURRENT)
        except FileNotFoundError:
            pass
    os.rename(bdir, bdir + ".undone")
    return Result(True, "OK", {"restored": m.get("from"), "undone": m["to"]},
                  "Log out and back in (or reboot) to load every change.",
                  text=f"Restored the code from before {m['date']}.")


def register(sub):
    p = sub.add_parser("update", help="update AIOS")
    s = p.add_subparsers(dest="action", required=True)
    c = s.add_parser("code", help="scripts and configuration from the AIOS git repository")
    cs = c.add_subparsers(dest="code_action", required=True)
    cs.add_parser("check", help="download and show what would change").set_defaults(func=code_check)
    a = cs.add_parser("apply", help="apply the changes (asks first)")
    a.add_argument("--confirm", metavar="TOKEN")
    a.set_defaults(func=code_apply)
    cs.add_parser("rollback", help="undo the last update").set_defaults(func=code_rollback)
    cs.add_parser("notify", help="check and tell the desktop once per new version (daily timer)"
                  ).set_defaults(func=code_notify)
