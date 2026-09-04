#!/usr/bin/env python3
"""
GHOSTBOARD OS — générateur de thème.

    brand/palette.toml  ──▶  tout le thème du système

Change un hex dans la palette, relance, et GTK 2/3/4, les décorations de
fenêtre, le terminal, le fond d'écran, la barre des tâches et l'animation de
boot suivent. C'est la seule façon de re-thémer l'OS : aucune couleur ne doit
être écrite en dur ailleurs.

    ./render-theme.py                  # génère dans build/theme (rien n'est touché)
    ./render-theme.py --install        # installe pour l'utilisateur courant
    ./render-theme.py --check          # vérifie contrastes + cohérence, sort 1 si KO
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from ghostpalette import (  # noqa: E402
    Canvas, Palette, REPO_ROOT, contrast_ratio, mix, render_template, rgba,
)

TPL_DIR = Path(__file__).resolve().parent / "templates"

# Contraste minimal toléré pour du texte porteur de sens sur son fond.
# 4.5 = AA normal, 3.0 = AA grand texte. Sur 800x480 on ne descend pas plus bas.
MIN_CONTRAST = {
    ("text", "bg"): 4.5,
    ("text", "panel"): 4.5,
    ("text_dim", "panel"): 3.0,
    ("accent", "panel"): 3.0,
    ("input", "panel"): 3.0,
    ("on_accent", "accent"): 4.5,
}


# ---------------------------------------------------------------------------
#  Valeurs de substitution
# ---------------------------------------------------------------------------
def build_values(p: Palette) -> dict:
    v = p.flat()

    # Variantes sans '#' — xfwm4 exige ses couleurs sous la forme #RRGGBB
    # mais certains gabarits ont besoin des 6 chiffres seuls.
    for key in ("bg", "panel", "separator", "accent", "input", "text", "text_dim"):
        v[f"{key}_nohash"] = p[key].lstrip("#")

    # Surfaces translucides ("mica"). Si aucun compositeur ne tourne, X ignore
    # simplement l'alpha et on retombe sur la couleur opaque : pas de casse.
    v["taskbar_bg"] = rgba(p["panel"], p.mica["taskbar_alpha"])
    v["startmenu_bg"] = rgba(p["panel"], p.mica["startmenu_alpha"])
    v["popup_bg"] = rgba(p["panel"], p.mica["popup_alpha"])
    v["term_darkness"] = round(p.mica["popup_alpha"], 3)

    # Mise en page du fond d'écran, calée sur la taille réelle de la dalle
    w, h = p.layout["screen_w"], p.layout["screen_h"]
    v["wm_x"] = round(w * 0.07)
    v["wm_y"] = round(h * 0.44)
    v["rule_y"] = round(h * 0.44) + 22
    v["rule_w"] = round(w * 0.38)
    v["tagline_y"] = round(h * 0.44) + 52
    v["corner_y"] = h - 16

    # Palette de commandes : 78 % de la largeur, ancrée en haut. Le nombre de
    # lignes est CALCULÉ pour que la fenêtre ne dépasse jamais la dalle —
    # sur 480 px de haut, une liste de 10 entrées sort de l'écran.
    v["rofi_w"] = round(w * 0.78)
    v["rofi_y"] = round(h * 0.10)
    line_px = p.font["ui_size_px"] + 14          # texte + padding de l'élément
    chrome = 10 * 2 + 34 + 8 + round(h * 0.10)   # marges + inputbar + espace
    v["rofi_lines"] = max(3, min(8, (h - chrome) // line_px))
    return v


# ---------------------------------------------------------------------------
#  Boutons de fenêtre xfwm4 (PNG générés, sans dépendance graphique)
# ---------------------------------------------------------------------------
BTN_W, BTN_H = 26, 20  # zones larges façon Windows 11


def _button(glyph: str, fg: str, bg: str | None) -> Canvas:
    c = Canvas(BTN_W, BTN_H, scale=4)
    if bg:
        c.fill_rect(1, 1, BTN_W - 1, BTN_H - 1, bg)
    cx, cy, r = BTN_W / 2, BTN_H / 2, 3.6
    if glyph == "close":
        c.line(cx - r, cy - r, cx + r, cy + r, fg, 1.3)
        c.line(cx - r, cy + r, cx + r, cy - r, fg, 1.3)
    elif glyph == "maximize":
        c.line(cx - r, cy - r, cx + r, cy - r, fg, 1.2)
        c.line(cx - r, cy + r, cx + r, cy + r, fg, 1.2)
        c.line(cx - r, cy - r, cx - r, cy + r, fg, 1.2)
        c.line(cx + r, cy - r, cx + r, cy + r, fg, 1.2)
    elif glyph == "hide":
        c.line(cx - r, cy + 1, cx + r, cy + 1, fg, 1.3)
    elif glyph == "shade":
        c.line(cx - r, cy - 2, cx, cy + 2, fg, 1.3)
        c.line(cx, cy + 2, cx + r, cy - 2, fg, 1.3)
    elif glyph == "stick":
        c.fill_rect(cx - 2, cy - 2, cx + 2, cy + 2, fg)
    return c


def render_buttons(p: Palette, out_dir: Path) -> int:
    """Un PNG par (bouton, état). Les états sont ce qui rend l'interface lisible :
    survol = accent, fermeture = couleur d'erreur. Rien d'autre ne bouge."""
    n = 0
    for glyph in ("close", "maximize", "hide", "shade", "stick"):
        # Fermer est la seule action destructrice : elle vire au rose au survol.
        prelight_bg = p["input"] if glyph == "close" else p["accent"]
        prelight_fg = p["bg"]
        states = {
            "active": (p["text"], None),
            "inactive": (p["text_dim"], None),
            "prelight": (prelight_fg, prelight_bg),
            "pressed": (prelight_fg, mix(prelight_bg, p["bg"], 0.3)),
        }
        for state, (fg, bg) in states.items():
            _button(glyph, fg, bg).save(out_dir / f"{glyph}-{state}.png")
            n += 1
        # Variantes "toggled" attendues par xfwm4 pour maximize/shade/stick
        if glyph in ("maximize", "shade", "stick"):
            for state, (fg, bg) in states.items():
                _button(glyph, fg, bg).save(
                    out_dir / f"{glyph}-toggled-{state}.png")
                n += 1
    return n


# ---------------------------------------------------------------------------
#  Génération
# ---------------------------------------------------------------------------
def render_all(p: Palette, out: Path) -> dict[str, Path]:
    v = build_values(p)
    theme = out / "themes" / p.theme_id
    share = out / "share"
    written: dict[str, Path] = {}

    def emit(tpl_name: str, dest: Path, key: str) -> None:
        text = (TPL_DIR / tpl_name).read_text(encoding="utf-8")
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(render_template(text, v), encoding="utf-8")
        written[key] = dest

    emit("index.theme.tmpl", theme / "index.theme", "index.theme")
    emit("gtk3.css.tmpl", theme / "gtk-3.0" / "gtk.css", "gtk3")
    emit("gtk4.css.tmpl", theme / "gtk-4.0" / "gtk.css", "gtk4")
    emit("gtk2.rc.tmpl", theme / "gtk-2.0" / "gtkrc", "gtk2")
    emit("xfwm4.themerc.tmpl", theme / "xfwm4" / "themerc", "xfwm4")
    emit("terminalrc.tmpl", share / "terminalrc", "terminalrc")
    emit("Xresources.tmpl", share / "Xresources", "Xresources")
    emit("wallpaper.svg.tmpl", share / "wallpaper.svg", "wallpaper.svg")
    emit("rofi.rasi.tmpl", share / "ghostboard.rasi", "rofi")
    emit("start-icon.svg.tmpl",
         share / "icons" / "hicolor" / "scalable" / "apps" / "ghostboard-start.svg",
         "start-icon")

    n = render_buttons(p, theme / "xfwm4")
    written["xfwm4-buttons"] = theme / "xfwm4"

    # -- palette exportée pour les consommateurs non-CSS ---------------------
    # L'animation de boot (JS) et les outils shell lisent CES fichiers.
    # Ils ne dupliquent pas la palette : ils en sont un rendu.
    share.mkdir(parents=True, exist_ok=True)
    payload = {
        "meta": p.meta, "color": dict(p.c), "derived": p.d, "mica": p.mica,
        "font": p.font, "layout": p.layout, "boot": p.boot, "terminal": p.term,
    }
    (share / "palette.json").write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    written["palette.json"] = share / "palette.json"

    sh_lines = [
        "# GHOSTBOARD OS — palette pour les scripts shell. GÉNÉRÉ. NE PAS ÉDITER.",
        "# Utilisation :  . /usr/share/ghostboard/palette.sh",
    ]
    for k, val in list(p.c.items()) + list(p.d.items()):
        sh_lines.append(f'GB_{k.upper()}="{val}"')
    for k, val in p.meta.items():
        sh_lines.append(f'GB_{k.upper()}="{val}"')
    sh_lines.append(f'GB_SCREEN_W="{p.layout["screen_w"]}"')
    sh_lines.append(f'GB_SCREEN_H="{p.layout["screen_h"]}"')
    (share / "palette.sh").write_text("\n".join(sh_lines) + "\n", encoding="utf-8")
    written["palette.sh"] = share / "palette.sh"

    # Variante script classique pour l'animation de boot : fetch() est bloqué
    # sur file://, donc la palette est injectée plutôt que chargée.
    (share / "palette.js").write_text(
        "/* GHOSTBOARD OS — GÉNÉRÉ depuis brand/palette.toml. NE PAS ÉDITER. */\n"
        "window.GHOSTBOARD_THEME = "
        + json.dumps(payload, indent=2, ensure_ascii=False) + ";\n",
        encoding="utf-8")
    written["palette.js"] = share / "palette.js"

    # -- fond d'écran en PNG (rsvg-convert si présent) -----------------------
    # xfdesktop lit le SVG s'il a le chargeur gdk-pixbuf ; le PNG est le repli
    # sûr, et il est plus rapide à peindre au démarrage de session.
    svg, png = share / "wallpaper.svg", share / "wallpaper.png"
    if shutil.which("rsvg-convert"):
        try:
            subprocess.run(
                ["rsvg-convert", "-w", str(p.layout["screen_w"]),
                 "-h", str(p.layout["screen_h"]), "-o", str(png), str(svg)],
                check=True, capture_output=True)
            written["wallpaper.png"] = png
        except subprocess.CalledProcessError as exc:
            print(f"  ! rsvg-convert a échoué ({exc}) — le SVG reste utilisable",
                  file=sys.stderr)
    else:
        print("  ! rsvg-convert absent — fond d'écran laissé en SVG", file=sys.stderr)

    print(f"  {n} boutons de fenêtre générés")
    return written


# ---------------------------------------------------------------------------
#  Vérification
# ---------------------------------------------------------------------------
def check(p: Palette) -> int:
    print("Contrastes (WCAG, sur dalle 4 pouces) :")
    failures = 0
    for (fg, bg), minimum in MIN_CONTRAST.items():
        ratio = contrast_ratio(p[fg], p[bg])
        ok = ratio >= minimum
        failures += not ok
        print(f"  {'OK ' if ok else 'KO '} {fg:>10s} sur {bg:<10s} "
              f"{ratio:5.2f}:1  (minimum {minimum})")

    print("\nCohérence :")
    if p.font["ui_size_px"] < 15:
        print(f"  KO  police d'interface {p.font['ui_size_px']}px < plancher 15px "
              f"sur cette dalle")
        failures += 1
    else:
        print(f"  OK  police d'interface {p.font['ui_size_px']}px >= 15px")

    acts = ("ignite_ms", "seek_ms", "lock_ms", "settle_ms", "discharge_ms")
    budget = sum(p.boot[a] for a in acts)
    total = p.boot["duration_ms"]
    if budget != total:
        # Égalité stricte : les actes sont enchaînés sur une seule horloge
        # normalisée. Un écart décale toutes les phases suivantes.
        print(f"  KO  animation de boot : les 5 actes font {budget}ms pour un "
              f"duration_ms de {total}ms — ils doivent être égaux")
        failures += 1
    else:
        print(f"  OK  animation de boot : {' + '.join(str(p.boot[a]) for a in acts)}"
              f" = {total}ms")
    if total > 2500:
        print(f"  KO  animation de boot : {total}ms mange trop du budget de 20s")
        failures += 1

    if p.layout["taskbar_h"] > p.layout["screen_h"] * 0.10:
        print(f"  KO  barre des tâches {p.layout['taskbar_h']}px = "
              f"{p.layout['taskbar_h'] / p.layout['screen_h']:.0%} de l'écran")
        failures += 1
    else:
        print(f"  OK  barre des tâches {p.layout['taskbar_h']}px = "
              f"{p.layout['taskbar_h'] / p.layout['screen_h']:.0%} de la hauteur")
    return failures


# ---------------------------------------------------------------------------
#  Installation
# ---------------------------------------------------------------------------
def install(built: Path, home: Path, share_dir: Path) -> None:
    """Recopie idempotente. Les cibles sont écrasées : la palette fait foi."""
    theme_src = next((built / "themes").iterdir())
    theme_dst = home / ".themes" / theme_src.name
    if theme_dst.exists():
        shutil.rmtree(theme_dst)
    shutil.copytree(theme_src, theme_dst)
    print(f"  thème      -> {theme_dst}")

    share_dir.mkdir(parents=True, exist_ok=True)
    for item in (built / "share").iterdir():
        if item.is_dir():
            shutil.copytree(item, share_dir / item.name, dirs_exist_ok=True)
        else:
            shutil.copy2(item, share_dir / item.name)
    print(f"  ressources -> {share_dir}")

    rofi_dir = home / ".config" / "rofi"
    rofi_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(built / "share" / "ghostboard.rasi", rofi_dir / "ghostboard.rasi")
    (rofi_dir / "config.rasi").write_text(
        '// GHOSTBOARD OS — GÉNÉRÉ. NE PAS ÉDITER.\n'
        'configuration {\n'
        '  modi: "drun,run";\n'
        '  show-icons: false;\n'
        '  terminal: "xfce4-terminal";\n'
        '  kb-cancel: "Escape";\n'
        '  matching: "fuzzy";\n'
        '  sort: true;\n'
        '  sorting-method: "fzf";\n'
        '}\n'
        '@theme "ghostboard"\n', encoding="utf-8")
    print(f"  rofi       -> {rofi_dir}")

    term_dir = home / ".config" / "xfce4" / "terminal"
    term_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(built / "share" / "terminalrc", term_dir / "terminalrc")
    print(f"  terminal   -> {term_dir / 'terminalrc'}")

    shutil.copy2(built / "share" / "Xresources", home / ".Xresources")
    print(f"  X          -> {home / '.Xresources'}")

    # Icône du bouton démarrer : dans le thème d'icônes de l'utilisateur, pour
    # que le panneau la trouve par son nom (« ghostboard-start ») et non par
    # un chemin en dur qui casserait au moindre déplacement.
    icon_src = (built / "share" / "icons" / "hicolor" / "scalable" / "apps"
                / "ghostboard-start.svg")
    icon_dst = home / ".local" / "share" / "icons" / "hicolor" / "scalable" / "apps"
    icon_dst.mkdir(parents=True, exist_ok=True)
    shutil.copy2(icon_src, icon_dst / "ghostboard-start.svg")
    print(f"  icône      -> {icon_dst / 'ghostboard-start.svg'}")


def main() -> int:
    ap = argparse.ArgumentParser(description="Génère le thème GHOSTBOARD OS")
    ap.add_argument("--palette", default=REPO_ROOT / "brand" / "palette.toml")
    ap.add_argument("--out", default=REPO_ROOT / "build" / "theme")
    ap.add_argument("--install", action="store_true",
                    help="installe pour l'utilisateur courant")
    ap.add_argument("--check", action="store_true",
                    help="vérifie seulement (contrastes, cohérence)")
    ap.add_argument("--home", default=os.path.expanduser("~"))
    ap.add_argument("--share-dir", default="/usr/share/ghostboard")
    args = ap.parse_args()

    p = Palette(args.palette)
    print(f"GHOSTBOARD OS — thème « {p.theme_id} » depuis {Path(args.palette).name}")

    if args.check:
        failures = check(p)
        print(f"\n{'ÉCHEC' if failures else 'OK'} — {failures} problème(s)")
        return 1 if failures else 0

    out = Path(args.out)
    if out.exists():
        shutil.rmtree(out)
    written = render_all(p, out)
    for key, path in written.items():
        print(f"  {key:16s} {path.relative_to(REPO_ROOT) if REPO_ROOT in path.parents else path}")

    if args.install:
        print("\nInstallation :")
        install(out, Path(args.home), Path(args.share_dir))
    return 0


if __name__ == "__main__":
    sys.exit(main())
