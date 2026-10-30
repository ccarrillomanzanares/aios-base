#!/bin/sh
# AIOS — comprobaciones dentro de la imagen (las lanza tests/run.py por la
# consola serie, como el usuario aios). Cada una imprime "PASS nombre" o
# "FAIL nombre: detalle". Todo lo de prueba va a /run o /tmp: la VM arranca en
# modo snapshot y al apagarla no queda nada.
# Variables: HOST (el VPS visto desde QEMU), GITPORT, MOCKPORT, PW (contraseña).
HOST=${HOST:-10.0.2.2}; PW=${PW:-aios}
S() { echo "$PW" | sudo -S -p "" "$@"; }
pass() { echo "PASS $1"; }
fail() { echo "FAIL $1: $2"; }
check() { # check <nombre> <orden...>: PASS si la orden sale con 0
    n="$1"; shift
    if out=$("$@" 2>&1); then pass "$n"; else fail "$n" "$(echo "$out" | tail -2 | tr '\n' ' ')"; fi
}
jcode() { python3 -c 'import json,sys; print(json.loads(sys.stdin.read().strip().splitlines()[-1]).get("code"))'; }

# La VM sin KVM es lenta: swayidle bloquearía la sesión a los 5 min y sway no
# deja capturar una pantalla bloqueada. En pausa durante las comprobaciones.
pkill -STOP -x swayidle

# --- Sistema --------------------------------------------------------------------
# Ningún ciclo de dependencias al arrancar: systemd los rompe quitando trabajos
# (con aios-zram mal ordenado se perdía el montaje de /tmp)
cyc=$(journalctl -b --no-pager | grep -c 'ordering cycle')
[ "$cyc" = 0 ] && [ "$(findmnt -n -o FSTYPE /tmp)" = tmpfs ] && pass boot-no-cycles || \
    fail boot-no-cycles "$cyc cycle(s); /tmp is $(findmnt -n -o FSTYPE /tmp)"
[ -z "$(systemctl --failed --no-legend)" ] && pass services-ok || fail services-ok "$(systemctl --failed --no-legend | tr '\n' ' ')"
[ "$(systemctl is-active sshd)" != active ] && pass sshd-off || fail sshd-off "sshd is running"
# Cortafuegos: tabla cargada y entrada cerrada por defecto (la salida la prueban
# todas las comprobaciones que bajan algo del VPS)
fw=$(S nft list chain inet aios input 2>&1)
echo "$fw" | grep -q 'policy drop' && pass firewall-on || fail firewall-on "$(systemctl is-active aios-firewall) $(echo "$fw" | head -2 | tr '\n' ' ')"
S systemctl reload aios-firewall && [ "$(S nft list tables | grep -c 'inet aios')" = 1 ] && pass firewall-reload || fail firewall-reload "reload failed or duplicated table"
open=$(ss -ltnuH 2>/dev/null | awk '{print $5}' | grep -vE '^(127\.|\[::1\]|.*%lo:|10\.0\.2\.15%.*:68$)' | tr '\n' ' ')
[ -z "$open" ] && pass no-open-ports || fail no-open-ports "$open"
grep -q '^COMMIT=' /etc/aios/build-info && pass build-info || fail build-info "missing"
# (el passwd de BusyBox no tiene -S: el estado se lee de /etc/shadow)
[ -n "$(S grep '^root:' /etc/shadow | cut -d: -f2)" ] && pass root-status || fail root-status "no root entry in shadow"
command -v chpasswd >/dev/null && pass chpasswd-present || fail chpasswd-present "aios-firstboot needs it"
# La VM tiene puerto serie (tipo 16550A): la condición de aios-uart.conf debe dejar su getty
[ "$(systemctl is-active serial-getty@ttyS0)" = active ] && pass serial-getty || fail serial-getty "$(systemctl is-active serial-getty@ttyS0)"
# Historial estable para la caché del prompt (plantilla generada por aios-llama)
llargs=$(tr '\0' ' ' < /proc/$(pidof llama-server | cut -d' ' -f1)/cmdline 2>/dev/null)
echo "$llargs" | grep -q -- '--chat-template-file' && pass llama-stable-template || \
    fail llama-stable-template "$(echo "$llargs" | cut -c1-200)"

# --- Red -------------------------------------------------------------------------
check net-status aios net status
[ "$(aios net status --json | jcode)" = OK ] && pass net-json || fail net-json "not OK"

