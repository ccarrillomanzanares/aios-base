#!/usr/bin/env python3
"""AIOS — pruebas de la imagen ('make test'). Dos fases:

  native  binarios reales de la imagen ejecutados en el VPS (rápido):
          el agente con el modelo de verdad usando herramientas, 'look' con
          visión, reconocimiento de voz y el chat contra un proveedor externo.
  vm      la imagen arrancada en QEMU (snapshot: no se modifica nada):
          tests/vm-checks.sh por la consola serie, primer arranque, y desde
          fuera el audio grabado por QEMU y una captura de la sesión.

Uso: tests/run.py [native|vm|all]. Resultados en build/test-results/.
Sin KVM la VM es lenta (~10 min); la fase native no la necesita.
"""
import glob
import json
import os
import pty
import re
import select
import shutil
import signal
import socket
import struct
import subprocess
import sys
import tempfile
import time
import urllib.request
import wave

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "build", "output")
TARGET = os.path.join(OUT, "target")
IMAGE = os.path.join(OUT, "images", "aios.img")
RESULTS = os.path.join(ROOT, "build", "test-results")
OVERLAY = os.path.join(ROOT, "board", "aios", "rootfs-overlay")
LIB = os.path.join(OVERLAY, "usr", "lib", "aios")
MODELS = os.path.join(TARGET, "usr", "share", "aios", "models")

results = []


def report(name, ok, detail=""):
    results.append((name, ok, detail))
    print(f"{'PASS' if ok else 'FAIL'} {name}" + (f": {detail}" if detail and not ok else ""), flush=True)


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def cpu_variant():
    """La variante de ggml para la CPU del VPS (la imagen trae todas)."""
    flags = open("/proc/cpuinfo").read()
    return "haswell" if " avx2" in flags else "sandybridge" if " avx" in flags else "x64"


def target_cmd(binary, *args):
    """Ejecuta un binario de la imagen en el VPS con sus propias bibliotecas.
    whisper lleva su propio ggml con el mismo nombre que el de llama.cpp: sus
    bibliotecas van primero, como hace su RPATH en la imagen."""
    libs = [f"{TARGET}/usr/lib", f"{TARGET}/lib"]
    if "/opt/whisper/" in binary:
        libs.insert(0, f"{TARGET}/opt/whisper/lib")
    libs = ":".join(libs)
    return [f"{TARGET}/lib/ld-linux-x86-64.so.2", "--library-path", libs, binary, *args]


def wait_http(url, seconds, proc=None):
    end = time.time() + seconds
    while time.time() < end:
        if proc and proc.poll() is not None:
            return False
        try:
            with urllib.request.urlopen(url, timeout=2) as r:
                if r.status == 200:
                    return True
        except OSError:
            pass
        time.sleep(1)
    return False


def pty_run(argv, env, script, timeout=600):
    """Conversación por pseudoterminal: script = [(espera_regex, texto_a_enviar)]."""
    pid, fd = pty.fork()
    if pid == 0:
        os.environ.update(env)
        os.execvp(argv[0], argv)
    out = b""
    end = time.time() + timeout

    def read_until(pat):
        nonlocal out
        while time.time() < end:
            r, _, _ = select.select([fd], [], [], 0.2)
            if r:
                try:
                    out += os.read(fd, 65536)
                except OSError:
                    return False
            # sin colores: el chat pinta en gris "[N tokens, X tok/s]"
            if re.search(pat, re.sub(rb"\x1b\[[0-9;?]*[A-Za-z]", b"", out[-4000:])):
                return True
        return False

    ok = True
    for pat, send in script:
        if not read_until(pat):
            ok = False
            break
        if send is not None:
            os.write(fd, send.encode() + b"\r")
    try:
        os.kill(pid, signal.SIGKILL)
        os.waitpid(pid, 0)
    except OSError:
        pass
    return ok, re.sub(r"\x1b\[[0-9;?]*[A-Za-z]", "", out.decode(errors="replace"))


# --- Fase nativa ------------------------------------------------------------------------

