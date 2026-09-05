#!/usr/bin/env bash
# Tests du firmware compagnon ESP32 (companion/firmware).
# On ne peut pas compiler ESP32 ici (pas de toolchain) : on vérifie donc la
# cohérence statique — thème dérivé de la palette, correction du dépassement
# mémoire, présence du gate d'autorisation, équilibre des accolades, câblage
# de `ghost-bruce flash`. Si PlatformIO est présent, on compile pour de vrai.
set -uo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
FW="$ROOT/companion/firmware"
pass=0; fail=0
ck() { if [[ "$2" == "0" ]]; then echo "  OK  $1"; pass=$((pass+1));
       else echo "  KO  $1${3:+ — $3}"; fail=$((fail+1)); fi; }

echo "firmware — thème dérivé de la palette"
python3 "$FW/tools/gen-theme.py" --check >/dev/null 2>&1
ck "theme_colors.h à jour avec brand/palette.toml" $?
grep -q '168, 85, 247' "$FW/include/theme_colors.h" 2>/dev/null
ck "NeoPixel scan = accent #A855F7" $?
grep -q '255, 77, 141' "$FW/include/theme_colors.h" 2>/dev/null
ck "NeoPixel attack = input #FF4D8D" $?

echo
echo "firmware — Deauther : corrections et garde-fous"
grep -q 'deauth_frame\[24\] = 7' "$FW/src/modules/deauther.cpp"
ck "reason code écrit à l'index 24 (dans les limites)" $?
! grep -q 'deauth_frame\[26\] = 7' "$FW/src/modules/deauther.cpp"
ck "plus de dépassement deauth_frame[26]" $?
grep -q 'AUTHORIZED USE ONLY' "$FW/src/modules/deauther.cpp"
ck "écran d'autorisation présent" $?
grep -q 'AUTH_HOLD_MS' "$FW/src/modules/deauther.cpp"
ck "appui long de confirmation (AUTH_HOLD_MS)" $?
# L'émission ne doit démarrer qu'une fois 'authorized' vrai.
grep -q 'authorized = true' "$FW/src/modules/deauther.cpp"
ck "attaque gatée derrière 'authorized'" $?

echo
echo "firmware — modules ESP-HACK réimplémentés (clean-room)"
for m in beaconspam evilportal sniffer blespam authtest bruteforce; do
  [[ -f "$FW/src/modules/$m.cpp" ]]; ck "module $m présent" $?
done
# Chaque module actif (émission ou tentative d'auth) passe par le gate partagé.
for m in beaconspam evilportal blespam authtest bruteforce; do
  grep -q 'AuthGate::confirm' "$FW/src/modules/$m.cpp"; ck "$m : gaté avant action" $?
done
# Helper de connexion partagé, réutilisé par authtest et bruteforce.
[[ -f "$FW/src/wifitry.cpp" ]]; ck "helper WifiTry présent" $?
grep -q 'WifiTry::attempt' "$FW/src/modules/authtest.cpp"; ck "authtest utilise WifiTry" $?
grep -q 'WifiTry::attempt' "$FW/src/modules/bruteforce.cpp"; ck "bruteforce utilise WifiTry" $?
# Le sniffer est passif : pas de gate, pas d'émission.
! grep -q 'esp_wifi_80211_tx\|AuthGate::confirm' "$FW/src/modules/sniffer.cpp"
ck "sniffer : passif (aucune émission)" $?
# Menu à deux niveaux avec les catégories à matériel externe.
for cat in SubGHz Infrared NRF24 NFC iButton; do
  grep -q "\"$cat\"" "$FW/src/modules/menu.cpp"; ck "catégorie $cat au menu" $?
done
# Les catégories à matériel absent doivent afficher un gate, pas émettre.
grep -q 'gbDrawHardwareGate' "$FW/src/modules/hwstub.cpp"; ck "matériel absent -> écran 'Connect'" $?

echo
echo "firmware — wordlist embarquée (Auth Test)"
python3 "$FW/tools/gen-wordlist.py" --check >/dev/null 2>&1
ck "wordlist.h à jour avec data/wordlist.txt" $?
grep -q 'GB_WORDLIST_COUNT' "$FW/include/wordlist.h" 2>/dev/null
ck "wordlist.h expose GB_WORDLIST_COUNT" $?
grep -q 'GB_WORDLIST' "$FW/src/modules/authtest.cpp"
ck "authtest consomme la wordlist générée" $?
# Toutes les entrées générées doivent respecter la plage WPA (8..63).
python3 - "$FW/include/wordlist.h" <<'PY'
import re, sys
txt = open(sys.argv[1], encoding="utf-8").read()
words = re.findall(r'^    "(.*)",$', txt, re.M)
words = [w for w in words if w != ""]   # placeholder liste vide
bad = [w for w in words if not (8 <= len(w) <= 63)]
sys.exit(1 if bad else 0)
PY
ck "toutes les entrées dans la plage WPA 8..63" $?

echo
echo "firmware — cohérence structurelle"
bad=0
for f in "$FW"/src/*.cpp "$FW"/src/modules/*.cpp; do
  # Compte accolades ouvrantes/fermantes (heuristique : suffisant pour repérer
  # une accolade orpheline, comme celle du code d'origine).
  o=$(tr -cd '{' < "$f" | wc -c); c=$(tr -cd '}' < "$f" | wc -c)
  [[ "$o" == "$c" ]] || { bad=1; echo "     déséquilibre dans $(basename "$f"): {=$o }=$c"; }
done
ck "accolades équilibrées dans tous les .cpp" $bad
grep -q 'ESP32DIV' "$FW/src/modules/deauther.cpp" && ! grep -q 'nRF-BOX' "$FW/src/modules/deauther.cpp"
ck "SSID de l'AP unifié (plus de 'nRF-BOX')" $?

echo
echo "firmware — flash via ghost-bruce"
# Sans PlatformIO, la commande doit résoudre le firmware PUIS signaler pio
# manquant (et non 'firmware introuvable') — ça prouve le câblage du chemin.
out="$(GHOSTBOARD_FIRMWARE="$FW" python3 "$ROOT/tools/ghost-bruce" flash --build-only 2>&1)"
if command -v pio >/dev/null 2>&1 || command -v platformio >/dev/null 2>&1; then
  GHOSTBOARD_FIRMWARE="$FW" python3 "$ROOT/tools/ghost-bruce" flash --build-only >/dev/null 2>&1
  ck "compilation PlatformIO (build-only)" $?
else
  grep -q 'PlatformIO est absent' <<<"$out"
  ck "flash résout le firmware puis réclame PlatformIO (sauté : pio absent)" $?
fi

echo
echo "$([[ $fail -eq 0 ]] && echo SUCCÈS || echo ÉCHEC) : $pass réussi(s), $fail échec(s)"
exit $(( fail > 0 ))
