# ---------------------------------------------------------------------------
#  pio_prebuild.py — hook PlatformIO exécuté AVANT chaque compilation.
#
#  Régénère les fichiers dérivés pour qu'ils soient toujours à jour dans le
#  binaire flashé :
#    - include/theme_colors.h depuis brand/palette.toml
#    - include/wordlist.h     depuis data/wordlist.txt
#
#  Référencé par platformio.ini : extra_scripts = pre:tools/pio_prebuild.py
#  Best-effort : si un générateur échoue (ex. tomllib absent), on n'interrompt
#  pas le build — le header committé sert de repli.
# ---------------------------------------------------------------------------
import subprocess
import sys
from pathlib import Path

Import("env")  # noqa: F821  (fourni par PlatformIO/SCons)

TOOLS = Path(__file__).resolve().parent

for script in ("gen-theme.py", "gen-wordlist.py"):
    path = TOOLS / script
    if not path.exists():
        continue
    try:
        subprocess.run([sys.executable, str(path)], check=True)
    except Exception as exc:  # noqa: BLE001
        print(f"[ghostboard] {script} non régénéré ({exc}) — header existant conservé")
