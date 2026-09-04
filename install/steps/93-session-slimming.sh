#!/usr/bin/env bash
# DESCRIPTION: Dégraissage de la session — le levier principal sur la RAM au repos
# ============================================================================
#  Une session XFCE « normale » traîne une demi-douzaine de services que
#  personne n'a demandés : pont d'accessibilité, générateur de vignettes,
#  moniteurs de volumes pour appareils photo et téléphones, portails de bureau,
#  démon de gestion d'énergie. Aucun n'a de sens sur un cyberdeck.
#
#  Chacun coûte entre 8 et 40 Mo résidents, en permanence, pour rien. C'est là
#  que se joue la cible des 900 Mo — pas dans le noyau.
#
#  RÈGLE tenue ici : on privilégie la DÉSACTIVATION PAR CONFIGURATION à la
#  neutralisation par masquage. Régler Thunar pour qu'il ne demande jamais de
#  vignette est réversible d'une case à cocher ; masquer tumblerd casse
#  silencieusement le jour où on en veut. Le masquage n'est employé que là où
#  il n'existe pas de réglage.
#
#  Tout est réversible, et `ghost-perf` dit à tout moment ce qui est actif.
# ============================================================================
set -uo pipefail
. "$(dirname "${BASH_SOURCE[0]}")/../lib/common.sh"
need_root
require_step 40-xfce-desktop "il n'y a rien à dégraisser sans bureau installé"

# ---------------------------------------------------------------------------
#  1. Pont d'accessibilité (at-spi2)
# ---------------------------------------------------------------------------
step "Pont d'accessibilité"
# Toute application GTK démarre at-spi-bus-launcher + at-spi2-registryd, soit
# ~20 Mo et deux processus, pour un lecteur d'écran que ce deck n'a pas. La
# variable d'environnement suffit : GTK ne charge alors même pas le module.
info "at-spi2 : ~20 Mo pour un lecteur d'écran absent de ce deck"
write_file /etc/X11/Xsession.d/90ghostboard-lean <<'XS'
# GHOSTBOARD OS — allègement de session.
# NO_AT_BRIDGE empêche GTK de charger le pont d'accessibilité : ni processus,
# ni trafic D-Bus. Pour réactiver l'accessibilité, supprimer ce fichier.
export NO_AT_BRIDGE=1
export GTK_MODULES=""
# Chromium et GTK cherchent parfois un portail de bureau, utile surtout en
# Flatpak. Sans conteneur, le portail n'apporte rien et coûte deux processus.
export GTK_USE_PORTAL=0
XS
good "at-spi2 neutralisé par variable d'environnement (réversible)"

# ---------------------------------------------------------------------------
#  2. Vignettes (tumbler)
# ---------------------------------------------------------------------------
step "Générateur de vignettes"
# tumblerd est activé par D-Bus dès que Thunar affiche un dossier. Il monte à
# ~30 Mo et fait travailler le CPU sur des images qu'on ne regarde pas sur une
# dalle de 4 pouces. On le désactive par CONFIGURATION de Thunar : rien n'est
# masqué, la case existe toujours dans les préférences.
for target in /etc/skel "$GHOSTBOARD_HOME"; do
  xdg="$target/.config/xfce4/xfconf/xfce-perchannel-xml"
  run mkdir -p "$xdg"
  write_file "$xdg/thunar.xml" <<'THUNAR'
<?xml version="1.0" encoding="UTF-8"?>
<!-- GHOSTBOARD OS — Thunar.
     Vignettes coupées : tumblerd n'est alors jamais activé par D-Bus.
     Sur 800x480, une vue en liste compacte montre plus qu'une grille d'icônes. -->
<channel name="thunar" version="1.0">
  <property name="misc-thumbnail-mode" type="string" value="THUNAR_THUMBNAIL_MODE_NEVER"/>
  <property name="misc-thumbnail-max-file-size" type="uint64" value="0"/>
  <property name="default-view" type="string" value="ThunarCompactView"/>
  <property name="misc-single-click" type="bool" value="false"/>
  <property name="misc-text-beside-icons" type="bool" value="false"/>
  <property name="last-show-hidden" type="bool" value="false"/>
  <property name="misc-volume-management" type="bool" value="true"/>
  <property name="misc-recursive-permissions" type="string" value="THUNAR_RECURSIVE_PERMISSIONS_NEVER"/>
</channel>
THUNAR
done
run chown -R "$GHOSTBOARD_USER" "$GHOSTBOARD_HOME/.config" 2>/dev/null || true
good "vignettes coupées — tumblerd ne sera plus activé"

