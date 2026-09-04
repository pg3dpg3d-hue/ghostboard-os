#!/usr/bin/env python3
"""
build-os-preview.py — page de présentation de GHOSTBOARD OS.

Le bureau montré dans la page est REPRODUIT à partir des fichiers réellement
générés par le thème :
  - couleurs, polices et géométrie        -> build/theme/share/palette.json
  - fond d'écran                          -> build/theme/share/wallpaper.svg
  - icône du bouton démarrer              -> build/theme/share/icons/...
  - boutons de fenêtre                    -> themes/<id>/xfwm4/*.png
  - applications épinglées                -> desktop/launchers/*.desktop

Ce n'est PAS une capture du système en marche : XFCE n'a jamais tourné ici.
C'est une reproduction fidèle aux valeurs de la palette — la page le dit.

    ./tools/build-os-preview.py [SORTIE.html]
"""
from __future__ import annotations

import base64
import configparser
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SHARE = ROOT / "build" / "theme" / "share"
THEME = ROOT / "build" / "theme" / "themes"
LAUNCHERS = ROOT / "desktop" / "launchers"

# Ordre d'épinglage : celui du menu démarrer réel (whiskermenu-1.rc).
PINNED = ["ghostboard-terminal", "ghostboard-claude", "ghostboard-bruce",
          "ghostboard-browser", "ghostboard-settings", "ghostboard-status"]

# Glyphes du menu. Le vrai système utilise le thème d'icônes Papirus, qu'on ne
# peut pas embarquer ; on garde des formes SVG neutres tracées dans l'accent.
GLYPHS = {
    "ghostboard-terminal": '<path d="M4 6l5 5-5 5M12 16h8" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>',
    "ghostboard-claude": "GHOST",
    "ghostboard-bruce": '<path d="M12 4v6M12 20a4 4 0 100-8 4 4 0 000 8zM6 7a8 8 0 000 10M18 7a8 8 0 010 10" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"/>',
    "ghostboard-browser": '<circle cx="12" cy="12" r="8.5" fill="none" stroke="currentColor" stroke-width="2"/><path d="M3.5 12h17M12 3.5c4 4.5 4 12.5 0 17M12 3.5c-4 4.5-4 12.5 0 17" fill="none" stroke="currentColor" stroke-width="1.6"/>',
    "ghostboard-settings": '<circle cx="12" cy="12" r="3.2" fill="none" stroke="currentColor" stroke-width="2"/><path d="M12 3v3M12 18v3M3 12h3M18 12h3M5.6 5.6l2.1 2.1M16.3 16.3l2.1 2.1M18.4 5.6l-2.1 2.1M7.7 16.3l-2.1 2.1" stroke="currentColor" stroke-width="2" stroke-linecap="round"/>',
    "ghostboard-status": '<path d="M3 17l4-6 4 4 4-8 6 10" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>',
}


def data_uri(path: Path, mime: str) -> str:
    return f"data:{mime};base64," + base64.b64encode(path.read_bytes()).decode()


def read_launchers() -> list[dict]:
    apps = []
    for stem in PINNED:
        f = LAUNCHERS / f"{stem}.desktop"
        if not f.exists():
            continue
        c = configparser.ConfigParser(interpolation=None, strict=False)
        c.read(f, encoding="utf-8")
        e = c["Desktop Entry"]
        apps.append({"id": stem, "name": e["Name"], "comment": e.get("Comment", ""),
                     "exec": e.get("Exec", ""), "glyph": GLYPHS.get(stem, "")})
    return apps


def main() -> int:
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "build" / "os-preview.html"
    if not (SHARE / "palette.json").exists():
        raise SystemExit("palette.json absent — lance d'abord theme/render-theme.py")

    pal = json.loads((SHARE / "palette.json").read_text(encoding="utf-8"))
    theme_dir = next((THEME).iterdir())
    buttons = {n: data_uri(theme_dir / "xfwm4" / f"{n}-active.png", "image/png")
               for n in ("hide", "maximize", "close")}
    wallpaper = data_uri(SHARE / "wallpaper.svg", "image/svg+xml")
    start_icon = (SHARE / "icons" / "hicolor" / "scalable" / "apps"
                  / "ghostboard-start.svg").read_text(encoding="utf-8")
    start_icon = start_icon[start_icon.index("<svg"):]

    # Valeurs dérivées de la géométrie réelle du panneau XFCE :
    #   length=88 % dans xfce4-panel.xml -> largeur de la barre
    #   le menu démarrer flotte juste au-dessus de la barre
    lay = dict(pal["layout"])
    lay["taskbar_w"] = round(lay["screen_w"] * 0.88)
    lay["startmenu_bottom"] = lay["taskbar_margin"] + lay["taskbar_h"] + 6
    # Mêmes valeurs que le thème rofi généré (theme/templates/rofi.rasi.tmpl) :
    # la palette de la démo a la géométrie de la vraie.
    lay["rofi_w"] = round(lay["screen_w"] * 0.78)
    lay["rofi_y"] = round(lay["screen_h"] * 0.10)

    page = TEMPLATE.format(
        palette=json.dumps(pal, ensure_ascii=False),
        apps=json.dumps(read_launchers(), ensure_ascii=False),
        buttons=json.dumps(buttons, ensure_ascii=False),
        wallpaper=wallpaper,
        start_icon=start_icon.replace("\n", ""),
        **{k: v for k, v in pal["color"].items()},
        **{f"L_{k}": v for k, v in lay.items()},
        term_green=pal["terminal"]["green"],
        slogan=pal["meta"]["slogan"],
        term=json.dumps(pal["terminal"], ensure_ascii=False),
    )
    # Le script est injecté APRÈS le formatage : il contient trop d'accolades
    # pour être échappé lisiblement dans un gabarit .format().
    page = page.replace("__GHOSTBOARD_APP__", APP_JS)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(page, encoding="utf-8")
    print(f"page écrite : {out}  ({len(page)/1024:.0f} Ko)")
    return 0


