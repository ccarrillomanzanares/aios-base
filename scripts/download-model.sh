#!/bin/sh
# AIOS — descarga el modelo local del hito 0 a models/ (fuera de git).
# post-build.sh copia models/*.gguf a /usr/share/aios/models/ en la imagen.
# Uso: scripts/download-model.sh [cuantización]   (por defecto Q4_K_M)
set -e
REPO="unsloth/Qwen3.5-4B-GGUF"
QUANT="${1:-Q4_K_M}"
DEST="$(dirname "$(readlink -f "$0")")/../models"
URL="https://huggingface.co/$REPO/resolve/main"
mkdir -p "$DEST"

get() { # get <fichero remoto> <nombre local>
    if [ -s "$DEST/$2" ]; then
        echo "ya está: models/$2"
        return
    fi
    echo "descargando $1 -> models/$2"
    curl -fL --retry 3 -C - -o "$DEST/$2.part" "$URL/$1"
    mv -f "$DEST/$2.part" "$DEST/$2"
}

get "Qwen3.5-4B-$QUANT.gguf" "Qwen3.5-4B-$QUANT.gguf"
# El mmproj del repo se llama igual en todos los modelos: se renombra para que
# en /usr/share/aios/models se sepa de qué modelo es.
get "mmproj-F16.gguf" "Qwen3.5-4B-mmproj-F16.gguf"
ls -lh "$DEST"/*.gguf
