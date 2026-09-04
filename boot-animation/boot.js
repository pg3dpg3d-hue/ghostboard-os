/*
 * ============================================================================
 *  GHOSTBOARD OS — animation d'allumage (WebGL / three.js)
 * ============================================================================
 *  Le seul moment spectaculaire de l'OS. Cinq actes, ~1,8 s, puis le contexte
 *  WebGL est DÉTRUIT et plus une seule boucle ne tourne sur la machine.
 *
 *    1. AMORÇAGE   (220 ms)  Une ligne de balayage descend l'écran. Les
 *                            particules NAISSENT sur son passage — elles
 *                            n'existent pas avant. La dalle s'allume.
 *    2. RECHERCHE  (380 ms)  Dérive turbulente : les particules cherchent leur
 *                            place dans un champ de flux procédural.
 *    3. VERROU     (620 ms)  Les lettres se posent UNE PAR UNE, de gauche à
 *                            droite, chacune avec un éclat de verrouillage et
 *                            un décrochage de bandes horizontales.
 *    4. ASSISE     (380 ms)  Le filet d'accent se trace de gauche à droite,
 *                            le slogan s'écrit caractère par caractère.
 *    5. DÉCHARGE   (200 ms)  Onde de choc radiale, extinction, destruction.
 *
 *  Toutes les durées viennent de brand/palette.toml. Leur somme est vérifiée
 *  par `ghost-theme check` : les actes s'enchaînent sur une horloge normalisée
 *  unique, un écart décalerait tout.
 *
 *  Techniques employées, et pourquoi elles sont gratuites :
 *    - Particules échantillonnées sur le logotype RASTERISÉ à l'exécution :
 *      changer la police ou le mot ne demande aucun maillage.
 *    - Indice de lettre et détection de bord calculés au même passage : c'est
 *      ce qui permet le verrouillage lettre par lettre et l'aberration
 *      chromatique sur les contours, sans seconde texture.
 *    - Lueur par sprite additif, pas par post-traitement : un vrai bloom
 *      coûterait deux passes plein écran pour 1,8 s d'affichage.
 *    - Turbulence, décrochage et onde de choc entièrement dans le vertex
 *      shader : aucune donnée ne remonte au CPU pendant l'animation.
 *
 *  Mode aperçu : si window.GHOSTBOARD_BOOT_PREVIEW est vrai, la page ne se
 *  ferme pas et expose window.ghostboardBootReplay(). C'est ce qui permet à la
 *  page de présentation de rejouer EXACTEMENT ce fichier, sans copie.
 * ============================================================================
 */
import * as THREE from './vendor/three.module.min.js';

window.__ghostboardStarted = true;

const PREVIEW = !!window.GHOSTBOARD_BOOT_PREVIEW;

// ---------------------------------------------------------------------------
//  Thème — injecté par palette.js, généré depuis brand/palette.toml.
//  Les valeurs en dur ne sont qu'un filet si le fichier manque.
// ---------------------------------------------------------------------------
const T = window.GHOSTBOARD_THEME || {};
const C = T.color || {};
const BOOT = T.boot || {};
const LAYOUT = T.layout || {};
const FONT = T.font || {};
const META = T.meta || {};

const COLOR = {
  bg: C.bg || '#08070C',
  panel: C.panel || '#14111C',
  accent: C.accent || '#A855F7',
  input: C.input || '#FF4D8D',
  text: C.text || '#D6D2E0',
  dim: C.text_dim || '#6E6880',
};

// --- les cinq actes, en millisecondes puis en fractions de l'horloge globale
const MS = {
  ignite: BOOT.ignite_ms ?? 220,
  seek: BOOT.seek_ms ?? 380,
  lock: BOOT.lock_ms ?? 620,
  settle: BOOT.settle_ms ?? 380,
  discharge: BOOT.discharge_ms ?? 200,
};
const TOTAL = MS.ignite + MS.seek + MS.lock + MS.settle + MS.discharge;