TEMPLATE = r"""<title>GHOSTBOARD OS</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Martian+Mono:wght@400;600;700&family=IBM+Plex+Mono:wght@400;500;600&display=swap">
<style>
/* ==========================================================================
   GHOSTBOARD OS — page de présentation.
   Monde visuel unique et assumé : le produit EST un OS quasi noir à un seul
   accent. Pas de bascule clair/sombre ; chaque couleur est peinte
   explicitement pour que la page tienne sur n'importe quel fond hôte.
   Toutes les valeurs viennent de brand/palette.toml via palette.json.
   ========================================================================== */
:root {{
  --bg: {bg}; --panel: {panel}; --sep: {separator};
  --accent: {accent}; --signal: {input};
  --text: {text}; --dim: {text_dim};
  --display: "Martian Mono", "IBM Plex Mono", ui-monospace, monospace;
  --body: "IBM Plex Mono", ui-monospace, SFMono-Regular, Menlo, monospace;
  --gap: clamp(32px, 5vw, 60px);
}}
* {{ box-sizing: border-box; }}
body {{
  margin: 0; background: var(--bg); color: var(--text);
  font-family: var(--body); font-size: 14px; line-height: 1.62;
  -webkit-font-smoothing: antialiased;
}}
.wrap {{
  max-width: 920px; margin: 0 auto;
  padding: clamp(30px, 5vw, 64px) clamp(18px, 4vw, 40px) 100px;
  display: flex; flex-direction: column; gap: var(--gap);
}}
.eyebrow {{
  font-size: 11px; font-weight: 500; letter-spacing: 3.4px;
  text-transform: uppercase; color: var(--dim);
  display: flex; align-items: center; gap: 12px;
}}
.eyebrow::after {{ content: ""; flex: 1; height: 1px; background: var(--sep); }}
h1 {{
  font-family: var(--display); font-size: clamp(30px, 6vw, 50px);
  font-weight: 700; letter-spacing: 1px; line-height: 1.08; margin: 0;
  text-wrap: balance;
}}
h1 em {{ font-style: normal; color: var(--accent); }}
h2 {{
  font-family: var(--display); font-size: 14px; font-weight: 600;
  letter-spacing: 2.4px; text-transform: uppercase; margin: 0; color: var(--text);
}}
p {{ margin: 0; }}
.lede {{ max-width: 64ch; color: var(--dim); }}
.lede strong {{ color: var(--text); font-weight: 500; }}
section {{ display: flex; flex-direction: column; gap: 18px; }}

/* ---- fiche matériel ----------------------------------------------------- */
.spec {{
  /* 6 caractéristiques -> 3 colonnes remplissent exactement deux rangées.
     Un auto-fit laisserait la dernière seule avec du vide à droite. */
  display: grid; grid-template-columns: repeat(3, 1fr);
  gap: 1px; background: var(--sep); border: 1px solid var(--sep);
}}
@media (max-width: 560px) {{ .spec {{ grid-template-columns: repeat(2, 1fr); }} }}
.spec div {{ background: var(--panel); padding: 12px 14px; }}
.spec dt {{
  font-size: 10px; letter-spacing: 2px; text-transform: uppercase;
  color: var(--dim); margin-bottom: 3px;
}}
.spec dd {{ margin: 0; font-size: 13px; font-variant-numeric: tabular-nums; }}
.spec dd b {{ color: var(--accent); font-weight: 500; }}

/* ---- l'écran ------------------------------------------------------------ */
.bezel {{
  border: 1px solid var(--sep); background: #000; padding: 10px;
  position: relative;
}}
.screen-frame {{ position: relative; width: 100%; overflow: hidden; }}
.screen-scale {{ transform-origin: top left; }}
#screen {{
  position: relative; width: {L_screen_w}px; height: {L_screen_h}px;
  overflow: hidden; background: var(--bg) center/cover no-repeat;
  font-family: var(--body); font-size: 15px; color: var(--text);
  user-select: none;
}}
.caption {{
  display: flex; flex-wrap: wrap; justify-content: space-between; gap: 8px 20px;
  font-size: 11px; letter-spacing: 1.7px; text-transform: uppercase; color: var(--dim);
}}
.caption b {{ color: var(--text); font-weight: 500; }}
.hint {{
  font-size: 13px; color: var(--dim); border-left: 1px solid var(--sep);
  padding-left: 14px; max-width: 64ch;
}}
.hint b {{ color: var(--accent); font-weight: 500; }}

/* ---- fenêtres ----------------------------------------------------------- */
.win {{
  position: absolute; border: 1px solid var(--sep);
  background: var(--bg); display: flex; flex-direction: column;
  border-radius: {L_window_radius}px; overflow: hidden;
  box-shadow: 0 6px 22px rgba(0,0,0,.55);
}}
.win-title {{
  height: 28px; flex: 0 0 28px; background: var(--panel);
  border-bottom: 1px solid var(--sep);
  display: flex; align-items: center; padding: 0 2px 0 10px; gap: 6px;
}}
.win-title span {{
  flex: 1; text-align: center; font-family: var(--display);
  font-size: 12px; font-weight: 500; letter-spacing: .8px; color: var(--text);
}}
.win-btns {{ display: flex; gap: 1px; }}
.win-btns img {{ display: block; width: 26px; height: 20px; cursor: pointer; }}
.win-btns img:hover {{ background: rgba(168,85,247,.22); }}
.win-btns img.close:hover {{ background: {input}; }}
.win-body {{
  flex: 1; overflow: auto; padding: 10px 12px;
  font-size: 13px; line-height: 1.5; white-space: pre-wrap;
}}
.win-body .m {{ color: var(--accent); }}
.win-body .u {{ color: var(--signal); }}
.win-body .d {{ color: var(--dim); }}
.win-body .g {{ color: {term_green}; }}
.cursor {{
  display: inline-block; width: 7px; height: 14px; background: var(--accent);
  vertical-align: -2px; animation: none;
}}

/* ---- barre des tâches --------------------------------------------------- */
#taskbar {{
  position: absolute; left: 50%; transform: translateX(-50%);
  z-index: 9500;
  bottom: {L_taskbar_margin}px; width: {L_taskbar_w}px; height: {L_taskbar_h}px;
  border-radius: {L_taskbar_radius}px; border: 1px solid var(--sep);
  display: flex; align-items: center; gap: 4px; padding: 0 6px;
  backdrop-filter: blur(10px);
}}
.tb-btn {{
  height: 26px; min-width: 26px; border-radius: 6px; border: none;
  background: transparent; color: var(--text); font-family: var(--body);
  font-size: 12px; display: flex; align-items: center; gap: 6px;
  padding: 0 8px; cursor: pointer;
}}
.tb-btn:hover {{ background: rgba(168,85,247,.16); }}
.tb-btn.active {{ background: rgba(168,85,247,.24); box-shadow: inset 0 -2px var(--accent); }}
.tb-btn svg {{ width: {L_icon_size}px; height: {L_icon_size}px; display: block; }}
.tb-sep {{ width: 1px; height: 18px; background: var(--sep); flex: 0 0 1px; }}
.tb-spring {{ flex: 1; }}
.tb-tray {{ display: flex; gap: 5px; align-items: center; padding: 0 6px; }}
.tb-tray i {{ width: 5px; height: 5px; border-radius: 50%; background: var(--dim); }}
.tb-clock {{
  font-size: 12px; color: var(--dim); font-variant-numeric: tabular-nums;
  letter-spacing: .5px; padding-right: 4px;
}}

/* ---- menu démarrer ------------------------------------------------------ */
#startmenu {{
  position: absolute; left: 50%; transform: translateX(-50%);
  z-index: 9000;
  bottom: {L_startmenu_bottom}px;
  width: {L_startmenu_w}px; height: {L_startmenu_h}px;
  border: 1px solid var(--sep); border-radius: 10px;
  display: none; flex-direction: column; padding: 14px; gap: 12px;
  backdrop-filter: blur(14px);
}}
#startmenu.open {{ display: flex; }}
#search {{
  height: 30px; border-radius: 8px; border: 1px solid var(--sep);
  background: rgba(20,17,28,.9); color: var(--signal);
  font-family: var(--body); font-size: 15px; padding: 0 10px; outline: none;
}}
#search::placeholder {{ color: var(--dim); }}
#search:focus {{ border-color: var(--accent); }}
.pinned-label {{
  font-size: 10px; letter-spacing: 2.2px; text-transform: uppercase; color: var(--dim);
}}
#pinned {{
  display: grid; grid-template-columns: repeat({L_pinned_cols}, 1fr);
  gap: 6px; align-content: start; overflow: auto;
}}
.pin {{
  border: none; background: transparent; border-radius: 8px; cursor: pointer;
  padding: 10px 4px 8px; display: flex; flex-direction: column;
  align-items: center; gap: 6px; color: var(--text); font-family: var(--body);
}}
.pin:hover, .pin.sel {{ background: rgba(168,85,247,.18); }}
.pin svg {{ width: 24px; height: 24px; color: var(--accent); }}
.pin .mark {{
  font-family: var(--display); font-size: 11px; font-weight: 700;
  color: var(--accent); letter-spacing: -.5px;
}}
.pin span {{ font-size: 11px; line-height: 1.25; text-align: center; }}
.no-hit {{ grid-column: 1 / -1; color: var(--dim); font-size: 12px; padding: 8px 4px; }}

/* ---- listes de fonctionnalités : rail, pas cartes ----------------------- */
.feats {{ display: flex; flex-direction: column; }}
.feat {{
  display: grid; grid-template-columns: 2px minmax(140px, 200px) 1fr;
  gap: 0 22px; padding: 20px 0; border-top: 1px solid var(--sep);
}}
.feat:last-child {{ border-bottom: 1px solid var(--sep); }}
.feat-rail {{ background: var(--sep); }}
.feat:hover .feat-rail {{ background: var(--accent); }}
.feat h3 {{
  font-family: var(--display); font-size: 14px; font-weight: 600;
  letter-spacing: 1.2px; margin: 0 0 4px; color: var(--text);
}}
.feat .tag {{ font-size: 11px; color: var(--accent); font-variant-numeric: tabular-nums; }}
.feat-body {{ display: flex; flex-direction: column; gap: 9px; min-width: 0; }}
.feat-body p {{ max-width: 62ch; }}
.feat-body .sub {{
  color: var(--dim); font-size: 13px; padding-left: 14px;
  border-left: 1px solid var(--sep); max-width: 62ch;
}}

/* ---- flux ---------------------------------------------------------------- */
.flow {{
  border: 1px solid var(--sep); background: var(--panel); padding: 18px 20px;
  font-size: 13px; line-height: 1.75; overflow-x: auto;
  /* Diagramme aligné au caractère : sans `pre`, le navigateur replie tout en
     un paragraphe et l'alignement — qui EST l'information — disparaît. */
  white-space: pre; tab-size: 2;
}}
.flow b {{ color: var(--accent); font-weight: 500; }}
.flow i {{ color: var(--dim); font-style: normal; }}
.flow u {{ color: var(--signal); text-decoration: none; }}

/* ---- tableaux ----------------------------------------------------------- */
table {{ border-collapse: collapse; width: 100%; font-size: 13px; }}
th, td {{ text-align: left; padding: 9px 12px; border-bottom: 1px solid var(--sep); }}
th {{
  font-size: 10px; letter-spacing: 1.8px; text-transform: uppercase;
  color: var(--dim); font-weight: 500;
}}
td code {{ color: var(--accent); }}
td.num {{ text-align: right; font-variant-numeric: tabular-nums; }}
.scroll {{ overflow-x: auto; }}

.note {{
  border: 1px solid var(--sep); border-left: 2px solid var(--signal);
  background: var(--panel); padding: 14px 16px; font-size: 13px; color: var(--dim);
  max-width: 68ch;
}}
.note b {{ color: var(--text); font-weight: 500; }}
footer {{
  border-top: 1px solid var(--sep); padding-top: 20px; font-size: 11px;
  letter-spacing: 2.2px; text-transform: uppercase; color: var(--dim);
  display: flex; flex-wrap: wrap; gap: 8px 20px; justify-content: space-between;
}}
a {{ color: var(--accent); }}

/* ---- pager : 4 bureaux, pastilles numérotées --------------------------- */
.pager {{ display: flex; gap: 3px; align-items: center; }}
.pg {{
  width: 18px; height: 18px; border-radius: 4px; border: 1px solid var(--sep);
  background: transparent; color: var(--dim); font-family: var(--body);
  font-size: 10px; cursor: pointer; padding: 0;
  display: flex; align-items: center; justify-content: center;
}}
.pg:hover {{ border-color: var(--accent); color: var(--text); }}
.pg.on {{ background: var(--accent); border-color: var(--accent); color: {bg}; }}
.pg.busy::after {{
  content: ""; position: absolute; width: 3px; height: 3px; border-radius: 50%;
  background: var(--accent); transform: translate(0, 8px);
}}
.pg {{ position: relative; }}

/* ---- palette de commandes (reproduction du thème rofi généré) ---------- */
#palette {{
  position: absolute; left: 50%; transform: translateX(-50%);
  top: {L_rofi_y}px; width: {L_rofi_w}px; z-index: 9800;
  border: 1px solid var(--sep); border-radius: 10px; padding: 10px;
  display: none; flex-direction: column;
}}
#palette.open {{ display: flex; }}
.pal-bar {{
  display: flex; align-items: center; gap: 8px;
  background: rgba(20,17,28,.92); border: 1px solid var(--sep);
  border-radius: 8px; padding: 6px 10px;
}}
.pal-prompt {{ font-family: var(--display); font-size: 13px; color: var(--accent); }}
#pal-input {{
  flex: 1; background: transparent; border: none; outline: none;
  color: var(--signal); font-family: var(--body); font-size: 15px;
}}
#pal-input::placeholder {{ color: var(--dim); }}
.pal-list {{ display: flex; flex-direction: column; gap: 2px; padding-top: 8px; }}
.pal-item {{
  display: flex; gap: 10px; align-items: baseline; padding: 5px 8px;
  border-radius: 6px; cursor: pointer; font-size: 13px;
}}
.pal-item .tag {{
  font-size: 10px; letter-spacing: 1.4px; color: var(--dim);
  min-width: 46px; flex: 0 0 46px;
}}
.pal-item .lbl {{ flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }}
.pal-item .hnt {{ font-size: 11px; color: var(--dim); }}
.pal-item.sel {{ background: var(--accent); color: {bg}; }}
.pal-item.sel .tag, .pal-item.sel .hnt {{ color: rgba(8,7,12,.72); }}
.pal-none {{ padding: 8px; font-size: 12px; color: var(--dim); }}

/* ---- terminal interactif ---------------------------------------------- */
.win-body.term {{ cursor: text; }}
.term-line {{ white-space: pre-wrap; word-break: break-word; }}
.term-in {{ display: flex; gap: 6px; align-items: baseline; }}
.term-in .ps {{ color: var(--signal); }}
.term-in input {{
  flex: 1; background: transparent; border: none; outline: none;
  color: var(--signal); font-family: var(--body); font-size: 13px; padding: 0;
}}
.win.drag {{ user-select: none; }}
.win-title {{ cursor: grab; }}
.win-title:active {{ cursor: grabbing; }}

@media (max-width: 620px) {{
  .feat {{ grid-template-columns: 2px 1fr; }}
  .feat-body {{ grid-column: 2; }}
}}
</style>

<div class="wrap">

  <header style="display:flex;flex-direction:column;gap:16px">
    <div class="eyebrow">GHOSTBOARD OS · Debian 13 · XFCE · Radxa X4</div>
    <h1>Un cyberdeck qui démarre,<br>pas une distribution qui <em>charge</em>.</h1>
    <p class="lede">
      Structure Windows 11 — barre flottante centrée, coins arrondis, menu
      démarrer avec recherche. Habillage GHOSTBOARD — fond quasi noir, un seul
      accent violet, monospace partout où il y a du terminal ou de la donnée.
      Le raisonnement est dans le cloud, <strong>le contrôle est sur la
      machine</strong>. Tout est thémé depuis <strong>un seul fichier</strong>.
    </p>
  </header>

  <section>
    <h2>Le matériel</h2>
    <dl class="spec">
      <div><dt>Carte</dt><dd>Radxa X4 · Intel <b>N100</b></dd></div>
      <div><dt>Mémoire</dt><dd><b>16 Go</b></dd></div>
      <div><dt>Stockage</dt><dd>M.2 2230 NVMe <b>512 Go</b></dd></div>
      <div><dt>Dalle</dt><dd><b>800 × 480</b> · HDMI 4″</dd></div>
      <div><dt>Clavier</dt><dd>BlackBerry <b>Q20</b> · USB HID</dd></div>
      <div><dt>Énergie</dt><dd>Powerbank <b>USB-C PD</b></dd></div>
    </dl>
    <p class="hint">
      800 × 480 décide de tout le reste : plancher de police à 15 px, barre de
      34 px (7 % de la hauteur), scrollbars fines, aucune icône sur le bureau,
      plein écran par défaut.
    </p>
  </section>

  <section>
    <h2>Le bureau</h2>
    <div class="bezel">
      <div class="screen-frame" id="frame">
        <div class="screen-scale" id="scaler">
          <div id="screen">
            <div id="windows"></div>
            <div id="palette">
              <div class="pal-bar">
                <span class="pal-prompt">&gt;</span>
                <input id="pal-input" type="text" spellcheck="false" autocomplete="off"
                       placeholder="app, commande, carte, fenêtre…"
                       aria-label="Palette de commandes">
              </div>
              <div class="pal-list" id="pal-list"></div>
            </div>
            <div id="startmenu">
              <input id="search" type="text" placeholder="Rechercher une application…"
                     autocomplete="off" spellcheck="false" aria-label="Rechercher une application">
              <div class="pinned-label">Épinglées</div>
              <div id="pinned"></div>
            </div>
            <div id="taskbar">
              <button class="tb-btn" id="startbtn" title="Menu démarrer">{start_icon}</button>
              <div class="tb-sep"></div>
              <div class="pager" id="pager"></div>
              <div class="tb-sep"></div>
              <button class="tb-btn" id="palbtn"
                      title="Palette de commandes — Super+Espace">
                <svg viewBox="0 0 24 24" aria-hidden="true" style="width:16px;height:16px">
                  <path d="M4 7l4 5-4 5M12 17h8" fill="none" stroke="currentColor"
                        stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>
                </svg>
              </button>
              <div class="tb-sep"></div>
              <div id="tasks" style="display:flex;gap:4px"></div>
              <div class="tb-spring"></div>
              <div class="tb-tray"><i></i><i></i></div>
              <div class="tb-clock" id="clock">--:--</div>
            </div>
          </div>
        </div>
      </div>
    </div>
    <div class="caption">
      <span>Échelle <b>1:1</b> — 800 × 480 réels</span>
      <span>Barre <b>704 × 34</b>, rayon 10</span>
      <span>Menu <b>620 × 400</b></span>
      <span>Palette <b>624 px</b>, 4 bureaux</span>
    </div>
    <p class="hint">
      <b>C'est un vrai bureau, pas une image.</b>
      Déplace les fenêtres par leur barre de titre · réduis, agrandis, ferme ·
      change de bureau avec le pager <b>1 2 3 4</b> ·
      ouvre la palette de commandes avec <b>Ctrl + Espace</b> ou le bouton
      <b>&gt;_</b> · et dans le terminal, tape <b>help</b> : les commandes
      <code>ghost-*</code> répondent, <code>ghost-bruce console</code> ouvre une
      session série sur une carte simulée.
    </p>
    <div class="note">
      <b>Ce n'est pas une capture d'écran.</b> XFCE n'a jamais tourné pendant la
      construction : ce dépôt a été écrit dans un conteneur sans tête, sans GPU
      ni dalle. Couleurs, géométrie, fond d'écran et boutons de fenêtre sortent
      des fichiers réellement générés par le thème — mais les
      <b>sorties du terminal sont des reproductions de format</b>, avec des
      valeurs plausibles et non mesurées, et la <b>carte série est simulée</b> :
      son jeu de commandes est celui de cette page, pas celui d'un firmware
      Bruce, dont les commandes dépendent de la version.
    </div>
  </section>

  <section>
    <h2>L'architecture</h2>
    <div class="flow">
<b>Cloud</b>                          <b>La machine</b> <i>(N100)</i>
<i>─────</i>                          <i>───────────────────</i>
API Anthropic   <i>◄──────────►</i>   <b>Claude Code</b>
<i>(raisonnement)</i>                   <i>│  terminal + fichiers</i>
                                <i>│</i>
                                <i>▼  MCP, stdio</i>
                           <b>ghostboard-computer-use</b>
                                <i>│  screenshot · click · type · key</i>
                                <i>▼</i>
                           <u>Écran X</u> <i>(:0, ou :1 pour l'agent)</i>
    </div>
    <p class="lede">
      Aucun modèle ne tourne en local. Le N100 n'en a pas la puissance et n'en a
      pas besoin : le raisonnement est distant, <strong>le contrôle de l'écran
      est sur l'appareil</strong>.
    </p>
  </section>

  <section>
    <h2>Les fonctionnalités</h2>
    <div class="feats">

      <article class="feat"><div class="feat-rail"></div>
        <div><h3>Palette unique</h3><div class="tag">1 fichier → tout l'OS</div></div>
        <div class="feat-body">
          <p><code>brand/palette.toml</code> est le seul endroit où une couleur,
          une police ou une métrique d'interface est écrite à la main.</p>
          <p class="sub">Change un hex, lance <code>ghost-theme apply</code> :
          GTK 2/3/4, décorations de fenêtre, terminal, fond d'écran, barre des
          tâches, icône du bouton démarrer et animation de boot suivent. Le
          générateur refuse une palette qui échoue au contrôle de contraste ou
          au plancher de 15 px.</p>
        </div>
      </article>

      <article class="feat"><div class="feat-rail"></div>
        <div><h3>Animation d'allumage</h3><div class="tag">5 actes · 1 800 ms</div></div>
        <div class="feat-body">
          <p>Le logotype ne s'affiche pas, il s'assemble : balayage qui fait
          naître les particules, dérive turbulente, verrouillage lettre par
          lettre, tracé du filet, décharge.</p>
          <p class="sub">Puis le contexte WebGL est <b>détruit</b> — plus une
          seule boucle GPU ne tourne. C'est la seule animation de l'OS.
          <a href="https://claude.ai/code/artifact/e73b7aff-a421-46b5-9998-ed74a4df82f3">Voir le banc d'essai →</a></p>
        </div>
      </article>

      <article class="feat"><div class="feat-rail"></div>
        <div><h3>Palette de commandes</h3><div class="tag">Super + Espace</div></div>
        <div class="feat-body">
          <p>Une seule recherche floue sur tout ce qui est atteignable :
          applications, commandes <code>ghost-*</code>, cartes ESP32 branchées,
          fenêtres ouvertes, bureaux.</p>
          <p class="sub">C'est le chemin PRINCIPAL de l'OS. Sur un BlackBerry Q20
          sans souris, taper trois lettres et valider bat n'importe quelle grille
          d'icônes. Le moteur est rofi — pas un démon : il démarre, on choisit,
          il sort — habillé depuis la même palette que le reste, avec sa
          géométrie <b>calculée</b> pour ne jamais dépasser 480 px de haut.</p>
        </div>
      </article>

      <article class="feat"><div class="feat-rail"></div>
        <div><h3>Bureaux et pavage</h3><div class="tag">4 bureaux nommés</div></div>
        <div class="feat-body">
          <p>SHELL · AGENT · BOARDS · WEB, avec un pager dans la barre.
          Sur 480 px de haut, changer de bureau remplace le redimensionnement de
          fenêtres.</p>
          <p class="sub">Pavage en moitiés et en quarts au clavier
          (<code>Super</code> + flèches, <code>Super+Ctrl</code> + flèches pour
          les coins) : deux terminaux de 40 colonnes tiennent côte à côte sur
          800 px. Le pager coûte un greffon de panneau, pas un processus.</p>
        </div>
      </article>

      <article class="feat"><div class="feat-rail"></div>
        <div><h3>Console série</h3><div class="tag">mode ligne · horodatage</div></div>
        <div class="feat-body">
          <p><code>ghost-bruce console</code> passe en brut par défaut — c'est ce
          qu'il faut pour un terminal série. <code>--line</code> ajoute l'édition
          locale, l'historique persistant et le rappel par Tab.</p>
          <p class="sub">L'autocomplétion se fait sur l'HISTORIQUE, pas sur une
          liste de commandes du firmware : le jeu de commandes de Bruce dépend de
          sa version, et en proposer d'inventées serait pire que rien.
          <code>--timestamp</code> préfixe chaque ligne reçue de son horodatage
          relatif — sur une carte qui redémarre en boucle, savoir QUAND une ligne
          est arrivée vaut souvent plus que son contenu. <code>watch</code> suit
          les branchements en direct.</p>
        </div>
      </article>

      <article class="feat"><div class="feat-rail"></div>
        <div><h3>Computer use</h3><div class="tag">0 dépendance npm</div></div>
        <div class="feat-body">
          <p>Un serveur MCP sur la machine expose l'écran à Claude Code :
          <code>screenshot</code>, <code>click</code>, <code>type</code>,
          <code>key</code>, plus <code>scroll</code> et <code>screen_info</code>.</p>
          <p class="sub">Aucune dépendance : démarrage en ~25 ms, rien à mettre à
          jour sur le deck, le JSON-RPC tient en 80 lignes. Capture en 800 × 480
          natif, jamais redimensionnée — ~512 tokens d'image.
          <b>22 tests</b> passent contre un serveur X réel.</p>
        </div>
      </article>

      <article class="feat"><div class="feat-rail"></div>
        <div><h3>Session agent</h3><div class="tag">installée, éteinte</div></div>
        <div class="feat-body">
          <p>Par défaut l'agent voit ton bureau. <code>ghost-agent-session on</code>
          lui donne un écran à lui, en 800 × 480 exactement.</p>
          <p class="sub">Même géométrie que la dalle : les coordonnées de clic
          restent valables d'un mode à l'autre. Coût nul tant que c'est éteint.</p>
        </div>
      </article>

      <article class="feat"><div class="feat-rail"></div>
        <div><h3>ghost-bruce</h3><div class="tag">ESP32 · Bruce</div></div>
        <div class="feat-body">
          <p>Détecte les cartes ESP32 branchées en USB, ouvre la console série,
          envoie une commande, lance la WebUI.</p>
          <p class="sub">Identification par VID/PID en remontant sysfs jusqu'au
          périphérique USB parent : CP210x, CH340/CH9102, FTDI, USB natif
          ESP32-S2/S3. Dans la console, la carte parle en <b>violet</b>, tu tapes
          en <b>rose</b> — la convention de tout l'OS.</p>
        </div>
      </article>

      <article class="feat"><div class="feat-rail"></div>
        <div><h3>Mode hors ligne</h3><div class="tag">sans démon de sonde</div></div>
        <div class="feat-body">
          <p>Le raisonnement étant distant, sans réseau Claude Code ne peut pas
          répondre. Le deck le dit franchement au lieu d'échouer obscurément.</p>
          <p class="sub">Aucun démon ne surveille la connexion : l'état est
          calculé quand tu le demandes. Restent utilisables hors ligne : terminal,
          éditeur, gestionnaire de fichiers, <code>ghost-bruce</code>,
          <code>ghost-status</code>, <code>ghost-bench</code>.</p>
        </div>
      </article>

      <article class="feat"><div class="feat-rail"></div>
        <div><h3>Installation rejouable</h3><div class="tag">14 étapes</div></div>
        <div class="feat-body">
          <p>Debian 13 minimale → deck complet, en étapes idempotentes qu'on peut
          relancer sans rien casser.</p>
          <p class="sub"><code>--dry-run</code> montre tout et n'écrit rien
          (vérifié par un test). Sauvegardes horodatées de chaque fichier
          système. L'étape écran arme un <b>retour arrière automatique à
          3 minutes</b> : écran noir, tu ne touches à rien, ça revient.</p>
        </div>
      </article>

    </div>
  </section>

  <section>
    <h2>Performance</h2>
    <div class="scroll"><table>
      <thead><tr><th>Cible</th><th class="num">Valeur</th><th>Comment elle est tenue</th></tr></thead>
      <tbody>
        <tr><td>Boot jusqu'au bureau</td><td class="num">&lt; 20 s</td>
            <td>GRUB à 0 s <span style="color:var(--dim)">(~5 s)</span>, pas de gestionnaire de session <span style="color:var(--dim)">(~1-2 s)</span>, initramfs réduit</td></tr>
        <tr><td>RAM au repos</td><td class="num">&lt; 900 Mo</td>
            <td>~130 Mo de services de session retirés : at-spi2, tumblerd, démon Thunar, moniteurs gvfs, UPower</td></tr>
        <tr><td>CPU au repos</td><td class="num">&lt; 3 %</td>
            <td>Aucun démon d'énergie : un oneshot écrit gouverneur, EPP et ASPM au démarrage, puis sort</td></tr>
        <tr><td>Boucle GPU après boot</td><td class="num">aucune</td>
            <td><code>WEBGL_lose_context</code> en fin d'animation, vérifié par <code>ghost-bench</code></td></tr>
        <tr><td>Ouverture d'application</td><td class="num">&lt; 700 ms</td>
            <td>NVMe sans ordonnanceur logiciel, <code>noatime</code>, <code>/tmp</code> en RAM</td></tr>
      </tbody>
    </table></div>
    <div class="note">
      <b>Ces chiffres sont des cibles, pas des mesures.</b> Le dépôt a été
      construit dans un conteneur sans N100, sans NVMe et sans dalle.
      <code>BENCHMARKS.md</code> est volontairement vide de résultats : ils
      doivent sortir du deck via <code>ghost-bench --markdown</code>. Inventer
      des chiffres rendrait le fichier pire qu'inutile.
    </div>
    <p class="lede">
      <code>ghost-perf</code> exécute <strong>23 contrôles sur le système
      vivant</strong> — il ne lit aucun jalon d'installation, parce qu'un script
      qui s'est exécuté ne prouve rien : un paquet peut réactiver un service, une
      mise à jour écraser une configuration.
    </p>
  </section>

  <section>
    <h2>La boîte à outils</h2>
    <div class="scroll"><table>
      <thead><tr><th>Commande</th><th>Ce qu'elle fait</th></tr></thead>
      <tbody>
        <tr><td><code>ghost-theme apply</code></td><td>Régénère tout le thème depuis la palette</td></tr>
        <tr><td><code>ghost-run</code></td><td>Palette de commandes — apps, commandes, cartes, fenêtres, bureaux</td></tr>
        <tr><td><code>ghost-perf</code></td><td>Audite chaque optimisation, avec la commande de correction</td></tr>
        <tr><td><code>ghost-bench</code></td><td>Mesure boot, RAM, CPU, NVMe — et où partent les mégaoctets</td></tr>
        <tr><td><code>ghost-status</code></td><td>Réseau, API joignable, mémoire, cartes branchées</td></tr>
        <tr><td><code>ghost-bruce</code></td><td>Cartes ESP32 : liste, console, commande, WebUI</td></tr>
        <tr><td><code>ghost-claude</code></td><td>Lance Claude Code, prévient si l'API est injoignable</td></tr>
        <tr><td><code>ghost-session-mode</code></td><td>Bascule entre session directe et gestionnaire de session</td></tr>
        <tr><td><code>ghost-agent-session</code></td><td>Donne à l'agent un écran séparé du tien</td></tr>
        <tr><td><code>ghost-display-guard</code></td><td>Filet de sécurité de l'affichage — <code>keep</code> après un test réussi</td></tr>
        <tr><td><code>ghost-boot-splash</code></td><td>Rejoue l'animation sans redémarrer</td></tr>
      </tbody>
    </table></div>
  </section>

  <footer>
    <span>{slogan}</span>
    <span>Debian 13 · XFCE · Radxa X4 · 800 × 480</span>
  </footer>
</div>

<script>
  /* Données du système, telles que générées depuis brand/palette.toml et les
     .desktop du dépôt. Le script applicatif ne contient aucune valeur en dur. */
  window.__GB_PAL  = {palette};
  window.__GB_APPS = {apps};
  window.__GB_BTN  = {buttons};
  window.__GB_WALL = "{wallpaper}";
</script>
<script>
__GHOSTBOARD_APP__
</script>
"""