# ---------------------------------------------------------------------------
#  3. Démon Thunar
# ---------------------------------------------------------------------------
step "Démon Thunar"
# XFCE lance `Thunar --daemon` à chaque session pour accélérer la PREMIÈRE
# ouverture du gestionnaire de fichiers. Sur un deck où l'app principale est un
# terminal, on paie ~35 Mo en permanence pour économiser 300 ms une fois.
for target in /etc/skel "$GHOSTBOARD_HOME"; do
  run mkdir -p "$target/.config/autostart"
  write_file "$target/.config/autostart/thunar.desktop" <<'AS'
[Desktop Entry]
Type=Application
Name=Thunar (daemon)
Comment=GHOSTBOARD: ~35 Mo résidents pour gagner 300 ms au premier lancement.
Exec=true
Hidden=true
X-GNOME-Autostart-enabled=false
AS
done
good "démon Thunar désactivé (le gestionnaire de fichiers marche toujours)"

# ---------------------------------------------------------------------------
#  4. Moniteurs de volumes gvfs
# ---------------------------------------------------------------------------
step "Moniteurs de volumes"
# gvfs lance un moniteur PAR FAMILLE de périphériques. On garde udisks2 — c'est
# lui qui monte les clés USB — et on retire les autres : appareils photo (MTP,
# gphoto2), appareils Apple (afc), comptes en ligne (goa). Aucun ne concerne un
# cyberdeck, chacun coûte ~10 Mo.
slimmed=0
for unit in gvfs-gphoto2-volume-monitor.service gvfs-mtp-volume-monitor.service \
            gvfs-afc-volume-monitor.service gvfs-goa-volume-monitor.service; do
  if run systemctl --global mask "$unit" >/dev/null 2>&1; then
    slimmed=$((slimmed + 1))
  fi
done
[[ "$slimmed" -gt 0 ]] && good "$slimmed moniteur(s) gvfs masqué(s) — udisks2 conservé pour les clés USB"
info "réactiver : sudo systemctl --global unmask <unité>"

# ---------------------------------------------------------------------------
#  5. UPower
# ---------------------------------------------------------------------------
step "UPower"
# UPower interroge en boucle des batteries. Le deck est alimenté par powerbank
# USB-C PD : il n'expose AUCUN capteur de batterie au système. Le démon
# surveille donc le vide.
if systemctl list-unit-files upower.service >/dev/null 2>&1; then
  battery=0
  for b in /sys/class/power_supply/*; do
    [[ -f "$b/type" ]] && [[ "$(cat "$b/type" 2>/dev/null)" == "Battery" ]] && battery=1
  done
  if [[ "$battery" -eq 1 ]]; then
    info "une batterie est déclarée par le noyau — UPower conservé"
  else
    run systemctl disable --now upower.service >/dev/null 2>&1 \
      && good "UPower désactivé (aucune batterie exposée par le matériel)"
  fi
fi

# ---------------------------------------------------------------------------
#  6. Portails de bureau
# ---------------------------------------------------------------------------
step "Portails de bureau"
# xdg-desktop-portal + son moteur GTK servent à isoler les applications en
# conteneur (Flatpak, Snap). Sans conteneur, ils ne font qu'ajouter deux
# processus et un aller-retour D-Bus au sélecteur de fichiers.
if systemctl --global list-unit-files 'xdg-desktop-portal*' >/dev/null 2>&1; then
  if confirm "Masquer les portails de bureau (aucun Flatpak/Snap sur ce deck) ?"; then
    for unit in xdg-desktop-portal.service xdg-desktop-portal-gtk.service; do
      run systemctl --global mask "$unit" >/dev/null 2>&1 || true
    done
    good "portails masqués — GTK_USE_PORTAL=0 est déjà posé plus haut"
    info "si un sélecteur de fichiers se comporte mal : systemctl --global unmask xdg-desktop-portal.service"
  else
    info "portails conservés"
  fi
fi

# ---------------------------------------------------------------------------
#  7. Ce qu'on ne touche PAS, et pourquoi
# ---------------------------------------------------------------------------
step "Conservé volontairement"
info "dbus, polkit, xfconfd, xfsettingsd — la session ne démarre pas sans"
info "udisks2                         — monte les clés USB, utile sur un deck"
info "NetworkManager                  — le Wi-Fi d'un appareil nomade"
info "xfwm4 en compositeur            — sans lui, pas de translucidité de barre"
info "aucune pile audio n'est installée — ~40 Mo jamais dépensés"

say ""
info "Vérifier le résultat après reconnexion :"
info "  ghost-perf          audit complet, ligne par ligne"
info "  ghost-bench         RAM au repos et répartition par processus"
