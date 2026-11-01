#!/usr/bin/env bash
set -euo pipefail
APPIMAGE="$1"
if [[ -z "$APPIMAGE" ]]; then echo "Usage: $0 NFS2S3-x86_64.AppImage"; exit 64; fi
[[ -f "$APPIMAGE" ]] || { echo "Fichier introuvable : $APPIMAGE" >&2; exit 1; }
APPIMAGE="$(realpath "$APPIMAGE")"
mkdir -p "$HOME/.local/bin" "$HOME/.local/share/applications" "$HOME/.local/share/icons"
install -m 755 "$APPIMAGE" "$HOME/.local/bin/nfs2s3-gui.AppImage"
REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
install -m 644 "$REPO_ROOT/gui/nfs2s3.svg" "$HOME/.local/share/icons/nfs2s3.svg"
cat > "$HOME/.local/share/applications/nfs2s3.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=NFS2S3
Comment=Transfert sécurisé NFS vers S3
Exec=$HOME/.local/bin/nfs2s3-gui.AppImage
Icon=$HOME/.local/share/icons/nfs2s3.svg
Categories=Utility;System;
Terminal=false
EOF
echo "NFS2S3 installé. Lancez-le depuis le menu des applications."
