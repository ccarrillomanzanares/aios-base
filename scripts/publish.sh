#!/bin/sh
# AIOS — publica la imagen en https://ccmai.org/aios/releases/, en dos fases:
#
#   scripts/publish.sh img    aios.img -> aios.img.xz (+ .sha256): USB, BIOS y UEFI
#   scripts/publish.sh vbox   aios.img -> aios.ova (+ .sha256): VM de VirtualBox lista
#                             para importar; se arranca su disco en QEMU antes de publicar
#   scripts/publish.sh web    la web (ccmai.org/aios) desde las plantillas de web/ con lo
#                             publicado en releases/; «img» y «vbox» la regeneran al final
#   scripts/publish.sh web preview   igual, pero solo en build/web-preview
#
# Las dos fases van por separado: tras «img» se avisa al usuario (que descarga la
# imagen para probarla) y después se hace «vbox». Las dos parten de
# build/output/images/aios.img, que debe venir de un commit limpio (DIRTY=no) y
# haber pasado 'make test'. La versión publicada antes se guarda en build/.
# Necesita sudo (releases/ es de root) y VirtualBox para «vbox».
set -e
ROOT="$(readlink -f "$(dirname "$0")/..")"
IMG="$ROOT/build/output/images/aios.img"
INFO="$ROOT/build/output/target/etc/aios/build-info"
RELEASES="${AIOS_RELEASES:-/var/www/ccmai.org/aios/releases}"
URL="https://ccmai.org/aios/releases"

WEB="$(dirname "$RELEASES")"

# web [preview]: plantillas de web/ -> build/web-preview, y si no es preview, a la web
# (copia de las páginas anteriores en build/web-prev-FECHA)
web() {
    out="$ROOT/build/web-preview"
    rm -rf "$out"
    python3 "$ROOT/scripts/render-web.py" "$RELEASES" "$out"
    [ "$1" = preview ] && { echo "Borrador en $out"; return 0; }
    prev="$ROOT/build/web-prev-$(date +%Y%m%d-%H%M%S)"
    mkdir -p "$prev/releases"
    for page in index.html changelog.html changelog-lfs.html releases/index.html; do
        [ -f "$WEB/$page" ] && cp "$WEB/$page" "$prev/$page"
        sudo install -m 0644 "$out/$page" "$WEB/$page"
    done
    curl -fsS https://ccmai.org/aios/ | grep -q "$(git -C "$ROOT" describe --tags --abbrev=0 --match 'v*')" || \
        { echo "ERROR: la web no muestra la versión nueva" >&2; exit 1; }
    echo "WEB ACTUALIZADA https://ccmai.org/aios/ (anterior en $prev)"
}

if [ "$1" = web ]; then
    web "$2"
    exit 0
fi

[ -f "$IMG" ] && [ -f "$INFO" ] || { echo "No hay imagen: ejecuta 'make'" >&2; exit 1; }
COMMIT=$(sed -n 's/^COMMIT=//p' "$INFO" | cut -c1-7)
if ! grep -q '^DIRTY=no' "$INFO" && [ "$FORCE" != 1 ]; then
    echo "La imagen viene de un árbol con cambios sin commit (DIRTY=yes). FORCE=1 para publicarla igual." >&2
    exit 1
fi

