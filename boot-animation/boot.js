/*
 * GHOSTBOARD OS — animation d'allumage (WebGL / three.js)
 *
 * Le logotype GHOSTBOARD se condense depuis un nuage de particules, tient
 * ~250 ms, puis disparaît. Durée totale pilotée par brand/palette.toml.
 *
 * Règle non négociable : à la fin, le contexte WebGL est DÉTRUIT
 * (`WEBGL_lose_context`) et la boucle de rendu arrêtée. Aucune boucle GPU ne
 * doit survivre au boot — c'est une cible de performance, pas une préférence.
 *
 * Les positions cibles des particules sont échantillonnées à l'exécution
 * depuis le logotype rasterisé : changer la police ou le texte dans la palette
 * suffit, il n'y a pas de maillage à régénérer.
 */
import * as THREE from './vendor/three.module.min.js';

window.__ghostboardStarted = true;

// ---------------------------------------------------------------------------
//  Thème — injecté par palette.js, lui-même généré depuis brand/palette.toml.
//  Les valeurs en dur ici ne sont qu'un filet si le fichier manque.
// ---------------------------------------------------------------------------
const T = window.GHOSTBOARD_THEME || {};
const C = T.color || {};
const BOOT = T.boot || {};
const LAYOUT = T.layout || {};
const FONT = T.font || {};

const COLOR = {
  bg: C.bg || '#08070C',
  accent: C.accent || '#A855F7',
  input: C.input || '#FF4D8D',
  text: C.text || '#D6D2E0',
  dim: C.text_dim || '#6E6880',
};
const CONVERGE = BOOT.converge_ms ?? 950;
const HOLD = BOOT.hold_ms ?? 250;
const FADEOUT = BOOT.fadeout_ms ?? 200;
const TOTAL = CONVERGE + HOLD + FADEOUT;
const COUNT = BOOT.particle_count ?? 9000;
const WORDMARK = (T.meta && T.meta.name) || 'GHOSTBOARD';
const DISPLAY_FONT = FONT.display || 'Martian Mono';
const UI_FONT = FONT.ui || 'IBM Plex Mono';

const stage = document.getElementById('stage');
const tagline = document.getElementById('tagline');
const fallback = document.getElementById('fallback');

// ---------------------------------------------------------------------------
//  Replis
// ---------------------------------------------------------------------------
function paintStaticFallback() {
  fallback.style.background = COLOR.bg;
  fallback.querySelector('.wordmark').style.color = COLOR.text;
  fallback.querySelector('.wordmark').style.fontFamily =
    `"${DISPLAY_FONT}", "${UI_FONT}", monospace`;
  fallback.classList.add('on');
  showTagline();
}

function showTagline() {
  if (BOOT.tagline === false) return;
  tagline.style.color = COLOR.dim;
  tagline.style.bottom = Math.round((LAYOUT.screen_h || 480) * 0.24) + 'px';
  tagline.classList.add('on');
}

/** Sortie propre : c'est le seul chemin de sortie de ce script. */
let finished = false;
function finish(disposeFn) {
  if (finished) return;
  finished = true;
  try { if (disposeFn) disposeFn(); } catch (e) { /* on sort quoi qu'il arrive */ }
  // Le lanceur tue de toute façon la fenêtre : window.close() ne fait
  // qu'accélérer, il n'est jamais la seule garantie.
  try { window.close(); } catch (e) { /* ignoré */ }
}

// prefers-reduced-motion : pas de particules, pas de WebGL, pas de discussion.
if (window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches) {
  document.body.style.background = COLOR.bg;
  paintStaticFallback();
  setTimeout(() => finish(null), HOLD + FADEOUT);
} else {
  try {
    run();
  } catch (err) {
    console.error('[ghostboard-boot] rendu impossible :', err);
    paintStaticFallback();
    setTimeout(() => finish(null), HOLD + FADEOUT);
  }
}