// Bornes normalisées : tout le shader raisonne en 0..1, jamais en millisecondes.
const ACT = {
  igniteEnd: MS.ignite / TOTAL,
  seekEnd: (MS.ignite + MS.seek) / TOTAL,
  lockStart: (MS.ignite + MS.seek) / TOTAL,
  lockEnd: (MS.ignite + MS.seek + MS.lock) / TOTAL,
  settleStart: (MS.ignite + MS.seek + MS.lock) / TOTAL,
  settleEnd: (MS.ignite + MS.seek + MS.lock + MS.settle) / TOTAL,
  dischargeStart: (MS.ignite + MS.seek + MS.lock + MS.settle) / TOTAL,
};

const COUNT = BOOT.particle_count ?? 20000;
const WORDMARK = META.name || 'GHOSTBOARD';
const SLOGAN = META.slogan || 'CUSTOM HARDWARE. READY TO EXPLORE.';
const DISPLAY_FONT = FONT.display || 'Martian Mono';
const UI_FONT = FONT.ui || 'IBM Plex Mono';

const stage = document.getElementById('stage');
const tagline = document.getElementById('tagline');
const fallback = document.getElementById('fallback');
const scanline = document.getElementById('scanline');
const readout = document.getElementById('readout');

// ---------------------------------------------------------------------------
//  Replis
// ---------------------------------------------------------------------------
function paintStaticFallback() {
  document.body.style.background = COLOR.bg;
  const mark = fallback.querySelector('.wordmark');
  mark.style.color = COLOR.text;
  mark.style.fontFamily = `"${DISPLAY_FONT}", "${UI_FONT}", monospace`;
  fallback.classList.add('on');
  tagline.textContent = SLOGAN;
  tagline.style.color = COLOR.dim;
  tagline.style.bottom = Math.round((LAYOUT.screen_h || 480) * 0.24) + 'px';
  tagline.classList.add('on');
}

let finished = false;
/** Sortie propre. C'est le seul chemin de sortie de ce script. */
function finish(disposeFn) {
  if (finished) return;
  finished = true;
  try { if (disposeFn) disposeFn(); } catch (e) { /* on sort quoi qu'il arrive */ }
  if (PREVIEW) {
    window.dispatchEvent(new CustomEvent('ghostboard-boot-done'));
    return;
  }
  // Le lanceur tue de toute façon la fenêtre : window.close() ne fait
  // qu'accélérer, il n'est jamais la seule garantie.
  try { window.close(); } catch (e) { /* ignoré */ }
}

function reducedMotion() {
  return window.matchMedia
    && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
}