# publish FICHERO NOMBRE: copia a releases/ con su .sha256, guardando antes la anterior
publish() {
    src="$1"; name="$2"
    if [ -f "$RELEASES/$name" ]; then
        old=$(sed -n 's/^COMMIT=//p' "$RELEASES/$name.info" 2>/dev/null | cut -c1-7)
        keep="$ROOT/build/prev-${old:-unknown}-$name"
        [ -f "$keep" ] || sudo cat "$RELEASES/$name" > "$keep"
        echo "Anterior guardada en $keep"
    fi
    # copia con otro nombre y mv: quien descargue nunca ve un fichero a medias
    # 0644: VBoxManage crea el .ova en 0600 y la web no podría servirlo
    sudo install -m 0644 "$src" "$RELEASES/.$name.new"
    sudo mv "$RELEASES/.$name.new" "$RELEASES/$name"
    (cd "$(dirname "$src")" && sha256sum "$(basename "$src")") | sed "s|  .*|  $name|" | \
        sudo tee "$RELEASES/$name.sha256" >/dev/null
    sudo install -m 0644 "$INFO" "$RELEASES/$name.info"
    # comprobación desde fuera: lo que sirve la web es lo que se ha publicado
    remote=$(curl -fsS "$URL/$name.sha256" | cut -d' ' -f1)
    local_sum=$(sha256sum "$src" | cut -d' ' -f1)
    [ "$remote" = "$local_sum" ] || { echo "ERROR: la web sirve otro sha256 para $name" >&2; exit 1; }
    size=$(curl -fsSI "$URL/$name" | tr -d '\r' | sed -n 's/^content-length: //Ip')
    echo "PUBLICADA $URL/$name  ($size bytes, commit $COMMIT)"
    echo "sha256 $local_sum"
}

case "$1" in
img)
    out="$ROOT/build/aios-$COMMIT.img.xz"
    if [ ! -f "$out" ] || [ "$IMG" -nt "$out" ]; then
        echo "Comprimiendo $IMG ..."
        xz -T0 -6 -k -c "$IMG" > "$out.tmp"
        mv "$out.tmp" "$out"
    fi
    xz -t "$out"
    publish "$out" aios.img.xz
    web
    ;;
vbox)
    command -v VBoxManage >/dev/null || { echo "Falta VirtualBox (VBoxManage)" >&2; exit 1; }
    out="$ROOT/build/aios-$COMMIT.ova"
    work="$ROOT/build/vbox-$COMMIT"
    vm="aios-export-$COMMIT"
    # ya convertido y arrancado (aios-COMMIT.ova.ok): solo falta publicar
    if [ -f "$out.ok" ] && [ "$out.ok" -nt "$IMG" ]; then
        publish "$out" aios.ova
        web
        exit 0
    fi
    rm -f "$out.ok"
    rm -rf "$work"
    mkdir -p "$work"
    # si quedó una VM de un intento anterior, fuera
    VBoxManage unregistervm "$vm" --delete >/dev/null 2>&1 || true
    echo "Convirtiendo a VDI ..."
    VBoxManage convertfromraw "$IMG" "$work/aios.vdi" --format VDI
    VBoxManage createvm --name "$vm" --ostype Linux_64 --basefolder "$work" --register
    # 8 GB y 4 CPU: el perfil mínimo de AIOS (modelo local de 4B). BIOS: la imagen
    # arranca igual en UEFI, pero así la VM no depende del firmware EFI de VirtualBox.
    VBoxManage modifyvm "$vm" --memory 8192 --cpus 4 --firmware bios \
        --graphicscontroller vmsvga --vram 128 --rtc-use-utc on \
        --nic1 nat --nic-type1 virtio --audio-enabled on --audio-controller hda \
        --audio-out on --audio-in on --usb-ohci on --mouse usbtablet
    VBoxManage storagectl "$vm" --name SATA --add sata --controller IntelAhci --portcount 1 --bootable on
    VBoxManage storageattach "$vm" --storagectl SATA --port 0 --device 0 --type hdd --medium "$work/aios.vdi"
    rm -f "$out.tmp.ova"
    VBoxManage export "$vm" --output "$out.tmp.ova" --vsys 0 --product AIOS \
        --producturl https://ccmai.org/aios --version "$COMMIT" \
        --description "AIOS: an operating system with its own local AI assistant. Login: aios / aios (changed at first start)."
    VBoxManage unregistervm "$vm" --delete
    mv "$out.tmp.ova" "$out"
    # Antes de publicar: el disco que lleva el .ova arranca (QEMU lee su VMDK)
    vmdk=$(tar -tf "$out" | grep '\.vmdk$' | head -1)
    tar -xf "$out" -C "$work" "$vmdk"
    python3 "$ROOT/tests/run.py" boot "$work/$vmdk" vmdk
    rm -rf "$work"
    touch "$out.ok"
    publish "$out" aios.ova
    web
    ;;
*)
    echo "Uso: $0 img|vbox|web [preview]" >&2
    exit 2
    ;;
esac
