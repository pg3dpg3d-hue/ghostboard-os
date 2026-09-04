#!/usr/bin/env bash
# Test de la détection ghost-bruce sur un faux arbre sysfs.
# Deux cartes typiques du parc Bruce : M5Stick (CP210x) et T-Embed (USB natif).
set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(dirname "$HERE")"
TMP="$(mktemp -d)"; trap 'rm -rf "$TMP"' EXIT
pass=0; fail=0
check() { if [[ "$2" == "1" ]]; then echo "  OK  $1"; pass=$((pass+1));
          else echo "  KO  $1${3:+ — $3}"; fail=$((fail+1)); fi; }

mk_board() { # nom_tty vid pid produit fabricant serie
  local tty="$1" vid="$2" pid="$3" prod="$4" manu="$5" ser="$6"
  local usb="$TMP/usbdev/$tty"
  mkdir -p "$usb" "$TMP/sys/$tty"
  printf '%s' "$vid"  > "$usb/idVendor"
  printf '%s' "$pid"  > "$usb/idProduct"
  printf '%s' "$prod" > "$usb/product"
  printf '%s' "$manu" > "$usb/manufacturer"
  printf '%s' "$ser"  > "$usb/serial"
  # Le vrai sysfs interpose une ou deux couches (interface, port) entre le tty
  # et le périphérique USB : on reproduit ça pour tester la remontée.
  mkdir -p "$usb/1-2:1.0/ttyport"
  ln -s "$usb/1-2:1.0/ttyport" "$TMP/sys/$tty/device"
}

mk_board ttyUSB0 10c4 ea60 "CP2104 USB to UART Bridge Controller" "Silicon Labs" "01F3A2B7"
mk_board ttyACM0 303a 1001 "T-Embed ESP32-S3"                     "LilyGO"       "3C8427AF"
mk_board ttyUSB1 1a86 7523 "USB Serial"                           "QinHeng"      ""

echo "ghost-bruce — détection"
out="$(GHOSTBOARD_SYSFS_TTY="$TMP/sys" "$ROOT/tools/ghost-bruce" list 2>&1)"
echo "$out" | sed 's/^/    /'
echo
grep -q "3 carte(s)"                    <<<"$out" && check "les 3 cartes sont listées" 1 || check "les 3 cartes sont listées" 0
grep -q "/dev/ttyUSB0"                  <<<"$out" && check "port ttyUSB0 vu" 1 || check "port ttyUSB0 vu" 0
grep -q "Silicon Labs CP210x"           <<<"$out" && check "puce CP210x identifiée par VID:PID" 1 || check "puce CP210x identifiée" 0
grep -q "Espressif USB CDC/JTAG natif"  <<<"$out" && check "USB natif Espressif identifié" 1 || check "USB natif Espressif identifié" 0
grep -q "QinHeng CH340"                 <<<"$out" && check "puce CH340 identifiée (typique CYD)" 1 || check "puce CH340 identifiée" 0
grep -qi "LilyGO T-Embed"               <<<"$out" && check "modèle T-Embed déduit du descripteur USB" 1 || check "modèle T-Embed déduit" 0
grep -q "01F3A2B7"                      <<<"$out" && check "numéro de série remonté" 1 || check "numéro de série remonté" 0
grep -q "dialout"                       <<<"$out" && check "accès refusé signalé avec la marche à suivre" 1 || check "accès refusé signalé" 0

echo
echo "ghost-bruce — sélection"
info="$(GHOSTBOARD_SYSFS_TTY="$TMP/sys" "$ROOT/tools/ghost-bruce" -d /dev/ttyACM0 info 2>/dev/null)"
[[ "$(python3 -c 'import json,sys;print(json.load(sys.stdin)["device"])' <<<"$info")" == "/dev/ttyACM0" ]] \
  && check "-d sélectionne le port demandé" 1 || check "-d sélectionne le port demandé" 0
[[ "$(python3 -c 'import json,sys;print(json.load(sys.stdin)["board"])' <<<"$info")" == *"T-Embed"* ]] \
  && check "info renvoie le modèle en JSON" 1 || check "info renvoie le modèle en JSON" 0

err="$(GHOSTBOARD_SYSFS_TTY="$TMP/sys" "$ROOT/tools/ghost-bruce" -d /dev/nexistepas info 2>&1)"; rc=$?
[[ "$rc" -ne 0 && "$err" == *"introuvable"* ]] \
  && check "port inexistant -> erreur explicite" 1 || check "port inexistant -> erreur explicite" 0

empty="$(GHOSTBOARD_SYSFS_TTY="$TMP/vide" "$ROOT/tools/ghost-bruce" list 2>&1)"; rc=$?
[[ "$rc" -eq 1 && "$empty" == *"Aucune carte"* ]] \
  && check "aucune carte -> message clair, code 1" 1 || check "aucune carte -> code 1" 0

echo
echo "$([[ $fail -eq 0 ]] && echo SUCCÈS || echo ÉCHEC) : $pass réussi(s), $fail échec(s)"
exit $(( fail > 0 ))