def native():
    print("== native: binarios de la imagen en este equipo", flush=True)
    tmp = tempfile.mkdtemp(prefix="aios-test-")
    procs = []
    try:
        variant = cpu_variant()
        model = sorted(f for f in glob.glob(f"{MODELS}/*.gguf") if "mmproj" not in f)[0]
        mmproj = glob.glob(f"{MODELS}/*mmproj*.gguf")[0]
        port = free_port()
        env = dict(os.environ, GGML_BACKEND_PATH=f"{TARGET}/usr/lib/ggml/libggml-cpu-{variant}.so")
        llama = subprocess.Popen(target_cmd(f"{TARGET}/usr/bin/llama-server", "-m", model, "--mmproj", mmproj,
                                            "--host", "127.0.0.1", "--port", str(port), "-c", "8192",
                                            "-t", str(min(8, os.cpu_count())), "-np", "1", "--jinja"),
                                 env=env, stdout=open(f"{tmp}/llama.log", "w"), stderr=subprocess.STDOUT)
        procs.append(llama)
        report("native-llama-server", wait_http(f"http://127.0.0.1:{port}/health", 300, llama),
               "did not start; see llama.log")

        # 'aios' de prueba: la CLI del overlay, con un /sys falso (brillo al 50 %)
        sysfs = f"{tmp}/sys/class/backlight/intel_backlight"
        os.makedirs(sysfs)
        for k, v in (("type", "raw"), ("max_brightness", "1000"), ("brightness", "500")):
            open(f"{sysfs}/{k}", "w").write(v + "\n")
        bindir = f"{tmp}/bin"
        os.makedirs(bindir)
        with open(f"{bindir}/aios", "w") as f:
            f.write(f"#!/bin/sh\nexec python3 -B -c \"import sys; sys.path.insert(0, '{LIB}'); "
                    f"from aios.cli import main; sys.exit(main())\" \"$@\"\n")
        os.chmod(f"{bindir}/aios", 0o755)
        chat_env = {"AIOS_LLAMA_PORT": str(port), "AIOS_LIB": LIB, "AIOS_SYSFS": f"{tmp}/sys",
                    "PATH": f"{bindir}:{os.environ['PATH']}", "TERM": "dumb", "HOME": tmp,
                    "XDG_RUNTIME_DIR": tmp, "XDG_CONFIG_HOME": f"{tmp}/cfg"}
        chat = ["python3", "-B", f"{OVERLAY}/usr/bin/aios-chat"]

        # Agente: consulta (sin preguntar) y cambio (pide confirmación)
        ok, out = pty_run(chat, chat_env, [
            (rb"> $", "¿Qué brillo tiene la pantalla ahora mismo? Usa la herramienta."),
            (rb"tok/s\]\s*\r?\n\s*> $", "Pon el brillo al 80 por ciento."),
            (rb"\[y/N\] $", "y"),
            (rb"tok/s\]\s*\r?\n\s*> $", "/exit")], timeout=600)
        open(f"{RESULTS}/native-agent.txt", "w").write(out)
        report("agent-reads-with-tool", "[aios ui brightness]" in out and "50" in out, "no tool call or no 50%")
        report("agent-asks-before-change", "Run 'aios ui brightness 80" in out, "no confirmation prompt")
        now = int(open(f"{sysfs}/brightness").read())
        report("agent-change-applied", now == 800, f"brightness is {now}")
        report("chat-history-saved", bool(glob.glob(f"{tmp}/.local/share/aios/chats/*.json")), "no history file")

        # Visión: la captura de la sesión de AIOS
        p = subprocess.run(["python3", "-B", "-c", f"import sys; sys.path.insert(0,'{LIB}'); "
                            "from aios.cli import main; sys.exit(main())",
                            "ai", "look", "--file", f"{ROOT}/tests/data/aios-session.png",
                            "What words are written at the top of the screen?", "--json"],
                           capture_output=True, text=True, timeout=600,
                           env=dict(os.environ, AIOS_LLAMA_PORT=str(port), XDG_CONFIG_HOME=f"{tmp}/cfg"))
        try:
            ans = json.loads(p.stdout.strip().splitlines()[-1])
        except (ValueError, IndexError):
            ans = {}
        text = (ans.get("data") or {}).get("answer", "")
        open(f"{RESULTS}/native-look.txt", "w").write(text or p.stdout + p.stderr)
        report("look-sees-screen", ans.get("ok") and re.search(r"AIOS|TERMINAL|LOGON", text, re.I),
               (text or p.stderr)[-200:])

        # Voz: espeak de la imagen dice una frase, whisper de la imagen la transcribe
        spoken = f"{tmp}/voz.wav"
        espeak_env = dict(os.environ, ESPEAK_DATA_PATH=f"{TARGET}/usr/share")
        subprocess.run(target_cmd(f"{TARGET}/usr/bin/espeak", "-v", "es", "-s", "140", "-w", spoken,
                                  "Hola, esto es una prueba de voz del sistema."),
                       env=espeak_env, capture_output=True, timeout=60)
        resample_16k(spoken, f"{tmp}/voz16.wav")
        wmodel = glob.glob(f"{MODELS}/whisper/*.bin")
        p = subprocess.run(target_cmd(f"{TARGET}/opt/whisper/bin/whisper-cli", "-m", wmodel[0] if wmodel else "",
                                      "-f", f"{tmp}/voz16.wav", "-l", "auto", "-nt", "-np", "-t", "4"),
                           capture_output=True, text=True, timeout=300,
                           env=dict(os.environ, GGML_BACKEND_PATH=f"{TARGET}/opt/whisper/lib/libggml-cpu-{variant}.so"))
        open(f"{RESULTS}/native-voice.txt", "w").write(p.stdout + "\n---\n" + p.stderr[-2000:])
        report("voice-transcribes", "prueba" in p.stdout.lower(), p.stdout.strip()[:120] or p.stderr[-200:])

        # Chat contra un proveedor externo (servidor OpenAI simulado con X-API-Key)
        mport = free_port()
        mock = subprocess.Popen(["python3", "-B", f"{ROOT}/tests/mock_openai.py", str(mport)],
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        procs.append(mock)
        time.sleep(1)
        cli = ["python3", "-B", "-c", f"import sys; sys.path.insert(0,'{LIB}'); from aios.cli import main; sys.exit(main())"]
        cenv = dict(os.environ, XDG_CONFIG_HOME=f"{tmp}/cfg")
        subprocess.run(cli + ["ai", "add", "mock", "--url", f"http://127.0.0.1:{mport}/v1", "--api-key",
                              "secreto123", "--key-header", "X-API-Key"], env=cenv, capture_output=True)
        subprocess.run(cli + ["ai", "use", "mock", "--confirm", "send-mock"], env=cenv, capture_output=True)
        ok, out = pty_run(chat, dict(chat_env, XDG_CONFIG_HOME=f"{tmp}/cfg"),
                          [(rb"> $", "hola"), (rb"Respuesta remota", "/exit")], timeout=60)
        report("chat-remote-provider", ok and "REMOTE AI: mock" in out, out[-200:])
    except (IndexError, OSError) as e:
        report("native-setup", False, str(e))
    finally:
        for p in procs:
            p.kill()
        shutil.rmtree(tmp, ignore_errors=True)


def resample_16k(src, dst):
    """WAV mono a 16 kHz (lo que pide whisper), con interpolación lineal."""
    try:
        with wave.open(src) as w:
            rate, n = w.getframerate(), w.getnframes()
            data = struct.unpack(f"<{n}h", w.readframes(n))
    except (OSError, wave.Error, struct.error):
        return
    out_n = int(n * 16000 / rate)
    res = []
    for i in range(out_n):
        x = i * rate / 16000
        j = int(x)
        a, b = data[min(j, n - 1)], data[min(j + 1, n - 1)]
        res.append(int(a + (b - a) * (x - j)))
    with wave.open(dst, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(16000)
        w.writeframes(struct.pack(f"<{len(res)}h", *res))


# --- Fase VM -----------------------------------------------------------------------------

class Serial:
    def __init__(self, path):
        self.s = socket.socket(socket.AF_UNIX)
        self.s.connect(path)
        self.s.settimeout(1)
        self.buf = b""

    def wait(self, pat, seconds):
        end = time.time() + seconds
        while time.time() < end:
            try:
                d = self.s.recv(65536)
                if d:
                    self.buf += d
            except socket.timeout:
                pass
            if re.search(pat, self.buf):
                return True
        return False

    def send(self, text):
        self.s.sendall(text.encode() + b"\r")

    def text(self):
        txt = re.sub(r"\x1b(\[[0-9;?]*[A-Za-z]|\][^\\]*\\)", "", self.buf.decode(errors="replace"))
        return txt.replace("\r", "")


def monitor(path, cmd):
    m = socket.socket(socket.AF_UNIX)
    m.connect(path)
    time.sleep(0.5)
    m.recv(4096)
    m.send((cmd + "\n").encode())
    time.sleep(2)
    m.close()


def serve_repo(tmp):
    """Repo git servible por HTTP: el de ahora + un commit de prueba."""
    repo = f"{tmp}/www/aios-base.git"
    subprocess.run(["git", "clone", "-q", "--bare", ROOT, repo], check=True)
    work = f"{tmp}/work"
    subprocess.run(["git", "clone", "-q", repo, work], check=True)
    f = f"{work}/board/aios/rootfs-overlay/usr/bin/aios-test-update"
    open(f, "w").write("#!/bin/sh\necho 'update OK'\n")
    os.chmod(f, 0o755)
    g = ["git", "-C", work, "-c", "user.name=test", "-c", "user.email=test@aios"]
    subprocess.run(g + ["add", "-A"], check=True)
    subprocess.run(g + ["commit", "-qm", "test update"], check=True)
    subprocess.run(g + ["push", "-q", "origin", "HEAD:main"], check=True)
    subprocess.run(["git", "-C", repo, "update-server-info"], check=True)
    shutil.copy(f"{ROOT}/tests/vm-checks.sh", f"{tmp}/www/vm-checks.sh")


def vm():
    print("== vm: la imagen en QEMU (snapshot)", flush=True)
    if not os.path.exists(IMAGE):
        report("vm-image", False, "no image: run 'make' first")
        return
    tmp = tempfile.mkdtemp(prefix="aios-vm-")
    procs = []
    try:
        serve_repo(tmp)
        hport, mport = free_port(), free_port()
        procs.append(subprocess.Popen(["python3", "-m", "http.server", str(hport), "--bind", "127.0.0.1",
                                       "--directory", f"{tmp}/www"],
                                      stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL))
        procs.append(subprocess.Popen(["python3", "-B", f"{ROOT}/tests/mock_openai.py", str(mport)],
                                      stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL))
        ser, mon, wav = f"{tmp}/serial.sock", f"{tmp}/monitor.sock", f"{RESULTS}/vm-audio.wav"
        kvm = ["-enable-kvm", "-cpu", "host"] if os.access("/dev/kvm", os.W_OK) else []
        qemu = subprocess.Popen(["qemu-system-x86_64", *kvm, "-m", "6G", "-smp", "4",
                                 "-drive", f"file={IMAGE},format=raw,if=virtio,snapshot=on",
                                 # dos pantallas: extender, duplicar, apagar una
                                 "-device", "virtio-vga,max_outputs=2", "-display", "none",
                                 "-audiodev", f"wav,id=snd0,path={wav}",
                                 "-device", "intel-hda", "-device", "hda-duplex,audiodev=snd0",
                                 "-monitor", f"unix:{mon},server,nowait",
                                 "-serial", f"unix:{ser},server,nowait",
                                 "-nic", "user,model=virtio-net-pci"],
                                stdout=subprocess.DEVNULL, stderr=open(f"{RESULTS}/qemu.log", "w"))
        procs.append(qemu)
        time.sleep(2)
        s = Serial(ser)
        end = time.time() + 600
        while not s.wait(rb"login: $", 15):
            s.send("")
            if time.time() > end or qemu.poll() is not None:
                report("vm-boots", False, "no login prompt")
                return
        report("vm-boots", True)
        time.sleep(60)  # sesión gráfica, servicios de usuario y modelo
        s.send("aios")
        s.wait(rb"Password: ", 30)
        s.send("aios")
        s.wait(rb"\$ $", 60)
        s.buf = b""
        s.send(f"curl -s http://10.0.2.2:{hport}/vm-checks.sh | HOST=10.0.2.2 GITPORT={hport} "
               f"MOCKPORT={mport} sh 2>&1; echo CHECKS-END")
        s.wait(rb"\nCHECKS-END\r?\n", 2400)  # \n delante: no el eco de la orden
        out = s.text()
        open(f"{RESULTS}/vm-checks.txt", "w").write(out)
        for m in re.finditer(r"^(PASS|FAIL) (\S+)(?:: (.*))?$", out, re.M):
            report(m.group(2), m.group(1) == "PASS", m.group(3) or "")
        if "CHECKS DONE" not in out:
            report("vm-checks-complete", False, "the script did not finish")

        # Primer arranque: contraseña nueva y root bloqueado
        s.buf = b""
        s.send("aios-firstboot --force")
        steps = [(rb"Language \(number, Enter to keep\): $", ""),
                 (rb"Keyboard \(number, Enter to keep\): $", ""),
                 (rb"Time zone \(number, Enter to keep\): $", ""),
                 (rb"\[Y/n\] $", "y"), (rb"New password: $", "nueva-clave-1"),
                 (rb"Repeat it: $", "nueva-clave-1"), (rb"Password changed", None)]
        ok = True
        for pat, ans in steps:
            if not s.wait(pat, 120):
                ok = False
                break
            if ans is not None:
                s.send(ans)
        s.wait(rb"\$ $", 120)
        report("firstboot-password", ok, s.text()[-300:])
        s.buf = b""
        s.send("echo nueva-clave-1 | sudo -S -p '' grep '^root:' /etc/shadow | cut -d: -f2 | cut -c1; echo FB-END")
        s.wait(rb"\nFB-END\r?\n", 60)
        report("firstboot-root-locked", re.search(r"^!$", s.text(), re.M) is not None, s.text()[-200:])

        monitor(mon, f"screendump {tmp}/screen.ppm")
        try:
            from PIL import Image  # solo para guardar la captura en PNG
            Image.open(f"{tmp}/screen.ppm").save(f"{RESULTS}/vm-screen.png")
        except Exception:
            shutil.copy(f"{tmp}/screen.ppm", f"{RESULTS}/vm-screen.ppm")
        monitor(mon, "quit")
        qemu.wait(30)
        report("audio-reaches-speakers", audio_has_sound(wav), "the recorded output is silent")
    except (OSError, subprocess.SubprocessError) as e:
        report("vm-setup", False, str(e))
    finally:
        for p in procs:
            if p.poll() is None:
                p.kill()
        shutil.rmtree(tmp, ignore_errors=True)


def audio_has_sound(path):
    """¿Hay sonido en lo que QEMU grabó de la tarjeta (aios audio test, aplay)?"""
    try:
        with wave.open(path) as w:
            n, width, ch = w.getnframes(), w.getsampwidth(), w.getnchannels()
            data = w.readframes(n)
    except (OSError, wave.Error):
        return False
    if width != 2 or not data:
        return False
    samples = struct.unpack(f"<{len(data) // 2}h", data)
    loud = sum(1 for x in samples if abs(x) > 1000)
    return loud > 0.01 * len(samples) / ch * 0.1


def main():
    which = sys.argv[1] if len(sys.argv) > 1 else "all"
    os.makedirs(RESULTS, exist_ok=True)
    if which in ("native", "all"):
        native()
    if which in ("vm", "all"):
        vm()
    failed = [r for r in results if not r[1]]
    print(f"\n{len(results) - len(failed)}/{len(results)} passed. Details in {RESULTS}/")
    for name, _, detail in failed:
        print(f"  FAIL {name}: {detail}")
    return 1 if failed or not results else 0


if __name__ == "__main__":
    sys.exit(main())
