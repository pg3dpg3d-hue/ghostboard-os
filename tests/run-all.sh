#!/usr/bin/env bash
# GHOSTBOARD OS — tous les tests.
#
#   bash tests/run-all.sh
#
# Le test MCP a besoin d'un serveur X. Si Xvfb est présent, un écran virtuel
# 800x480 (la résolution exacte de la dalle) est monté pour l'occasion ; sinon
# le test tourne quand même et vérifie que les erreurs remontent proprement.
set -uo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
rc=0
hr() { printf '\n\033[38;2;168;85;247m── %s\033[0m\n' "$1"; }

hr "Configuration, thème et syntaxe"
bash tests/test-config.sh || rc=1

hr "Détection des cartes Bruce"
bash tests/test-bruce.sh || rc=1

hr "Audit de performance et répartition mémoire"
bash tests/test-perf.sh || rc=1

hr "Serveur MCP computer use"
if command -v Xvfb >/dev/null 2>&1 && ! [[ -n "${DISPLAY:-}" ]]; then
  Xvfb :99 -screen 0 800x480x24 -nolisten tcp >/dev/null 2>&1 &
  xp=$!
  for _ in $(seq 1 40); do DISPLAY=:99 xdpyinfo >/dev/null 2>&1 && break; sleep 0.1; done
  DISPLAY=:99 GHOSTBOARD_MCP_DISPLAY=:99 node tests/test-mcp.js || rc=1
  kill "$xp" 2>/dev/null; wait "$xp" 2>/dev/null
else
  node tests/test-mcp.js || rc=1
fi

hr "Installateur : le mode à blanc n'écrit rien"
before="$(md5sum /etc/fstab 2>/dev/null | cut -d' ' -f1)"
GHOSTBOARD_USER="${USER:-root}" ./install/ghostboard-install.sh --dry-run --yes \
  --step 10-base-system >/dev/null 2>&1
after="$(md5sum /etc/fstab 2>/dev/null | cut -d' ' -f1)"
if [[ "$before" == "$after" ]]; then echo "  OK  /etc/fstab intact après --dry-run"
else echo "  KO  /etc/fstab modifié par --dry-run"; rc=1; fi

printf '\n%s\n' "$([[ $rc -eq 0 ]] && echo 'TOUS LES TESTS PASSENT' || echo 'DES TESTS ONT ÉCHOUÉ')"
exit $rc
