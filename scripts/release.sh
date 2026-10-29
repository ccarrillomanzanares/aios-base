#!/bin/sh
# AIOS — publica una versión para 'aios update code': etiqueta firmada con la
# clave de ~/.ssh/aios-release (su parte pública está en
# board/aios/rootfs-overlay/etc/aios/update-signers). No hace push: lo imprime.
# Uso: scripts/release.sh v0.1.0 "mensaje"
set -e
TAG="$1"; MSG="${2:-AIOS $1}"
KEY="${AIOS_RELEASE_KEY:-$HOME/.ssh/aios-release}"
ROOT="$(dirname "$(readlink -f "$0")")/.."
case "$TAG" in v[0-9]*) ;; *) echo "uso: $0 vX.Y.Z [mensaje]" >&2; exit 2 ;; esac
[ -f "$KEY" ] || { echo "no está la clave $KEY" >&2; exit 1; }
git -C "$ROOT" diff --quiet HEAD || { echo "hay cambios sin commit" >&2; exit 1; }
git -C "$ROOT" -c gpg.format=ssh -c user.signingkey="$KEY.pub" tag -s "$TAG" -m "$MSG"
git -C "$ROOT" -c gpg.format=ssh \
    -c gpg.ssh.allowedSignersFile="$ROOT/board/aios/rootfs-overlay/etc/aios/update-signers" \
    verify-tag "$TAG"
echo "Firmada $TAG. Para publicarla: git push origin main $TAG"
