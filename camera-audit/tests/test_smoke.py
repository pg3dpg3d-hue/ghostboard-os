#!/usr/bin/env python3
"""
Test de démarrage de la TUI — pilote les 4 écrans sans terminal (run_test).

Nécessite Textual. Sans lui (hors venv), le test se déclare « sauté » et sort
en 0 : un test d'interface ne doit pas faire échouer la suite sur une machine
où la TUI n'est pas installée.

  python tests/test_smoke.py
"""
import asyncio
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

try:
    import textual  # noqa: F401
except ModuleNotFoundError:
    print("  -- sauté : textual absent (lance camera-audit/install.sh)")
    sys.exit(0)

from ghostboard import bridge  # noqa: E402
from ghostboard.app import (ReconApp, WelcomeScreen, TargetsScreen,  # noqa: E402
                            RunScreen, FindingsScreen)

_p = _f = 0


def ck(label, cond):
    global _p, _f
    print(("  OK  " if cond else "  KO  ") + label)
    _p += bool(cond); _f += (not cond)


async def main() -> int:
    app = ReconApp()
    async with app.run_test(size=(53, 16)) as pilot:
        ck("backend démo sans auditkit", app.backend.is_demo)
        ck("Welcome monté", isinstance(app.screen, WelcomeScreen))
        await pilot.press("enter"); await pilot.pause()
        ck("Entrée -> Targets", isinstance(app.screen, TargetsScreen))
        ck("cibles pré-remplies au périmètre",
           "192.168.1.0/24" in app.screen.query_one("#targets-input").text)
        await pilot.press("f5"); await pilot.pause()
        ck("F5 -> Run", isinstance(app.screen, RunScreen))
        for _ in range(100):
            await pilot.pause(0.1)
            if app.screen._done:
                break
        ck("scan démo terminé", app.screen._done)
        ck("7 findings collectés", len(app.findings) == 7)
        await pilot.press("enter"); await pilot.pause()
        ck("Entrée -> Findings", isinstance(app.screen, FindingsScreen))
        rows = app.screen._rows
        ck("findings triés par sévérité",
           [int(r.severity) for r in rows] == sorted(
               [int(r.severity) for r in rows], reverse=True))
        ck("tête = CRITICAL", rows and rows[0].severity == bridge.Severity.CRITICAL)
        out = Path(tempfile.mkdtemp()) / "r.html"
        app.backend.make_report(rows, out)
        ck("rapport HTML régénérable", out.exists() and "GHOSTBOARD" in out.read_text())
    print(f"\n{'SUCCÈS' if _f == 0 else 'ÉCHEC'} : {_p} réussi(s), {_f} échec(s)")
    return 1 if _f else 0


sys.exit(asyncio.run(main()))
