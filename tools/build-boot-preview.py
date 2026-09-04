#!/usr/bin/env python3
"""
build-boot-preview.py — banc d'essai autonome pour l'animation d'allumage.

Produit une page HTML unique qui exécute LE VRAI boot-animation/boot.js.
Il n'existe pas de seconde version de l'animation : ce qu'on voit dans le banc
est octet pour octet ce qui tourne sur le deck.

Trois transformations, et trois seulement :
  1. `import * as THREE from './vendor/...'` est retiré — le banc charge
     three.js en UMD depuis cdnjs, qui expose le global THREE.
  2. La feuille de style de l'animation est recadrée : `position: fixed` devient
     `absolute` et la règle `html, body` devient une règle sur le cadre, pour
     que l'animation vive dans une boîte de 800x480 au lieu de couvrir la page.
  3. La palette est injectée en JSON plutôt que chargée depuis palette.js.

    ./tools/build-boot-preview.py [SORTIE.html]
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ANIM = ROOT / "boot-animation"
PALETTE_JSON = ROOT / "build" / "theme" / "share" / "palette.json"

# three.js en UMD. Le dépôt épingle 0.185 (ESM) pour le deck ; cdnjs ne sert
# de build UMD que jusqu'à r134. Les API utilisées par boot.js (BufferGeometry,
# ShaderMaterial, Points, OrthographicCamera, CanvasTexture, setAnimationLoop,
# Object3D.clear) existent identiquement dans les deux.
THREE_CDN = "https://cdnjs.cloudflare.com/ajax/libs/three.js/r134/three.min.js"


def extract_style(html: str) -> str:
    m = re.search(r"<style>(.*?)</style>", html, re.S)
    if not m:
        raise SystemExit("index.html : bloc <style> introuvable")
    css = m.group(1)
    # La règle html/body de l'animation suppose le plein écran. Dans le banc,
    # c'est le cadre qui joue ce rôle.
    css = re.sub(r"html,\s*body\s*\{[^}]*\}",
                 "#deck { position: relative; width: 800px; height: 480px;\n"
                 "    overflow: hidden; background: #000; cursor: default; }",
                 css, count=1)
    css = css.replace("position: fixed;", "position: absolute;")
    # Portée : chaque sélecteur de l'animation est préfixé par #deck pour ne pas
    # fuir sur le reste de la page.
    out = []
    for rule in re.split(r"(?<=\})", css):
        if not rule.strip():
            continue
        head, sep, body = rule.partition("{")
        if not sep:
            out.append(rule)
            continue
        sels = []
        for sel in head.split(","):
            sel = sel.strip()
            if not sel or sel.startswith("@"):
                sels.append(sel)
            elif sel.startswith("#deck"):
                sels.append(sel)
            else:
                sels.append(f"#deck {sel}")
        out.append(", ".join(sels) + " {" + body)
    return "\n".join(out)


def extract_markup(html: str) -> str:
    """Les cinq conteneurs de l'animation, en un seul bloc contigu.

    On découpe une TRANCHE plutôt que d'extraire div par div : #fallback
    contient un div imbriqué, et une expression non gourmande s'arrête sur le
    </div> intérieur — ce qui laisse une balise ouverte qui avale la suite de
    la page. Trancher du premier au dernier conteneur ne peut pas déséquilibrer
    le balisage.
    """
    start_tag = '<div id="stage">'
    end_tag = '<div id="tagline"></div>'
    if start_tag not in html or end_tag not in html:
        raise SystemExit("index.html : conteneurs #stage / #tagline introuvables")
    block = html[html.index(start_tag):html.index(end_tag) + len(end_tag)]
    for needed in ("stage", "scanline", "readout", "fallback", "tagline"):
        if f'id="{needed}"' not in block:
            raise SystemExit(f"index.html : conteneur #{needed} absent de la tranche")
    if block.count("<div") != block.count("</div>"):
        raise SystemExit("index.html : balisage déséquilibré dans la tranche extraite")
    return block


def extract_boot_js() -> str:
    js = (ANIM / "boot.js").read_text(encoding="utf-8")
    js, n = re.subn(r"^import \* as THREE from .*?;\s*$",
                    "// [banc] import ES retiré : three.js est chargé en UMD (global THREE).",
                    js, count=1, flags=re.M)
    if n != 1:
        raise SystemExit("boot.js : ligne d'import three.js introuvable")
    return js


def main() -> int:
    out_path = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "build" / "boot-bench.html"
    if not PALETTE_JSON.exists():
        raise SystemExit("palette.json absent — lance d'abord theme/render-theme.py")

    palette = json.loads(PALETTE_JSON.read_text(encoding="utf-8"))
    html = (ANIM / "index.html").read_text(encoding="utf-8")
    anim_css = extract_style(html)
    anim_markup = extract_markup(html)
    boot_js = extract_boot_js()

    c = palette["color"]
    boot = palette["boot"]
    acts = [
        ("01", "AMORÇAGE", "ignite_ms",
         "Une ligne de balayage descend la dalle. Les particules n'existent pas "
         "avant son passage : elles naissent sur la ligne et s'en détachent.",
         "L'ordre de naissance mêle 40 % de position verticale et 60 % d'aléatoire. "
         "Purement vertical, le balayage traversait 480 px en n'émettant que sur "
         "les 100 px du logotype."),
        ("02", "RECHERCHE", "seek_ms",
         "Dérive turbulente dans un champ de flux. Les particules cherchent, "
         "elles ne convergent pas encore.",
         "Flux à deux octaves de sinus déphasés dans le vertex shader — pas de "
         "bruit de Perlin, pas de texture. La profondeur module taille ET opacité, "
         "ce qui stratifie le nuage au lieu d'en faire un aplat."),
        ("03", "VERROU", "lock_ms",
         "Les lettres se posent une par une, de gauche à droite. Chacune arrive "
         "avec un éclat bref et un décrochage de bandes horizontales.",
         "Chaque pixel connaît sa lettre : l'indice est calculé au moment de "
         "rasteriser le mot, en même temps que la détection de bord. "
         "easeOutExpo — le mot se pose, il ne rebondit pas."),
        ("04", "ASSISE", "settle_ms",
         "Le filet d'accent se trace de gauche à droite. Le slogan s'écrit "
         "caractère par caractère, curseur bloc compris.",
         "Le filet est fait des mêmes particules que le mot, simplement "
         "verrouillées plus tard. Le slogan est du DOM : sur une dalle de "
         "4 pouces, du texte net bat une approximation en particules."),
        ("05", "DÉCHARGE", "discharge_ms",
         "Onde de choc radiale, extinction, puis destruction du contexte WebGL.",
         "WEBGL_lose_context, tous les tampons libérés, boucle de rendu arrêtée. "
         "C'est une cible de performance : aucune boucle GPU ne survit au boot."),
    ]
    total = sum(boot[a[2]] for a in acts)

    def act_rows() -> str:
        rows = []
        elapsed = 0
        for i, (num, name, key, what, how) in enumerate(acts):
            ms = boot[key]
            rows.append(f'''
        <article class="act" data-act="{i}">
          <div class="act-rail" aria-hidden="true"></div>
          <div class="act-id">
            <span class="act-num">{num}</span>
            <h3 class="act-name">{name}</h3>
            <span class="act-ms">{ms}&thinsp;ms</span>
            <span class="act-range">{elapsed} → {elapsed + ms}&thinsp;ms</span>
          </div>
          <div class="act-body">
            <p class="act-what">{what}</p>
            <p class="act-how">{how}</p>
          </div>
        </article>''')
            elapsed += ms
        return "".join(rows)

    def act_segments() -> str:
        segs = []
        for i, (num, name, key, _, _) in enumerate(acts):
            pct = boot[key] / total * 100
            segs.append(f'<div class="seg" data-act="{i}" style="flex:0 0 {pct:.4f}%">'
                        f'<span class="seg-num">{num}</span>'
                        f'<span class="seg-name">{name}</span>'
                        f'<span class="seg-ms">{boot[key]}</span></div>')
        return "".join(segs)

    page = PAGE_TEMPLATE.format(
        three_cdn=THREE_CDN,
        anim_css=anim_css,
        anim_markup=anim_markup,
        boot_js=boot_js,
        palette_json=json.dumps(palette, ensure_ascii=False),
        bg=c["bg"], panel=c["panel"], sep=c["separator"], accent=c["accent"],
        input=c["input"], text=c["text"], dim=c["text_dim"],
        total_ms=total, total_s=f"{total / 1000:.2f}",
        budget_pct=f"{total / 20000 * 100:.1f}",
        act_rows=act_rows(), act_segments=act_segments(),
        particles=boot["particle_count"], timeout=boot["timeout_ms"],
        slogan=palette["meta"]["slogan"],
    )
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(page, encoding="utf-8")
    print(f"banc écrit : {out_path}  ({len(page) / 1024:.0f} Ko)")
    return 0


PAGE_TEMPLATE = r"""<title>GHOSTBOARD Ignition Bench</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Martian+Mono:wght@400;600;700&family=IBM+Plex+Mono:wght@400;500;600&display=swap">
<style>
/* ==========================================================================
   GHOSTBOARD — banc d'essai de l'animation d'allumage.
   Monde visuel unique et assumé : c'est un écran de démarrage sur une dalle
   quasi noire. Pas de bascule clair/sombre — chaque couleur est peinte
   explicitement pour que la page tienne sur n'importe quel fond hôte.
   ========================================================================== */
