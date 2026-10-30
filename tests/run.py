#!/usr/bin/env python3
"""AIOS — pruebas de la imagen ('make test'). Dos fases:

  native  binarios reales de la imagen ejecutados en el VPS (rápido):
          el agente con el modelo de verdad usando herramientas, 'look' con
          visión, reconocimiento de voz y el chat contra un proveedor externo.
  vm      la imagen arrancada en QEMU (snapshot: no se modifica nada):
          tests/vm-checks.sh por la consola serie, primer arranque, y desde
          fuera el audio grabado por QEMU y una captura de la sesión.

  install aios-install desde el USB a un segundo disco y ese disco arrancado
          en BIOS y en UEFI (frase de /home por la consola serie).

Uso: tests/run.py [native|vm|install|all]. Resultados en build/test-results/.
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
        # Como aios-llama: plantilla con el historial estable y estados guardados en disco
        tpl, slots = f"{tmp}/chat-template.jinja", f"{tmp}/slots"
        os.makedirs(slots)
        subprocess.run(["python3", "-I", f"{LIB}/aios/gguf.py", "template", model, tpl])
        llama = subprocess.Popen(target_cmd(f"{TARGET}/usr/bin/llama-server", "-m", model, "--mmproj", mmproj,
                                            "--host", "127.0.0.1", "--port", str(port), "-c", "8192",
                                            "-t", str(min(8, os.cpu_count())), "-np", "2", "--kv-unified", "--jinja",
                                            *(["--chat-template-file", tpl] if os.path.exists(tpl) else []),
                                            "--slot-save-path", slots),
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
        report("agent-asks-before-change", "Run 'aios ui brightness 80'" in out, "no confirmation prompt")
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

        # Prompt fijo guardado: la primera vez se procesa y se guarda; la segunda se
        # restaura y un mensaje nuevo solo procesa la pregunta
        probe = (f"import importlib.machinery as M, importlib.util as U, json\n"
                 f"l=M.SourceFileLoader('c','{OVERLAY}/usr/bin/aios-chat'); m=U.module_from_spec(U.spec_from_loader('c',l)); l.exec_module(m)\n"
                 f"m.warm_prefix(); m.warm_prefix()\n"
                 # otra petición entre medias (como /look o el diag): va al slot 1 y no borra el del chat
                 f"m.local_post('/completion', {{'prompt': 'An unrelated request. ' * 40, 'n_predict': 1, 'id_slot': 1}})\n"
                 f"r=m.local_post('/v1/chat/completions', {{'messages': [{{'role':'system','content':m.SYSTEM}}, {{'role':'user','content':'Hola'}}], "
                 f"'tools': m.TOOLS, 'max_tokens': 8, 'chat_template_kwargs': {{'enable_thinking': False}}, 'id_slot': m.SLOT}})\n"
                 f"print(json.dumps(r['timings']))")
        r = subprocess.run(["python3", "-B", "-c", probe], capture_output=True, text=True, timeout=600,
                           env=dict(chat_env, AIOS_LLAMA_PORT=str(port)))
        saved = glob.glob(f"{slots}/prefix-*.bin")
        try:
            processed = json.loads(r.stdout.strip().splitlines()[-1])["prompt_n"]
        except (ValueError, IndexError, KeyError):
            processed = None
        # Con --mmproj, llama.cpp no guarda estados en disco (501): se exige lo que
        # sí vale, el prefijo ya procesado antes del primer mensaje
        report("prefix-warm", processed is not None and processed < 60,
               f"processed={processed} saved_to_disk={len(saved)} {r.stderr[-200:]}")
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
        # Receptor de emparejamiento (aios ai pair) como el del VPS
        pport = free_port()
        os.makedirs(f"{tmp}/diag")
        open(f"{tmp}/diag.token", "w").write("token-de-prueba-0123456789")
        procs.append(subprocess.Popen(["python3", "-I", f"{ROOT}/scripts/diag-server.py", "--port", str(pport),
                                       "--dir", f"{tmp}/diag", "--token-file", f"{tmp}/diag.token",
                                       "--public-url", f"http://10.0.2.2:{pport}"],
                                      stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL))
        ser, mon, wav = f"{tmp}/serial.sock", f"{tmp}/monitor.sock", f"{RESULTS}/vm-audio.wav"
        kvm = ["-enable-kvm", "-cpu", "host"] if os.access("/dev/kvm", os.W_OK) else []
        # Sin KVM cada CPU virtual es un hilo del VPS: más CPU, prueba más rápida.
        # 12 de 16 por defecto: en el VPS corre también el llama de llama-hardened.
        smp = os.environ.get("AIOS_TEST_SMP", "12")
        qemu = subprocess.Popen(["qemu-system-x86_64", *kvm, "-m", "6G", "-smp", smp,
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
        # Descargado a un fichero y con la entrada en /dev/null: con 'curl | sh', una
        # orden que lea la entrada estándar se come un trozo del propio guion
        s.send(f"curl -s -o /tmp/vm-checks.sh http://10.0.2.2:{hport}/vm-checks.sh && HOST=10.0.2.2 "
               f"GITPORT={hport} MOCKPORT={mport} PAIRPORT={pport} sh /tmp/vm-checks.sh </dev/null 2>&1; "
               f"echo CHECKS-END")
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


# --- Fase install: aios-install desde el USB a un segundo disco ------------------------

def qemu_boot(tmp, drives, uefi=False, name="vm"):
    """QEMU con unos discos (el primero arranca) y la consola serie en un socket."""
    ser = f"{tmp}/{name}.sock"
    fw = []
    if uefi:
        code = "/usr/share/OVMF/OVMF_CODE_4M.fd"
        shutil.copy("/usr/share/OVMF/OVMF_VARS_4M.fd", f"{tmp}/{name}-vars.fd")
        fw = ["-drive", f"if=pflash,format=raw,readonly=on,file={code}",
              "-drive", f"if=pflash,format=raw,file={tmp}/{name}-vars.fd"]
    kvm = ["-enable-kvm", "-cpu", "host"] if os.access("/dev/kvm", os.W_OK) else []
    disks = []
    for path, snapshot in drives:
        disks += ["-drive", f"file={path},format=raw,if=virtio" + (",snapshot=on" if snapshot else "")]
    q = subprocess.Popen(["qemu-system-x86_64", *kvm, "-m", "6G", "-smp", os.environ.get("AIOS_TEST_SMP", "12"),
                          *fw, *disks, "-display", "none", "-serial", f"unix:{ser},server,nowait",
                          "-nic", "user,model=virtio-net-pci"],
                         stdout=subprocess.DEVNULL, stderr=open(f"{RESULTS}/qemu-{name}.log", "w"))
    time.sleep(2)
    return q, Serial(ser)


def serial_login(s, q, seconds=900, passphrase=None):
    """Espera el login (contestando antes a la frase de /home si se pide) y entra como aios."""
    end = time.time() + seconds
    asked = 0
    while time.time() < end and q.poll() is None:
        if passphrase and s.wait(rb"passphrase for", 5) and asked < 5:
            # la primera vez mal: tries=0 debe volver a preguntar
            s.send("clave-mala" if asked == 0 else passphrase)
            asked += 1
            # al teclear, systemd repinta el prompt (borra «press TAB»): no es una
            # pregunta nueva. Si la nueva llegara dentro de estos 2 s y se perdiera,
            # el Intro de abajo cuenta como intento vacío y vuelve a preguntar.
            time.sleep(2)
            s.wait(rb"$^", 0.5)
            s.buf = s.buf.replace(b"passphrase for", b"")
            continue
        if s.wait(rb"login: $", 10):
            s.send("aios")
            s.wait(rb"Password: ", 30)
            s.send("aios")
            # el prompt de aios lleva color: «$\e[0m »
            return s.wait(rb"\$(\x1b\[[0-9;]*m)* ", 120), asked
        s.send("")
    return False, asked


def serial_run(s, cmd, seconds=120):
    s.buf = b""
    s.send(f"{cmd}; echo RUN-END")
    s.wait(rb"\nRUN-END\r?\n", seconds)
    return s.text()


def install():
    print("== install: aios-install desde el USB a un segundo disco (QEMU)", flush=True)
    if not os.path.exists(IMAGE):
        report("install-image", False, "no image: run 'make' first")
        return
    # el disco de destino ocupa ~7 GB: en build/, no en /tmp (puede ser tmpfs)
    tmp = tempfile.mkdtemp(prefix="aios-install-", dir=os.path.join(ROOT, "build"))
    disk = f"{tmp}/disk.img"
    q = None
    try:
        with open(disk, "wb") as f:
            f.truncate(30 * 1024 ** 3)
        q, s = qemu_boot(tmp, [(IMAGE, True), (disk, False)], name="usb")
        ok, _ = serial_login(s, q)
        report("install-usb-boots", ok, s.text()[-300:])
        if not ok:
            return
        out = serial_run(s, "aios-install --list --json")
        m = re.search(r"^\[.*\]$", out, re.M)
        lst = {d["name"]: d for d in json.loads(m.group(0))} if m else {}
        report("install-list", lst.get("vda", {}).get("usable") is False and lst.get("vdb", {}).get("usable"),
               out[-300:])
        out = serial_run(s, "echo aios | sudo -S -p '' aios-install --disk /dev/vdb --confirm vda "
                            "--passphrase-file /dev/null; echo RC=$?")
        report("install-refuses-mismatch", "RC=1" in out and "Not confirmed" in out, out[-300:])
        out = serial_run(s, "printf 'clave-de-prueba\\n' > /tmp/pp; echo aios | sudo -S -p '' "
                            "aios-install --disk /dev/vdb --confirm vdb --passphrase-file /tmp/pp; echo RC=$?", 3600)
        open(f"{RESULTS}/install-run.txt", "w").write(out)
        report("install-runs", "RC=0" in out and "AIOS is installed" in out, out[-400:])
        q.kill()
        q.wait()
        if "RC=0" not in out:
            return

        # El disco solo, en BIOS: frase de /home (una mal, otra bien), sesión y montajes
        q, s = qemu_boot(tmp, [(disk, True)], name="disk-bios")
        ok, asked = serial_login(s, q, passphrase="clave-de-prueba")
        open(f"{RESULTS}/install-serial-bios.txt", "w").write(s.text())
        report("install-boots-bios", ok, s.text()[-300:])
        report("install-asks-again", asked >= 2, f"passphrase asked {asked} times")
        if ok:
            out = serial_run(s, "findmnt -no SOURCE /; findmnt -no SOURCE,FSTYPE /home; "
                                "ls -a ~ | grep -c bash_profile; cat /etc/aios/install.conf")
            open(f"{RESULTS}/install-bios.txt", "w").write(out)
            report("install-root-on-disk", re.search(r"^/dev/vda2$", out, re.M) is not None, out[-300:])
            report("install-home-encrypted", re.search(r"^/dev/mapper/home ext4$", out, re.M) is not None,
                   out[-300:])
            report("install-home-copied", re.search(r"^1$", out, re.M) is not None, out[-300:])
        q.kill()
        q.wait()

        # UEFI con el USB también enchufado: arranca el disco, no el USB
        q, s = qemu_boot(tmp, [(disk, True), (IMAGE, True)], uefi=True, name="disk-uefi")
        ok, _ = serial_login(s, q, passphrase="clave-de-prueba")
        open(f"{RESULTS}/install-serial-uefi.txt", "w").write(s.text())
        report("install-boots-uefi", ok, s.text()[-300:])
        if ok:
            out = serial_run(s, "findmnt -no SOURCE /; cat /proc/cmdline")
            report("install-uefi-not-usb", re.search(r"^/dev/vda2$", out, re.M) is not None
                   and "a105a105" not in out, out[-300:])
    except (OSError, subprocess.SubprocessError, ValueError) as e:
        report("install-setup", False, str(e))
    finally:
        if q and q.poll() is None:
            q.kill()
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
    if which in ("install", "all"):
        install()
    failed = [r for r in results if not r[1]]
    print(f"\n{len(results) - len(failed)}/{len(results)} passed. Details in {RESULTS}/")
    for name, _, detail in failed:
        print(f"  FAIL {name}: {detail}")
    return 1 if failed or not results else 0


if __name__ == "__main__":
    sys.exit(main())
