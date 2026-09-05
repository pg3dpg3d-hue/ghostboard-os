#!/usr/bin/env bash
# DESCRIPTION: Coffre chiffré LUKS pour les secrets (clé API, LLM, SSH)
# ============================================================================
#  La session directe s'ouvre sans mot de passe : ce coffre chiffre les
#  identifiants pour qu'un deck perdu ne livre pas la clé API Claude.
#
#  Ceci N'EST PAS le chiffrement du disque entier (FDE). Le FDE protège tout
#  l'OS mais se met en place à l'installation de Debian (LVM chiffré) — voir
#  docs/ENCRYPTION.md. Ce coffre est la protection non destructive des SECRETS,
#  ajoutable après coup.
# ============================================================================
set -uo pipefail
. "$(dirname "${BASH_SOURCE[0]}")/../lib/common.sh"
need_root
apt_refresh

step "cryptsetup"
apt_install cryptsetup

step "Détection"
root_src="$(findmnt -no SOURCE / 2>/dev/null)"
if [[ "$root_src" == /dev/mapper/* ]] && cryptsetup status "${root_src#/dev/mapper/}" >/dev/null 2>&1; then
  good "racine déjà chiffrée (FDE) : $root_src — le coffre reste utile pour isoler les secrets"
else
  info "racine NON chiffrée ($root_src) : le FDE demande une réinstallation (docs/ENCRYPTION.md)."
  info "Le coffre chiffre au moins les secrets, sans réinstaller."
fi

step "Création du coffre"
if [[ -f /var/lib/ghostboard/vault.img ]]; then
  good "un coffre existe déjà (/var/lib/ghostboard/vault.img)"
elif confirm "Créer un coffre chiffré de 2 Go pour les secrets ?"; then
  info "Tu vas choisir une phrase de passe. Elle protège tes clés — pas de phrase, pas de secrets."
  as_user_env() { GHOSTBOARD_SHARE="$GHOSTBOARD_SHARE" "$@"; }
  if [[ "$DRY_RUN" == "1" ]]; then
    info "[à blanc] créerait /var/lib/ghostboard/vault.img (2G, LUKS2)"
  else
    SUDO_USER="$GHOSTBOARD_USER" /usr/local/bin/ghost-vault create --size 2G \
      && good "coffre créé" || warn "création interrompue — relance : sudo ghost-vault create"
  fi
else
  info "ignoré"
fi

step "Ouverture au login (facultatif)"
# Pour ouvrir le coffre à la session sans mot de passe root (seulement la
# phrase du coffre), on autorise ghost-vault open via sudoers, et on l'ajoute
# en autostart. La phrase, elle, est toujours demandée.
if confirm "Autoriser l'ouverture du coffre au login (sudoers + autostart) ?"; then
  write_file /etc/sudoers.d/ghostboard-vault <<SUDOERS
# GHOSTBOARD OS — ouvrir/fermer le coffre sans mot de passe root.
# La phrase de passe du coffre reste demandée par cryptsetup.
$GHOSTBOARD_USER ALL=(root) NOPASSWD: /usr/local/bin/ghost-vault open, /usr/local/bin/ghost-vault close
SUDOERS
  run chmod 0440 /etc/sudoers.d/ghostboard-vault
  for target in /etc/skel "$GHOSTBOARD_HOME"; do
    run mkdir -p "$target/.config/autostart"
    write_file "$target/.config/autostart/ghostboard-vault.desktop" <<AS
[Desktop Entry]
Type=Application
Name=GHOSTBOARD vault
Comment=Ouvre le coffre chiffré (demande la phrase de passe)
Exec=xfce4-terminal -T "GHOSTBOARD vault" -e "sudo ghost-vault open"
X-GNOME-Autostart-Phase=Applications
AS
  done
  run chown -R "$GHOSTBOARD_USER" "$GHOSTBOARD_HOME/.config" 2>/dev/null || true
  good "ouverture au login armée (la phrase du coffre est toujours demandée)"
else
  info "ignoré — ouvre à la main : sudo ghost-vault open"
fi

say ""
info "État : ghost-vault status   ·   ghost-status (ligne « Encryption »)"
info "Protéger un dossier de plus : sudo ghost-vault protect ~/.ssh"