:root {{
  --bg:      {bg};
  --panel:   {panel};
  --sep:     {sep};
  --accent:  {accent};
  --signal:  {input};
  --text:    {text};
  --dim:     {dim};
  --display: "Martian Mono", "IBM Plex Mono", ui-monospace, monospace;
  --body:    "IBM Plex Mono", ui-monospace, SFMono-Regular, Menlo, monospace;
  --gap:     clamp(28px, 4.5vw, 52px);
}}

* {{ box-sizing: border-box; }}
body {{
  margin: 0;
  background: var(--bg);
  color: var(--text);
  font-family: var(--body);
  font-size: 14px;
  line-height: 1.62;
  -webkit-font-smoothing: antialiased;
}}
.wrap {{
  max-width: 900px;
  margin: 0 auto;
  padding: clamp(28px, 5vw, 64px) clamp(18px, 4vw, 40px) 96px;
  display: flex;
  flex-direction: column;
  gap: var(--gap);
}}

/* ---- en-tête ------------------------------------------------------------ */
.masthead {{ display: flex; flex-direction: column; gap: 14px; }}
.eyebrow {{
  font-family: var(--body);
  font-size: 11px; font-weight: 500;
  letter-spacing: 3.4px; text-transform: uppercase;
  color: var(--dim);
  display: flex; align-items: center; gap: 12px;
}}
.eyebrow::after {{
  content: ""; flex: 1; height: 1px; background: var(--sep);
}}
h1 {{
  font-family: var(--display);
  font-size: clamp(27px, 5.2vw, 42px);
  font-weight: 700; letter-spacing: 1px; line-height: 1.12;
  margin: 0; color: var(--text); text-wrap: balance;
}}
h1 em {{ font-style: normal; color: var(--accent); }}
.standfirst {{
  margin: 0; max-width: 63ch; color: var(--dim); font-size: 14px;
}}
.standfirst strong {{ color: var(--text); font-weight: 500; }}

