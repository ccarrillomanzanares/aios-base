"""voice — hablar con AIOS: grabar (PipeWire), transcribir (whisper.cpp, en
local) y leer en voz alta (espeak).

Pulsar y mantener Super+Espacio graba; al soltar se transcribe y el texto
llega al chat (fichero de entrada + SIGUSR1 al proceso de aios-chat). En el
chat, /voice graba hasta pulsar Enter.
"""
import json
import os
import re
import signal
import subprocess
import time

WHISPER = "/opt/whisper/bin/whisper-cli"
MODEL_DIR = "/usr/share/aios/models/whisper"
MIN_SECONDS = 0.6   # pulsaciones más cortas se ignoran


def runtime_dir():
    return os.environ.get("XDG_RUNTIME_DIR") or f"/run/user/{os.getuid()}"


def paths():
    d = runtime_dir()
    return {"wav": os.path.join(d, "aios-voice.wav"), "pid": os.path.join(d, "aios-voice.pid"),
            "inbox": os.path.join(d, "aios-chat.inbox"), "chat": os.path.join(d, "aios-chat.pid")}


def recording():
    try:
        pid = int(open(paths()["pid"]).read())
        os.kill(pid, 0)
        return pid
    except (OSError, ValueError):
        return None


def refresh_bar():
    """Repinta la barra (indicador ● REC) sin esperar a su ciclo de 5 s."""
    subprocess.run(["pkill", "-USR1", "-f", "aios-status"], capture_output=True)


def start():
    """Empieza a grabar en segundo plano (16 kHz mono, lo que pide Whisper)."""
    if recording():
        return False
    p = paths()
    proc = subprocess.Popen(["pw-record", "--rate", "16000", "--channels", "1",
                             "--format", "s16", p["wav"]],
                            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL, start_new_session=True)
    with open(p["pid"], "w") as f:
        f.write(str(proc.pid))
    refresh_bar()
    return True


def stop():
    """Para la grabación; devuelve la ruta del WAV o None si fue demasiado corta."""
    p = paths()
    pid = recording()
    if not pid:
        return None
    os.kill(pid, signal.SIGINT)  # pw-record cierra bien el WAV con SIGINT
    for _ in range(50):
        try:
            os.kill(pid, 0)
            time.sleep(0.05)
        except OSError:
            break
    try:
        os.unlink(p["pid"])
    except FileNotFoundError:
        pass
    refresh_bar()
    try:
        size = os.path.getsize(p["wav"])
    except OSError:
        return None
    return p["wav"] if size > 44 + 16000 * 2 * MIN_SECONDS else None


def model():
    try:
        files = sorted(f for f in os.listdir(MODEL_DIR) if f.endswith(".bin"))
    except OSError:
        files = []
    return os.path.join(MODEL_DIR, files[0]) if files else None


def transcribe(wav, language="auto"):
    """(texto, idioma) con whisper.cpp; el idioma lo detecta él."""
    m = model()
    if not m or not os.path.exists(WHISPER):
        raise RuntimeError("speech recognition is not installed")
    threads = str(max(1, min(4, os.cpu_count() or 1)))
    p = subprocess.run([WHISPER, "-m", m, "-f", wav, "-l", language, "-t", threads,
                        "-nt", "-np"], capture_output=True, text=True, timeout=300)
    if p.returncode != 0:
        raise RuntimeError(p.stderr.strip()[-300:] or "whisper failed")
    text = " ".join(line.strip() for line in p.stdout.splitlines() if line.strip())
    text = re.sub(r"\[[A-Z_ ]+\]|\((?:[^)]*music|[^)]*silence)[^)]*\)", "", text, flags=re.I).strip()
    lang = re.search(r"auto-detected language:\s*(\w+)", p.stderr)
    return text, (lang.group(1) if lang else (None if language == "auto" else language))


def deliver(text, lang):
    """Entrega el texto al chat abierto. False si no hay chat."""
    p = paths()
    try:
        pid = int(open(p["chat"]).read())
        os.kill(pid, 0)
    except (OSError, ValueError):
        return False
    with open(p["inbox"], "w") as f:
        json.dump({"text": text, "lang": lang}, f)
    os.kill(pid, signal.SIGUSR1)
    return True


_speaker = None


def speak(text, lang=None):
    """Lee el texto en voz alta sin bloquear; corta lo que estuviera diciendo."""
    global _speaker
    if _speaker and _speaker.poll() is None:
        _speaker.kill()
    voice = (lang or os.environ.get("LANG", "es")[:2] or "es").lower()
    text = re.sub(r"[*_`#>|]", " ", text)[:2000]  # sin marcas de markdown
    cmd = f"espeak -v {voice} -s 165 --stdout | pw-play -"
    try:
        _speaker = subprocess.Popen(["sh", "-c", cmd], stdin=subprocess.PIPE,
                                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                    start_new_session=True)
        _speaker.stdin.write(text.encode())
        _speaker.stdin.close()
    except OSError:
        _speaker = None