# Wifi con radios virtuales: wlan1 punto de acceso con DHCP, wlan0 estación
S modprobe mac80211_hwsim radios=2 && sleep 4
printf '[Match]\nName=wlan1\n[Network]\nAddress=192.168.80.1/24\nDHCPServer=yes\n' > /tmp/ap.network
S mkdir -p /run/systemd/network && S cp /tmp/ap.network /run/systemd/network/10-aios-test-ap.network
S networkctl reload; iwctl device wlan1 set-property Mode ap; sleep 2
# El servidor DHCP del punto de acceso de prueba está en esta misma VM: el
# cortafuegos (solo cliente) bloquearía sus peticiones. Abierto solo en wlan1.
S nft add rule inet aios input iifname wlan1 udp dport 67 accept
iwctl ap wlan1 start AIOS-TEST testpass123; sleep 2; S networkctl reconfigure wlan1; sleep 3
aios net wifi scan | grep -q AIOS-TEST && pass wifi-scan || fail wifi-scan "AIOS-TEST not found"
[ "$(aios net wifi connect AIOS-TEST --json | jcode)" = WIFI_NEEDS_PASSWORD ] && pass wifi-needs-password || fail wifi-needs-password "?"
# Nombre aproximado (como lo escribe el modelo o la voz): encuentra AIOS-TEST
[ "$(aios net wifi connect "aios test" --json | jcode)" = WIFI_NEEDS_PASSWORD ] && pass wifi-fuzzy-ssid || fail wifi-fuzzy-ssid "?"
[ "$(aios net wifi connect AIOS-TEST --password malamala1 --json | jcode)" = WIFI_AUTH_FAILED ] && pass wifi-bad-password || fail wifi-bad-password "?"
S ls /var/lib/iwd | grep -q AIOS-TEST && fail wifi-no-residue "profile saved after failure" || pass wifi-no-residue
r=$(aios net wifi connect AIOS-TEST --password testpass123 --json); [ "$(echo "$r" | jcode)" = OK ] && pass wifi-connect || fail wifi-connect "$r"
python3 -c "import runpy; print(runpy.run_path('/usr/bin/aios-status')['line']())" | grep -q "WIFI AIOS-TEST" && pass bar-wifi || fail bar-wifi "bar"
# El agente conecta: la contraseña se teclea sin eco (primero mala, luego buena) y el
# modelo no la ve. Se olvida la red para que la pida.
iwctl station wlan0 disconnect; iwctl known-networks AIOS-TEST forget
cat > /tmp/wifi-drive.py <<'PYEOF'
import os, pty, re, sys, time
pid, fd = pty.fork()
if pid == 0:
    os.execvp("python3", ["python3", "-c", "import importlib.machinery as M, importlib.util as U, json\n"
        "l=M.SourceFileLoader('c','/usr/bin/aios-chat'); m=U.module_from_spec(U.spec_from_loader('c',l)); l.exec_module(m)\n"
        "print('RESULT', json.dumps(m.run_aios('net wifi connect \"aios test\" --password delmodelo')))"])
out = b""
def wait(pat, t=180):
    global out
    end = time.time() + t
    while time.time() < end:
        try:
            out += os.read(fd, 4096)
        except OSError:
            break
        if re.search(pat, out):
            return
    print("TIMEOUT", pat, out.decode(errors="replace")[-300:]); sys.exit(1)
wait(rb'Password for wifi "AIOS-TEST"'); os.write(fd, b"malamala1\n")
wait(rb'Wrong password\. Password for wifi'); os.write(fd, b"testpass123\n")
wait(rb"RESULT .*\n")
text = out.decode(errors="replace")
print("SHOWN" if "testpass123" in text or "malamala1" in text else "HIDDEN")
print(text[text.index("RESULT"):].splitlines()[0])
PYEOF
r=$(python3 /tmp/wifi-drive.py 2>&1)
echo "$r" | grep -q HIDDEN && echo "$r" | grep -q '"code": "OK"' && pass agent-wifi-password || fail agent-wifi-password "$(echo "$r" | tail -2 | tr '\n' ' ')"
check wifi-disconnect aios net wifi disconnect

# --- Sonido ------------------------------------------------------------------------
for u in pipewire pipewire-pulse wireplumber; do
    [ "$(systemctl --user is-active $u)" = active ] && pass "audio-$u" || fail "audio-$u" "$(systemctl --user is-active $u)"
