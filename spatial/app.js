import * as THREE from 'three';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';
import { GLTFLoader } from 'three/addons/loaders/GLTFLoader.js';
import { STLLoader } from 'three/addons/loaders/STLLoader.js';
import { OBJLoader } from 'three/addons/loaders/OBJLoader.js';
import { PLYLoader } from 'three/addons/loaders/PLYLoader.js';
import { CSS2DRenderer, CSS2DObject } from 'three/addons/renderers/CSS2DRenderer.js';

const $ = id => document.getElementById(id);
const canvas = $('scene');
const viewport = $('viewport');
const scene = new THREE.Scene();
scene.background = new THREE.Color(0x0b0711);
scene.fog = new THREE.FogExp2(0x0b0711, 0.0007);

const renderer = new THREE.WebGLRenderer({ canvas, antialias: true, alpha: false, preserveDrawingBuffer: true, powerPreference: 'high-performance' });
renderer.outputColorSpace = THREE.SRGBColorSpace;
renderer.toneMapping = THREE.ACESFilmicToneMapping;
renderer.toneMappingExposure = 1.1;
renderer.localClippingEnabled = true;
const labels = new CSS2DRenderer();
labels.domElement.style.cssText = 'position:absolute;inset:0;pointer-events:none;overflow:hidden';
viewport.appendChild(labels.domElement);

const perspective = new THREE.PerspectiveCamera(42, 1, 0.01, 1000000);
perspective.position.set(4, 3, 6);
const orthographic = new THREE.OrthographicCamera(-2, 2, 2, -2, -1000000, 1000000);
let camera = perspective;
const controls = new OrbitControls(camera, renderer.domElement);
controls.enableDamping = false;
controls.screenSpacePanning = true;
controls.addEventListener('change', requestRender);

scene.add(new THREE.HemisphereLight(0xdcc8ff, 0x24152f, 2.2));
const key = new THREE.DirectionalLight(0xffffff, 3.5); key.position.set(5, 8, 4); scene.add(key);
const rim = new THREE.DirectionalLight(0xa855f7, 2.0); rim.position.set(-5, 2, -4); scene.add(rim);
const grid = new THREE.GridHelper(20, 40, 0xa855f7, 0x39274b); grid.material.transparent = true; grid.material.opacity = 0.5; scene.add(grid);
const axes = new THREE.AxesHelper(1); scene.add(axes);
const content = new THREE.Group(); scene.add(content);
const marks = new THREE.Group(); scene.add(marks);
const clipPlane = new THREE.Plane(new THREE.Vector3(0, -1, 0), 0);
const roots = [], measurements = [], annotations = [];
let selected = null, selectionBox = null, mode = null, measurePoints = [], renderPending = false;
const raycaster = new THREE.Raycaster(), pointer = new THREE.Vector2();

function requestRender() {
  if (renderPending) return;
  renderPending = true;
  requestAnimationFrame(() => { renderPending = false; render(); });
}
function resize() {
  const w = viewport.clientWidth, h = viewport.clientHeight;
  const maxPixels = 1280 * 800;
  const wanted = w * h * devicePixelRatio ** 2;
  renderer.setPixelRatio(Math.min(devicePixelRatio, Math.sqrt(maxPixels / Math.max(1, w * h))));
  renderer.setSize(w, h, false); labels.setSize(w, h);
  perspective.aspect = w / Math.max(1, h); perspective.updateProjectionMatrix();
  const aspect = w / Math.max(1, h), span = orthographic.userData.span || 4;
  orthographic.left = -span * aspect / 2; orthographic.right = span * aspect / 2;
  orthographic.top = span / 2; orthographic.bottom = -span / 2; orthographic.updateProjectionMatrix();
  requestRender();
}
function render() {
  renderer.render(scene, camera); labels.render(scene, camera);
  $('telemetry').textContent = `${renderer.info.render.triangles.toLocaleString('fr-FR')} triangles · ${renderer.info.render.calls} appels`;
}
new ResizeObserver(resize).observe(viewport);

function bounds() {
  const box = new THREE.Box3().setFromObject(content);
  return box.isEmpty() ? new THREE.Box3(new THREE.Vector3(-1, -1, -1), new THREE.Vector3(1, 1, 1)) : box;
}
function fit(object = content) {
  const box = new THREE.Box3().setFromObject(object); if (box.isEmpty()) return;
  const center = box.getCenter(new THREE.Vector3()), size = box.getSize(new THREE.Vector3());
  const radius = Math.max(size.length() * 0.65, 0.1);
  controls.target.copy(center);
  if (camera.isPerspectiveCamera) {
    const direction = camera.position.clone().sub(controls.target).normalize();
    camera.position.copy(center).addScaledVector(direction.lengthSq() ? direction : new THREE.Vector3(1, .7, 1), radius * 2.2);
    camera.near = Math.max(radius / 1000, 0.001); camera.far = radius * 1000; camera.updateProjectionMatrix();
  } else {
    orthographic.userData.span = Math.max(size.x, size.y, size.z) * 1.35;
    resize();
  }
  controls.update(); requestRender();
}

