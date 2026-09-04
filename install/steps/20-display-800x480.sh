#!/usr/bin/env bash
# DESCRIPTION: Dalle HDMI 800x480 — mode vidéo, DPI, garde-fou de revert
# ============================================================================
#  ÉTAPE SENSIBLE. Si le mode vidéo est faux, l'écran devient noir.
#
#  Deux protections :
#    1. l'étape refuse de tourner si 00-preflight n'est pas passée
#       (donc sans filet SSH constaté) ;
#    2. un GARDE-FOU : après application, un minuteur systemd restaure la
#       configuration précédente dans 3 minutes, SAUF si tu confirmes que
#       l'écran fonctionne toujours (`ghost-display-guard keep`).
#       Écran noir = on ne touche à rien, on attend 3 minutes, ça revient.
# ============================================================================
set -uo pipefail
. "$(dirname "${BASH_SOURCE[0]}")/../lib/common.sh"
need_root
require_step 00-preflight "sans filet SSH constaté, perdre l'écran c'est perdre la machine"

XORG_CONF=/etc/X11/xorg.conf.d/20-ghostboard-panel.conf

step "Mode vidéo 800x480"
info "Beaucoup de petites dalles HDMI n'annoncent pas d'EDID correct."
info "On force donc le mode côté noyau ET côté Xorg."

apt_install x11-xserver-utils read-edid

# --- garde-fou --------------------------------------------------------------
write_file /usr/local/bin/ghost-display-guard 0755 <<'GUARD'
#!/usr/bin/env bash
# GHOSTBOARD OS — garde-fou d'affichage.
#   ghost-display-guard arm     sauvegarde et arme la restauration (3 min)
#   ghost-display-guard keep    l'écran marche : on garde, on désarme
#   ghost-display-guard revert  restaure immédiatement
set -uo pipefail
STATE=/var/lib/ghostboard/display-guard
CONF=/etc/X11/xorg.conf.d/20-ghostboard-panel.conf
case "${1:-}" in
  arm)
    mkdir -p "$STATE"
    [[ -f "$CONF" ]] && cp -a "$CONF" "$STATE/xorg.conf.previous" \
                     || : > "$STATE/no-previous-conf"
    systemd-run --unit=ghostboard-display-revert --on-active=180 \
      /usr/local/bin/ghost-display-guard revert >/dev/null 2>&1
    echo "Garde-fou armé : restauration automatique dans 3 minutes."
    echo "Si l'écran fonctionne : sudo ghost-display-guard keep"
    ;;
  keep)
    systemctl stop ghostboard-display-revert.timer 2>/dev/null
    systemctl stop ghostboard-display-revert.service 2>/dev/null
    rm -f "$STATE/xorg.conf.previous" "$STATE/no-previous-conf"
    echo "Configuration d'affichage conservée."
    ;;
  revert)
    if [[ -f "$STATE/xorg.conf.previous" ]]; then
      cp -a "$STATE/xorg.conf.previous" "$CONF"
    else
      rm -f "$CONF"
    fi
    rm -f "$STATE/xorg.conf.previous" "$STATE/no-previous-conf"
    logger -t ghostboard "configuration d'affichage restaurée par le garde-fou"
    echo "Configuration d'affichage restaurée."
    ;;
  *) sed -n '2,6p' "$0" | sed 's/^# \{0,1\}//'; exit 2 ;;
esac
GUARD
good "ghost-display-guard installé"

# --- détection de la sortie -------------------------------------------------
output=""
for card in /sys/class/drm/card*-*; do
  [[ -f "$card/status" ]] && [[ "$(cat "$card/status")" == "connected" ]] || continue
  output="$(basename "$card" | sed 's/^card[0-9]*-//')"
  break
done
if [[ -z "$output" ]]; then
  warn "aucune sortie vidéo connectée : configuration Xorg non écrite"
  info "Rebranche la dalle et relance : sudo ./install/ghostboard-install.sh --step 20-display-800x480 --force"
  exit 75   # « sautée », pas « en échec »
fi
good "sortie détectée : $output"

say ""
warn "Écriture de $XORG_CONF (mode forcé 800x480)."
info "Un garde-fou restaurera l'ancienne configuration dans 3 minutes"
info "si tu ne confirmes pas que l'écran fonctionne."
confirm "Appliquer la configuration d'affichage 800x480 ?" || { info "ignoré"; exit 75; }

run /usr/local/bin/ghost-display-guard arm

# Modeline CVT pour 800x480 @ 60 Hz — calculée, pas devinée :
#   cvt 800 480 60  ->  29.58 MHz, 800 848 928 1008, 480 483 493 500
write_file "$XORG_CONF" <<CONF
# GHOSTBOARD OS — dalle HDMI 4 pouces, 800x480.
# GÉNÉRÉ par install/steps/20-display-800x480.sh
#
# Le mode est FORCÉ : beaucoup de petites dalles HDMI n'exposent pas d'EDID
# exploitable, et X choisit alors 1024x768 sur un écran qui ne l'affiche pas.
# Modeline issue de : cvt 800 480 60
Section "Monitor"
    Identifier  "GHOSTBOARD-Panel"
    Modeline    "800x480_60.00"  29.58  800 848 928 1008  480 483 493 500 -hsync +vsync
    Option      "PreferredMode" "800x480_60.00"
    # DPI cohérent avec une dalle de ~4 pouces : sans ça, les polices sont
    # calculées pour un écran de bureau et deviennent illisibles.
    DisplaySize 102 61
EndSection

Section "Device"
    Identifier  "GHOSTBOARD-GPU"
    Driver      "modesetting"
    Option      "AccelMethod" "glamor"
    # TearFree coûte peu sur l'iGPU du N100 et évite le déchirement du
    # compositeur XFCE sur un écran à 60 Hz.
    Option      "TearFree" "true"
EndSection

Section "Screen"
    Identifier  "GHOSTBOARD-Screen"
    Device      "GHOSTBOARD-GPU"
    Monitor     "GHOSTBOARD-Panel"
    DefaultDepth 24
    SubSection "Display"
        Depth   24
        Modes   "800x480_60.00"
    EndSubSection
EndSection
CONF

step "Mode noyau"
info "Le mode est aussi forcé au démarrage : l'affichage est correct dès"
info "le chargement du noyau, pas seulement une fois X lancé."
if confirm "Ajouter video=$output:800x480@60 aux paramètres du noyau (GRUB) ?"; then
  backup_file /etc/default/grub
  if grep -q "video=$output:800x480" /etc/default/grub; then
    good "paramètre déjà présent"
  else
    run sed -i "s|^GRUB_CMDLINE_LINUX_DEFAULT=\"\(.*\)\"|GRUB_CMDLINE_LINUX_DEFAULT=\"\1 video=$output:800x480@60\"|" /etc/default/grub
    run update-grub && good "GRUB mis à jour"
  fi
else
  info "ignoré — X forcera quand même le mode"
fi

say ""
warn "REDÉMARRE, puis vérifie l'écran."
warn "S'il fonctionne :  sudo ghost-display-guard keep"
warn "Sinon : ne fais rien, la configuration revient seule en 3 minutes."
