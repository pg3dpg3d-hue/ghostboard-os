#!/usr/bin/env bash
# Validation structurelle de tout ce qui est livré : XML XFCE, SVG générés,
# JSON, fichiers .desktop, et syntaxe shell/python/node.
# Ce test existe parce qu'un XML cassé ne se voit pas avant le prochain
# démarrage de session — trop tard.
set -uo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
pass=0; fail=0
ck() { if [[ "$2" == "0" ]]; then echo "  OK  $1"; pass=$((pass+1));
       else echo "  KO  $1"; fail=$((fail+1)); fi; }

echo "Configuration XFCE (XML)"
for f in desktop/config/*.xml; do
  python3 -c "import xml.etree.ElementTree as ET,sys;ET.parse(sys.argv[1])" "$f" 2>/dev/null
  ck "$(basename "$f")" $?
done

echo "Lanceurs (.desktop)"
for f in desktop/launchers/*.desktop; do
  python3 - "$f" <<'PY' 2>/dev/null
import configparser, sys
c = configparser.ConfigParser(interpolation=None, strict=False)
c.read(sys.argv[1], encoding='utf-8')
e = c['Desktop Entry']
assert e['Type'] == 'Application' and e['Name'].strip() and e['Exec'].strip()
PY
  ck "$(basename "$f")" $?
done

echo "JSON"
for f in .mcp.json mcp-computer-use/package.json; do
  python3 -c "import json,sys;json.load(open(sys.argv[1]))" "$f" 2>/dev/null
  ck "$f" $?
done

echo "Thème généré depuis la palette"
python3 theme/render-theme.py --check >/dev/null 2>&1
ck "contrastes et cohérence de la palette" $?
out="$(mktemp -d)"
python3 theme/render-theme.py --out "$out" >/dev/null 2>&1
ck "génération complète" $?
for f in $(find "$out" -name '*.svg'); do
  python3 -c "import xml.etree.ElementTree as ET,sys;ET.parse(sys.argv[1])" "$f" 2>/dev/null
  ck "SVG $(basename "$f")" $?
done
n=$(find "$out" -name '*.png' | wc -l)
[[ "$n" -ge 32 ]]; ck "$n boutons de fenêtre PNG générés" $?
for want in gtk-3.0/gtk.css gtk-4.0/gtk.css xfwm4/themerc; do
  [[ -s "$out/themes/GhostboardSpectral/$want" ]]; ck "thème : $want" $?
done
for want in palette.json palette.sh palette.js terminalrc Xresources; do
  [[ -s "$out/share/$want" ]]; ck "ressource : $want" $?
done
grep -q '#A855F7' "$out/themes/GhostboardSpectral/gtk-3.0/gtk.css"
ck "accent de la palette présent dans le CSS généré" $?
rm -rf "$out"

echo "Pages générées depuis le thème"
gen="$(mktemp -d)"
for tool in build-boot-preview build-os-preview; do
  python3 "tools/$tool.py" "$gen/$tool.html" >/dev/null 2>&1
  ck "$tool.py s'exécute" $?
  # Un balisage déséquilibré ne se voit pas à l'oeil : une balise non fermée
  # avale silencieusement le reste de la page — c'est arrivé deux fois ici.
  python3 -c '
import sys
h = open(sys.argv[1], encoding="utf-8").read()
assert h.count("<div") == h.count("</div>"), (
    f"{h.count(chr(60)+chr(100)+chr(105)+chr(118))} ouvertures pour "
    f"{h.count(chr(60)+chr(47)+chr(100)+chr(105)+chr(118)+chr(62))} fermetures")
assert "<title>" in h[:8192], "titre absent des 8 premiers Ko"
assert len(h) > 20000, "page anormalement courte"
' "$gen/$tool.html" 2>/dev/null
  ck "$tool : balisage équilibré, titre présent" $?
done
rm -rf "$gen"

echo "Syntaxe"
for f in $(find . -name '*.sh' -not -path './build/*' -not -path './.git/*'); do
  bash -n "$f" 2>/dev/null; ck "shell $f" $?
done
for f in tools/ghost-claude tools/ghost-browser tools/ghost-status tools/ghost-theme \
         tools/ghost-boot-splash tools/ghostboard-session install/lib/common.sh; do
  bash -n "$f" 2>/dev/null; ck "shell $f" $?
done
for f in theme/ghostpalette.py theme/render-theme.py tools/ghost-bench tools/ghost-bruce \
         tools/ghost-hand runtime/hand_tracking.py; do
  python3 -c "import ast,sys;ast.parse(open(sys.argv[1]).read())" "$f" 2>/dev/null
  ck "python $f" $?
done
for f in mcp-computer-use/server.js tests/test-mcp.js; do
  node --check "$f" 2>/dev/null; ck "node $f" $?
done

echo
echo "$([[ $fail -eq 0 ]] && echo SUCCÈS || echo ÉCHEC) : $pass réussi(s), $fail échec(s)"
exit $(( fail > 0 ))
