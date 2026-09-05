#!/usr/bin/env bash
# DESCRIPTION: LLM local — config LM Studio (Dolphin) et démarrage du serveur
# ============================================================================
#  L'architecture a changé : le raisonnement tourne EN LOCAL sur le deck, via
#  LM Studio servant Dolphin derrière une API compatible OpenAI. Cette étape
#  configure l'accès (ghost-llm) et, si le CLI `lms` est présent, démarre le
#  serveur au boot.
#
#  LM Studio LUI-MÊME n'est pas installé ici : c'est une application à
#  télécharger (lmstudio.ai). Cette étape prépare tout autour et le dit
#  clairement si LM Studio manque — elle n'échoue pas pour autant.
# ============================================================================
set -uo pipefail
. "$(dirname "${BASH_SOURCE[0]}")/../lib/common.sh"
need_root

LLM_BASE_DEFAULT="http://127.0.0.1:1234/v1"

step "Configuration ghost-llm"
# Config lue par ghost-llm et ghost-status. model=auto -> le client choisit le
# modèle contenant « dolphin » parmi ceux que LM Studio sert.
write_file "$GHOSTBOARD_SHARE/llm.json" <<JSON
{
  "//": "GHOSTBOARD OS — accès au LLM local (LM Studio). Édite base/model si besoin.",
  "base": "$LLM_BASE_DEFAULT",
  "model": "auto",
  "key": "lm-studio",
  "temperature": 0.7,
  "system": "You are the on-device assistant of a GHOSTBOARD cyberdeck. Be concise: the screen is 4 inches. Plain text, no markdown tables.",
  "//ram": "Garde-fou : avertit si le modèle risque de ne pas tenir en RAM.",
  "ram_check": true,
  "ram_reserve_gb": 2.0,
  "//proxy": "Port de ghost-llm-proxy (route Claude Code sur le modèle local).",
  "proxy_port": 8788
}
JSON
run chmod a+r "$GHOSTBOARD_SHARE/llm.json"
good "config écrite : $GHOSTBOARD_SHARE/llm.json"

step "LM Studio"
if command -v lms >/dev/null 2>&1; then
  good "CLI LM Studio (lms) présent"
  # Service utilisateur : démarre le serveur LM Studio à l'ouverture de session,
  # sans démon système. `lms server start` est idempotent.
  su_home="$GHOSTBOARD_HOME/.config/systemd/user"
  run mkdir -p "$su_home"
  write_file "$su_home/ghostboard-lmstudio.service" <<UNIT
[Unit]
Description=GHOSTBOARD — serveur LM Studio (LLM local)
After=graphical-session.target

[Service]
Type=oneshot
RemainAfterExit=yes
# --port 1234 : c'est ce que pointe llm.json. headless : pas d'UI.
ExecStart=/usr/bin/env lms server start --port 1234
ExecStop=/usr/bin/env lms server stop

[Install]
WantedBy=default.target
UNIT
  run chown -R "$GHOSTBOARD_USER" "$GHOSTBOARD_HOME/.config/systemd" 2>/dev/null || true
  if confirm "Démarrer le serveur LM Studio automatiquement à l'ouverture de session ?"; then
    as_user systemctl --user daemon-reload 2>/dev/null || true
    as_user systemctl --user enable ghostboard-lmstudio.service 2>/dev/null \
      && good "serveur LM Studio activé au démarrage de session" \
      || warn "activation du service utilisateur impossible (systemd --user ?)"
  else
    info "non activé — démarrer à la main : lms server start --port 1234"
  fi
else
  warn "LM Studio (CLI lms) absent"
  info "Installe LM Studio depuis lmstudio.ai (AppImage x86_64), puis :"
  info "  1. charge un modèle Dolphin dans l'onglet Discover/My Models"
  info "  2. onglet Developer -> Start Server  (ou : lms server start)"
  info "  3. vérifie : ghost-llm --check"
fi

step "Réalité matérielle"
ram="$(ram_gb)"
info "Dolphin sur N100 (CPU, pas de GPU) : compte quelques tokens/s."
if [[ "$ram" -lt 16 ]]; then
  warn "${ram} Go de RAM : privilégie un Dolphin 3B (q4) — un 7B tiendra mais lentement"
else
  info "${ram} Go : un Dolphin 7B (q4) passe ; un 3B reste plus réactif sur la dalle"
fi

step "Claude Code sur le modèle local (facultatif)"
info "ghost-claude --local  route Claude Code vers le modèle local via un proxy"
info "de traduction (Anthropic -> OpenAI/LM Studio). Voir docs/CLAUDE-CODE-LOCAL.md."
info "Le petit modèle local fait mal l'agentique : à réserver au chat/édition simple."

say ""
info "Chat : ghost-llm        (menu : AI · Local LLM)"
info "Test : ghost-llm --check"
info "État : ghost-status  (ligne « Local LLM »)"
