#!/usr/bin/env bash
# Construit une image GHOSTBOARD avec l'outil officiel rpi-image-gen.
set -euo pipefail
PIN=262d4df5a9f9d4133370465399a7958a7c22cdc7
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(cd "$HERE/.." && pwd)"
BUILD_ROOT="${GHOSTBOARD_IMAGE_WORK:-$REPO/build/image}"
PASSWORD_HASH_FILE=""
INSTALL_DEPS=0
usage() { echo "Usage: $0 --password-hash-file FILE [--install-deps]"; }
while [[ $# -gt 0 ]]; do
  case "$1" in
    --password-hash-file) PASSWORD_HASH_FILE="${2:-}"; shift 2 ;;
    --install-deps) INSTALL_DEPS=1; shift ;;
    -h|--help) usage; exit 0 ;;
    *) usage >&2; exit 2 ;;
  esac
done
[[ "$(uname -s)" == Linux ]] || { echo "Build the image on Debian/Raspberry Pi OS 64-bit." >&2; exit 1; }
[[ -r "$PASSWORD_HASH_FILE" ]] || { echo "Provide a readable password hash file." >&2; exit 1; }
hash="$(tr -d '\r\n' < "$PASSWORD_HASH_FILE")"
[[ "$hash" =~ ^\$(y|6)\$[^:[:space:]]+$ ]] || { echo "Expected a yescrypt/SHA-512 crypt hash; generate one with rpi-image-gen/genpasswd." >&2; exit 1; }
mkdir -p "$BUILD_ROOT"
ENGINE="$BUILD_ROOT/rpi-image-gen"
if [[ ! -d "$ENGINE/.git" ]]; then
  git clone https://github.com/raspberrypi/rpi-image-gen.git "$ENGINE"
fi
git -C "$ENGINE" fetch --tags origin
git -C "$ENGINE" checkout --detach "$PIN"
[[ "$(git -C "$ENGINE" rev-parse HEAD)" == "$PIN" ]] || exit 1
if [[ "$INSTALL_DEPS" == 1 ]]; then sudo "$ENGINE/install_deps.sh"; fi
SOURCE="$(mktemp -d "$BUILD_ROOT/source.XXXXXX")"
mkdir -p "$SOURCE/config" "$SOURCE/layer" "$SOURCE/ghostboard-os"
cp "$HERE/rpi-image-gen/config/ghostboard.yaml" "$SOURCE/config/"
cp "$HERE/rpi-image-gen/layer/ghostboard-pi5.yaml" "$SOURCE/layer/"
rsync -a --delete --exclude .git --exclude build --exclude outputs "$REPO/" "$SOURCE/ghostboard-os/"
private_config="$SOURCE/config/ghostboard-private.yaml"
cleanup() { rm -f "$private_config"; }
trap cleanup EXIT INT TERM
cp "$SOURCE/config/ghostboard.yaml" "$private_config"
chmod 600 "$private_config"
HASH="$hash" python3 - "$private_config" <<'PY'
import os, pathlib, sys
p=pathlib.Path(sys.argv[1])
s=p.read_text()
s=s.replace('  user1sudo: passwd\n', '  user1sudo: passwd\n  user1passhash: ' + repr(os.environ['HASH']) + '\n')
p.write_text(s)
PY
"$ENGINE/rpi-image-gen" build -S "$SOURCE" -c ghostboard-private.yaml
echo "Image generated under: $ENGINE/work/image-ghostboard-pi5"
