#!/usr/bin/env bash
# DESCRIPTION: Animation d'allumage WebGL + session GHOSTBOARD
# ============================================================================
#  Le seul moment spectaculaire de l'OS : ~1,4 s, puis le contexte WebGL est
#  détruit et plus rien ne tourne.
#
#  L'animation est lancée par une ENVELOPPE de session, pas par un démarrage
#  automatique : elle passe donc avant que le bureau ne soit dessiné, sans
#  clignotement. La session « Xfce Session » standard reste disponible à
#  l'écran de connexion — c'est le filet si l'enveloppe casse.
# ============================================================================
set -uo pipefail
. "$(dirname "${BASH_SOURCE[0]}")/../lib/common.sh"
need_root
apt_refresh

SPLASH_DIR="$GHOSTBOARD_SHARE/boot-animation"

step "Navigateur de rendu"
# Chromium sert aussi de navigateur du deck : il n'est pas installé pour
# l'animation seule.
apt_install chromium || apt_install chromium-browser

step "three.js"
run bash "$GHOSTBOARD_REPO/boot-animation/fetch-vendor.sh" \
  || die "récupération de three.js impossible (réseau ?)"

step "Installation de l'animation"
run install -d -m 0755 "$SPLASH_DIR/vendor"
install_file "$GHOSTBOARD_REPO/boot-animation/index.html" "$SPLASH_DIR/index.html"
install_file "$GHOSTBOARD_REPO/boot-animation/boot.js"    "$SPLASH_DIR/boot.js"
for f in "$GHOSTBOARD_REPO"/boot-animation/vendor/*.js; do
  install_file "$f" "$SPLASH_DIR/vendor/$(basename "$f")"
done
# La palette injectée dans la page : même source de vérité que le reste.
if [[ -f "$GHOSTBOARD_SHARE/palette.js" ]]; then
  install_file "$GHOSTBOARD_SHARE/palette.js" "$SPLASH_DIR/palette.js"
else
  warn "palette.js absent — lance d'abord l'étape 50-theme"
fi
run chmod -R a+rX "$SPLASH_DIR"

step "Session GHOSTBOARD"
write_file /usr/share/xsessions/ghostboard.desktop <<'XS'
[Desktop Entry]
Name=GHOSTBOARD
Comment=GHOSTBOARD OS — boot animation, then XFCE
Exec=/usr/local/bin/ghostboard-session
TryExec=/usr/local/bin/ghostboard-session
Icon=ghostboard-start
Type=Application
DesktopNames=XFCE
XS
good "session « GHOSTBOARD » ajoutée à l'écran de connexion"
info "« Xfce Session » reste sélectionnable : c'est le mode de secours."

step "Horodatage du bureau prêt"
# Sert à ghost-bench pour mesurer « boot -> bureau utilisable », qui est la
# vraie cible (< 20 s), et non « boot -> systemd a fini ».
for target in /etc/skel "$GHOSTBOARD_HOME"; do
  run mkdir -p "$target/.config/autostart"
  write_file "$target/.config/autostart/ghostboard-bench-mark.desktop" <<'AS'
[Desktop Entry]
Type=Application
Name=GHOSTBOARD boot timestamp
Comment=Records when the desktop became usable, for ghost-bench
Exec=ghost-bench --mark-ready
NoDisplay=true
X-GNOME-Autostart-Phase=Applications
AS
done
run chown -R "$GHOSTBOARD_USER" "$GHOSTBOARD_HOME/.config" 2>/dev/null || true
good "horodatage installé"

say ""
info "Tester l'animation sans redémarrer, depuis une session graphique :"
info "  ghost-boot-splash"
info "La désactiver : passer boot.enabled = false dans brand/palette.toml,"
info "puis 'sudo ghost-theme apply' (ou GHOSTBOARD_BOOT=0 pour un seul essai)."