done
# Solo los de usuario: los de sistema abrían la tarjeta y dejaban sin micrófono (HP 15s)
sysaudio=$(systemctl list-units --no-legend --plain 'pipewire*' 'wireplumber*' | awk '{print $1}' | tr '\n' ' ')
[ -z "$sysaudio" ] && pass audio-no-system-pipewire || fail audio-no-system-pipewire "$sysaudio"
[ -f /usr/lib/spa-0.2/bluez5/libspa-bluez5.so ] && pass audio-bluetooth-plugin || fail audio-bluetooth-plugin "PipeWire built without bluez5"
check audio-status aios audio status
check audio-volume aios audio volume 60
pactl info 2>/dev/null | grep -q "on PipeWire" && pass audio-pulse-apps || fail audio-pulse-apps "pactl does not see PipeWire"
python3 - <<'EOF'
import math, struct, wave
with wave.open("/tmp/tone.wav", "wb") as w:
    w.setnchannels(1); w.setsampwidth(2); w.setframerate(48000)
    w.writeframes(b"".join(struct.pack("<h", int(12000 * math.sin(2 * math.pi * 440 * i / 48000))) for i in range(48000)))
EOF
check audio-alsa-apps aplay -q -D default /tmp/tone.wav
check audio-test aios audio test "prueba de sonido"
echo "hola" | espeak -v es --stdout | pw-play - && pass voice-speaks || fail voice-speaks "espeak | pw-play -"
check audio-mute aios audio mute on
aios audio status --json | grep -q '"muted": true' && pass audio-muted || fail audio-muted "not muted"
aios audio mute off >/dev/null
[ -x /opt/whisper/bin/whisper-cli ] && ls /usr/share/aios/models/whisper/*.bin >/dev/null 2>&1 && pass voice-installed || fail voice-installed "whisper or model missing"
# whisper de verdad en la imagen (su ggml, no el de llama.cpp): un segundo de audio
python3 -c "import wave; w=wave.open('/tmp/s.wav','wb'); w.setnchannels(1); w.setsampwidth(2); w.setframerate(16000); w.writeframes(bytes(32000))"
out=$(timeout 900 /opt/whisper/bin/whisper-cli -m /usr/share/aios/models/whisper/*.bin -f /tmp/s.wav -l es -nt -np -t 4 2>&1); rc=$?
[ $rc -eq 0 ] && ! echo "$out" | grep -q GGML_ASSERT && pass voice-whisper-runs || fail voice-whisper-runs "rc=$rc $(echo "$out" | grep -m1 -E 'ASSERT|error')"
ls /lib/firmware/intel/sof/sof-icl.ri >/dev/null 2>&1 && ls /usr/share/alsa/ucm2 >/dev/null 2>&1 && pass audio-sof-ucm || fail audio-sof-ucm "SOF or UCM missing"

# --- Pantalla y diagnóstico -----------------------------------------------------------
# La VM es lenta: swayidle ya habrá apagado la pantalla y grim no tendría qué copiar
SWAYSOCK=$(ls /run/user/$(id -u)/sway-ipc.*.sock 2>/dev/null | head -1) swaymsg 'output * power on' >/dev/null
sleep 3  # hasta que sway pinte un fotograma, grim falla ("failed to copy output")
f=$(aios-screenshot) && [ -s "$f" ] && pass screenshot || fail screenshot "$f locked=$(pgrep -x swaylock >/dev/null && echo yes || echo no)"
aios-diag --local > /tmp/diag.out 2>&1
t=$(sed -n 's/.*saved \(\/tmp\/[^ ]*\.tar\.gz\).*/\1/p' /tmp/diag.out)
[ -n "$t" ] && gzip -dc "$t" | tar -tf - | grep -q 'screenshots/aios-' && pass diag-screenshots || fail diag-screenshots "$(tail -2 /tmp/diag.out)"
gzip -dc "$t" | tar -tf - | grep -q 'audio.txt' && pass diag-audio || fail diag-audio "no audio.txt"

# --- Escritorio: bloqueo, notificaciones, pantallas ------------------------------------
export WAYLAND_DISPLAY=${WAYLAND_DISPLAY:-wayland-1}
for p in swayidle mako; do pgrep -x $p >/dev/null && pass "desktop-$p" || fail "desktop-$p" "not running"; done
command -v swaylock >/dev/null && pass desktop-swaylock || fail desktop-swaylock "missing"
# swaylock comprueba la contraseña con PAM como aios, es decir, con unix_chkpwd:
# sin setuid rechazaba todas y el bloqueo no se podía quitar
printf '%s\0' "$PW" | /usr/sbin/unix_chkpwd aios nullok && pass lock-password-ok || \
    fail lock-password-ok "$(ls -l /usr/sbin/unix_chkpwd)"
