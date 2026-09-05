#!/usr/bin/env python3
"""
gen-theme.py — dérive les couleurs du firmware compagnon depuis la palette.

Comme le reste de GHOSTBOARD, le firmware ESP32 ne code aucune couleur en dur :
il lit brand/palette.toml (la source unique) et régénère include/theme_colors.h.

L'écran OLED de la carte est monochrome (u8g2) : c'est la LED NeoPixel qui
porte la charte. On mappe donc les états de la carte sur la palette :

    off     -> éteint
    scan    -> accent  (violet, « ce que fait la machine »)
    attack  -> input   (la couleur d'alerte/erreur de la charte)
    ok      -> un vert dérivé (confirmation ponctuelle)

Usage :
    tools/gen-theme.py                 # écrit include/theme_colors.h
    tools/gen-theme.py --check         # échoue si le fichier est périmé (CI)
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

try:
    import tomllib  # Python 3.11+ (Debian 13)
except ModuleNotFoundError:  # repli pour un poste plus ancien
    import tomli as tomllib  # type: ignore

HERE = Path(__file__).resolve().parent
FIRMWARE = HERE.parent
# Remonte jusqu'à la racine du dépôt pour retrouver la palette partagée.
REPO = FIRMWARE.parent.parent
PALETTE = REPO / "brand" / "palette.toml"
OUT = FIRMWARE / "include" / "theme_colors.h"


def hex_to_rgb(h: str) -> tuple[int, int, int]:
    h = h.lstrip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def render(colors: dict) -> str:
    accent = hex_to_rgb(colors["accent"])
    danger = hex_to_rgb(colors["input"])
    # Vert de confirmation : pas dans la palette (interface violet/rose), on le
    # dérive discret et froid pour ne jamais rivaliser avec l'accent.
    ok = (46, 204, 113)

    def macro(name: str, rgb: tuple[int, int, int], note: str) -> str:
        r, g, b = rgb
        return f"#define {name:<16} {r}, {g}, {b}   // {note}"

    return "\n".join(
        [
            "// ---------------------------------------------------------------------------",
            "//  theme_colors.h — GÉNÉRÉ depuis brand/palette.toml. Ne pas éditer à la main.",
            "//  Régénérer :  companion/firmware/tools/gen-theme.py",
            "//",
            "//  Couleurs de la LED NeoPixel (l'OLED est monochrome). Triplets R,G,B",
            "//  passés tels quels à Adafruit_NeoPixel::Color().",
            "// ---------------------------------------------------------------------------",
            "#pragma once",
            "",
            macro("GB_NEO_OFF", (0, 0, 0), "repos / veille"),
            macro("GB_NEO_SCAN", accent, f"accent {colors['accent']} — scan / activité"),
            macro("GB_NEO_ATTACK", danger, f"input {colors['input']} — émission deauth (alerte)"),
            macro("GB_NEO_OK", ok, "confirmation ponctuelle"),
            "",
        ]
    )


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true",
                    help="échoue si theme_colors.h ne correspond plus à la palette")
    args = ap.parse_args()

    if not PALETTE.exists():
        print(f"palette introuvable : {PALETTE}", file=sys.stderr)
        return 2
    data = tomllib.loads(PALETTE.read_text(encoding="utf-8"))
    content = render(data["color"])

    if args.check:
        current = OUT.read_text(encoding="utf-8") if OUT.exists() else ""
        if current != content:
            print("theme_colors.h est périmé — relance tools/gen-theme.py", file=sys.stderr)
            return 1
        print("theme_colors.h à jour.")
        return 0

    OUT.write_text(content, encoding="utf-8")
    print(f"écrit {OUT.relative_to(REPO)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
