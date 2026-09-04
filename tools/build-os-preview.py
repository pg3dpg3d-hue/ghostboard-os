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
            <div id="startmenu">
              <input id="search" type="text" placeholder="Rechercher une application…"
                     autocomplete="off" spellcheck="false" aria-label="Rechercher une application">
              <div class="pinned-label">Épinglées</div>
              <div id="pinned"></div>
            </div>
            <div id="taskbar">
              <button class="tb-btn" id="startbtn" title="Menu démarrer">{start_icon}</button>
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
      <span>Barre <b>704 × 34</b>, rayon 10, marge 4</span>
      <span>Menu <b>620 × 400</b>, grille 5</span>
    </div>
    <p class="hint">
      <b>C'est manipulable.</b> Ouvre le menu démarrer, tape pour filtrer, lance
      une application. Couleurs, géométrie, fond d'écran, icône du bouton et
      boutons de fenêtre viennent des fichiers réellement produits par le thème.
    </p>
    <div class="note">
      <b>Ce n'est pas une capture d'écran.</b> XFCE n'a jamais tourné pendant la
      construction : ce dépôt a été écrit dans un conteneur sans tête, sans GPU
      ni dalle. C'est une reproduction fidèle aux valeurs de la palette et à la
      géométrie du panneau, pas une photo du système en marche.
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
(function () {{
  var PAL   = {palette};
  var APPS  = {apps};
  var BTN   = {buttons};
  var TERM  = {term};
  var W = PAL.layout.screen_w, H = PAL.layout.screen_h;

  var screen = document.getElementById('screen');
  screen.style.backgroundImage = 'url("{wallpaper}")';
  document.getElementById('taskbar').style.background =
    'rgba(' + hexrgb(PAL.color.panel) + ',' + PAL.mica.taskbar_alpha + ')';
  document.getElementById('startmenu').style.background =
    'rgba(' + hexrgb(PAL.color.panel) + ',' + PAL.mica.startmenu_alpha + ')';

  function hexrgb(h) {{
    h = h.replace('#', '');
    return [parseInt(h.slice(0,2),16), parseInt(h.slice(2,4),16), parseInt(h.slice(4,6),16)].join(',');
  }}

  // La dalle fait 800x480 : on met le rendu à l'échelle du conteneur plutôt que
  // de le redimensionner, pour que ce soit bien la géométrie du deck qu'on voie.
  var frame = document.getElementById('frame'), scaler = document.getElementById('scaler');
  function fit() {{
    var s = Math.min(1, frame.clientWidth / W);
    scaler.style.transform = 'scale(' + s + ')';
    frame.style.height = Math.round(H * s) + 'px';
  }}
  window.addEventListener('resize', fit); fit();

  // ---- horloge : format de la barre réelle (%H:%M) -------------------------
  function tick() {{
    var d = new Date();
    document.getElementById('clock').textContent =
      String(d.getHours()).padStart(2,'0') + ':' + String(d.getMinutes()).padStart(2,'0');
  }}
  tick(); setInterval(tick, 20000);

  // ---- contenu des fenêtres : le FORMAT réel des sorties d'outils ----------
  function body(id) {{
    var m = '<span class="m">', u = '<span class="u">', d = '<span class="d">', e = '</span>';
    if (id === 'ghostboard-bruce') return [
      m + '2 carte(s) détectée(s)' + e, '',
      '  /dev/ttyACM0  ' + m + 'LilyGO T-Embed / T-Display' + e,
      d + '    pont série   Espressif USB CDC/JTAG natif  [303a:1001]' + e,
      d + '    n° de série  3C8427AF' + e, '',
      '  /dev/ttyUSB0  ' + m + 'M5Stick (M5Stack)' + e,
      d + '    pont série   Silicon Labs CP210x  [10c4:ea60]' + e, '',
      u + '$ ' + e + 'ghost-bruce console<span class="cursor"></span>'
    ].join('\n');
    if (id === 'ghostboard-status') return [
      m + '  GHOSTBOARD OS' + e + d + '  CUSTOM HARDWARE. READY TO EXPLORE.' + e,
      d + '  ────────────────────────────────────────' + e,
      '  Network                ' + m + 'wlan0' + e + d + ' 192.168.1.24/24' + e,
      '  Anthropic API          ' + m + 'reachable' + e + d + '  HTTP 200' + e,
      '  Memory                 ' + m + '612 MB / 16038 MB (3%)' + e + d + '  < 900 MB target' + e,
      '  Bruce boards           ' + m + '2 connected' + e,
      '  Display                ' + d + '800x480 on :0' + e
    ].join('\n');
    if (id === 'ghostboard-claude') return [
      m + '  GHOSTBOARD' + e + d + ' — API Anthropic joignable' + e, '',
      u + '> ' + e + 'prends une capture et clique sur le menu démarrer', '',
      d + '  ● screenshot  800x480, 41 Ko' + e,
      d + '  ● click       (48, 459)' + e,
      m + '  Menu ouvert. La recherche a le focus.' + e, '',
      u + '> ' + e + '<span class="cursor"></span>'
    ].join('\n');
    if (id === 'ghostboard-settings') return d +
      'Gestionnaire de réglages XFCE.\n\nThème : GhostboardSpectral\nPolice : IBM Plex Mono 11.2\n' +
      'Boutons de fenêtre : |HMC (à droite)\nCompositeur : actif (translucidité de la barre)' + e;
    if (id === 'ghostboard-browser') return d +
      'Chromium — fenêtre calée sur 800x480,\ntélémétrie et préchargement coupés.' + e;
    // Terminal
    return [
      u + '$ ' + e + 'ghost-perf --fails',
      '', m + '  GHOSTBOARD OS — audit de performance' + e,
      d + '  état réel du système, pas les jalons d\'installation' + e, '',
      '<span class="g">  ✓</span> 23 contrôles · 0 écart',
      '', u + '$ ' + e + '<span class="cursor"></span>'
    ].join('\n');
  }}

  // ---- fenêtres -----------------------------------------------------------
  var open = {{}}, z = 10;
  function openApp(app) {{
    closeMenu();
    if (open[app.id]) {{ open[app.id].style.zIndex = ++z; paintTasks(app.id); return; }}
    var w = document.createElement('div');
    w.className = 'win';
    // Plein écran par défaut, moins la barre : sur 480 px de haut, une fenêtre
    // flottante n'a pas de sens. C'est la règle de l'OS réel.
    w.style.cssText = 'left:8px;top:8px;width:' + (W-16) + 'px;height:' +
      (H - 16 - {L_taskbar_h} - {L_taskbar_margin} - 6) + 'px;z-index:' + (++z);
    w.innerHTML =
      '<div class="win-title"><span>' + app.name + '</span><div class="win-btns">' +
      '<img alt="Réduire" src="' + BTN.hide + '">' +
      '<img alt="Agrandir" src="' + BTN.maximize + '">' +
      '<img class="close" alt="Fermer" src="' + BTN.close + '"></div></div>' +
      '<div class="win-body">' + body(app.id) + '</div>';
    w.querySelector('.close').addEventListener('click', function () {{
      w.remove(); delete open[app.id]; paintTasks();
    }});
    w.addEventListener('mousedown', function () {{ w.style.zIndex = ++z; paintTasks(app.id); }});
    document.getElementById('windows').appendChild(w);
    open[app.id] = w;
    paintTasks(app.id);
  }}

  function paintTasks(activeId) {{
    var host = document.getElementById('tasks');
    host.innerHTML = '';
    APPS.forEach(function (a) {{
      if (!open[a.id]) return;
      var b = document.createElement('button');
      b.className = 'tb-btn' + (a.id === activeId ? ' active' : '');
      b.textContent = a.name;
      b.addEventListener('click', function () {{ openApp(a); }});
      host.appendChild(b);
    }});
  }}

  // ---- menu démarrer ------------------------------------------------------
  var menu = document.getElementById('startmenu');
  var search = document.getElementById('search');
  var grid = document.getElementById('pinned');

  function icon(app) {{
    if (app.glyph === 'GHOST') return '<span class="mark">GB</span>';
    return '<svg viewBox="0 0 24 24" aria-hidden="true">' + app.glyph + '</svg>';
  }}
  function paintPinned(filter) {{
    var q = (filter || '').trim().toLowerCase();
    grid.innerHTML = '';
    var hits = APPS.filter(function (a) {{
      return !q || a.name.toLowerCase().indexOf(q) >= 0
                || a.comment.toLowerCase().indexOf(q) >= 0;
    }});
    if (!hits.length) {{
      grid.innerHTML = '<div class="no-hit">Aucune application ne correspond à « ' +
        q.replace(/[<>&]/g, '') + ' ».</div>';
      return;
    }}
    hits.forEach(function (a, i) {{
      var b = document.createElement('button');
      b.className = 'pin' + (q && i === 0 ? ' sel' : '');
      b.innerHTML = icon(a) + '<span>' + a.name + '</span>';
      b.title = a.comment;
      b.addEventListener('click', function () {{ openApp(a); }});
      grid.appendChild(b);
    }});
  }}
  function openMenu() {{
    menu.classList.add('open'); search.value = ''; paintPinned(''); search.focus();
  }}
  function closeMenu() {{ menu.classList.remove('open'); }}

  document.getElementById('startbtn').addEventListener('click', function (ev) {{
    ev.stopPropagation();
    menu.classList.contains('open') ? closeMenu() : openMenu();
  }});
  search.addEventListener('input', function () {{ paintPinned(search.value); }});
  search.addEventListener('keydown', function (ev) {{
    if (ev.key === 'Escape') {{ closeMenu(); }}
    if (ev.key === 'Enter') {{
      var first = grid.querySelector('.pin');
      if (first) first.click();
    }}
  }});
  screen.addEventListener('click', function (ev) {{
    if (!menu.contains(ev.target)) closeMenu();
  }});

  // État de repos : le terminal ouvert. Une page qui s'affiche sur un bureau
  // vide ne montrerait pas ce que fait l'OS.
  paintPinned('');
  openApp(APPS[0]);
}})();
</script>
"""

if __name__ == "__main__":
    sys.exit(main())
