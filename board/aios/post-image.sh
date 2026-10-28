#!/bin/sh
# AIOS — post-image: genera aios.img (USB y QEMU, BIOS + UEFI) con genimage.
# Se ejecuta desde el árbol de Buildroot.
set -e
BOARD_DIR="$(dirname "$(readlink -f "$0")")"
ROOT_PARTUUID="a105a105-02"   # firma de disco de genimage.cfg + partición 2

# Partición EFI: GRUB EFI de Buildroot + kernel + nuestro grub.cfg
ESP="$BINARIES_DIR/esp"
rm -rf "$ESP"
mkdir -p "$ESP/boot/grub"
cp -r "$BINARIES_DIR/efi-part/EFI" "$ESP/"
cp "$BINARIES_DIR/bzImage" "$ESP/boot/bzImage"
sed "s|@ROOT@|PARTUUID=$ROOT_PARTUUID|g" "$BOARD_DIR/grub.cfg" > "$ESP/boot/grub/grub.cfg"
# GRUB lee rutas distintas según el firmware: BIOS -> /boot/grub/grub.cfg,
# UEFI -> /EFI/BOOT/grub.cfg. El de Buildroot apunta a la partición 1 (la FAT),
# lo que da pantalla negra en UEFI (lección de newos): se escribe el nuestro en las dos.
cp "$ESP/boot/grub/grub.cfg" "$ESP/EFI/BOOT/grub.cfg"

# Primer sector BIOS de GRUB
if [ ! -f "$BINARIES_DIR/boot.img" ]; then
    for p in "$HOST_DIR/lib/grub/i386-pc/boot.img" "$TARGET_DIR/lib/grub/i386-pc/boot.img" \
             "$BUILD_DIR"/grub2-*/build-i386-pc/grub-core/boot.img; do
        [ -f "$p" ] && { cp -f "$p" "$BINARIES_DIR/boot.img"; break; }
    done
fi
[ -f "$BINARIES_DIR/boot.img" ] || { echo "post-image: falta boot.img de GRUB"; exit 1; }

support/scripts/genimage.sh -c "$BOARD_DIR/genimage.cfg"

echo ""
echo "=== AIOS: imagen generada ==="
echo "  $BINARIES_DIR/aios.img"
echo "  QEMU:  make qemu"
echo "  USB:   sudo dd if=aios.img of=/dev/sdX bs=4M status=progress conv=fsync"
