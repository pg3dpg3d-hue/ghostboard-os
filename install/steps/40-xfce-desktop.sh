#!/usr/bin/env bash
# DESCRIPTION: XFCE minimal + gestionnaire de session, sans la suite complète
# ============================================================================
#  On installe les composants XFCE un par un, PAS le méta-paquet `xfce4`.
#  Le méta-paquet tire une trentaine d'applications (gestionnaire de mots de
#  passe, bloc-notes, économiseurs d'écran, mixeur…) dont aucune n'a sa place
#  sur un écran de 4 pouces qui vise 20 s de boot.
# ============================================================================
set -uo pipefail
. "$(dirname "${BASH_SOURCE[0]}")/../lib/common.sh"
need_root
has_stamp 00-preflight || die "lance d'abord l'étape 00-preflight"
apt_refresh

step "Serveur X et bureau"
apt_install \
  xserver-xorg-core xserver-xorg-input-libinput xserver-xorg-video-intel \
  x11-utils x11-xserver-utils xinit dbus-x11 \
  xfwm4 xfce4-session xfdesktop4 xfce4-panel xfce4-settings \
  xfce4-terminal xfce4-appfinder xfce4-screenshooter \
  xfce4-whiskermenu-plugin \
  thunar \
  papirus-icon-theme adwaita-icon-theme \
  policykit-1 xdg-utils

step "Gestionnaire de session"
info "LightDM est le plus léger des gestionnaires de connexion GTK."
info "Le changer est une opération sensible : si la session ne démarre plus,"
info "il faut passer par une console texte (Ctrl+Alt+F2) ou par SSH."
if confirm "Installer LightDM comme gestionnaire de session ?"; then
  apt_install lightdm lightdm-gtk-greeter
  write_file /etc/lightdm/lightdm.conf.d/60-ghostboard.conf <<'LDM'
# GHOSTBOARD OS — écran de connexion.
[Seat:*]
greeter-hide-users=false
greeter-show-manual-login=false
# La session GHOSTBOARD (animation d'allumage + XFCE) est celle par défaut.
# « Xfce Session » reste sélectionnable : c'est le filet si l'enveloppe casse.
user-session=ghostboard
LDM
  write_file /etc/lightdm/lightdm-gtk-greeter.conf.d/60-ghostboard.conf <<'GRT'
# GHOSTBOARD OS — thème de l'écran de connexion, cohérent avec le bureau.
[greeter]
theme-name=GhostboardSpectral
icon-theme-name=Papirus-Dark
font-name=IBM Plex Mono 11
background=/usr/share/ghostboard/wallpaper.png
indicators=~spacer;~clock;~session;~power
clock-format=%H:%M
hide-user-image=true
GRT
  good "LightDM configuré"
else
  info "ignoré — connexion en console puis 'startx' reste possible"
fi

step "Réglages XFCE par défaut"
# Copiés dans /etc/skel ET dans le compte existant : un nouveau compte hérite
# du bureau GHOSTBOARD, et le compte actuel le reçoit tout de suite.
for target in /etc/skel "$GHOSTBOARD_HOME"; do
  xdg="$target/.config/xfce4/xfconf/xfce-perchannel-xml"
  run mkdir -p "$xdg" "$target/.config/xfce4/panel"
  for f in "$GHOSTBOARD_REPO"/desktop/config/*.xml; do
    install_file "$f" "$xdg/$(basename "$f")"
  done
  install_file "$GHOSTBOARD_REPO/desktop/config/whiskermenu-1.rc" \
    "$target/.config/xfce4/panel/whiskermenu-1.rc"
  good "configuration XFCE déposée dans $target"
done
run chown -R "$GHOSTBOARD_USER" "$GHOSTBOARD_HOME/.config" 2>/dev/null || true

step "Services de session inutiles"
# xfce4-session lance par défaut des choses qu'un deck n'utilise pas.
for target in /etc/skel "$GHOSTBOARD_HOME"; do
  run mkdir -p "$target/.config/autostart"
  for unwanted in xfce4-power-manager xscreensaver light-locker \
                  print-applet blueman geoclue-demo-agent; do
    write_file "$target/.config/autostart/$unwanted.desktop" <<AS
[Desktop Entry]
Type=Application
Name=$unwanted
Hidden=true
X-GNOME-Autostart-enabled=false
AS
  done
done
good "démarrages automatiques superflus neutralisés"
info "(fichiers dans ~/.config/autostart — supprime-en un pour le réactiver)"