function setView(view) {
  const box = bounds(), center = box.getCenter(new THREE.Vector3()), size = box.getSize(new THREE.Vector3()), distance = Math.max(size.length() * 1.5, 2);
  if (view === 'perspective') {
    camera = perspective; camera.position.copy(center).add(new THREE.Vector3(distance, distance * .7, distance));
  } else {
    camera = orthographic;
    const direction = { top: new THREE.Vector3(0, 1, 0), front: new THREE.Vector3(0, 0, 1), right: new THREE.Vector3(1, 0, 0) }[view];
    camera.position.copy(center).addScaledVector(direction, distance);
    camera.up.set(0, 1, 0); if (view === 'top') camera.up.set(0, 0, -1);
    camera.lookAt(center); camera.userData.span = Math.max(size.x, size.y, size.z) * 1.35 || 4; resize();
  }
  controls.object = camera; controls.target.copy(center); controls.update();
  document.querySelectorAll('[data-view]').forEach(b => b.classList.toggle('active', b.dataset.view === view)); requestRender();
}

function eachMaterial(fn) {
  content.traverse(obj => { if (obj.isMesh) (Array.isArray(obj.material) ? obj.material : [obj.material]).forEach(fn); });
}
function applyMaterialModes() {
  const xray = $('xray').checked, wire = $('wire').checked, clipping = Number($('clip').value) >= -100;
  eachMaterial(mat => {
    if (mat.userData.originalOpacity === undefined) mat.userData.originalOpacity = mat.opacity;
    mat.transparent = xray || mat.userData.originalOpacity < 1;
    mat.opacity = xray ? 0.24 : mat.userData.originalOpacity;
    mat.depthWrite = !xray; mat.wireframe = wire; mat.clippingPlanes = clipping ? [clipPlane] : []; mat.needsUpdate = true;
  });
  requestRender();
}

function prepareRoot(root, name) {
  root.name = name; root.userData.sourceName = name;
  content.add(root); root.updateMatrixWorld(true);
  const box = new THREE.Box3().setFromObject(root), center = box.getCenter(new THREE.Vector3());
  root.traverse(obj => {
    if (!obj.isMesh) return;
    obj.castShadow = obj.receiveShadow = true;
    obj.userData.basePosition = obj.position.clone();
    const worldCenter = new THREE.Box3().setFromObject(obj).getCenter(new THREE.Vector3());
    const targetWorld = worldCenter.clone().add(worldCenter.clone().sub(center).normalize().multiplyScalar(Math.max(box.getSize(new THREE.Vector3()).length() * .15, .01)));
    const parent = obj.parent;
    const localA = parent ? parent.worldToLocal(worldCenter.clone()) : worldCenter.clone();
    const localB = parent ? parent.worldToLocal(targetWorld) : targetWorld.clone();
    obj.userData.explodeVector = localB.sub(localA);
  });
  roots.push(root); applyMaterialModes(); rebuildTree(); fit(root); $('drop').classList.add('hidden');
}

async function loadFile(file) {
  if (file.size > 250 * 1024 * 1024) throw new Error(`${file.name}: limite de 250 Mio`);
  const ext = file.name.split('.').pop().toLowerCase();
  $('status').textContent = `Chargement de ${file.name}…`;
  let root;
  if (ext === 'glb' || ext === 'gltf') {
    const data = ext === 'glb' ? await file.arrayBuffer() : await file.text();
    const gltf = await new Promise((resolve, reject) => new GLTFLoader().parse(data, '', resolve, reject)); root = gltf.scene;
  } else if (ext === 'stl') {
    const geometry = new STLLoader().parse(await file.arrayBuffer()); geometry.computeVertexNormals();
    root = new THREE.Mesh(geometry, new THREE.MeshStandardMaterial({ color: 0xa855f7, roughness: .55, metalness: .15 }));
  } else if (ext === 'ply') {
    const geometry = new PLYLoader().parse(await file.arrayBuffer()); geometry.computeVertexNormals();
    root = new THREE.Mesh(geometry, new THREE.MeshStandardMaterial({ color: 0x9fe8ff, vertexColors: geometry.hasAttribute('color'), roughness: .65 }));
  } else if (ext === 'obj') root = new OBJLoader().parse(await file.text());
  else throw new Error(`${file.name}: format non pris en charge`);
  prepareRoot(root, file.name); $('status').textContent = `${file.name} chargé localement`;
}
async function loadFiles(files) {
  for (const file of files) try { await loadFile(file); } catch (error) { $('status').textContent = error.message; console.error(error); }
  requestRender();
}

