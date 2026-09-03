#!/usr/bin/env bash
# DESCRIPTION: Node.js LTS + Claude Code, cœur du système
# ============================================================================
#  Claude Code est le centre de l'OS : accès terminal et fichiers, et c'est
#  lui qui orchestre le serveur MCP computer use.
#
#  Node est installé depuis NodeSource plutôt que depuis Debian : la version
#  de Debian 13 est figée pour la durée de la stable, et Claude Code suit le
#  rythme des LTS.
# ============================================================================
set -uo pipefail
. "$(dirname "${BASH_SOURCE[0]}")/../lib/common.sh"
need_root
apt_refresh

NODE_MAJOR="${NODE_MAJOR:-22}"

step "Node.js $NODE_MAJOR LTS"
if command -v node >/dev/null 2>&1 && \
   [[ "$(node -v | sed 's/^v\([0-9]*\).*/\1/')" -ge "$NODE_MAJOR" ]]; then
  good "Node $(node -v) déjà installé"
else
  apt_install ca-certificates curl gnupg
  keyring=/etc/apt/keyrings/nodesource.gpg
  if [[ ! -f "$keyring" ]]; then
    run install -d -m 0755 /etc/apt/keyrings
    run bash -c "curl -fsSL https://deb.nodesource.com/gpgkey/nodesource-repo.gpg.key \
      | gpg --dearmor -o '$keyring'" || die "récupération de la clé NodeSource impossible"
    run chmod a+r "$keyring"
  fi
  write_file /etc/apt/sources.list.d/nodesource.list <<SRC
deb [signed-by=$keyring] https://deb.nodesource.com/node_${NODE_MAJOR}.x nodistro main
SRC
  _APT_REFRESHED=""; apt_refresh
  apt_install nodejs
  good "Node $(node -v) installé"
fi

step "Claude Code"
if command -v claude >/dev/null 2>&1; then
  good "déjà installé : $(claude --version 2>/dev/null | head -1)"
else
  # Installation globale, mais avec un préfixe npm propre à l'utilisateur :
  # pas de paquet npm en root, et les mises à jour ne demandent pas sudo.
  as_user bash -c '
    set -e
    prefix="$HOME/.local/npm-global"
    mkdir -p "$prefix"
    npm config set prefix "$prefix"
    npm install -g @anthropic-ai/claude-code
  ' || die "installation de Claude Code impossible (réseau ?)"

  write_file /etc/profile.d/ghostboard-npm.sh <<'NPM'
# GHOSTBOARD OS — binaires npm de l'utilisateur dans le PATH.
case ":$PATH:" in
  *":$HOME/.local/npm-global/bin:"*) ;;
  *) export PATH="$HOME/.local/npm-global/bin:$PATH" ;;
esac
NPM
  good "Claude Code installé dans ~/.local/npm-global"
  info "Ouvre une nouvelle session pour que le PATH soit pris en compte."
fi

say ""
info "Authentification : lance 'claude' une fois et suis les instructions."
info "Sans réseau, 'ghost-claude' te préviendra plutôt que d'échouer en silence."
