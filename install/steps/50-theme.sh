#!/usr/bin/env bash
# DESCRIPTION: Polices de marque + thème GHOSTBOARD généré depuis la palette
# ============================================================================
#  Tout ce qui a une couleur dans cet OS sort de brand/palette.toml.
#  Cette étape lance le générateur et installe le résultat.
# ============================================================================
set -uo pipefail
. "$(dirname "${BASH_SOURCE[0]}")/../lib/common.sh"
need_root
apt_refresh

step "Polices"
# IBM Plex Mono est dans Debian. Martian Mono n'y est pas : on va la chercher
# dans le dépôt google/fonts (OFL), voir boot-animation/fetch-fonts.sh.
apt_install fonts-ibm-plex fontconfig librsvg2-bin librsvg2-common
run bash "$GHOSTBOARD_REPO/boot-animation/fetch-fonts.sh" /usr/local/share/fonts/ghostboard
run fc-cache -f >/dev/null 2>&1 || true
if fc-list 2>/dev/null | grep -qi 'martian'; then
  good "Martian Mono disponible pour fontconfig"
else
  warn "Martian Mono introuvable après installation — le logotype retombera sur IBM Plex Mono"
fi

step "Vérification de la palette"
# Un thème illisible ne doit pas pouvoir s'installer : contrastes et tailles
# de police sont contrôlés avant écriture.
run python3 "$GHOSTBOARD_REPO/theme/render-theme.py" --check \
  || die "la palette échoue au contrôle de lisibilité — corrige brand/palette.toml"

step "Génération et installation"
as_user python3 "$GHOSTBOARD_REPO/theme/render-theme.py" \
  --install --home "$GHOSTBOARD_HOME" --share-dir "$GHOSTBOARD_SHARE"

# Le fond d'écran et la palette sont lus par le gestionnaire de connexion,
# qui tourne sous un autre compte : ils doivent être lisibles par tous.
run chmod -R a+rX "$GHOSTBOARD_SHARE"

step "Lanceurs d'applications"
run mkdir -p "$GHOSTBOARD_HOME/.local/share/applications"
for f in "$GHOSTBOARD_REPO"/desktop/launchers/*.desktop; do
  install_file "$f" "$GHOSTBOARD_HOME/.local/share/applications/$(basename "$f")"
done
run chown -R "$GHOSTBOARD_USER" "$GHOSTBOARD_HOME/.local" 2>/dev/null || true
as_user update-desktop-database "$GHOSTBOARD_HOME/.local/share/applications" 2>/dev/null || true
as_user gtk-update-icon-cache -f -t "$GHOSTBOARD_HOME/.local/share/icons/hicolor" 2>/dev/null || true
good "lanceurs installés"

step "Outils GHOSTBOARD"
for t in ghost-theme ghost-status ghost-claude ghost-browser ghost-bench \
         ghost-perf ghost-run ghost-llm ghost-bruce ghost-boot-splash \
         ghostboard-session; do
  install_file "$GHOSTBOARD_REPO/tools/$t" "/usr/local/bin/$t" 0755
done
good "outils installés dans /usr/local/bin"

# Lien vers la TUI RECON (elle vit dans camera-audit/, pas dans tools/) pour
# que ghost-run et le PATH la trouvent. Le module s'installe séparément via
# camera-audit/install.sh (dépendances lourdes : docker, nmap, venv).
if [[ -x "$GHOSTBOARD_REPO/camera-audit/bin/ghost-recon" ]]; then
  run ln -sf "$GHOSTBOARD_REPO/camera-audit/bin/ghost-recon" /usr/local/bin/ghost-recon
  good "ghost-recon relié (installer le module : camera-audit/install.sh)"
fi

# ghost-theme doit retrouver le dépôt pour régénérer le thème plus tard.
write_file /etc/profile.d/ghostboard.sh <<PROF
# GHOSTBOARD OS — emplacement du dépôt, pour ghost-theme et ghost-bench.
export GHOSTBOARD_REPO="$GHOSTBOARD_REPO"
export GHOSTBOARD_SHARE="$GHOSTBOARD_SHARE"
PROF
good "GHOSTBOARD_REPO=$GHOSTBOARD_REPO exporté pour toutes les sessions"