function rebuildTree() {
  const tree = $('tree'); tree.textContent = '';
  roots.forEach((root, index) => {
    const button = document.createElement('button');
    const eye = document.createElement('span'); eye.className = 'eye'; eye.textContent = root.visible ? '●' : '○';
    const label = document.createElement('span'); label.textContent = root.name || `Modèle ${index + 1}`;
    button.append(eye, label); button.onclick = event => {
      if (event.target === eye) { root.visible = !root.visible; rebuildTree(); requestRender(); }
      else { select(root); fit(root); }
    }; tree.append(button);
  });
  if (!roots.length) tree.innerHTML = '<p class="empty">Aucun modèle chargé</p>';
}

function triangles(object) {
  let total = 0; object.traverse(o => { if (o.isMesh && o.geometry) total += o.geometry.index ? o.geometry.index.count / 3 : (o.geometry.attributes.position?.count || 0) / 3; }); return Math.round(total);
}
function select(object) {
  selected = object;
  if (selectionBox) scene.remove(selectionBox);
  selectionBox = new THREE.Box3Helper(new THREE.Box3().setFromObject(object), 0xff4d8d); scene.add(selectionBox);
  const box = new THREE.Box3().setFromObject(object), size = box.getSize(new THREE.Vector3()), pos = box.getCenter(new THREE.Vector3()), unit = $('units').value;
  $('properties').innerHTML = `<dt>Objet</dt><dd>${escapeHtml(object.name || object.type)}</dd><dt>Dimensions</dt><dd>${formatVec(size, unit)}</dd><dt>Centre</dt><dd>${formatVec(pos, unit)}</dd><dt>Triangles</dt><dd>${triangles(object).toLocaleString('fr-FR')}</dd>`;
  requestRender();
}
const escapeHtml = text => String(text).replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c]);
const formatVec = (v, unit) => `${v.x.toPrecision(4)} × ${v.y.toPrecision(4)} × ${v.z.toPrecision(4)} ${unit}`;

function effectivelyVisible(object) {
  for (let current = object; current; current = current.parent) if (!current.visible) return false;
  return true;
}
function hit(event) {
  const rect = renderer.domElement.getBoundingClientRect();
  pointer.set((event.clientX - rect.left) / rect.width * 2 - 1, -(event.clientY - rect.top) / rect.height * 2 + 1);
  raycaster.setFromCamera(pointer, camera);
  return raycaster.intersectObjects(roots, true).find(x => effectivelyVisible(x.object));
}
function setMode(next) {
  mode = mode === next ? null : next; measurePoints = [];
  $('mode').textContent = mode === 'measure' ? 'MESURE : choisissez deux points' : mode === 'annotate' ? 'ANNOTATION : choisissez un point' : '';
  $('measure').classList.toggle('active', mode === 'measure'); $('annotate').classList.toggle('active', mode === 'annotate');
}
function labelObject(text, extra = '') {
  const element = document.createElement('div'); element.className = `spatial-label ${extra}`; element.textContent = text; return new CSS2DObject(element);
}
function addMeasurement(a, b) {
  const distance = a.distanceTo(b), unit = $('units').value;
  const geometry = new THREE.BufferGeometry().setFromPoints([a, b]);
  const line = new THREE.Line(geometry, new THREE.LineBasicMaterial({ color: 0x45f0b1, depthTest: false })); line.renderOrder = 10;
  const label = labelObject(`${distance.toPrecision(5)} ${unit}`, 'measurement-label'); label.position.copy(a).lerp(b, .5); marks.add(line, label);
  measurements.push({ a: a.toArray(), b: b.toArray(), distance, unit }); rebuildNotes(); requestRender();
}
function addAnnotation(point) {
  const text = prompt('Annotation technique :'); if (!text?.trim()) return;
  const marker = new THREE.Mesh(new THREE.SphereGeometry(Math.max(bounds().getSize(new THREE.Vector3()).length() / 180, .005), 12, 8), new THREE.MeshBasicMaterial({ color: 0xff4d8d, depthTest: false }));
  marker.position.copy(point); marker.renderOrder = 11;
  const label = labelObject(text.trim()); label.position.copy(point); label.position.y += .03; marks.add(marker, label);
  annotations.push({ point: point.toArray(), text: text.trim() }); rebuildNotes(); requestRender();
}
function rebuildNotes() {
  $('measurements').innerHTML = measurements.length ? measurements.map((m, i) => `<div class="note"><b>M${i + 1}</b> ${m.distance.toPrecision(5)} ${escapeHtml(m.unit)}</div>`).join('') : '<p class="empty">Aucune mesure</p>';
  $('annotations').innerHTML = annotations.length ? annotations.map((a, i) => `<div class="note"><b>A${i + 1}</b> ${escapeHtml(a.text)}</div>`).join('') : '<p class="empty">Aucune annotation</p>';
}