// ---------------------------------------------------------------------------
//  Échantillonnage du logotype
//  Un seul passage produit, pour chaque pixel opaque : sa position, la LETTRE
//  à laquelle il appartient (verrouillage lettre par lettre) et s'il est sur
//  un BORD de glyphe (aberration chromatique des contours).
// ---------------------------------------------------------------------------
function sampleWordmark(width, height) {
  const cv = document.createElement('canvas');
  cv.width = width;
  cv.height = height;
  const ctx = cv.getContext('2d', { willReadFrequently: true });

  // Taille de police ajustée pour occuper ~78 % de la largeur de la dalle.
  let size = Math.round(height * 0.20);
  const targetW = width * 0.78;
  ctx.textBaseline = 'middle';
  for (let i = 0; i < 12; i++) {
    ctx.font = `600 ${size}px "${DISPLAY_FONT}", "${UI_FONT}", monospace`;
    const w = ctx.measureText(WORDMARK).width + size * 0.14 * (WORDMARK.length - 1);
    if (Math.abs(w - targetW) < 4) break;
    size = Math.max(8, Math.round(size * (targetW / Math.max(w, 1))));
  }

  ctx.fillStyle = '#fff';
  ctx.font = `600 ${size}px "${DISPLAY_FONT}", "${UI_FONT}", monospace`;
  ctx.textAlign = 'left';

  // Crénage manuel : le logotype est espacé, comme sur le fond d'écran.
  const tracking = size * 0.14;
  const letters = WORDMARK.split('');
  const widths = letters.map((ch) => ctx.measureText(ch).width);
  const totalW = widths.reduce((a, b) => a + b, 0) + tracking * (letters.length - 1);
  const baseY = height * 0.46;

  // Bornes horizontales par lettre : c'est ce qui donne l'indice de lettre.
  const bounds = [];
  let x = width / 2 - totalW / 2;
  for (let i = 0; i < letters.length; i++) {
    ctx.fillText(letters[i], x, baseY);
    bounds.push([x - tracking * 0.5, x + widths[i] + tracking * 0.5]);
    x += widths[i] + tracking;
  }

  // Filet d'accent : mêmes particules, mais verrouillé à l'acte 4.
  const ruleW = Math.round(totalW);
  const ruleX = Math.round(width / 2 - ruleW / 2);
  const ruleY = Math.round(baseY + size * 0.78);
  ctx.fillRect(ruleX, ruleY, ruleW, 2);

  const data = ctx.getImageData(0, 0, width, height).data;
  const alphaAt = (px, py) =>
    (px < 0 || py < 0 || px >= width || py >= height)
      ? 0 : data[(py * width + px) * 4 + 3];

  const pts = [];
  for (let py = 0; py < height; py++) {
    for (let px = 0; px < width; px++) {
      if (alphaAt(px, py) <= 128) continue;
      // Bord = au moins un voisin transparent. Deux lignes, aucun coût réel,
      // et ça donne des contours qui virent au rose pendant le vol.
      const edge = (alphaAt(px - 1, py) <= 128 || alphaAt(px + 1, py) <= 128
                 || alphaAt(px, py - 1) <= 128 || alphaAt(px, py + 1) <= 128) ? 1 : 0;
      let letter = -1;                      // -1 = filet d'accent
      if (py < ruleY - 2) {
        for (let i = 0; i < bounds.length; i++) {
          if (px >= bounds[i][0] && px < bounds[i][1]) { letter = i; break; }
        }
        if (letter === -1) letter = 0;      // pixel hors borne : rattaché au début
      }
      pts.push(px, py, letter, edge);
    }
  }
  return {
    pts, count: pts.length / 4, fontSize: size,
    letterCount: letters.length, ruleY, ruleX, ruleW,
  };
}

// ---------------------------------------------------------------------------
//  Habillage DOM — ligne de balayage, relevé technique, slogan.
//  Volontairement hors WebGL : du texte net et une ligne franche coûtent moins
//  cher en DOM qu'en particules, et restent lisibles sur une dalle de 4 pouces.
// ---------------------------------------------------------------------------
function setupOverlays(W, H) {
  scanline.style.background =
    `linear-gradient(90deg, transparent, ${COLOR.accent}, ${COLOR.input}, ${COLOR.accent}, transparent)`;
  // Lueur portée : c'est ce qui fait lire la ligne comme une DÉCHARGE et non
  // comme un filet de mise en page. Elle disparaît avec elle à la fin de l'acte 1.
  scanline.style.boxShadow = `0 0 14px ${COLOR.accent}, 0 0 4px ${COLOR.input}`;
  scanline.style.opacity = '0';

  if (BOOT.readout !== false) {
    const lines = [
      META.os_name || 'GHOSTBOARD OS',
      `${W}x${H} · ${(LAYOUT.screen_w || 800) === W ? 'NATIVE' : 'SCALED'}`,
      'CLOUD REASONING · LOCAL CONTROL',
    ];
    readout.innerHTML = lines
      .map((l) => `<div class="line">${l}</div>`).join('');
    readout.style.color = COLOR.dim;
    readout.style.fontFamily = `"${UI_FONT}", monospace`;
  }

  tagline.style.color = COLOR.dim;
  tagline.style.bottom = Math.round(H * 0.24) + 'px';
  tagline.textContent = '';
}