printf '%s\0' "no-es-$PW" | /usr/sbin/unix_chkpwd aios nullok 2>/dev/null && \
    fail lock-password-wrong "accepted a wrong password" || pass lock-password-wrong
python3 -c "import sys; sys.path.insert(0,'/usr/lib/aios'); from aios import notify; sys.exit(0 if notify.send('AIOS test', 'notification') else 1)" \
    && pass notify-send || fail notify-send "mako did not take it"
n=$(aios ui display list --json | python3 -c 'import json,sys; print(len(json.loads(sys.stdin.read().strip().splitlines()[-1])["data"]["displays"]))')
[ "${n:-0}" -ge 1 ] && pass display-list || fail display-list "no displays"
if [ "${n:-0}" -ge 2 ]; then
    check display-extend aios ui display extend right
    aios ui display list --json | grep -q '"position": \[[1-9]' && pass display-extended || fail display-extended "second display not placed to the right"
    check display-mirror aios ui display mirror
    sleep 3; pgrep -x wl-mirror >/dev/null && pass display-mirror-running || fail display-mirror-running "wl-mirror not running"
    check display-unmirror aios ui display extend
    second=$(aios ui display list --json | python3 -c 'import json,sys; print(json.loads(sys.stdin.read().strip().splitlines()[-1])["data"]["displays"][1]["name"])')
    check display-off aios ui display off "$second"
    first=$(aios ui display list --json | python3 -c 'import json,sys; print(json.loads(sys.stdin.read().strip().splitlines()[-1])["data"]["displays"][0]["name"])')
    [ "$(aios ui display off "$first" --json | jcode)" = UI_LAST_DISPLAY ] && pass display-keeps-last || fail display-keeps-last "turned off the last display"
    check display-on aios ui display on "$second"
    ls ~/.config/sway/config.d/50-aios-displays.conf >/dev/null && pass display-remembered || fail display-remembered "no config saved"
fi

# --- Bluetooth (la VM no tiene adaptador: debe decirlo, no fallar) ---------------------
{ [ "$(systemctl is-active bluetooth)" = active ] || [ ! -d /sys/class/bluetooth ]; } && pass bt-service || fail bt-service "$(systemctl is-active bluetooth)"
c=$(aios bt status --json | jcode); { [ "$c" = OK ] || [ "$c" = BT_NO_ADAPTER ]; } && pass bt-status || fail bt-status "$c"

# --- Autoprueba de hardware -------------------------------------------------------------
aios sys selftest --json > /tmp/selftest.json 2>&1
python3 - <<'PY' && pass selftest-runs || fail selftest-runs "$(tail -c 200 /tmp/selftest.json)"
import json
r = json.loads(open("/tmp/selftest.json").read().strip().splitlines()[-1])
names = {t["test"] for t in r["data"]["results"]}
assert {"cpu", "gpu", "sound", "wifi", "bluetooth", "voice", "model"} <= names, names
PY
# sin el programa locale en la imagen: se prueba con glibc directamente
python3 -c 'import locale; locale.setlocale(locale.LC_ALL, "fr_FR.UTF-8")' 2>/dev/null && pass locales || fail locales "fr_FR missing"

# --- Proveedor externo ------------------------------------------------------------------
[ -n "$MOCKPORT" ] && {
    check ai-add aios ai add mock --url "http://$HOST:$MOCKPORT/v1" --api-key secreto123 --key-header X-API-Key
    [ "$(aios ai use mock --json | jcode)" = CONFIRM_REQUIRED ] && pass ai-use-needs-confirm || fail ai-use-needs-confirm "?"
    check ai-use aios ai use mock --confirm send-mock
    check ai-status aios ai status
    check ai-models aios ai models mock
    check ai-use-model aios ai use mock --model mock-35b
    # Emparejamiento: interactivo (con --json avisa), y sus herramientas
    [ "$(aios ai pair --json | jcode)" = AI_PAIR_INTERACTIVE ] && pass ai-pair-json || fail ai-pair-json "?"
    openssl genpkey -algorithm RSA -pkeyopt rsa_keygen_bits:3072 -out /tmp/k.pem 2>/dev/null &&
        qrencode -t ANSIUTF8 https://ccmai.org >/dev/null && pass ai-pair-tools || fail ai-pair-tools "openssl or qrencode"
    aios ai use local >/dev/null; aios ai remove mock >/dev/null
}

