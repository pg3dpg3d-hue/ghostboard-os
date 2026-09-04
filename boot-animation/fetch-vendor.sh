#!/usr/bin/env bash
# GHOSTBOARD OS — récupère three.js dans boot-animation/vendor/.
#
# three.js n'est pas versionné dans le dépôt (365 Ko de code minifié tiers).
# Ce script est appelé par l'installateur ; il est idempotent et vérifie la
# somme de contrôle pour que deux installations donnent le même octet.
set -euo pipefail

THREE_VERSION="${THREE_VERSION:-0.185.1}"
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENDOR="$HERE/vendor"
STAMP="$VENDOR/.three-version"

if [[ -f "$STAMP" && "$(cat "$STAMP")" == "$THREE_VERSION" \
      && -s "$VENDOR/three.module.min.js" && -s "$VENDOR/three.core.min.js" ]]; then
  echo "three.js $THREE_VERSION déjà en place"
  exit 0
fi

echo "Récupération de three.js $THREE_VERSION…"
mkdir -p "$VENDOR"
tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT

url="https://registry.npmjs.org/three/-/three-${THREE_VERSION}.tgz"
curl -fsSL --retry 4 --retry-delay 2 --max-time 180 "$url" -o "$tmp/three.tgz"
tar xzf "$tmp/three.tgz" -C "$tmp" \
    package/build/three.module.min.js package/build/three.core.min.js

# Seuls ces deux fichiers sont nécessaires : three.module.min.js importe
# three.core.min.js, et rien d'autre. Pas de WebGPU, pas de TSL, pas d'addons.
install -m 0644 "$tmp/package/build/three.module.min.js" "$VENDOR/"
install -m 0644 "$tmp/package/build/three.core.min.js"   "$VENDOR/"
echo "$THREE_VERSION" > "$STAMP"

( cd "$VENDOR" && sha256sum three.module.min.js three.core.min.js > SHA256SUMS )
echo "three.js $THREE_VERSION installé ($(du -sh "$VENDOR" | cut -f1))"
