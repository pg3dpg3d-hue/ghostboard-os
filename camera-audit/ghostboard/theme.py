"""
theme.py — charte GHOSTBOARD pour la TUI RECON.

Les couleurs ne sont PAS redéfinies ici : elles sont SOURCÉES depuis la palette
du système (brand/palette.toml, ou build/theme/share/palette.json une fois le
thème généré). Changer un hex dans la palette et régénérer suffit à re-thémer
ce module en même temps que le reste de l'OS.

La sévérité utilise une rampe sémantique distincte de l'accent — conforme à la
doctrine GHOSTBOARD : une seule couleur d'accent (le violet, « ce que fait la
machine »), et des couleurs sémantiques séparées pour le danger.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

# Repli si aucune palette n'est trouvée (module isolé, hors du dépôt). Ce sont
# les valeurs de brand/palette.toml au moment de l'écriture — un filet, pas une
# source de vérité.
_FALLBACK = {
    "bg": "#08070C", "panel": "#14111C", "separator": "#251F35",
    "accent": "#A855F7", "input": "#FF4D8D", "text": "#D6D2E0",
    "text_dim": "#6E6880",
    "_term": {"red": "#FF4D8D", "green": "#5FD7A4", "yellow": "#D9B25F",
              "magenta": "#A855F7", "cyan": "#61C6D4"},
}


def _repo_root() -> Path:
    """Racine du dépôt GHOSTBOARD. camera-audit/ghostboard/theme.py -> ../../.."""
    env = os.environ.get("GHOSTBOARD_REPO")
    if env and Path(env).is_dir():
        return Path(env)
    return Path(__file__).resolve().parent.parent.parent


def _candidates() -> list[Path]:
    root = _repo_root()
    share = os.environ.get("GHOSTBOARD_SHARE", "/usr/share/ghostboard")
    return [
        Path(share) / "palette.json",                 # installé sur le deck
        root / "build" / "theme" / "share" / "palette.json",  # généré en dépôt
        root / "brand" / "palette.toml",              # source de vérité
    ]


def load_palette() -> dict:
    """Renvoie un dict plat de couleurs, sévérité comprise. Toujours complet."""
    colors = dict(_FALLBACK)
    term = dict(_FALLBACK["_term"])
    for path in _candidates():
        if not path.is_file():
            continue
        try:
            if path.suffix == ".json":
                data = json.loads(path.read_text(encoding="utf-8"))
                colors.update(data.get("color", {}))
                term.update(data.get("terminal", {}))
            else:  # .toml
                try:
                    import tomllib
                except ModuleNotFoundError:  # pragma: no cover
                    import tomli as tomllib  # type: ignore
                data = tomllib.loads(path.read_text(encoding="utf-8"))
                colors.update(data.get("color", {}))
                term.update(data.get("terminal", {}))
            break
        except Exception:
            continue

    # Rampe de sévérité, dérivée des couleurs ANSI de la palette : le rouge/rose
    # de la marque pour le critique (déjà « erreur »), l'ambre pour élevé, le
    # cyan pour moyen, le texte faible pour info. Aucune couleur nouvelle.
    colors["sev_critical"] = colors.get("input", term.get("red"))
    colors["sev_high"] = term.get("yellow", "#D9B25F")
    colors["sev_medium"] = term.get("cyan", "#61C6D4")
    colors["sev_info"] = colors.get("text_dim", "#6E6880")
    colors["ok"] = term.get("green", "#5FD7A4")
    colors.pop("_term", None)
    return colors


def css_variables() -> dict[str, str]:
    """Variables injectées dans le CSS Textual, préfixées `gb-`.

    L'App fusionne ceci dans get_css_variables(), et recon.tcss référence
    `$gb-accent`, `$gb-sev-critical`, etc. C'est ce qui garde la feuille de
    style pilotée par la palette sans étape de génération séparée."""
    p = load_palette()
    out = {
        "gb-bg": p["bg"], "gb-panel": p["panel"], "gb-sep": p["separator"],
        "gb-accent": p["accent"], "gb-input": p["input"],
        "gb-text": p["text"], "gb-dim": p["text_dim"],
        "gb-sev-critical": p["sev_critical"], "gb-sev-high": p["sev_high"],
        "gb-sev-medium": p["sev_medium"], "gb-sev-info": p["sev_info"],
        "gb-ok": p["ok"],
    }
    return out


# Bannière ASCII. Compacte : ~46 colonnes de large, elle tient sur la dalle
# 4 pouces (~53 colonnes en IBM Plex Mono 15 px). Pas de FIGlet à installer.
BANNER = r"""
  ___ _  _ ___  ___ _____ ___  ___  __ _ _ _
 / __| || / _ \/ __|_   _| _ )/ _ \/ _` | '_|
| (_ | __ | (_) \__ \ | | | _ \ (_) \__,|_|
 \___|_||_|\___/|___/ |_| |___/\___/|___(_)
"""

TAGLINE = "CUSTOM HARDWARE. READY TO EXPLORE."
MODULE_NAME = "RECON · CAMERA AUDIT"