# --- Actualización por git ---------------------------------------------------------------
[ -n "$GITPORT" ] && {
    printf "REPO=http://$HOST:$GITPORT/aios-base.git\nBRANCH=main\nCHANNEL=release\n" > /tmp/u.conf
    S cp /tmp/u.conf /etc/aios/update.conf
    code=$(S aios update code check --json | jcode)
    { [ "$code" = UPDATE_NO_RELEASE ] || [ "$code" = UPDATE_AVAILABLE ]; } && pass update-release-channel || fail update-release-channel "$code"
    sed -i 's/CHANNEL=release/CHANNEL=main/' /tmp/u.conf; S cp /tmp/u.conf /etc/aios/update.conf
    [ "$(S aios update code check --json | jcode)" = UPDATE_AVAILABLE ] && pass update-check || fail update-check "no update"
    # Aviso diario: notifica una vez por versión (la segunda vez, nada)
    n1=$(S aios update code notify --json | python3 -c 'import json,sys; print(json.loads(sys.stdin.read().strip().splitlines()[-1])["data"].get("notified"))')
    n2=$(S aios update code notify --json | python3 -c 'import json,sys; print(json.loads(sys.stdin.read().strip().splitlines()[-1])["data"].get("notified"))')
    [ "$n1" = True ] && [ "$n2" = None ] && pass update-notify-once || fail update-notify-once "first=$n1 second=$n2"
    [ "$(systemctl is-enabled aios-update-check.timer)" = enabled ] && pass update-timer || fail update-timer "$(systemctl is-enabled aios-update-check.timer)"
    tok=$(S aios update code apply --json | python3 -c 'import json,sys; print(json.loads(sys.stdin.read().strip().splitlines()[-1]).get("confirm"))')
    S aios update code apply --confirm "$tok" >/dev/null && [ "$(aios-test-update 2>/dev/null)" = "update OK" ] && pass update-apply || fail update-apply "?"
    S aios update code rollback >/dev/null && ! command -v aios-test-update >/dev/null && pass update-rollback || fail update-rollback "?"
}
# --- Portapapeles y dictado (wl-clipboard, wtype) ------------------------------------------
export WAYLAND_DISPLAY=${WAYLAND_DISPLAY:-wayland-1}
printf 'texto copiado ñ' | wl-copy && [ "$(wl-paste --no-newline)" = "texto copiado ñ" ] && pass clipboard || fail clipboard "$(wl-paste 2>&1 | head -1)"
# Solo pulsa y suelta Mayús: no escribe nada en la ventana del chat
wtype -M shift -m shift && pass dictate-wtype || fail dictate-wtype "virtual keyboard refused"

# --- Emparejamiento de un proveedor (aios ai pair) de punta a punta ---------------------------
# El "navegador" cifra la clave con openssl, como WebCrypto (RSA-OAEP SHA-256)
[ -n "$PAIRPORT" ] && [ -n "$MOCKPORT" ] && {
cat > /tmp/pair-drive.py <<'PYEOF'
import base64, json, os, pty, re, subprocess, sys, time, urllib.request
host, pport, mport = sys.argv[1:4]
srv = f"http://{host}:{pport}/aios-diag/pair"
pid, fd = pty.fork()
if pid == 0:
    os.execvp("aios", ["aios", "ai", "pair", "--server", srv])
out = b""
def wait(pat, t=120):
    global out
    end = time.time() + t
    while time.time() < end:
        try:
            out += os.read(fd, 4096)
        except OSError:
            break
        m = re.search(pat, out)
        if m:
            return m
    print("TIMEOUT", pat, out.decode(errors="replace")[-300:]); sys.exit(1)
code = wait(rb"code\s+([A-Z0-9]{3}-[A-Z0-9]{3})").group(1).decode().replace("-", "")
pub = json.load(urllib.request.urlopen(f"{srv}/key?c={code}"))["pubkey"]
open("/tmp/pub.pem", "w").write(pub)
enc = subprocess.run(["openssl", "pkeyutl", "-encrypt", "-pubin", "-inkey", "/tmp/pub.pem",
                      "-pkeyopt", "rsa_padding_mode:oaep", "-pkeyopt", "rsa_oaep_md:sha256",
                      "-pkeyopt", "rsa_mgf1_md:sha256"], input=b"secreto123", capture_output=True, check=True).stdout
body = {"code": code, "key_enc": base64.b64encode(enc).decode(), "provider": {
    "name": "paired", "label": "Test server", "url": f"http://{host}:{mport}/v1", "key_header": "X-API-Key"}}
urllib.request.urlopen(urllib.request.Request(f"{srv}/submit", data=json.dumps(body).encode(),
                                              headers={"Content-Type": "application/json"}))
wait(rb"Name for this provider \[paired\]: "); os.write(fd, b"\n")
wait(rb"Use it now\? \[Y/n\] "); os.write(fd, b"y\n")
wait(rb"Continue\? \[y/N\] "); os.write(fd, b"y\n")
wait(rb'Using "paired"')
print("PAIRED")
PYEOF
r=$(python3 /tmp/pair-drive.py "$HOST" "$PAIRPORT" "$MOCKPORT" 2>&1)
echo "$r" | grep -q PAIRED && aios ai list | grep -q "paired" && pass ai-pair-flow || fail ai-pair-flow "$(echo "$r" | tail -2 | tr '\n' ' ')"
aios ai use local >/dev/null; aios ai remove paired >/dev/null
}