let down = null;
renderer.domElement.addEventListener('pointerdown', e => { down = [e.clientX, e.clientY]; });
renderer.domElement.addEventListener('pointerup', e => {
  if (!down || Math.hypot(e.clientX - down[0], e.clientY - down[1]) > 5) return; down = null;
  const intersection = hit(e); if (!intersection) return;
  if (mode === 'measure') {
    measurePoints.push(intersection.point.clone()); if (measurePoints.length === 2) { addMeasurement(...measurePoints); setMode(null); }
  } else if (mode === 'annotate') { addAnnotation(intersection.point.clone()); setMode(null); }
  else select(intersection.object);
});

function download(name, data, type) {
  const a = document.createElement('a'); a.href = URL.createObjectURL(new Blob([data], { type })); a.download = name; a.click(); setTimeout(() => URL.revokeObjectURL(a.href), 1000);
}
function report() {
  const box = bounds(), payload = {
    format: 'ghostboard-spatial-session/1', created: new Date().toISOString(), units: $('units').value,
    models: roots.map(r => ({ name: r.name, visible: r.visible, triangles: triangles(r) })),
    bounds: { min: box.min.toArray(), max: box.max.toArray() }, measurements, annotations,
    camera: { type: camera.type, position: camera.position.toArray(), target: controls.target.toArray() },
    analysis: { explode: Number($('explode').value), clipping: Number($('clip').value), xray: $('xray').checked, wireframe: $('wire').checked },
  };
  download('ghostboard-spatial-report.json', JSON.stringify(payload, null, 2), 'application/json');
}

$('open').onclick = () => $('files').click(); $('files').onchange = e => { const files = [...e.target.files]; e.target.value = ''; loadFiles(files); };
$('fit').onclick = () => fit(); $('measure').onclick = () => setMode('measure'); $('annotate').onclick = () => setMode('annotate');
$('clearMarks').onclick = () => { marks.clear(); measurements.length = annotations.length = 0; rebuildNotes(); requestRender(); };
$('snapshot').onclick = () => { render(); const a = document.createElement('a'); a.download = 'ghostboard-spatial.png'; a.href = canvas.toDataURL('image/png'); a.click(); };
$('export').onclick = report;
document.querySelectorAll('[data-view]').forEach(button => button.onclick = () => setView(button.dataset.view));
$('explode').oninput = event => {
  const factor = Number(event.target.value) / 100; $('explodeValue').textContent = `${event.target.value}%`;
  content.traverse(obj => { if (obj.isMesh && obj.userData.basePosition) obj.position.copy(obj.userData.basePosition).addScaledVector(obj.userData.explodeVector, factor * 5); });
  if (selectionBox && selected) selectionBox.box.setFromObject(selected); requestRender();
};
$('clip').oninput = event => {
  const value = Number(event.target.value), box = bounds(), y = THREE.MathUtils.mapLinear(value, -100, 100, box.min.y, box.max.y);
  $('clipValue').textContent = value < -100 ? 'désactivée' : `${y.toPrecision(4)} ${$('units').value}`; clipPlane.constant = y; applyMaterialModes();
};
$('xray').onchange = $('wire').onchange = applyMaterialModes;
$('units').onchange = () => { if (selected) select(selected); rebuildNotes(); };
for (const type of ['dragenter', 'dragover']) viewport.addEventListener(type, e => { e.preventDefault(); $('drop').classList.remove('hidden'); });
viewport.addEventListener('dragleave', () => roots.length && $('drop').classList.add('hidden'));
viewport.addEventListener('drop', e => { e.preventDefault(); loadFiles(e.dataTransfer.files); });
addEventListener('keydown', e => {
  if (e.key === 'Escape') setMode(null); else if (e.key.toLowerCase() === 'f') fit(); else if (e.key.toLowerCase() === 'm') setMode('measure'); else if (e.key.toLowerCase() === 'a') setMode('annotate');
  else if ('1234'.includes(e.key)) setView(['perspective', 'top', 'front', 'right'][Number(e.key) - 1]);
});
setView('perspective'); resize(); requestRender();
