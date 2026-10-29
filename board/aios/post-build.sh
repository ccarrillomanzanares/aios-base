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
