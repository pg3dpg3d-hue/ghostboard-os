#!/usr/bin/env bash
# DESCRIPTION: Serveur MCP computer use, branché à Claude Code
# ============================================================================
#  Le raisonnement est dans le cloud, le CONTRÔLE DE L'ÉCRAN est ici.
#  Ce serveur expose screenshot / click / type / key à Claude Code.
#
#  Session dédiée (décision v1) : le mécanisme est installé mais DÉSACTIVÉ.
#  Par défaut l'agent voit ton bureau (:0). Pour lui donner un écran séparé :
#      sudo systemctl enable --now ghostboard-agent-display
#      ghost-agent-session on
#  Bascule sans réinstaller, et coût nul tant que c'est éteint.
# ============================================================================
set -uo pipefail
. "$(dirname "${BASH_SOURCE[0]}")/../lib/common.sh"
need_root
apt_refresh

MCP_DIR=/usr/local/lib/ghostboard/mcp-computer-use

step "Outils de capture et de saisie"
# scrot : capture PNG, ~1 Mo de dépendances. xdotool : clics et frappes.
# Aucun des deux ne tourne en tâche de fond : ils sont appelés à la demande.
apt_install scrot xdotool

step "Installation du serveur"
run install -d -m 0755 "$MCP_DIR"
install_file "$GHOSTBOARD_REPO/mcp-computer-use/server.js" "$MCP_DIR/server.js" 0755
install_file "$GHOSTBOARD_REPO/mcp-computer-use/package.json" "$MCP_DIR/package.json" 0644
good "serveur installé dans $MCP_DIR (zéro dépendance npm)"

step "Enregistrement auprès de Claude Code"
if as_user bash -lc 'command -v claude >/dev/null 2>&1'; then
  # `claude mcp add` est idempotent côté nom : on retire d'abord une éventuelle
  # entrée précédente pour éviter les doublons.
  as_user bash -lc "claude mcp remove ghostboard-computer-use --scope user 2>/dev/null || true"
  if as_user bash -lc "claude mcp add ghostboard-computer-use --scope user -- node '$MCP_DIR/server.js'"; then
    good "serveur MCP enregistré (portée utilisateur)"
  else
    warn "'claude mcp add' a échoué — configuration écrite à la main ci-dessous"
    as_user mkdir -p "$GHOSTBOARD_HOME/.claude"
    as_user bash -c "cat > '$GHOSTBOARD_HOME/.claude/ghostboard-mcp.json'" <<JSON
{
  "mcpServers": {
    "ghostboard-computer-use": {
      "command": "node",
      "args": ["$MCP_DIR/server.js"],
      "env": { "GHOSTBOARD_MCP_DISPLAY": ":0" }
    }
  }
}
JSON
    info "fusionne ce fichier dans ta configuration Claude Code :"
    info "  $GHOSTBOARD_HOME/.claude/ghostboard-mcp.json"
  fi
else
  warn "Claude Code absent — lance d'abord l'étape 60-nodejs-claude-code"
fi

step "Session graphique dédiée à l'agent (désactivée par défaut)"
# Xvfb à la résolution exacte de la dalle : ce que l'agent voit correspond
# pixel pour pixel à ce que verrait l'écran, donc les coordonnées de clic
# restent valables si tu bascules d'un mode à l'autre.
write_file /etc/systemd/system/ghostboard-agent-display.service <<UNIT
[Unit]
Description=GHOSTBOARD — écran virtuel dédié à l'agent (computer use)
Documentation=file://$GHOSTBOARD_REPO/docs/agent-session.md
After=network.target

[Service]
Type=simple
User=$GHOSTBOARD_USER
# 800x480 : identique à la dalle. L'agent ne doit jamais raisonner sur une
# géométrie différente de la vraie.
ExecStart=/usr/bin/Xvfb :1 -screen 0 800x480x24 -nolisten tcp
ExecStartPost=/bin/sh -c 'for i in \$(seq 1 50); do DISPLAY=:1 /usr/bin/xdpyinfo >/dev/null 2>&1 && break; sleep 0.1; done; DISPLAY=:1 /usr/bin/xfwm4 --daemon 2>/dev/null || true'
Restart=on-failure
RestartSec=2

[Install]
WantedBy=multi-user.target
UNIT

write_file /usr/local/bin/ghost-agent-session 0755 <<'AGENT'
#!/usr/bin/env bash
# GHOSTBOARD OS — bascule de la session vue par l'agent.
#
#   ghost-agent-session status   sur quel écran l'agent travaille
#   ghost-agent-session on       écran dédié :1 (l'agent ne voit pas ton bureau)
#   ghost-agent-session off      ton bureau :0 (défaut)
#
# La bascule change GHOSTBOARD_MCP_DISPLAY dans la configuration MCP de
# Claude Code. Redémarre Claude Code pour qu'elle prenne effet.
set -uo pipefail
CONF="$HOME/.claude.json"
case "${1:-status}" in
  on)
    sudo systemctl enable --now ghostboard-agent-display || exit 1
    python3 - "$CONF" :1 <<'PY'
import json, sys, pathlib
p = pathlib.Path(sys.argv[1]); disp = sys.argv[2]
d = json.loads(p.read_text()) if p.exists() else {}
srv = d.setdefault("mcpServers", {}).setdefault("ghostboard-computer-use", {})
srv.setdefault("command", "node")
srv.setdefault("args", ["/usr/local/lib/ghostboard/mcp-computer-use/server.js"])
srv.setdefault("env", {})["GHOSTBOARD_MCP_DISPLAY"] = disp
p.write_text(json.dumps(d, indent=2) + "\n")
print(f"MCP computer use -> écran {disp}")
PY
    echo "Redémarre Claude Code pour appliquer."
    ;;
  off)
    python3 - "$CONF" :0 <<'PY'
import json, sys, pathlib
p = pathlib.Path(sys.argv[1]); disp = sys.argv[2]
d = json.loads(p.read_text()) if p.exists() else {}
srv = d.setdefault("mcpServers", {}).setdefault("ghostboard-computer-use", {})
srv.setdefault("env", {})["GHOSTBOARD_MCP_DISPLAY"] = disp
p.write_text(json.dumps(d, indent=2) + "\n")
print(f"MCP computer use -> écran {disp}")
PY
    sudo systemctl disable --now ghostboard-agent-display 2>/dev/null || true
    echo "Redémarre Claude Code pour appliquer."
    ;;
  status)
    active=$(systemctl is-active ghostboard-agent-display 2>/dev/null || echo inactive)
    disp=$(python3 -c '
import json,pathlib,sys
p=pathlib.Path(sys.argv[1])
try:
    print(json.loads(p.read_text())["mcpServers"]["ghostboard-computer-use"]["env"]["GHOSTBOARD_MCP_DISPLAY"])
except Exception:
    print(":0 (défaut)")' "$CONF")
    echo "écran virtuel de l'agent : $active"
    echo "le MCP pilote l'écran      : $disp"
    ;;
  *) sed -n '2,10p' "$0" | sed 's/^# \{0,1\}//'; exit 2 ;;
esac
AGENT

run systemctl daemon-reload
good "session dédiée prête, DÉSACTIVÉE (ghost-agent-session on pour l'activer)"

say ""
info "Vérifier le serveur MCP :"
info "  node $GHOSTBOARD_REPO/tests/test-mcp.js"