/** Le slogan s'écrit. Un fondu aurait été plus doux — et beaucoup moins juste
 *  pour une marque dont l'outil principal est un terminal. */
function typeTagline(progress) {
  if (BOOT.tagline === false) return;
  const n = Math.floor(progress * SLOGAN.length);
  const shown = SLOGAN.slice(0, n);
  // Curseur bloc pendant la frappe, retiré une fois la ligne complète.
  tagline.textContent = n < SLOGAN.length ? shown + '█' : SLOGAN;
  tagline.classList.add('on');
}

// ---------------------------------------------------------------------------
//  Lancement
// ---------------------------------------------------------------------------
let activeDispose = null;

function boot() {
  if (reducedMotion()) {
    paintStaticFallback();
    setTimeout(() => finish(null), Math.min(600, TOTAL));
    return;
  }
  try {
    activeDispose = run();
  } catch (err) {
    console.error('[ghostboard-boot] rendu impossible :', err);
    paintStaticFallback();
    setTimeout(() => finish(null), Math.min(600, TOTAL));
  }
}

function run() {
  const W = LAYOUT.screen_w || window.innerWidth || 800;
  const H = LAYOUT.screen_h || window.innerHeight || 480;

  const sample = sampleWordmark(W, H);
  if (sample.count < 200) throw new Error('logotype non rasterisable');
  console.log(`[ghostboard-boot] logotype : ${sample.count} px échantillonnés, `
    + `police ${sample.fontSize}px, ${sample.letterCount} lettres`);

  setupOverlays(W, H);

  const renderer = new THREE.WebGLRenderer({
    antialias: false,          // inutile pour des sprites additifs, coûteux
    alpha: false,
    powerPreference: 'high-performance',
    failIfMajorPerformanceCaveat: false,
  });
  // Résolution native, ratio 1 : chaque pixel rendu en trop est du watt perdu.
  renderer.setPixelRatio(1);
  renderer.setSize(W, H, false);
  renderer.setClearColor(new THREE.Color(COLOR.bg), 1);
  stage.appendChild(renderer.domElement);

  // Caméra orthographique en unités « pixel » : le logotype tombe pile sur la
  // grille de la dalle, sans flou de reprojection.
  const camera = new THREE.OrthographicCamera(-W / 2, W / 2, H / 2, -H / 2, -3000, 3000);
  const scene = new THREE.Scene();

  // ---- attributs -----------------------------------------------------------
  const n = Math.min(COUNT, sample.count);
  const stride = sample.count / n;
  const target = new Float32Array(n * 3);
  const birthPos = new Float32Array(n * 3);
  const scatter = new Float32Array(n * 3);
  const colors = new Float32Array(n * 3);
  const seed = new Float32Array(n);
  const birth = new Float32Array(n);
  const lockStart = new Float32Array(n);
  const lockDur = new Float32Array(n);

  const cAccent = new THREE.Color(COLOR.accent);
  const cInput = new THREE.Color(COLOR.input);
  const cText = new THREE.Color(COLOR.text);
  const cEdge = new THREE.Color(COLOR.accent).lerp(new THREE.Color(COLOR.input), 0.40);

  for (let i = 0; i < n; i++) {
    const src = Math.floor(i * stride) * 4;
    const px = sample.pts[src];
    const py = sample.pts[src + 1];
    const letter = sample.pts[src + 2];
    const isEdge = sample.pts[src + 3] === 1;
    const isRule = letter < 0;

    const tx = px - W / 2;
    const ty = H / 2 - py;
    target[i * 3] = tx;
    target[i * 3 + 1] = ty;
    target[i * 3 + 2] = 0;

    // ACTE 1 — naissance sur la ligne de balayage : la particule apparaît à
    // SA hauteur finale, mais n'importe où en x. Le balayage « révèle » donc
    // la bande horizontale où elle vit avant qu'elle ne trouve sa colonne.
    birthPos[i * 3] = (Math.random() - 0.5) * W * 1.15;
    birthPos[i * 3 + 1] = ty + (Math.random() - 0.5) * 5;
    birthPos[i * 3 + 2] = (Math.random() - 0.5) * 90;

    // ACTE 2 — ancre de dérive : un nuage large et profond vers lequel la
    // particule s'éloigne avant d'être rappelée.
    const ang = Math.random() * Math.PI * 2;
    // pow(r, 0.6) concentre vers le centre : une nébuleuse a un coeur, une
    // distribution uniforme n'en a pas et ressemble à du bruit.
    const rad = 130 + Math.pow(Math.random(), 0.6) * 360;
    scatter[i * 3] = Math.cos(ang) * rad * 0.95;
    scatter[i * 3 + 1] = Math.sin(ang) * rad * 0.42;   // aplati, comme le mot
    scatter[i * 3 + 2] = (Math.random() - 0.5) * 1900; // profondeur creusée

    seed[i] = Math.random() * 6.2831;
    // Naissance étalée sur l'acte 1. 40 % de l'ordre vient de la hauteur
    // finale (le balayage garde son sens de lecture haut -> bas), 60 % est
    // aléatoire : sans ça la ligne traverse 480 px en n'émettant que sur la
    // bande de 100 px qu'occupe le logotype, et les 3/4 du balayage sont vides.
    birth[i] = (0.4 * (py / H) + 0.6 * Math.random()) * ACT.igniteEnd;

    if (isRule) {
      // ACTE 4 — le filet se trace de gauche à droite.
      const xNorm = (px - sample.ruleX) / Math.max(sample.ruleW, 1);
      lockStart[i] = ACT.settleStart + xNorm * (ACT.settleEnd - ACT.settleStart) * 0.55;
      lockDur[i] = (ACT.settleEnd - ACT.settleStart) * 0.35;
    } else {
      // ACTE 3 — une lettre après l'autre. L'étalement occupe 60 % de l'acte,
      // le reste laisse à la dernière lettre le temps de se poser.
      const span = ACT.lockEnd - ACT.lockStart;
      lockStart[i] = ACT.lockStart
        + (letter / Math.max(sample.letterCount, 1)) * span * 0.6
        + Math.random() * span * 0.05;
      lockDur[i] = span * 0.4;
    }

    // Une seule couleur d'accent domine. Les bords virent vers le rose : c'est
    // une aberration chromatique, pas une seconde couleur de marque.
    let col = cAccent;
    const r = Math.random();
    if (isRule) col = cAccent;
    else if (isEdge && r < 0.45) col = cEdge;
    else if (r < 0.04) col = cInput;
    else if (r < 0.13) col = cText;
    colors[i * 3] = col.r;
    colors[i * 3 + 1] = col.g;
    colors[i * 3 + 2] = col.b;
  }

  const geometry = new THREE.BufferGeometry();
  geometry.setAttribute('position', new THREE.BufferAttribute(target, 3));
  geometry.setAttribute('aBirthPos', new THREE.BufferAttribute(birthPos, 3));
  geometry.setAttribute('aScatter', new THREE.BufferAttribute(scatter, 3));
  geometry.setAttribute('aColor', new THREE.BufferAttribute(colors, 3));
  geometry.setAttribute('aSeed', new THREE.BufferAttribute(seed, 1));
  geometry.setAttribute('aBirth', new THREE.BufferAttribute(birth, 1));
  geometry.setAttribute('aLockStart', new THREE.BufferAttribute(lockStart, 1));
  geometry.setAttribute('aLockDur', new THREE.BufferAttribute(lockDur, 1));

  const sprite = makeSpriteTexture();

  const material = new THREE.ShaderMaterial({
    uniforms: {
      uT: { value: 0 },            // horloge normalisée 0..1 sur toute la séquence
      uTime: { value: 0 },         // secondes, pour la turbulence
      uGlitch: { value: 0 },
      uDischarge: { value: 0 },
      uOpacity: { value: 1 },
      uSize: { value: 3.0 },
      uMap: { value: sprite },
      uScanY: { value: 0 },        // position de la ligne de balayage, en unités monde
      uSeekEnd: { value: ACT.seekEnd },
    },
    transparent: true,
    depthTest: false,
    depthWrite: false,
    blending: THREE.AdditiveBlending,
    vertexShader: `
      attribute vec3  aBirthPos;
      attribute vec3  aScatter;
      attribute vec3  aColor;
      attribute float aSeed;
      attribute float aBirth;
      attribute float aLockStart;
      attribute float aLockDur;

      uniform float uT, uTime, uGlitch, uDischarge, uSize, uScanY, uSeekEnd;

      varying vec3  vColor;
      varying float vLock;    // 0 en vol, 1 posée
      varying float vFlash;   // éclat au moment du verrouillage
      varying float vAlive;
      varying float vDepthFade;

      float hash(float x) { return fract(sin(x * 78.233) * 43758.5453); }

      // Champ de flux à deux octaves. Pas du vrai bruit de Perlin : des
      // sinus déphasés suffisent à donner un mouvement qui ne se répète pas
      // à l'oeil sur 400 ms, pour un coût dérisoire.
      vec3 flow(vec3 p, float t, float s) {
        float a = sin(p.y * 0.012 + t * 1.7 + s) + 0.5 * sin(p.y * 0.031 - t * 2.6 + s * 1.7);
        float b = cos(p.x * 0.010 - t * 1.4 + s * 2.1) + 0.5 * cos(p.x * 0.027 + t * 3.1 + s);
        float c = sin((p.x + p.y) * 0.008 + t * 1.1 + s * 3.3);
        return vec3(a, b, c);
      }

      void main() {
        // ---- ACTE 1 : la particule n'existe pas avant son heure -------------
        vAlive = step(aBirth, uT);

        // ---- ACTE 2 : dérive de la naissance vers l'ancre de recherche ------
        float drift = clamp((uT - aBirth) / max(aLockStart - aBirth, 0.001), 0.0, 1.0);
        vec3 wander = mix(aBirthPos, aScatter, smoothstep(0.0, 1.0, drift));

        // ---- ACTE 3/4 : verrouillage, easeOutExpo. Arrivée franche, pas de
        //                 rebond : le mot se POSE, il ne flotte pas. ---------
        float lockP = clamp((uT - aLockStart) / max(aLockDur, 0.001), 0.0, 1.0);
        float e = lockP >= 1.0 ? 1.0 : 1.0 - pow(2.0, -11.0 * lockP);
        vec3 pos = mix(wander, position, e);
        float rest = 1.0 - e;

        // Turbulence, amortie à mesure que la particule se pose.
        pos += flow(pos, uTime, aSeed) * vec3(16.0, 13.0, 130.0) * rest;

        // Décrochage par bandes horizontales : la seule vraie touche « hack ».
        // Il pulse au moment des verrouillages puis disparaît complètement.
        float band = floor((pos.y + 260.0) / 7.0);
        float jolt = step(0.86, hash(band + floor(uTime * 26.0)));
        pos.x += jolt * uGlitch * (hash(band) - 0.5) * 52.0;

        // ---- ACTE 5 : onde de choc radiale ----------------------------------
        vec2 dir = normalize(position.xy + vec2(0.0001));
        pos.xy += dir * uDischarge * (26.0 + hash(aSeed) * 46.0);
        pos.z += uDischarge * (hash(aSeed * 2.3) - 0.5) * 220.0;

        vColor = aColor;
        vLock = e;
        // Éclat centré sur la fin du verrouillage, très bref.
        vFlash = exp(-26.0 * abs(lockP - 0.88)) * step(0.35, lockP);

        // Attraction visuelle vers la ligne de balayage à la naissance : la
        // particule « sort » de la ligne au lieu d'apparaître de nulle part.
        float born = smoothstep(aBirth, aBirth + 0.022, uT);
        pos.y = mix(uScanY, pos.y, born);

        vec4 mv = modelViewMatrix * vec4(pos, 1.0);
        gl_Position = projectionMatrix * mv;

        // Profondeur simulée : loin = plus gros et plus diffus (bokeh pauvre),
        // proche et posé = petit et net. C'est ce qui donne le relief.
        float depth = 1.0 + abs(pos.z) * 0.0016;
        // Loin = plus gros ET plus faible : c'est ce couple qui fait la
        // profondeur de champ. La taille seule ne donne qu'un aplat plus épais.
        vDepthFade = 1.0 - clamp(abs(pos.z) / 1500.0, 0.0, 0.78);
        gl_PointSize = uSize * (1.0 + rest * 1.2) * depth * vAlive;
      }
    `,
    fragmentShader: `
      uniform sampler2D uMap;
      uniform float uOpacity;
      varying vec3  vColor;
      varying float vLock;
      varying float vFlash;
      varying float vAlive;
      varying float vDepthFade;

      void main() {
        if (vAlive < 0.5) discard;
        float a = texture2D(uMap, gl_PointCoord).a;
        if (a < 0.02) discard;

        // La teinte ne quitte JAMAIS l'accent de la palette : multiplier
        // au-delà de 1.0 écrête le bleu et fait virer le violet au rose.
        // La luminosité vient de la densité et d'un coeur blanc localisé.
        float core = pow(a, 4.0) * vLock;
        vec3 col = vColor * (0.30 + 0.70 * vLock)
                 + vec3(0.24) * core
                 + vColor * vFlash * 1.6;   // éclat de verrouillage

        // Trame horizontale très faible : une texture de dalle, pas un effet.
        float scan = 0.93 + 0.07 * sin(gl_FragCoord.y * 3.14159);

        gl_FragColor = vec4(col * scan, a * uOpacity * vDepthFade);
      }
    `,
  });

  const points = new THREE.Points(geometry, material);
  scene.add(points);

  function dispose() {
    renderer.setAnimationLoop(null);
    geometry.dispose();
    material.dispose();
    sprite.dispose();
    scene.remove(points);
    scene.clear();
    renderer.dispose();
    // Destruction explicite du contexte : sans ça le pilote garde le GPU
    // réveillé et on paie une boucle après le boot. C'est tout l'enjeu.
    const gl = renderer.getContext();
    const lose = gl && gl.getExtension('WEBGL_lose_context');
    if (lose) lose.loseContext();
    if (renderer.domElement.parentNode) renderer.domElement.remove();
    // Écran net avant la bascule vers la session : pas de rémanence.
    scanline.style.opacity = '0';
    readout.classList.remove('on');
    tagline.classList.remove('on');
    tagline.style.opacity = '0';
    document.body.style.background = COLOR.bg;
  }

  // ---- boucle --------------------------------------------------------------
  const t0 = performance.now();
  let frames = 0;

  renderer.setAnimationLoop(() => {
    const ms = performance.now() - t0;
    const t = Math.min(ms / TOTAL, 1);
    frames++;

    material.uniforms.uT.value = t;
    material.uniforms.uTime.value = ms / 1000;

    // ACTE 1 — la ligne de balayage descend, puis s'éteint.
    const ignite = Math.min(t / ACT.igniteEnd, 1);
    const scanPx = ignite * H;
    material.uniforms.uScanY.value = H / 2 - scanPx;
    if (t < ACT.igniteEnd * 1.25) {
      scanline.style.transform = `translateY(${scanPx.toFixed(1)}px)`;
      scanline.style.opacity = String(Math.max(0, 1 - Math.max(0, t / ACT.igniteEnd - 1) * 4));
    } else if (scanline.style.opacity !== '0') {
      scanline.style.opacity = '0';
    }

    // ACTE 2 — le relevé technique apparaît, puis s'efface au verrouillage.
    if (BOOT.readout !== false) {
      const readoutEnd = ACT.igniteEnd + (ACT.seekEnd - ACT.igniteEnd) * 0.45;
      if (t > ACT.igniteEnd * 0.3 && t < readoutEnd) readout.classList.add('on');
      else if (t >= readoutEnd) readout.classList.remove('on');
    }

    // ACTE 3 — le décrochage ne vit que pendant le verrouillage des lettres,
    // et décroît : il souligne l'action, il ne décore pas.
    if (t >= ACT.lockStart && t < ACT.lockEnd) {
      const p = (t - ACT.lockStart) / (ACT.lockEnd - ACT.lockStart);
      material.uniforms.uGlitch.value = (1 - p) * (0.55 + 0.45 * Math.abs(Math.sin(p * 18.0)));
    } else {
      material.uniforms.uGlitch.value = t < ACT.lockStart ? 0.35 : 0;
    }

    // ACTE 4 — le slogan s'écrit.
    if (t >= ACT.settleStart) {
      const p = Math.min((t - ACT.settleStart) / ((ACT.settleEnd - ACT.settleStart) * 0.8), 1);
      typeTagline(p);
    }

    // ACTE 5 — décharge et extinction.
    if (t >= ACT.dischargeStart) {
      const p = Math.min((t - ACT.dischargeStart) / (1 - ACT.dischargeStart), 1);
      material.uniforms.uDischarge.value = p * p;
      material.uniforms.uOpacity.value = 1 - p;
      tagline.style.opacity = String(1 - p);
    }

    renderer.render(scene, camera);

    if (ms >= TOTAL) {
      const fps = Math.round(frames / (ms / 1000));
      console.log(`[ghostboard-boot] ${frames} images en ${Math.round(ms)} ms `
        + `(~${fps} i/s), contexte détruit`);
      finish(dispose);
    }
  });

  // Garde-fou : si la boucle cale (pilote, veille, GPU absent), on sort quand
  // même. Rien ne doit retarder l'ouverture de session.
  setTimeout(() => finish(dispose), (BOOT.timeout_ms ?? 4500));
  return dispose;
}