// ---------------------------------------------------------------------------
//  Échantillonnage du logotype
//  On rasterise le mot une fois dans un canvas 2D, puis on garde les pixels
//  opaques comme positions cibles. Coût : ~5 ms, une seule fois.
// ---------------------------------------------------------------------------
function sampleWordmark(width, height) {
  const cv = document.createElement('canvas');
  cv.width = width;
  cv.height = height;
  const ctx = cv.getContext('2d', { willReadFrequently: true });

  // Taille de police ajustée pour occuper ~78 % de la largeur de la dalle.
  let size = Math.round(height * 0.20);
  const target = width * 0.78;
  ctx.textBaseline = 'middle';
  ctx.textAlign = 'center';
  for (let i = 0; i < 12; i++) {
    ctx.font = `600 ${size}px "${DISPLAY_FONT}", "${UI_FONT}", monospace`;
    const w = ctx.measureText(WORDMARK).width + size * 0.14 * (WORDMARK.length - 1);
    if (Math.abs(w - target) < 4) break;
    size = Math.max(8, Math.round(size * (target / Math.max(w, 1))));
  }

  ctx.fillStyle = '#fff';
  ctx.font = `600 ${size}px "${DISPLAY_FONT}", "${UI_FONT}", monospace`;
  // Crénage manuel : le logotype est espacé, comme sur le fond d'écran.
  const tracking = size * 0.14;
  const letters = WORDMARK.split('');
  const widths = letters.map((ch) => ctx.measureText(ch).width);
  const totalW = widths.reduce((a, b) => a + b, 0) + tracking * (letters.length - 1);
  let x = width / 2 - totalW / 2;
  const y = height * 0.46;
  ctx.textAlign = 'left';
  for (let i = 0; i < letters.length; i++) {
    ctx.fillText(letters[i], x, y);
    x += widths[i] + tracking;
  }

  // Filet d'accent sous le mot : même traitement, c'est aussi des particules.
  const ruleW = totalW * 0.999;
  const ruleY = Math.round(y + size * 0.78);
  ctx.fillRect(Math.round(width / 2 - ruleW / 2), ruleY, Math.round(ruleW), 2);

  const data = ctx.getImageData(0, 0, width, height).data;
  const pts = [];
  // Pas d'échantillonnage : 1 px suffit à 800x480, on décime ensuite.
  for (let py = 0; py < height; py++) {
    for (let px = 0; px < width; px++) {
      if (data[(py * width + px) * 4 + 3] > 128) {
        pts.push(px, py, py >= ruleY ? 1 : 0); // 3e valeur : 1 = filet d'accent
      }
    }
  }
  return { pts, count: pts.length / 3, fontSize: size };
}