/* ---- le deck ------------------------------------------------------------ */
.bench {{ display: flex; flex-direction: column; gap: 16px; }}
.deck-frame {{
  position: relative;
  width: 100%;
  border: 1px solid var(--sep);
  background: #000;
  overflow: hidden;
}}
.deck-scale {{ transform-origin: top left; }}
.deck-meta {{
  display: flex; flex-wrap: wrap; gap: 8px 22px; align-items: baseline;
  font-size: 11px; letter-spacing: 1.6px; text-transform: uppercase;
  color: var(--dim);
}}
.deck-meta b {{ color: var(--text); font-weight: 500; font-variant-numeric: tabular-nums; }}

/* ---- transport ---------------------------------------------------------- */
.transport {{ display: flex; align-items: center; gap: 16px; flex-wrap: wrap; }}
button.replay {{
  font-family: var(--body); font-size: 12px; font-weight: 600;
  letter-spacing: 2.4px; text-transform: uppercase;
  color: var(--bg); background: var(--accent);
  border: none; padding: 11px 22px; cursor: pointer;
}}
button.replay:hover {{ background: #C68CFA; }}
button.replay:focus-visible {{ outline: 2px solid var(--signal); outline-offset: 3px; }}
button.replay[disabled] {{ background: var(--sep); color: var(--dim); cursor: default; }}
.clock {{
  font-size: 12px; letter-spacing: 2px; color: var(--dim);
  font-variant-numeric: tabular-nums;
}}
.clock b {{ color: var(--accent); font-weight: 500; }}

/* ---- frise des actes : graduée en millisecondes réelles ----------------- */
.timeline {{ display: flex; flex-direction: column; gap: 0; }}
.track {{
  display: flex; width: 100%; position: relative;
  border: 1px solid var(--sep); background: var(--panel);
}}
.seg {{
  position: relative; min-width: 0;
  padding: 10px 8px 12px;
  border-right: 1px solid var(--sep);
  display: flex; flex-direction: column; gap: 2px;
  overflow: hidden;
}}
.seg:last-child {{ border-right: none; }}
.seg-num {{
  font-family: var(--display); font-size: 10px; font-weight: 700;
  color: var(--dim); letter-spacing: 0.5px;
}}
.seg-name {{
  font-size: 10px; letter-spacing: 1.3px; color: var(--text);
  white-space: nowrap; text-overflow: ellipsis; overflow: hidden;
}}
.seg-ms {{
  font-size: 10px; color: var(--dim); font-variant-numeric: tabular-nums;
}}
.seg.live {{ background: color-mix(in srgb, var(--accent) 18%, var(--panel)); }}
.seg.live .seg-num, .seg.live .seg-ms {{ color: var(--accent); }}
.playhead {{
  position: absolute; top: 0; bottom: 0; width: 2px;
  background: var(--signal); left: 0; opacity: 0;
  pointer-events: none;
}}
.playhead.on {{ opacity: 1; }}
.ticks {{
  display: flex; justify-content: space-between;
  font-size: 10px; letter-spacing: 1.4px; color: var(--dim);
  padding-top: 6px; font-variant-numeric: tabular-nums;
}}

/* ---- actes -------------------------------------------------------------- */
.acts {{ display: flex; flex-direction: column; }}
.act {{
  display: grid;
  grid-template-columns: 8px minmax(150px, 190px) 1fr;
  gap: 0 22px;
  padding: 22px 0;
  border-top: 1px solid var(--sep);
}}
.act:last-child {{ border-bottom: 1px solid var(--sep); }}
.act-rail {{ background: var(--sep); width: 2px; }}
.act.live .act-rail {{ background: var(--accent); }}
.act-id {{ display: flex; flex-direction: column; gap: 3px; }}
.act-num {{
  font-family: var(--display); font-size: 11px; font-weight: 700;
  color: var(--dim); letter-spacing: 1px;
}}
.act.live .act-num {{ color: var(--accent); }}
.act-name {{
  font-family: var(--display); font-size: 15px; font-weight: 600;
  letter-spacing: 1.4px; margin: 0; color: var(--text);
}}
.act-ms {{
  font-size: 19px; color: var(--accent); font-variant-numeric: tabular-nums;
  letter-spacing: 0.5px;
}}
.act-range {{ font-size: 11px; color: var(--dim); font-variant-numeric: tabular-nums; }}
.act-body {{ display: flex; flex-direction: column; gap: 10px; min-width: 0; }}
.act-what {{ margin: 0; color: var(--text); max-width: 62ch; }}
.act-how {{
  margin: 0; color: var(--dim); font-size: 13px; max-width: 62ch;
  padding-left: 14px; border-left: 1px solid var(--sep);
}}

/* ---- budget ------------------------------------------------------------- */
.budget {{ display: flex; flex-direction: column; gap: 12px; }}
.budget-bar {{
  position: relative; height: 34px; border: 1px solid var(--sep);
  background: var(--panel); display: flex; align-items: stretch;
}}
.budget-used {{ background: var(--accent); }}
.budget-rest {{
  flex: 1; display: flex; align-items: center; padding-left: 12px;
  font-size: 11px; letter-spacing: 1.8px; color: var(--dim);
  text-transform: uppercase;
}}
.budget-note {{ font-size: 13px; color: var(--dim); margin: 0; max-width: 64ch; }}
.budget-note b {{ color: var(--text); font-weight: 500; }}

/* ---- contrat ------------------------------------------------------------ */
.contract {{ display: flex; flex-direction: column; gap: 14px; }}
.contract ol {{
  margin: 0; padding: 0; list-style: none;
  display: flex; flex-direction: column; gap: 1px;
  background: var(--sep); border: 1px solid var(--sep);
}}
.contract li {{
  background: var(--panel); padding: 13px 16px;
  display: grid; grid-template-columns: minmax(140px, 210px) 1fr; gap: 6px 20px;
  font-size: 13px;
}}
.contract .cond {{ color: var(--signal); letter-spacing: 0.6px; }}
/* Le rose est réservé aux erreurs et à la saisie. La fin de séquence est ce
   que fait la machine : c'est de l'accent. */
.contract .cond.ok {{ color: var(--accent); }}
.contract .res {{ color: var(--dim); }}
.kicker {{
  font-family: var(--display); font-size: 13px; font-weight: 600;
  letter-spacing: 2.2px; text-transform: uppercase; color: var(--text);
  margin: 0;
}}

footer {{
  border-top: 1px solid var(--sep); padding-top: 20px;
  font-size: 11px; letter-spacing: 2.2px; text-transform: uppercase;
  color: var(--dim);
  display: flex; flex-wrap: wrap; gap: 8px 20px; justify-content: space-between;
}}

@media (max-width: 640px) {{
  .act {{ grid-template-columns: 4px 1fr; }}
  .act-body {{ grid-column: 2; }}
  .seg-name {{ display: none; }}
  .contract li {{ grid-template-columns: 1fr; }}
}}
@media (prefers-reduced-motion: reduce) {{
  .playhead {{ transition: none; }}
}}

/* ==========================================================================
   Feuille de style de l'animation, reprise telle quelle de
   boot-animation/index.html, recadrée dans #deck par build-boot-preview.py.
   ========================================================================== */
{anim_css}
</style>

<div class="wrap">

  <header class="masthead">
    <div class="eyebrow">GHOSTBOARD OS · séquence d'allumage</div>
    <h1>Le logotype ne s'affiche pas.<br>Il <em>s'assemble</em>.</h1>
    <p class="standfirst">
      Le seul moment spectaculaire de l'OS, en cinq actes et
      <strong>{total_s}&thinsp;s</strong>. Après quoi le contexte WebGL est détruit et
      plus une seule boucle GPU ne tourne sur la machine. Ci-dessous, la séquence
      réelle : cette page exécute le fichier <strong>boot.js</strong> du dépôt,
      pas une reconstitution.
    </p>
  </header>

  <section class="bench" aria-label="Animation d'allumage">
    <div class="deck-frame" id="deckFrame">
      <div class="deck-scale" id="deckScale">
        <div id="deck">
      {anim_markup}
        </div>
      </div>
    </div>

    <div class="transport">
      <button class="replay" id="replay" type="button">Rejouer la séquence</button>
      <div class="clock"><b id="clockMs">0</b> / {total_ms} ms &nbsp;·&nbsp;
        <span id="clockAct">au repos</span></div>
    </div>

    <div class="deck-meta">
      <span>Dalle <b>800 × 480</b></span>
      <span>Particules <b>{particles}</b> max</span>
      <span>Échantillonnées sur le <b>logotype rasterisé</b></span>
      <span>Garde-fou <b>{timeout} ms</b></span>
    </div>
  </section>

  <section class="timeline" aria-label="Chronologie des actes">
    <div class="track" id="track">
      {act_segments}
      <div class="playhead" id="playhead"></div>
    </div>
    <div class="ticks">
      <span>0 ms</span><span>{total_ms} ms</span>
    </div>
  </section>

  <section class="acts" aria-label="Détail des actes">
    {act_rows}
  </section>

  <section class="budget">
    <p class="kicker">Ce que ça coûte</p>
    <div class="budget-bar" role="img"
         aria-label="L'animation occupe {budget_pct} % du budget de démarrage de 20 secondes">
      <div class="budget-used" style="flex: 0 0 {budget_pct}%"></div>
      <div class="budget-rest">budget de boot — 20 s jusqu'au bureau utilisable</div>
    </div>
    <p class="budget-note">
      <b>{total_s} s sur 20 s, soit {budget_pct} %.</b> À quoi s'ajoute le démarrage de
      Chromium et l'analyse de three.js — mesuré à ~350 ms en rendu logiciel,
      moins sur l'iGPU du N100. Si c'est trop cher, <b>boot.enabled = false</b>
      dans la palette supprime l'animation sans rien casser d'autre.
    </p>
  </section>

  <section class="contract">
    <p class="kicker">Ce qui ne doit jamais arriver</p>
    <ol>
      <li><span class="cond">prefers-reduced-motion</span>
          <span class="res">Aucune particule, aucun WebGL. Logotype statique, puis la session s'ouvre.</span></li>
      <li><span class="cond">WebGL indisponible ou en échec</span>
          <span class="res">Capturé, journalisé, logotype statique. L'ouverture de session n'est jamais bloquée.</span></li>
      <li><span class="cond">Boucle de rendu calée</span>
          <span class="res">Le lanceur tue la fenêtre au garde-fou de {timeout} ms. Le bureau s'ouvre quand même.</span></li>
      <li><span class="cond ok">Fin de séquence</span>
          <span class="res">WEBGL_lose_context, tampons libérés, boucle arrêtée. Vérifié par ghost-bench : zéro client GPU après le boot.</span></li>
    </ol>
  </section>

  <footer>
    <span>{slogan}</span>
    <span>boot.js · three.js · 800 × 480</span>
  </footer>
</div>

<script src="{three_cdn}"></script>
<script>
  // Palette du système, injectée telle qu'elle est générée depuis
  // brand/palette.toml. Même source de vérité que le deck.
  window.GHOSTBOARD_THEME = {palette_json};
  // Mode aperçu : boot.js ne ferme pas la fenêtre et expose une reprise.
  window.GHOSTBOARD_BOOT_PREVIEW = true;
</script>
<script>
{boot_js}
</script>
<script>
(function () {{
  var TOTAL = window.GHOSTBOARD_BOOT_TOTAL_MS || {total_ms};
  var acts = window.GHOSTBOARD_BOOT_ACTS
    ? [acts_ms('ignite'), acts_ms('seek'), acts_ms('lock'), acts_ms('settle'), acts_ms('discharge')]
    : null;
  function acts_ms(k) {{ return window.GHOSTBOARD_BOOT_ACTS.MS[k]; }}
  if (!acts) acts = [220, 380, 620, 380, 200];

  var names = ['AMORÇAGE', 'RECHERCHE', 'VERROU', 'ASSISE', 'DÉCHARGE'];
  var bounds = [];
  var run = 0;
  for (var i = 0; i < acts.length; i++) {{ run += acts[i]; bounds.push(run); }}

  var deck = document.getElementById('deck');
  var frame = document.getElementById('deckFrame');
  var scaler = document.getElementById('deckScale');
  var replay = document.getElementById('replay');
  var playhead = document.getElementById('playhead');
  var clockMs = document.getElementById('clockMs');
  var clockAct = document.getElementById('clockAct');
  var segs = Array.prototype.slice.call(document.querySelectorAll('.seg'));
  var rows = Array.prototype.slice.call(document.querySelectorAll('.act'));

  // La dalle fait 800x480 : on la met à l'échelle du conteneur plutôt que de
  // redimensionner le rendu, pour que ce soit bien la géométrie du deck qui
  // s'affiche et pas une autre.
  function fit() {{
    var s = Math.min(1, frame.clientWidth / 800);
    scaler.style.transform = 'scale(' + s + ')';
    frame.style.height = Math.round(480 * s) + 'px';
  }}
  window.addEventListener('resize', fit);
  fit();

  function mark(idx) {{
    for (var i = 0; i < segs.length; i++) segs[i].classList.toggle('live', i === idx);
    for (var j = 0; j < rows.length; j++) rows[j].classList.toggle('live', j === idx);
    clockAct.textContent = idx >= 0 ? names[idx] : 'au repos';
  }}

  // La frise suit sa propre horloge, sur la même base que l'animation
  // (performance.now depuis le lancement). Elle n'interroge pas le rendu :
  // aucune donnée ne doit remonter du GPU pendant la séquence.
  var raf = null, t0 = 0;
  function tick() {{
    var ms = performance.now() - t0;
    var done = ms >= TOTAL;
    var clamped = Math.min(ms, TOTAL);
    clockMs.textContent = Math.round(clamped);
    playhead.style.left = (clamped / TOTAL * 100) + '%';
    var idx = 0;
    while (idx < bounds.length - 1 && clamped > bounds[idx]) idx++;
    mark(done ? -1 : idx);
    if (done) {{
      playhead.classList.remove('on');
      replay.disabled = false;
      restPoster();
      raf = null;
      return;
    }}
    raf = requestAnimationFrame(tick);
  }}

  // État de repos : le logotype statique reste à l'écran. Sur le deck, cet
  // instant est remplacé par l'ouverture de session ; sur un banc d'essai, un
  // cadre noir ne montrerait rien.
  function restPoster() {{
    var fb = deck.querySelector('#fallback');
    var tag = deck.querySelector('#tagline');
    if (fb) {{
      fb.style.background = 'transparent';
      var w = fb.querySelector('.wordmark');
      if (w) {{
        w.style.color = window.GHOSTBOARD_THEME.color.text;
        w.style.fontFamily = '"Martian Mono", "IBM Plex Mono", monospace';
      }}
      fb.classList.add('on');
    }}
    if (tag) {{
      tag.textContent = window.GHOSTBOARD_THEME.meta.slogan;
      tag.style.color = window.GHOSTBOARD_THEME.color.text_dim;
      tag.style.opacity = '0.8';
      tag.classList.add('on');
    }}
  }}

  function play() {{
    if (raf) cancelAnimationFrame(raf);
    replay.disabled = true;
    playhead.classList.add('on');
    var fb = deck.querySelector('#fallback');
    if (fb) fb.classList.remove('on');
    if (window.ghostboardBootReplay) window.ghostboardBootReplay();
    t0 = performance.now();
    raf = requestAnimationFrame(tick);
  }}

  replay.addEventListener('click', play);

  // boot.js se lance tout seul au chargement : on accroche la frise dessus.
  replay.disabled = true;
  playhead.classList.add('on');
  t0 = performance.now();
  raf = requestAnimationFrame(tick);
  window.addEventListener('ghostboard-boot-done', function () {{
    // Sécurité si la séquence se termine avant la frise (garde-fou, repli).
    if (!raf) {{ replay.disabled = false; restPoster(); }}
  }});
}})();
</script>
"""

if __name__ == "__main__":
    sys.exit(main())
