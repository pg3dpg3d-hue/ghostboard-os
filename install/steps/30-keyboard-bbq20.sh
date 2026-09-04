#!/usr/bin/env bash
# DESCRIPTION: Clavier BlackBerry Q20 (USB HID) — remappage et vitesse de répétition
# ============================================================================
#  Le BB Q20 se présente comme un clavier USB HID standard : il fonctionne
#  sans pilote. Ce qui manque, ce sont les touches qu'il n'a pas.
#
#  Pas de touche Super (menu démarrer), pas de flèches dédiées, pas de rangée
#  de chiffres. On comble ça par du remappage XKB, versionné et modifiable.
#
#  Les codes de touche exacts dépendent du firmware du PMOD. La règle udev
#  ci-dessous se déclenche sur le VID/PID de Solder Party ; si ta carte
#  s'annonce autrement, relève-la avec `lsusb` et ajuste ATTRS{idVendor}.
#  Pour trouver un keycode : `xev -event keyboard`, puis appuie sur la touche.
# ============================================================================
set -uo pipefail
. "$(dirname "${BASH_SOURCE[0]}")/../lib/common.sh"
need_root

apt_install x11-xkb-utils console-setup

step "Détection"
found=0
if command -v lsusb >/dev/null 2>&1; then
  while read -r l; do info "  $l"; found=1; done < <(lsusb | grep -iE 'solder|blackberry|q20|keyboard' || true)
fi
[[ "$found" == "0" ]] && warn "clavier BB Q20 non détecté — la configuration est écrite quand même"

step "Vitesse de répétition"
# Sur un clavier de la taille d'un pouce, la répétition par défaut (660 ms /
# 25 Hz) fait déraper la moindre correction. Plus long avant de partir,
# moins rapide une fois lancé.
write_file /etc/X11/xorg.conf.d/30-ghostboard-keyboard.conf <<'CONF'
# GHOSTBOARD OS — clavier BlackBerry Q20.
Section "InputClass"
    Identifier  "GHOSTBOARD-Keyboard"
    MatchIsKeyboard "on"
    Option      "XkbLayout" "us"
    Option      "XkbModel"  "pc105"
    # AutoRepeat "délai vitesse" en ms : 500 ms avant répétition, ~15 Hz ensuite.
    Option      "AutoRepeat" "500 66"
EndSection
CONF

step "Remappage XKB"
# Alt droite -> Super : le Q20 n'a pas de touche Windows, et le menu démarrer
# doit rester à un appui. Ctrl+Espace reste un second chemin (voir les
# raccourcis XFCE), pour ne jamais dépendre d'un seul remappage.
write_file /usr/share/X11/xkb/symbols/ghostboard <<'XKB'
// GHOSTBOARD OS — surcouche clavier pour le BlackBerry Q20.
// Chargée via l'option XKB "ghostboard:bbq20".
//
// Le Q20 n'a ni touche Super, ni flèches, ni rangée numérique dédiée.
// Ce fichier est fait pour être édité : relève tes codes avec
//   xev -event keyboard
// puis ajuste les lignes ci-dessous et relance `setxkbmap`.

partial modifier_keys
xkb_symbols "bbq20" {
    // Alt droite devient Super : ouvre le menu démarrer.
    key <RALT> { [ Super_R ] };
    modifier_map Mod4 { <RALT> };
};
XKB

# Déclare la surcouche dans les règles XKB pour que setxkbmap l'accepte.
for rules in /usr/share/X11/xkb/rules/evdev; do
  [[ -f "$rules" ]] || continue
  if grep -q 'ghostboard:bbq20' "$rules"; then
    info "règle XKB déjà déclarée"
  else
    backup_file "$rules"
    run python3 - "$rules" <<'PY'
import sys, re
p = sys.argv[1]
s = open(p).read()
# Insère l'option dans la section ! option = symbols
m = re.search(r'^! option = symbols\s*$', s, re.M)
if m and 'ghostboard:bbq20' not in s:
    i = m.end()
    s = s[:i] + "\n  ghostboard:bbq20     = +ghostboard(bbq20)" + s[i:]
    open(p, 'w').write(s)
    print("  option XKB ghostboard:bbq20 déclarée")
else:
    print("  section '! option = symbols' introuvable — remappage manuel requis")
PY
  fi
done

# Appliqué à chaque session, sans dépendre du succès de l'édition des règles.
write_file /etc/X11/Xsession.d/95ghostboard-keyboard <<'XS'
# GHOSTBOARD OS — remappage clavier BB Q20 à l'ouverture de session.
# Deux chemins : l'option XKB si elle est déclarée, sinon xmodmap en secours.
if command -v setxkbmap >/dev/null 2>&1; then
    setxkbmap -option ghostboard:bbq20 2>/dev/null || \
      { command -v xmodmap >/dev/null 2>&1 && \
        printf 'clear mod1\nkeycode 108 = Super_R\nadd mod4 = Super_R\n' | xmodmap - 2>/dev/null; }
fi
XS

step "Console (hors session graphique)"
write_file /etc/default/keyboard <<'KB'
# GHOSTBOARD OS — clavier console.
XKBMODEL="pc105"
XKBLAYOUT="us"
XKBVARIANT=""
XKBOPTIONS=""
BACKSPACE="guess"
KB

good "Clavier configuré."
info "Vérifier après redémarrage : appuie sur Alt droite -> le menu démarrer doit s'ouvrir."
info "Sinon : xev -event keyboard, relève le code, et édite"
info "  /usr/share/X11/xkb/symbols/ghostboard"
