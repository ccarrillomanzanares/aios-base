#!/bin/sh
# AIOS — post-build: se ejecuta sobre $TARGET_DIR antes de generar las imágenes.
set -e
BOARD_DIR="$(dirname "$(readlink -f "$0")")"
ROOT_DIR="$(readlink -f "$BOARD_DIR/../..")"

# --- Scripts del overlay: primero LF, DESPUÉS el bit de ejecución -------------
# (lección de newos: editados desde Windows llegan con CRLF y el shebang falla;
#  y "tr > f.lf && mv" crea un fichero nuevo 0644, así que el chmod va al final)
for f in "$TARGET_DIR"/usr/bin/aios "$TARGET_DIR"/usr/bin/aios-* \
         "$TARGET_DIR"/usr/lib/aios/aios/*.py "$TARGET_DIR"/home/aios/.bash_profile; do
    [ -f "$f" ] || continue
    tr -d '\r' < "$f" > "$f.lf" && mv -f "$f.lf" "$f"
done
chmod 0755 "$TARGET_DIR"/usr/bin/aios "$TARGET_DIR"/usr/bin/aios-*
chmod 0644 "$TARGET_DIR"/usr/lib/aios/aios/*.py

# --- llama.cpp: backends de CPU en un único sitio ----------------------------
# Con GGML_BACKEND_DL las variantes (libggml-cpu-haswell.so, -skylakex...) se
# instalan junto a los binarios; llama-server las busca en /usr/lib/ggml.
mkdir -p "$TARGET_DIR/usr/lib/ggml"
find "$TARGET_DIR/usr" -path "$TARGET_DIR/usr/lib/ggml" -prune -o \
     -name 'libggml-cpu*.so' -print | while read -r so; do
    mv -f "$so" "$TARGET_DIR/usr/lib/ggml/"
done
n=$(find "$TARGET_DIR/usr/lib/ggml" -name 'libggml-cpu*.so' | wc -l)
echo "post-build: $n variantes de CPU de ggml en /usr/lib/ggml"
[ "$n" -gt 0 ] || echo "post-build: AVISO: no hay variantes de CPU; revisar external.mk"

# --- Modelo local (hito 0: dentro de la raíz) --------------------------------
# 'make model' los deja en models/; aquí se copian a la imagen si existen.
mkdir -p "$TARGET_DIR/usr/share/aios/models"
if ls "$ROOT_DIR"/models/*.gguf >/dev/null 2>&1; then
    cp -f "$ROOT_DIR"/models/*.gguf "$TARGET_DIR/usr/share/aios/models/"
    echo "post-build: modelos copiados: $(ls "$ROOT_DIR"/models/*.gguf | xargs -n1 basename | tr '\n' ' ')"
else
    echo "post-build: AVISO: no hay modelos en models/ (ejecuta 'make model')"
fi

# --- Versión del código con que se genera la imagen ---------------------------
# 'aios update code' parte de este commit para saber qué ha cambiado.
{
    echo "COMMIT=$(git -C "$ROOT_DIR" rev-parse HEAD 2>/dev/null || echo unknown)"
    git -C "$ROOT_DIR" diff --quiet HEAD 2>/dev/null && echo "DIRTY=no" || echo "DIRTY=yes"
    echo "DATE=$(date -u +%Y-%m-%dT%H:%M:%SZ)"
} > "$TARGET_DIR/etc/aios/build-info"
echo "post-build: build-info $(head -1 "$TARGET_DIR/etc/aios/build-info")"

# --- aios-diag: token del receptor ------------------------------------------
# El token no va en git: se lee de local/diag.token si existe.
if [ -f "$ROOT_DIR/local/diag.token" ]; then
    install -m 0644 "$ROOT_DIR/local/diag.token" "$TARGET_DIR/etc/aios/diag.token"
    echo "post-build: token de aios-diag instalado"
else
    rm -f "$TARGET_DIR/etc/aios/diag.token"
    echo "post-build: AVISO: sin local/diag.token, aios-diag no podrá subir"
fi

# --- Modelo de voz (whisper.cpp) ------------------------------------------------
mkdir -p "$TARGET_DIR/usr/share/aios/models/whisper"
if ls "$ROOT_DIR"/models/whisper/*.bin >/dev/null 2>&1; then
    cp -f "$ROOT_DIR"/models/whisper/*.bin "$TARGET_DIR/usr/share/aios/models/whisper/"
    echo "post-build: modelo de voz: $(ls "$ROOT_DIR"/models/whisper/*.bin | xargs -n1 basename)"
else
    echo "post-build: AVISO: sin modelo de voz en models/whisper (ejecuta 'make model')"
fi

# --- Sonido: PipeWire para todas las aplicaciones ------------------------------
# Servicios de usuario (los arranca systemd --user al entrar aios): PipeWire,
# su servidor PulseAudio (pipewire-pulse) y WirePlumber.
USER_UNITS="$TARGET_DIR/etc/systemd/user"
mkdir -p "$USER_UNITS/sockets.target.wants" "$USER_UNITS/default.target.wants" \
         "$USER_UNITS/pipewire.service.wants"
for u in pipewire.socket pipewire-pulse.socket; do
    [ -f "$TARGET_DIR/usr/lib/systemd/user/$u" ] && \
        ln -sf "/usr/lib/systemd/user/$u" "$USER_UNITS/sockets.target.wants/$u"
done
for u in pipewire.service pipewire-pulse.service; do
    [ -f "$TARGET_DIR/usr/lib/systemd/user/$u" ] && \
        ln -sf "/usr/lib/systemd/user/$u" "$USER_UNITS/default.target.wants/$u"
done
if [ -f "$TARGET_DIR/usr/lib/systemd/user/wireplumber.service" ]; then
    ln -sf /usr/lib/systemd/user/wireplumber.service "$USER_UNITS/pipewire.service.wants/wireplumber.service"
    ln -sf /usr/lib/systemd/user/wireplumber.service "$USER_UNITS/pipewire-session-manager.service"
fi
# El paquete pulseaudio solo aporta libpulse (la cargan Firefox, SDL...): su
# demonio no debe arrancar nunca, el servidor PulseAudio es pipewire-pulse.
for u in pulseaudio.service pulseaudio.socket; do
    ln -sf /dev/null "$USER_UNITS/$u"
done
if [ -f "$TARGET_DIR/etc/pulse/client.conf" ]; then
    sed -i -E 's/^;? *autospawn *=.*/autospawn = no/' "$TARGET_DIR/etc/pulse/client.conf"
    grep -q '^autospawn = no' "$TARGET_DIR/etc/pulse/client.conf" || \
        echo 'autospawn = no' >> "$TARGET_DIR/etc/pulse/client.conf"