// ---------------------------------------------------------------------------
//  Scène
// ---------------------------------------------------------------------------
function run() {
  const W = LAYOUT.screen_w || window.innerWidth || 800;
  const H = LAYOUT.screen_h || window.innerHeight || 480;

  const sample = sampleWordmark(W, H);
  if (sample.count < 200) throw new Error('logotype non rasterisable');
  console.log(`[ghostboard-boot] logotype : ${sample.count} pixels échantillonnés, `
    + `police ${sample.fontSize}px`);

  const renderer = new THREE.WebGLRenderer({
    antialias: false,          // inutile pour des sprites additifs, coûteux
    alpha: false,
    powerPreference: 'high-performance',
    failIfMajorPerformanceCaveat: false,
  });
  // Résolution native, ratio 1. Pas de suréchantillonnage : c'est une dalle
  // de 800x480, chaque pixel rendu en trop est du watt gaspillé.
  renderer.setPixelRatio(1);
  renderer.setSize(W, H, false);
  renderer.setClearColor(new THREE.Color(COLOR.bg), 1);
  stage.appendChild(renderer.domElement);

  // Caméra orthographique en unités « pixel » : le logotype tombe pile sur la
  // grille de la dalle, pas de flou de reprojection.
  const camera = new THREE.OrthographicCamera(-W / 2, W / 2, H / 2, -H / 2, -2000, 2000);
  const scene = new THREE.Scene();

  // ---- attributs -----------------------------------------------------------
  const n = Math.min(COUNT, sample.count);
  const stride = sample.count / n;
  const start = new Float32Array(n * 3);
  const targetPos = new Float32Array(n * 3);
  const seed = new Float32Array(n);
  const delay = new Float32Array(n);
  const colors = new Float32Array(n * 3);

  const cAccent = new THREE.Color(COLOR.accent);
  const cInput = new THREE.Color(COLOR.input);
  const cText = new THREE.Color(COLOR.text);

  for (let i = 0; i < n; i++) {
    const src = Math.floor(i * stride) * 3;
    const px = sample.pts[src];
    const py = sample.pts[src + 1];
    const isRule = sample.pts[src + 2] === 1;

    const tx = px - W / 2;
    const ty = H / 2 - py;
    targetPos[i * 3] = tx;
    targetPos[i * 3 + 1] = ty;
    targetPos[i * 3 + 2] = 0;

    // Nuage de départ : large, profond, désordonné.
    const ang = Math.random() * Math.PI * 2;
    const rad = 260 + Math.random() * 640;
    start[i * 3] = Math.cos(ang) * rad * 1.35;
    start[i * 3 + 1] = Math.sin(ang) * rad * 0.75;
    start[i * 3 + 2] = (Math.random() - 0.5) * 1300;

    // Assemblage balayé de gauche à droite : le mot s'écrit, il n'apparaît pas.
    delay[i] = (px / W) * 0.34 + Math.random() * 0.12;
    seed[i] = Math.random() * 6.2831;

    // Une seule couleur d'accent domine. Le rose reste un marqueur, pas un décor.
    let col = cAccent;
    const r = Math.random();
    if (isRule) col = cAccent;
    else if (r < 0.06) col = cInput;
    else if (r < 0.17) col = cText;
    colors[i * 3] = col.r;
    colors[i * 3 + 1] = col.g;
    colors[i * 3 + 2] = col.b;
  }

  const geometry = new THREE.BufferGeometry();
  geometry.setAttribute('position', new THREE.BufferAttribute(targetPos, 3));
  geometry.setAttribute('aStart', new THREE.BufferAttribute(start, 3));
  geometry.setAttribute('aSeed', new THREE.BufferAttribute(seed, 1));
  geometry.setAttribute('aDelay', new THREE.BufferAttribute(delay, 1));
  geometry.setAttribute('aColor', new THREE.BufferAttribute(colors, 3));

  // Sprite radial généré en mémoire : la lueur sans post-traitement.
  // Un vrai bloom coûterait deux passes plein écran pour 1,4 s d'affichage.
  const sprite = makeSpriteTexture();

  const material = new THREE.ShaderMaterial({
    uniforms: {
      uProgress: { value: 0 },
      uTime: { value: 0 },
      uGlitch: { value: 1 },
      uOpacity: { value: 1 },
      uBurst: { value: 0 },
      uSize: { value: 3.0 },
      uMap: { value: sprite },
    },
    transparent: true,
    depthTest: false,
    depthWrite: false,
    blending: THREE.AdditiveBlending,
    vertexShader: `
      attribute vec3  aStart;
      attribute vec3  aColor;
      attribute float aSeed;
      attribute float aDelay;
      uniform float uProgress, uTime, uGlitch, uSize, uBurst;
      varying vec3  vColor;
      varying float vHot;

      float hash(float x) { return fract(sin(x * 78.233) * 43758.5453); }

      void main() {
        // Progression locale : chaque particule a son propre départ.
        float local = clamp((uProgress - aDelay) / max(1.0 - aDelay, 0.001), 0.0, 1.0);
        // easeOutExpo : arrivée franche puis immobile. Pas de rebond.
        float e = local >= 1.0 ? 1.0 : 1.0 - pow(2.0, -10.0 * local);

        vec3 pos = mix(aStart, position, e);

        // Frémissement en vol, amorti à l'arrivée.
        float rest = 1.0 - e;
        pos.x += sin(uTime * 5.5 + aSeed) * 9.0 * rest;
        pos.y += cos(uTime * 4.7 + aSeed * 1.7) * 9.0 * rest;

        // Décrochage horizontal par bandes : la seule vraie touche « hack ».
        // Amplitude pilotée par uGlitch, qui décroît à zéro avant la tenue.
        float band = floor((pos.y + 240.0) / 9.0);
        float jolt = step(0.82, hash(band + floor(uTime * 22.0)));
        pos.x += jolt * uGlitch * (hash(band) - 0.5) * 46.0;

        // Dispersion de sortie, le long du rayon.
        pos.xy += normalize(pos.xy + vec2(0.001)) * uBurst * (18.0 + hash(aSeed) * 34.0);

        vColor = aColor;
        vHot = e;

        vec4 mv = modelViewMatrix * vec4(pos, 1.0);
        gl_Position = projectionMatrix * mv;
        // Grosses particules en vol, resserrées une fois posées : c'est ce qui
        // fait lire le mot comme « net » à l'arrivée.
        gl_PointSize = uSize * (1.0 + rest * 2.4);
      }
    `,
    fragmentShader: `
      uniform sampler2D uMap;
      uniform float uOpacity;
      varying vec3  vColor;
      varying float vHot;
      void main() {
        float a = texture2D(uMap, gl_PointCoord).a;
        if (a < 0.02) discard;
        // Cœur plus clair une fois la particule arrivée : le mot « allume ».
        // La teinte ne doit JAMAIS quitter l'accent de la palette : multiplier
        // au-delà de 1.0 écrête le bleu et fait virer le violet au rose.
        // Densité + coeur blanc localisé font la luminosité, pas la saturation.
        float core = pow(a, 4.0) * vHot;
        vec3 col = vColor * (0.80 + 0.20 * vHot) + vec3(0.22) * core;
        gl_FragColor = vec4(col, a * uOpacity);
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
    tagline.classList.remove('on');
    tagline.style.opacity = '0';
    document.body.style.background = COLOR.bg;
  }

  // ---- boucle --------------------------------------------------------------
  const t0 = performance.now();
  let taglineShown = false;
  let frames = 0;

  renderer.setAnimationLoop(() => {
    const t = performance.now() - t0;
    frames++;

    const conv = Math.min(t / CONVERGE, 1);
    material.uniforms.uProgress.value = conv;
    material.uniforms.uTime.value = t / 1000;
    // Le décrochage s'éteint bien avant la fin de la convergence.
    material.uniforms.uGlitch.value = Math.max(0, 1 - conv / 0.7) ** 2;

    if (t > CONVERGE && !taglineShown) {
      taglineShown = true;
      showTagline();
    }

    if (t > CONVERGE + HOLD) {
      const out = Math.min((t - CONVERGE - HOLD) / FADEOUT, 1);
      material.uniforms.uOpacity.value = 1 - out;
      material.uniforms.uBurst.value = out;
      tagline.style.opacity = String(1 - out);
    }

    renderer.render(scene, camera);

    if (t >= TOTAL) {
      const fps = Math.round(frames / (t / 1000));
      console.log(`[ghostboard-boot] ${frames} images en ${Math.round(t)} ms (~${fps} i/s), contexte détruit`);
      finish(dispose);
    }
  });

  // Garde-fou : si la boucle cale (pilote, veille, GPU absent), on sort quand
  // même. Rien ne doit retarder l'ouverture de session.
  setTimeout(() => finish(dispose), (BOOT.timeout_ms ?? 4000));
}

/** Sprite radial 32x32 en mémoire — la lueur, sans passe de post-traitement. */
function makeSpriteTexture() {
  const s = 32;
  const cv = document.createElement('canvas');
  cv.width = cv.height = s;
  const ctx = cv.getContext('2d');
  const g = ctx.createRadialGradient(s / 2, s / 2, 0, s / 2, s / 2, s / 2);
  g.addColorStop(0.0, 'rgba(255,255,255,1)');
  g.addColorStop(0.25, 'rgba(255,255,255,0.85)');
  g.addColorStop(0.55, 'rgba(255,255,255,0.22)');
  g.addColorStop(1.0, 'rgba(255,255,255,0)');
  ctx.fillStyle = g;
  ctx.fillRect(0, 0, s, s);
  const tex = new THREE.CanvasTexture(cv);
  tex.minFilter = THREE.LinearFilter;
  tex.magFilter = THREE.LinearFilter;
  tex.generateMipmaps = false;
  return tex;
}