APP_JS = r"""
(function () {
  'use strict';
  // ==========================================================================
  //  GHOSTBOARD OS — bureau de démonstration.
  //  Reproduit le comportement réel : 4 bureaux nommés, fenêtres déplaçables,
  //  palette de commandes, terminal qui répond. Toutes les valeurs (couleurs,
  //  géométrie, applications) viennent des fichiers générés par le thème.
  // ==========================================================================
  var PAL = window.__GB_PAL, APPS = window.__GB_APPS, BTN = window.__GB_BTN;
  var W = PAL.layout.screen_w, H = PAL.layout.screen_h;
  var DESKS = ['SHELL', 'AGENT', 'BOARDS', 'WEB'];
  var TB = PAL.layout.taskbar_h + PAL.layout.taskbar_margin;

  var $ = function (id) { return document.getElementById(id); };
  var screen = $('screen'), winHost = $('windows');
  var desk = 0, z = 10, wins = {};

  screen.style.backgroundImage = 'url("' + window.__GB_WALL + '")';
  function rgba(hex, a) {
    var h = hex.replace('#', '');
    return 'rgba(' + parseInt(h.slice(0,2),16) + ',' + parseInt(h.slice(2,4),16)
         + ',' + parseInt(h.slice(4,6),16) + ',' + a + ')';
  }
  $('taskbar').style.background = rgba(PAL.color.panel, PAL.mica.taskbar_alpha);
  $('startmenu').style.background = rgba(PAL.color.panel, PAL.mica.startmenu_alpha);
  $('palette').style.background = rgba(PAL.color.panel, PAL.mica.startmenu_alpha);

  // ---- mise à l'échelle : la dalle fait 800x480, on la met à l'échelle du
  //      conteneur plutôt que de la redimensionner ------------------------
  var frame = $('frame'), scaler = $('scaler'), scale = 1;
  function fit() {
    scale = Math.min(1, frame.clientWidth / W);
    scaler.style.transform = 'scale(' + scale + ')';
    frame.style.height = Math.round(H * scale) + 'px';
  }
  window.addEventListener('resize', fit); fit();

  function clock() {
    var d = new Date();
    $('clock').textContent = String(d.getHours()).padStart(2,'0') + ':'
                           + String(d.getMinutes()).padStart(2,'0');
  }
  clock(); setInterval(clock, 20000);

  // ======================================================================
  //  Terminal : un shell qui répond réellement.
  //  Les sorties reproduisent le FORMAT des vrais outils ghost-*. Les
  //  valeurs affichées sont plausibles, pas mesurées — la page le dit.
  // ======================================================================
  function esc(s) {
    return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
  }
  var C = {
    m: function (t) { return '<span class="m">' + esc(t) + '</span>'; },
    u: function (t) { return '<span class="u">' + esc(t) + '</span>'; },
    d: function (t) { return '<span class="d">' + esc(t) + '</span>'; },
    g: function (t) { return '<span class="g">' + esc(t) + '</span>'; }
  };

  // Carte simulée : ce n'est PAS le firmware Bruce. Son jeu de commandes est
  // celui de ce simulateur ; celui d'une vraie carte dépend de sa version.
  var BOARD = {
    device: '/dev/ttyACM0', name: 'LilyGO T-Embed / T-Display',
    chip: 'Espressif USB CDC/JTAG natif', ids: '303a:1001', serial: '3C8427AF'
  };

  var COMMANDS = {
    'help': function () { return [
      C.m('Commandes disponibles dans cette démonstration :'), '',
      '  ' + C.m('ghost-status') + C.d('        réseau, API, mémoire, cartes'),
      '  ' + C.m('ghost-perf') + C.d('          audit des optimisations'),
      '  ' + C.m('ghost-perf --fails') + C.d('  seulement les écarts'),
      '  ' + C.m('ghost-bench') + C.d('         mesures face aux cibles'),
      '  ' + C.m('ghost-bruce list') + C.d('    cartes ESP32 branchées'),
      '  ' + C.m('ghost-bruce console') + C.d(' console série (carte simulée)'),
      '  ' + C.m('ghost-theme check') + C.d('   contrastes et cohérence'),
      '  ' + C.m('ghost-run --list') + C.d('    ce que propose la palette'),
      '  ' + C.m('clear') + C.d('               effacer'), '',
      C.d('Super+Espace ouvre la palette de commandes.')
    ]; },
    'ghost-status': function () { return [
      C.m('  GHOSTBOARD OS') + C.d('  CUSTOM HARDWARE. READY TO EXPLORE.'),
      C.d('  ────────────────────────────────────────────────'),
      '  Network                ' + C.m('wlan0') + C.d(' 192.168.1.24/24'),
      '  Anthropic API          ' + C.m('reachable') + C.d('  HTTP 200'),
      '  Claude Code            ' + C.m('installé'),
      '  Memory                 ' + C.m('612 MB / 16038 MB (4%)') + C.d('  < 900 MB'),
      '  Load                   ' + C.d('0.08 0.11 0.09'),
      '  Last boot              ' + C.d('12.482s (kernel 1.9s, userspace 10.5s)'),
      '  Boot device            ' + C.d('/dev/nvme0n1 (SSD/NVMe)'),
      '  Bruce boards           ' + C.m('1 connected'),
      '  Display                ' + C.d('800x480 on :0'), ''
    ]; },
    'ghost-perf': function () { return [
      '', C.m('  GHOSTBOARD OS — audit de performance'),
      C.d('  état réel du système, pas les jalons d\'installation'), '',
      C.d('  ── Démarrage'),
      '  ' + C.g('OK ') + ' Temporisation GRUB              ' + C.d('0 s, menu caché'),
      '  ' + C.g('OK ') + ' initramfs                       ' + C.d('réduit aux modules utilisés (23 Mo)'),
      '  ' + C.g('OK ') + ' Mode d\'ouverture de session     ' + C.d('session directe — aucun gestionnaire'),
      C.d('  ── Session'),
      '  ' + C.g('OK ') + ' Pont d\'accessibilité            ' + C.d('at-spi2 neutralisé'),
      '  ' + C.g('OK ') + ' Démon Thunar                    ' + C.d('absent'),
      '  ' + C.g('OK ') + ' Moniteurs de volumes            ' + C.d('seul udisks2'),
      C.d('  ── Résultat'),
      '  ' + C.g('OK ') + ' RAM au repos                    ' + C.d('612 Mo (cible < 900 Mo)'), '',
      '  24 conforme(s) · 0 écart(s) · 0 sans objet  —  ' + C.m('tout est conforme'), ''
    ]; },
    'ghost-perf --fails': function () { return [
      '', C.m('  GHOSTBOARD OS — audit de performance'), '',
      '  ' + C.g('Aucun écart.') + C.d('  24 contrôles passés.'), ''
    ]; },
    'ghost-bench': function () { return [
      '', C.m('  GHOSTBOARD OS — benchmark'), C.d('  ' + '─'.repeat(48)), '',
      C.d('  Debian GNU/Linux 13  |  Intel(R) N100  (4 cœurs)'), '',
      '  Mesure                             Obtenu         Cible   Verdict',
      C.d('  ' + '─'.repeat(66)),
      '  Boot to usable desktop           12.5 s        < 20 s   ' + C.g('PASS'),
      '  RAM at rest                       612 MB      < 900 MB   ' + C.g('PASS'),
      '  CPU at rest                       0.9 %          < 3 %   ' + C.g('PASS'),
      '  Terminal launch                   240 ms      < 700 ms   ' + C.g('PASS'),
      '  NVMe sequential read             1842 MB/s  > 500 MB/s   ' + C.g('PASS'), '',
      C.d('  Aucune boucle GPU résiduelle après le boot.'), '',
      C.u('  Chiffres d\'illustration : le dépôt n\'a jamais tourné sur un N100.'),
      C.u('  BENCHMARKS.md reste vide tant que le deck n\'a pas parlé.'), ''
    ]; },
    'ghost-bruce list': function () { return [
      C.m('1 carte(s) détectée(s)'), '',
      '  ' + BOARD.device + '  ' + C.m(BOARD.name),
      C.d('    pont série   ' + BOARD.chip + '  [' + BOARD.ids + ']'),
      C.d('    n° de série  ' + BOARD.serial), ''
    ]; },
    'ghost-theme check': function () { return [
      C.m('GHOSTBOARD OS — thème « GhostboardSpectral » depuis palette.toml'),
      'Contrastes (WCAG, sur dalle 4 pouces) :',
      '  ' + C.g('OK ') + '       text sur bg        13.53:1  ' + C.d('(minimum 4.5)'),
      '  ' + C.g('OK ') + '       text sur panel     12.56:1  ' + C.d('(minimum 4.5)'),
      '  ' + C.g('OK ') + '   text_dim sur panel      3.51:1  ' + C.d('(minimum 3.0)'),
      '  ' + C.g('OK ') + '     accent sur panel      4.71:1  ' + C.d('(minimum 3.0)'),
      '  ' + C.g('OK ') + '      input sur panel      5.94:1  ' + C.d('(minimum 3.0)'),
      '  ' + C.g('OK ') + '  on_accent sur accent      5.07:1  ' + C.d('(minimum 4.5)'), '',
      'Cohérence :',
      '  ' + C.g('OK ') + '  police d\'interface 15px >= 15px',
      '  ' + C.g('OK ') + '  animation de boot : 220 + 380 + 620 + 380 + 200 = 1800ms',
      '  ' + C.g('OK ') + '  barre des tâches 34px = 7% de la hauteur', '',
      C.m('OK — 0 problème(s)'), ''
    ]; },
    'ghost-run --list': function () {
      var out = [];
      APPS.forEach(function (a) { out.push(C.d('APP  ') + '  ' + a.name + C.d('   — ' + a.comment.slice(0, 46))); });
      [['ghost-status','Réseau, API joignable, mémoire, cartes branchées'],
       ['ghost-perf','Auditer chaque optimisation sur le système vivant'],
       ['ghost-bench','Mesurer boot, RAM, CPU, NVMe'],
       ['ghost-bruce list','Lister les cartes ESP32 branchées'],
       ['ghost-theme apply','Régénérer tout le thème depuis la palette']
      ].forEach(function (c) { out.push(C.d('CMD  ') + '  ' + c[0] + C.d('   — ' + c[1])); });
      out.push(C.d('CARTE') + '  ' + BOARD.name + ' — ' + BOARD.device + C.d('   — ' + BOARD.chip));
      DESKS.forEach(function (n, i) { out.push(C.d('BUREAU') + ' Bureau ' + (i+1) + ' — ' + n); });
      out.push('');
      return out;
    }
  };

  function termRun(win, line) {
    var body = win.querySelector('.win-body');
    var cmd = line.trim();
    print(body, '<span class="u">$ </span>' + esc(cmd));
    if (!cmd) { return; }
    if (cmd === 'clear') { body.querySelectorAll('.term-line').forEach(function (n) { n.remove(); }); return; }
    if (cmd === 'ghost-bruce console') { enterSerial(win); return; }
    var fn = COMMANDS[cmd];
    if (fn) { fn().forEach(function (l) { print(body, l); }); return; }
    if (cmd.indexOf('ghost-') === 0) {
      print(body, C.u(cmd.split(' ')[0] + ' : cette démonstration ne connaît qu\'un sous-ensemble.'));
      print(body, C.d('  tape « help » pour la liste.'));
      return;
    }
    print(body, C.u('commande introuvable : ' + cmd) + C.d('   (help)'));
  }

  function print(body, html) {
    var n = document.createElement('div');
    n.className = 'term-line';
    n.innerHTML = html;
    body.insertBefore(n, body.querySelector('.term-in'));
    body.scrollTop = body.scrollHeight;
  }

  // ---- session série simulée ---------------------------------------------
  function enterSerial(win) {
    var body = win.querySelector('.win-body');
    win.dataset.mode = 'serial';
    print(body, C.m('─ ghost-bruce ─ ' + BOARD.device + ' @ 115200 bauds'));
    print(body, C.d('  quitter : exit   —   la sortie de la carte est en violet'));
    print(body, C.u('  carte SIMULÉE : son jeu de commandes est celui de cette page,'));
    print(body, C.u('  pas celui d\'un firmware Bruce réel.'));
    print(body, '');
    setPrompt(win, '⟩');
  }

  var SERIAL = {
    'help': ['commandes du simulateur : info, scan, uptime, webui, exit'],
    'info': ['board : ' + BOARD.name, 'chip  : ESP32-S3', 'serial: ' + BOARD.serial,
             'free  : 214 kB'],
    'scan': ['scanning 2.4 GHz…', '  -42 dBm  ch 6   GHOSTBOARD-AP', '  -71 dBm  ch 1   <hidden>',
             '  -78 dBm  ch 11  freebox_XJKLMN', '3 networks'],
    'uptime': ['up 00:04:12, 3 resets'],
    'webui': ['starting web server…', 'AP up: GHOSTBOARD-AP', 'http://192.168.4.1']
  };

  function serialRun(win, line) {
    var body = win.querySelector('.win-body');
    var cmd = line.trim();
    print(body, '<span class="u">⟩ </span>' + esc(cmd));
    if (cmd === 'exit') {
      win.dataset.mode = 'shell';
      print(body, C.d('console fermée'));
      setPrompt(win, '$');
      return;
    }
    if (!cmd) { return; }
    var r = SERIAL[cmd];
    if (r) { r.forEach(function (l) { print(body, C.m(l)); }); }
    else { print(body, C.m('unknown command: ' + cmd) + C.d('  (help)')); }
  }

  function setPrompt(win, ch) { win.querySelector('.term-in .ps').textContent = ch; }

  // ======================================================================
  //  Fenêtres
  // ======================================================================
  function content(app) {
    if (app.id === 'ghostboard-terminal' || app.id === 'ghostboard-claude') return null;
    if (app.id === 'ghostboard-bruce') return COMMANDS['ghost-bruce list']().join('\n');
    if (app.id === 'ghostboard-status') return COMMANDS['ghost-status']().join('\n');
    if (app.id === 'ghostboard-settings') return [
      C.d('Gestionnaire de réglages XFCE'), '',
      '  Thème            ' + C.m('GhostboardSpectral'),
      '  Police           ' + C.m('IBM Plex Mono 11.2') + C.d('  (15 px)'),
      '  Titres           ' + C.m('Martian Mono Medium 11'),
      '  Boutons          ' + C.m('|HMC') + C.d('  à droite'),
      '  Compositeur      ' + C.m('actif') + C.d('  (translucidité de la barre)'),
      '  Bureaux          ' + C.m('4') + C.d('  SHELL · AGENT · BOARDS · WEB'),
      '  Animations GTK   ' + C.u('désactivées')
    ].join('\n');
    return [C.d('Chromium — fenêtre calée sur 800x480,'),
            C.d('télémétrie et préchargement coupés.')].join('\n');
  }

  function openApp(app) {
    closeMenus();
    var w = wins[app.id];
    if (w) { w.dataset.desk = desk; w.style.display = ''; w.style.zIndex = ++z; paint(app.id); return; }
    w = document.createElement('div');
    w.className = 'win';
    w.dataset.desk = desk;
    var isTerm = app.id === 'ghostboard-terminal' || app.id === 'ghostboard-claude';
    var bodyHtml = isTerm
      ? '<div class="term-in"><span class="ps">$</span><input type="text" spellcheck="false" autocomplete="off" aria-label="Ligne de commande"></div>'
      : '<div class="term-line">' + content(app) + '</div>';
    // Plein écran moins la barre : sur 480 px de haut, une fenêtre flottante
    // n'a pas de sens. C'est ce que fait l'OS réel (borderless_maximize).
    w.style.cssText = 'left:8px;top:8px;width:' + (W - 16) + 'px;height:'
      + (H - 16 - TB - 6) + 'px;z-index:' + (++z);
    w.innerHTML =
      '<div class="win-title"><span>' + esc(app.name) + '</span><div class="win-btns">'
      + '<img class="min" alt="Réduire" src="' + BTN.hide + '">'
      + '<img class="max" alt="Agrandir" src="' + BTN.maximize + '">'
      + '<img class="close" alt="Fermer" src="' + BTN.close + '"></div></div>'
      + '<div class="win-body' + (isTerm ? ' term' : '') + '">' + bodyHtml + '</div>';

    w.querySelector('.close').addEventListener('click', function (e) {
      e.stopPropagation(); w.remove(); delete wins[app.id]; paint();
    });
    w.querySelector('.min').addEventListener('click', function (e) {
      e.stopPropagation(); w.style.display = 'none'; paint();
    });
    w.querySelector('.max').addEventListener('click', function (e) {
      e.stopPropagation();
      if (w.dataset.max === '1') {
        w.dataset.max = '0';
        w.style.cssText = w.dataset.prev + ';z-index:' + (++z);
      } else {
        w.dataset.max = '1';
        w.dataset.prev = 'left:' + w.offsetLeft + 'px;top:' + w.offsetTop
          + 'px;width:' + w.offsetWidth + 'px;height:' + w.offsetHeight + 'px';
        w.style.cssText = 'left:0;top:0;width:' + W + 'px;height:' + (H - TB)
          + 'px;z-index:' + (++z);
      }
    });
    w.addEventListener('mousedown', function () { w.style.zIndex = ++z; paint(app.id); });
    if (isTerm) {
      var input = w.querySelector('.term-in input');
      w.querySelector('.win-body').addEventListener('click', function () { input.focus(); });
      input.addEventListener('keydown', function (ev) {
        if (ev.key !== 'Enter') return;
        var v = input.value; input.value = '';
        (w.dataset.mode === 'serial' ? serialRun : termRun)(w, v);
      });
      setTimeout(function () { input.focus(); }, 30);
    }
    dragify(w);
    winHost.appendChild(w);
    wins[app.id] = w;
    if (isTerm) {
      var b = w.querySelector('.win-body');
      print(b, C.m('GHOSTBOARD OS') + C.d('  —  tape « help »'));
      print(b, '');
    }
    paint(app.id);
  }

  // ---- déplacement à la souris -------------------------------------------
  function dragify(w) {
    var bar = w.querySelector('.win-title'), sx = 0, sy = 0, ox = 0, oy = 0, on = false;
    bar.addEventListener('mousedown', function (ev) {
      if (ev.target.tagName === 'IMG') return;      // les boutons ne déplacent pas
      on = true; w.classList.add('drag');
      sx = ev.clientX; sy = ev.clientY; ox = w.offsetLeft; oy = w.offsetTop;
      w.style.zIndex = ++z;
      ev.preventDefault();
    });
    window.addEventListener('mousemove', function (ev) {
      if (!on) return;
      // Le conteneur est mis à l'échelle : le déplacement de la souris doit
      // être divisé par le facteur, sinon la fenêtre part plus vite que le
      // curseur dès que la page est réduite.
      var nx = ox + (ev.clientX - sx) / scale;
      var ny = oy + (ev.clientY - sy) / scale;
      // On garde toujours la barre de titre attrapable.
      w.style.left = Math.max(-w.offsetWidth + 60, Math.min(W - 60, nx)) + 'px';
      w.style.top  = Math.max(0, Math.min(H - TB - 28, ny)) + 'px';
    });
    window.addEventListener('mouseup', function () {
      if (!on) return;
      on = false; w.classList.remove('drag'); w.dataset.max = '0';
    });
  }

  // ---- barre des tâches et pager -----------------------------------------
  function paint(activeId) {
    var host = $('tasks'); host.innerHTML = '';
    APPS.forEach(function (a) {
      var w = wins[a.id];
      if (!w || +w.dataset.desk !== desk) return;
      var b = document.createElement('button');
      b.className = 'tb-btn' + (a.id === activeId && w.style.display !== 'none' ? ' active' : '');
      b.textContent = a.name;
      b.addEventListener('click', function () {
        if (w.style.display === 'none') { w.style.display = ''; w.style.zIndex = ++z; paint(a.id); }
        else if (a.id === activeId) { w.style.display = 'none'; paint(); }
        else { w.style.zIndex = ++z; paint(a.id); }
      });
      host.appendChild(b);
    });
    var pg = $('pager'); pg.innerHTML = '';
    DESKS.forEach(function (name, i) {
      var busy = Object.keys(wins).some(function (k) { return +wins[k].dataset.desk === i; });
      var b = document.createElement('button');
      b.className = 'pg' + (i === desk ? ' on' : '') + (busy && i !== desk ? ' busy' : '');
      b.textContent = String(i + 1);
      b.title = name + (busy ? ' — occupé' : '');
      b.addEventListener('click', function () { gotoDesk(i); });
      pg.appendChild(b);
    });
  }

  function gotoDesk(i) {
    desk = i;
    Object.keys(wins).forEach(function (k) {
      wins[k].style.visibility = (+wins[k].dataset.desk === i) ? '' : 'hidden';
    });
    closeMenus();
    paint();
  }

  // ======================================================================
  //  Menu démarrer
  // ======================================================================
  var menu = $('startmenu'), search = $('search'), grid = $('pinned');
  function glyph(a) {
    return a.glyph === 'GHOST' ? '<span class="mark">GB</span>'
      : '<svg viewBox="0 0 24 24" aria-hidden="true">' + a.glyph + '</svg>';
  }
  function paintPinned(q) {
    q = (q || '').trim().toLowerCase();
    grid.innerHTML = '';
    var hits = APPS.filter(function (a) {
      return !q || a.name.toLowerCase().indexOf(q) >= 0
                || a.comment.toLowerCase().indexOf(q) >= 0;
    });
    if (!hits.length) {
      grid.innerHTML = '<div class="no-hit">Aucune application ne correspond.</div>';
      return;
    }
    hits.forEach(function (a, i) {
      var b = document.createElement('button');
      b.className = 'pin' + (q && i === 0 ? ' sel' : '');
      b.innerHTML = glyph(a) + '<span>' + esc(a.name) + '</span>';
      b.title = a.comment;
      b.addEventListener('click', function () { openApp(a); });
      grid.appendChild(b);
    });
  }
  function closeMenus() { menu.classList.remove('open'); pal.classList.remove('open'); }
  $('startbtn').addEventListener('click', function (ev) {
    ev.stopPropagation();
    var was = menu.classList.contains('open');
    closeMenus();
    if (!was) { menu.classList.add('open'); search.value = ''; paintPinned(''); search.focus(); }
  });
  search.addEventListener('input', function () { paintPinned(search.value); });
  search.addEventListener('keydown', function (ev) {
    if (ev.key === 'Escape') closeMenus();
    if (ev.key === 'Enter') { var f = grid.querySelector('.pin'); if (f) f.click(); }
  });

  // ======================================================================
  //  Palette de commandes — la reproduction de ghost-run
  // ======================================================================
  var pal = $('palette'), palInput = $('pal-input'), palList = $('pal-list'), palSel = 0, palHits = [];

  function palEntries() {
    var out = [];
    APPS.forEach(function (a) {
      out.push({ tag: 'APP', label: a.name, hint: a.comment,
                 run: function () { openApp(a); } });
    });
    Object.keys(COMMANDS).forEach(function (c) {
      out.push({ tag: 'CMD', label: c, hint: 'exécuter dans le terminal',
                 run: function () {
                   var t = APPS[0];
                   openApp(t);
                   var w = wins[t.id];
                   setTimeout(function () { termRun(w, c); }, 40);
                 } });
    });
    out.push({ tag: 'CARTE', label: BOARD.name + ' — ' + BOARD.device, hint: BOARD.chip,
               run: function () {
                 var t = APPS[0]; openApp(t);
                 setTimeout(function () { termRun(wins[t.id], 'ghost-bruce console'); }, 40);
               } });
    DESKS.forEach(function (n, i) {
      out.push({ tag: 'BUREAU', label: 'Bureau ' + (i + 1) + ' — ' + n,
                 hint: i === desk ? 'actuel' : 'basculer',
                 run: function () { gotoDesk(i); } });
    });
    Object.keys(wins).forEach(function (k) {
      var a = APPS.filter(function (x) { return x.id === k; })[0];
      if (!a) return;
      out.push({ tag: 'FEN', label: a.name, hint: 'basculer sur la fenêtre',
                 run: function () { openApp(a); } });
    });
    return out;
  }

  // Filtrage flou : les lettres doivent apparaître dans l'ordre, pas
  // forcément côte à côte — c'est le comportement de rofi en mode fuzzy.
  function fuzzy(hay, needle) {
    if (!needle) return true;
    hay = hay.toLowerCase(); needle = needle.toLowerCase();
    var i = 0;
    for (var j = 0; j < hay.length && i < needle.length; j++) {
      if (hay[j] === needle[i]) i++;
    }
    return i === needle.length;
  }

  // Le filtrage seul ne suffit pas : chercher « b » remontait « Terminal »
  // parce que sa description contient « IBM ». Ce qui compte est OÙ la
  // correspondance tombe — un début de nom vaut mieux qu'un mot perdu dans
  // une description.
  function score(e, q) {
    if (!q) return 0;
    var n = q.toLowerCase(), label = e.label.toLowerCase();
    if (label.indexOf(n) === 0) return 0;              // début du nom
    if (label.indexOf(n) > 0) return 1;                // dans le nom
    if (fuzzy(label, n)) return 2;                     // nom, en flou
    if ((e.hint || '').toLowerCase().indexOf(n) >= 0) return 3;  // dans l'aide
    return 4;                                          // aide, en flou
  }

  function paintPal() {
    var q = palInput.value.trim();
    palHits = palEntries().filter(function (e) {
      return fuzzy(e.tag + ' ' + e.label + ' ' + e.hint, q);
    }).map(function (e, i) {
      e._s = score(e, q); e._i = i; return e;
    }).sort(function (a, b) {
      // À score égal on garde l'ordre d'origine : applications, commandes,
      // cartes, bureaux, fenêtres. L'ordre ne doit pas sautiller.
      return a._s - b._s || a._i - b._i;
    }).slice(0, 6);
    if (palSel >= palHits.length) palSel = Math.max(0, palHits.length - 1);
    palList.innerHTML = '';
    if (!palHits.length) {
      palList.innerHTML = '<div class="pal-none">Rien ne correspond à « ' + esc(q) + ' ».</div>';
      return;
    }
    palHits.forEach(function (e, i) {
      var n = document.createElement('div');
      n.className = 'pal-item' + (i === palSel ? ' sel' : '');
      n.innerHTML = '<span class="tag">' + e.tag + '</span>'
                  + '<span class="lbl">' + esc(e.label) + '</span>'
                  + '<span class="hnt">' + esc(e.hint || '') + '</span>';
      n.addEventListener('click', function () { closeMenus(); e.run(); });
      palList.appendChild(n);
    });
  }

  function openPal() {
    closeMenus();
    pal.classList.add('open');
    palInput.value = ''; palSel = 0; paintPal(); palInput.focus();
  }
  palInput.addEventListener('input', function () { palSel = 0; paintPal(); });
  palInput.addEventListener('keydown', function (ev) {
    if (ev.key === 'Escape') { closeMenus(); return; }
    if (ev.key === 'ArrowDown') { palSel = Math.min(palSel + 1, palHits.length - 1); paintPal(); ev.preventDefault(); }
    if (ev.key === 'ArrowUp') { palSel = Math.max(palSel - 1, 0); paintPal(); ev.preventDefault(); }
    if (ev.key === 'Enter' && palHits[palSel]) { var e = palHits[palSel]; closeMenus(); e.run(); }
  });

  // Super+Espace comme sur le deck ; Ctrl+Espace parce que le navigateur
  // intercepte souvent la touche Super.
  screen.addEventListener('keydown', function (ev) {
    if (ev.code === 'Space' && (ev.metaKey || ev.ctrlKey)) { openPal(); ev.preventDefault(); }
  });
  document.addEventListener('keydown', function (ev) {
    if (ev.code === 'Space' && (ev.metaKey || ev.ctrlKey)
        && screen.contains(document.activeElement)) { openPal(); ev.preventDefault(); }
  });
  var palBtn = document.getElementById('palbtn');
  if (palBtn) palBtn.addEventListener('click', function (ev) { ev.stopPropagation(); openPal(); });

  screen.addEventListener('click', function (ev) {
    if (!menu.contains(ev.target) && !pal.contains(ev.target)) closeMenus();
  });

  // ---- état de repos : le terminal ouvert sur le bureau SHELL ------------
  paintPinned('');
  openApp(APPS[0]);
})();
"""


if __name__ == "__main__":
    sys.exit(main())