fi
# ALSA: el dispositivo "default" es PipeWire (aplay, juegos SDL, etc.)
mkdir -p "$TARGET_DIR/etc/alsa/conf.d"
for f in 50-pipewire.conf 99-pipewire-default.conf; do
    for d in usr/share/alsa/alsa.conf.d usr/share/pipewire/alsa-conf; do
        if [ -f "$TARGET_DIR/$d/$f" ]; then
            ln -sf "/$d/$f" "$TARGET_DIR/etc/alsa/conf.d/$f"
            break
        fi
    done
done
echo "post-build: sonido: $(ls "$TARGET_DIR/etc/alsa/conf.d" 2>/dev/null | tr '\n' ' ')"

# --- Servicios ----------------------------------------------------------------
WANTS="$TARGET_DIR/etc/systemd/system/multi-user.target.wants"
mkdir -p "$WANTS"
ln -sf /etc/systemd/system/aios-llama.service "$WANTS/aios-llama.service"
for unit in iwd.service systemd-networkd.service systemd-resolved.service; do
    for d in usr/lib/systemd/system lib/systemd/system; do
        if [ -f "$TARGET_DIR/$d/$unit" ]; then
            ln -sf "/$d/$unit" "$WANTS/$unit"
            break
        fi
    done
done
# resolv.conf gestionado por systemd-resolved
ln -sf ../run/systemd/resolve/stub-resolv.conf "$TARGET_DIR/etc/resolv.conf"

# --- SSH: desactivado (preset 10-aios.preset) y, si se activa, solo con claves
if [ -f "$TARGET_DIR/etc/ssh/sshd_config" ]; then
    sed -i -E 's/^#?(PasswordAuthentication|KbdInteractiveAuthentication) .*/\1 no/; s/^#?PermitRootLogin .*/PermitRootLogin no/' \
        "$TARGET_DIR/etc/ssh/sshd_config"
fi

# --- sudo: el grupo wheel administra (con contraseña) ------------------------
if [ -f "$TARGET_DIR/etc/sudoers.d/wheel" ]; then
    chmod 0440 "$TARGET_DIR/etc/sudoers.d/wheel"
    grep -qE '^[@#]includedir /etc/sudoers.d' "$TARGET_DIR/etc/sudoers" 2>/dev/null || \
        echo '@includedir /etc/sudoers.d' >> "$TARGET_DIR/etc/sudoers"
fi

# --- GRUB ----------------------------------------------------------------------
# El grub.cfg genérico de Buildroot en la raíz confundiría la búsqueda de
# /boot/grub/grub.cfg de la configuración embebida (lección de newos).
rm -f "$TARGET_DIR/boot/grub/grub.cfg"
