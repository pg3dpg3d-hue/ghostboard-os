#!/usr/bin/env bash
# Test d'intégration bout-en-bout de ghost-crack, contre un VRAI handshake WPA.
#
# On n'invente pas de handshake : on utilise la capture canonique d'aircrack-ng
# (test/wpa.cap, clé connue « biscotte »). Si ghost-crack la casse, c'est toute
# la chaîne du deck (run + brute + parsing de la clé) qui est validée — un échec
# désigne l'outil, pas un vecteur maison douteux.
#
# Ce test a besoin d'AIRCRACK-NG (le crack réel). Sans lui, il se saute (comme
# test-firmware saute la compilation PlatformIO). Il ne touche NI la carte NI le
# réseau : tout est hors-ligne sur un pcap.
#
# Variables surchargeables :
#   GHOST_CRACK_CAP    chemin d'un .cap/.pcap à utiliser (défaut : télécharge wpa.cap)
#   GHOST_CRACK_KEY    clé attendue dans ce cap        (défaut : biscotte)
#   GHOST_CRACK_BSSID  BSSID cible                     (défaut : celui de wpa.cap)
#   FULL=1             lance aussi le brute-force réel (~1-2 min ; sinon sauté)
set -uo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CRACK="$ROOT/tools/ghost-crack"
pass=0; fail=0; skip=0
ck() { if [[ "$2" == "0" ]]; then echo "  OK  $1"; pass=$((pass+1));
       else echo "  KO  $1${3:+ — $3}"; fail=$((fail+1)); fi; }
sk() { echo "  ..  $1 (sauté : $2)"; skip=$((skip+1)); }

echo "ghost-crack — bout-en-bout (vrai handshake WPA)"

# --- Prérequis : aircrack-ng -------------------------------------------------
if ! command -v aircrack-ng >/dev/null 2>&1; then
  sk "chaîne complète" "aircrack-ng absent (sudo apt install aircrack-ng)"
  echo; echo "IGNORÉ : $skip sauté(s) — installe aircrack-ng pour ce test."
  exit 0
fi

# --- Capture de référence ----------------------------------------------------
CAP="${GHOST_CRACK_CAP:-}"
KEY="${GHOST_CRACK_KEY:-biscotte}"
BSSID="${GHOST_CRACK_BSSID:-00:14:6C:7E:40:80}"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

if [[ -z "$CAP" ]]; then
  CAP="$TMP/wpa.cap"
  URL="https://github.com/aircrack-ng/aircrack-ng/raw/master/test/wpa.cap"
  if command -v curl >/dev/null 2>&1; then
    curl -fsSL "$URL" -o "$CAP" 2>/dev/null
  elif command -v wget >/dev/null 2>&1; then
    wget -qO "$CAP" "$URL" 2>/dev/null
  fi
  if [[ ! -s "$CAP" ]]; then
    sk "chaîne complète" "wpa.cap non téléchargeable — fournis GHOST_CRACK_CAP=<fichier>"
    echo; echo "IGNORÉ : $skip sauté(s)."
    exit 0
  fi
fi
[[ -s "$CAP" ]]; ck "capture de référence présente ($(basename "$CAP"))" $?

# Wordlist minuscule contenant la clé attendue : valide le chemin `run`.
printf 'motdepasse\n%s\nautrechose\n' "$KEY" > "$TMP/wl.txt"

# --- run : dictionnaire ------------------------------------------------------
out="$(python3 "$CRACK" run "$CAP" -w "$TMP/wl.txt" -b "$BSSID" 2>&1)"
grep -q "CLÉ RÉCUPÉRÉE" <<<"$out"; ck "run : clé récupérée (bandeau)" $?
grep -q "$KEY" <<<"$out";        ck "run : la clé affichée est « $KEY »" $?

# --- brute : génération à la volée, contre le MÊME vrai handshake ------------
# On restreint le jeu de caractères aux lettres de la clé pour que l'espace
# reste petit et atteignable en ~1-2 min : ça prouve que les candidats générés
# à la volée sont bien testés hors-ligne jusqu'à trouver la bonne.
uniq_chars="$(printf '%s' "$KEY" | fold -w1 | awk '!seen[$0]++{printf "%s",$0}')"
klen=${#KEY}
if [[ "${FULL:-0}" == "1" ]]; then
  out="$(python3 "$CRACK" brute "$CAP" --chars "$uniq_chars" \
          --min "$klen" --max "$klen" -b "$BSSID" 2>&1)"
  grep -q "$KEY" <<<"$out"; ck "brute : clé retrouvée par génération à la volée" $?
else
  sk "brute (crack réel, ~1-2 min)" "FULL!=1 — relance avec FULL=1 pour le crack complet"
  # Check rapide et déterministe : un espace minuscule et VOLONTAIREMENT faux
  # (une seule combinaison, « 00000000 ») déroule toute la mécanique — candidat
  # généré à la volée -> stdin -> aircrack -> résultat parsé — en ~1 s, sans
  # dépendre d'un kill à mi-course. La clé n'y est pas : on attend « non trouvée ».
  out="$(python3 "$CRACK" brute "$CAP" --chars 0 --min "$klen" --max "$klen" \
          -b "$BSSID" 2>&1)"
  grep -qi "trouv" <<<"$out"; ck "brute : chaîne à la volée -> aircrack -> résultat" $?
fi

echo
echo "$([[ $fail -eq 0 ]] && echo SUCCÈS || echo ÉCHEC) : $pass réussi(s), $fail échec(s), $skip sauté(s)"
exit $(( fail > 0 ))
