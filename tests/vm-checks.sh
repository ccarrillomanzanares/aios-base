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

# --- Sistema --------------------------------------------------------------------
[ -z "$(systemctl --failed --no-legend)" ] && pass services-ok || fail services-ok "$(systemctl --failed --no-legend | tr '\n' ' ')"
[ "$(systemctl is-active sshd)" != active ] && pass sshd-off || fail sshd-off "sshd is running"
open=$(ss -ltnuH 2>/dev/null | awk '{print $5}' | grep -vE '^(127\.|\[::1\]|.*%lo:|10\.0\.2\.15%.*:68$)' | tr '\n' ' ')
[ -z "$open" ] && pass no-open-ports || fail no-open-ports "$open"
grep -q '^COMMIT=' /etc/aios/build-info && pass build-info || fail build-info "missing"
# (el passwd de BusyBox no tiene -S: el estado se lee de /etc/shadow)
[ -n "$(S grep '^root:' /etc/shadow | cut -d: -f2)" ] && pass root-status || fail root-status "no root entry in shadow"
command -v chpasswd >/dev/null && pass chpasswd-present || fail chpasswd-present "aios-firstboot needs it"

# --- Red -------------------------------------------------------------------------
check net-status aios net status
[ "$(aios net status --json | jcode)" = OK ] && pass net-json || fail net-json "not OK"

# Wifi con radios virtuales: wlan1 punto de acceso con DHCP, wlan0 estación
S modprobe mac80211_hwsim radios=2 && sleep 4
printf '[Match]\nName=wlan1\n[Network]\nAddress=192.168.80.1/24\nDHCPServer=yes\n' > /tmp/ap.network
S mkdir -p /run/systemd/network && S cp /tmp/ap.network /run/systemd/network/10-aios-test-ap.network
S networkctl reload; iwctl device wlan1 set-property Mode ap; sleep 2
iwctl ap wlan1 start AIOS-TEST testpass123; sleep 2; S networkctl reconfigure wlan1; sleep 3
aios net wifi scan | grep -q AIOS-TEST && pass wifi-scan || fail wifi-scan "AIOS-TEST not found"
[ "$(aios net wifi connect AIOS-TEST --json | jcode)" = WIFI_NEEDS_PASSWORD ] && pass wifi-needs-password || fail wifi-needs-password "?"
[ "$(aios net wifi connect AIOS-TEST --password malamala1 --json | jcode)" = WIFI_AUTH_FAILED ] && pass wifi-bad-password || fail wifi-bad-password "?"
S ls /var/lib/iwd | grep -q AIOS-TEST && fail wifi-no-residue "profile saved after failure" || pass wifi-no-residue
r=$(aios net wifi connect AIOS-TEST --password testpass123 --json); [ "$(echo "$r" | jcode)" = OK ] && pass wifi-connect || fail wifi-connect "$r"
python3 -c "import runpy; print(runpy.run_path('/usr/bin/aios-status')['line']())" | grep -q "WIFI AIOS-TEST" && pass bar-wifi || fail bar-wifi "bar"
check wifi-disconnect aios net wifi disconnect

# --- Sonido ------------------------------------------------------------------------
for u in pipewire pipewire-pulse wireplumber; do
    [ "$(systemctl --user is-active $u)" = active ] && pass "audio-$u" || fail "audio-$u" "$(systemctl --user is-active $u)"
done
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
f=$(aios-screenshot) && [ -s "$f" ] && pass screenshot || fail screenshot "$f"
aios-diag --local > /tmp/diag.out 2>&1
t=$(sed -n 's/.*saved \(\/tmp\/[^ ]*\.tar\.gz\).*/\1/p' /tmp/diag.out)
[ -n "$t" ] && gzip -dc "$t" | tar -tf - | grep -q 'screenshots/aios-' && pass diag-screenshots || fail diag-screenshots "$(tail -2 /tmp/diag.out)"
gzip -dc "$t" | tar -tf - | grep -q 'audio.txt' && pass diag-audio || fail diag-audio "no audio.txt"

# --- Escritorio: bloqueo, notificaciones, pantallas ------------------------------------
export WAYLAND_DISPLAY=${WAYLAND_DISPLAY:-wayland-1}
for p in swayidle mako; do pgrep -x $p >/dev/null && pass "desktop-$p" || fail "desktop-$p" "not running"; done
command -v swaylock >/dev/null && pass desktop-swaylock || fail desktop-swaylock "missing"
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
[ "$(systemctl is-active bluetooth)" = active ] && pass bt-service || fail bt-service "$(systemctl is-active bluetooth)"
c=$(aios bt status --json | jcode); { [ "$c" = OK ] || [ "$c" = BT_NO_ADAPTER ]; } && pass bt-status || fail bt-status "$c"

# --- Autoprueba de hardware -------------------------------------------------------------
aios sys selftest --json > /tmp/selftest.json 2>&1
python3 - <<'PY' && pass selftest-runs || fail selftest-runs "$(tail -c 200 /tmp/selftest.json)"
import json
r = json.loads(open("/tmp/selftest.json").read().strip().splitlines()[-1])
names = {t["test"] for t in r["data"]["results"]}
assert {"cpu", "gpu", "sound", "wifi", "bluetooth", "voice", "model"} <= names, names
PY
locale -a 2>/dev/null | grep -qi "fr_FR.utf8" && pass locales || fail locales "fr_FR missing"

# --- Proveedor externo ------------------------------------------------------------------
[ -n "$MOCKPORT" ] && {
    check ai-add aios ai add mock --url "http://$HOST:$MOCKPORT/v1" --api-key secreto123 --key-header X-API-Key
    [ "$(aios ai use mock --json | jcode)" = CONFIRM_REQUIRED ] && pass ai-use-needs-confirm || fail ai-use-needs-confirm "?"
    check ai-use aios ai use mock --confirm send-mock
    check ai-status aios ai status
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
    tok=$(S aios update code apply --json | python3 -c 'import json,sys; print(json.loads(sys.stdin.read().strip().splitlines()[-1]).get("confirm"))')
    S aios update code apply --confirm "$tok" >/dev/null && [ "$(aios-test-update 2>/dev/null)" = "update OK" ] && pass update-apply || fail update-apply "?"
    S aios update code rollback >/dev/null && ! command -v aios-test-update >/dev/null && pass update-rollback || fail update-rollback "?"
}
echo "CHECKS DONE"