/** Sprite radial 32x32 en mémoire — la lueur, sans passe de post-traitement. */
function makeSpriteTexture() {
  const s = 32;
  const cv = document.createElement('canvas');
  cv.width = cv.height = s;
  const ctx = cv.getContext('2d');
  const g = ctx.createRadialGradient(s / 2, s / 2, 0, s / 2, s / 2, s / 2);
  g.addColorStop(0.0, 'rgba(255,255,255,1)');
  g.addColorStop(0.26, 'rgba(255,255,255,0.92)');
  g.addColorStop(0.48, 'rgba(255,255,255,0.20)');
  g.addColorStop(1.0, 'rgba(255,255,255,0)');
  ctx.fillStyle = g;
  ctx.fillRect(0, 0, s, s);
  const tex = new THREE.CanvasTexture(cv);
  tex.minFilter = THREE.LinearFilter;
  tex.magFilter = THREE.LinearFilter;
  tex.generateMipmaps = false;
  return tex;
}

// ---------------------------------------------------------------------------
//  Mode aperçu : rejouer sans recharger. Sert à la page de présentation, qui
//  exécute CE fichier — il n'existe pas de seconde version de l'animation.
// ---------------------------------------------------------------------------
if (PREVIEW) {
  window.ghostboardBootReplay = function replay() {
    try { if (activeDispose) activeDispose(); } catch (e) { /* ignoré */ }
    finished = false;
    activeDispose = null;
    stage.innerHTML = '';
    fallback.classList.remove('on');
    tagline.classList.remove('on');
    tagline.style.opacity = '';
    tagline.textContent = '';
    readout.classList.remove('on');
    scanline.style.opacity = '0';
    boot();
  };
  window.GHOSTBOARD_BOOT_TOTAL_MS = TOTAL;
  window.GHOSTBOARD_BOOT_ACTS = { MS, ACT, TOTAL };
}

boot();