# --- Recordatorios ------------------------------------------------------------------------
R=$HOME/.local/share/aios/reminders.json
st() { python3 -c "import json,sys; print([r.get('done') for r in json.load(open('$R')) if r['id']==sys.argv[1]][0])" "$1"; }
id1=$(aios remind add 3s "prueba de recordatorio" --json | python3 -c 'import json,sys; print(json.loads(sys.stdin.read().strip().splitlines()[-1])["data"].get("id"))')
id2=$(aios remind add 1h "otro" --json | python3 -c 'import json,sys; print(json.loads(sys.stdin.read().strip().splitlines()[-1])["data"].get("id"))')
sleep 10
[ "$(st "$id1")" = fired ] && pass remind-fires || fail remind-fires "state $(st "$id1"); $(systemctl --user status "aios-remind-$id1" --no-pager 2>&1 | tail -3 | tr '\n' ' ')"
aios remind list | grep -q "otro" && pass remind-list || fail remind-list "?"
aios remind cancel "$id2" >/dev/null && [ "$(st "$id2")" = cancelled ] && ! systemctl --user -q is-active "aios-remind-$id2.timer" && pass remind-cancel || fail remind-cancel "?"
[ "$(aios remind add ayer x --json | jcode)" = REMIND_BAD_TIME ] && pass remind-bad-time || fail remind-bad-time "?"
# Apagado cuando tocaba: al entrar en la sesión avisa como perdido
python3 -c "import json; d=json.load(open('$R')); d.append({'id':'old001','when':'2020-01-01 00:00:00','text':'perdido'}); json.dump(d, open('$R','w'))"
# (lo terminado hace más de una semana se limpia en la misma pasada: se mira lo que devuelve)
m=$(aios remind restore --json | python3 -c 'import json,sys; print(json.loads(sys.stdin.read().strip().splitlines()[-1])["data"].get("missed"))')
[ "$m" = 1 ] && pass remind-restore || fail remind-restore "missed=$m"

# --- Memoria: swap comprimida en RAM ------------------------------------------------------
grep -q '^/dev/zram0' /proc/swaps && [ "$(cat /proc/sys/vm/swappiness)" = 150 ] && pass zram-swap || \
    fail zram-swap "$(cat /proc/swaps | tail -1) swappiness=$(cat /proc/sys/vm/swappiness)"

# --- Temperatura y energía -------------------------------------------------------------
c=$(aios sys thermal --json | jcode); { [ "$c" = OK ] || [ "$c" = THERMAL_NO_SENSOR ]; } && pass sys-thermal || fail sys-thermal "$c"
aios sys power --json | grep -q '"on_ac": true' && pass power-on-ac || fail power-on-ac "$(aios sys power 2>&1)"
[ "$(systemctl show -p Result --value aios-power.service)" = success ] && pass power-service || \
    fail power-service "$(systemctl status aios-power.service --no-pager 2>&1 | tail -3 | tr '\n' ' ')"
[ -z "$(S aios sys power apply --profile battery --json | grep -v '"ok": true')" ] && pass power-battery-apply || fail power-battery-apply "?"
S aios sys power apply --profile ac >/dev/null
pkill -CONT -x swayidle
echo "CHECKS DONE"
