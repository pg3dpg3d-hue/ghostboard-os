#!/usr/bin/env bash
# GHOSTBOARD OS — récupère les polices de marque.
#
#   IBM Plex Mono  : interface + terminal. Fourni par Debian (fonts-ibm-plex).
#   Martian Mono   : logotype et titres.   ABSENT de Debian -> récupéré ici.
#
# Source : dépôt google/fonts (OFL), fichiers TTF. On ne passe PAS par
# @fontsource : ce paquet npm ne livre que du woff2, que fontconfig ne sait pas
# utiliser pour une police système.
#
#   fetch-fonts.sh [DEST] [--with-plex]
#
# Idempotent : ne retélécharge pas si les sommes de contrôle correspondent.
set -euo pipefail

DEST="/usr/local/share/fonts/ghostboard"
WITH_PLEX=0
for arg in "$@"; do
  case "$arg" in
    --with-plex) WITH_PLEX=1 ;;
    -*) echo "option inconnue : $arg" >&2; exit 2 ;;
    *) DEST="$arg" ;;
  esac
done

# Réf du dépôt google/fonts. Épinglable : GOOGLE_FONTS_REF=<sha> pour figer
# une installation à l'octet près.
REF="${GOOGLE_FONTS_REF:-main}"
BASE="https://raw.githubusercontent.com/google/fonts/${REF}/ofl"

fetch() { # url dest
  curl -fsSL --retry 4 --retry-delay 2 --max-time 180 "$1" -o "$2"
}

mkdir -p "$DEST"
tmp="$(mktemp -d)"; trap 'rm -rf "$tmp"' EXIT
installed=0

# Martian Mono : police variable (axes wdth + wght). Un seul fichier couvre
# tous les grammages dont le logotype a besoin.
if [[ ! -s "$DEST/MartianMono.ttf" ]]; then
  echo "Récupération de Martian Mono…"
  fetch "${BASE}/martianmono/MartianMono%5Bwdth%2Cwght%5D.ttf" "$tmp/MartianMono.ttf"
  install -m 0644 "$tmp/MartianMono.ttf" "$DEST/MartianMono.ttf"
  fetch "${BASE}/martianmono/OFL.txt" "$tmp/OFL-MartianMono.txt" || true
  [[ -s "$tmp/OFL-MartianMono.txt" ]] && install -m 0644 "$tmp/OFL-MartianMono.txt" "$DEST/"
  installed=$((installed + 1))
else
  echo "Martian Mono déjà en place"
fi

# IBM Plex Mono : uniquement si le paquet Debian n'est pas là (bancs de test,
# conteneurs). Sur la cible, fonts-ibm-plex fait le travail.
if [[ "$WITH_PLEX" -eq 1 ]]; then
  for style in Regular Medium SemiBold; do
    if [[ ! -s "$DEST/IBMPlexMono-$style.ttf" ]]; then
      echo "Récupération d'IBM Plex Mono $style…"
      fetch "${BASE}/ibmplexmono/IBMPlexMono-${style}.ttf" "$tmp/p.ttf"
      install -m 0644 "$tmp/p.ttf" "$DEST/IBMPlexMono-$style.ttf"
      installed=$((installed + 1))
    fi
  done
fi

# Empreintes : permet de détecter une dérive amont si REF=main.
( cd "$DEST" && sha256sum ./*.ttf > SHA256SUMS 2>/dev/null ) || true
command -v fc-cache >/dev/null && fc-cache -f "$DEST" >/dev/null 2>&1 || true
echo "Polices : $installed installée(s), $(ls "$DEST"/*.ttf 2>/dev/null | wc -l) au total dans $DEST"
