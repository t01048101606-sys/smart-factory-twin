// 범용 3D 공정 뷰어: 장면 정의(JSON, /api/line/scene)와 상태(JSON, /api/line/state)만으로 그린다.
// 새 공정은 장면 JSON 을 새로 만들고, 같은 모양의 상태를 내보내면 된다 (docs/scene_format.md).
import * as THREE from 'three';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';

const $ = id => document.getElementById(id);
const post = (u, b) => fetch(u, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(b) });
const embed = new URLSearchParams(location.search).get('embed');
if (embed) document.body.classList.add('embed');
if (embed === 'view') document.body.classList.add('view');

const get = (obj, path) => path.split('.').reduce((o, k) => (o == null ? undefined : o[k]), obj);   // "stations.press.ram"
const clamp01 = v => Math.max(0, Math.min(1, v));
const ease = (a, b, k) => a + (b - a) * k;

// ---------------------------------------------------------------- 기본 장면
const scene = new THREE.Scene();
const camera = new THREE.PerspectiveCamera(45, 1, 0.1, 300);
const renderer = new THREE.WebGLRenderer({ antialias: true });
renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
renderer.shadowMap.enabled = true;
document.body.appendChild(renderer.domElement);
const controls = new OrbitControls(camera, renderer.domElement);
controls.enableDamping = true;
scene.add(new THREE.AmbientLight(0xffffff, 0.8));
const sun = new THREE.DirectionalLight(0xffffff, 1.6);
sun.position.set(10, 20, 12); sun.castShadow = true;
sun.shadow.mapSize.width = 2048; sun.shadow.mapSize.height = 2048;
sun.shadow.camera.left = -25; sun.shadow.camera.right = 25; sun.shadow.camera.top = 20; sun.shadow.camera.bottom = -20;
scene.add(sun);

let VIEWS = {};
function setView(name) {
  const v = VIEWS[name]; if (!v) return;
  camera.position.set(...v.position); controls.target.set(...v.target); controls.update();
}

// ---------------------------------------------------------------- 장면 만들기
const binds = [];          // {obj, ...anim}
const belts = [];          // {tex, path}
const labelSprites = [];
let partSpec = null, partMats = {}, partGeo = null;
const partMeshes = [];

function makeLabel(o) {
  const c = document.createElement('canvas'); c.width = 320; c.height = 80;
  const g = c.getContext('2d');
  g.fillStyle = 'rgba(20,24,30,0.78)'; g.fillRect(0, 0, 320, 80);
  g.fillStyle = '#e6e9ee'; g.font = 'bold 34px "Malgun Gothic", sans-serif'; g.textAlign = 'center'; g.textBaseline = 'middle';
  g.fillText(o.text, 160, 42);
  const tex = new THREE.CanvasTexture(c); tex.colorSpace = THREE.SRGBColorSpace;
  const s = new THREE.Sprite(new THREE.SpriteMaterial({ map: tex, transparent: true, depthTest: true }));
  s.renderOrder = 10; s.position.set(...o.pos); const w = o.w || 2.4; s.scale.set(w, w / 4, 1);
  scene.add(s); labelSprites.push(s);
}

function makeBelt(o) {
  const c = document.createElement('canvas'); c.width = 64; c.height = 16;
  const g = c.getContext('2d');
  g.fillStyle = '#2f5a52'; g.fillRect(0, 0, 64, 16); g.fillStyle = '#5ad6bd'; g.fillRect(0, 6, 28, 4);
  const tex = new THREE.CanvasTexture(c); tex.wrapS = THREE.RepeatWrapping; tex.repeat.set(o.size[0], 1); tex.colorSpace = THREE.SRGBColorSpace;
  const m = new THREE.Mesh(new THREE.PlaneGeometry(o.size[0], o.size[1]), new THREE.MeshStandardMaterial({ map: tex, roughness: 0.8 }));
  m.rotation.x = -Math.PI / 2; m.position.set(...o.pos); m.receiveShadow = true; scene.add(m);
  belts.push({ tex, path: o.path });
}

function makeShape(o) {
  let geo;
  if (o.shape === 'box') geo = new THREE.BoxGeometry(...o.size);
  else if (o.shape === 'cylinder') geo = new THREE.CylinderGeometry(o.rt ?? o.r, o.rb ?? o.r, o.h, 28);
  else if (o.shape === 'sphere') geo = new THREE.SphereGeometry(o.r, 24, 16);
  else return null;
  const m = new THREE.Mesh(geo, new THREE.MeshStandardMaterial({
    color: o.color || '#888888', roughness: 0.55, metalness: 0.25, transparent: o.opacity != null, opacity: o.opacity ?? 1,
  }));
  m.position.set(...o.pos);
  if (o.rot) m.rotation.set(...o.rot);
  m.castShadow = o.opacity == null; m.receiveShadow = true;
  scene.add(m);
  (o.anim || []).forEach(a => binds.push({ obj: m, ...a }));
  return m;
}

function build(def) {
  document.title = def.title || '3D 공정 뷰어';
  $('title').textContent = def.title || '3D 공정 뷰어';
  scene.background = new THREE.Color(def.background || '#111418');
  VIEWS = def.views || {};
  camera.position.set(...def.camera.position); controls.target.set(...def.camera.target); controls.update();
  for (const o of def.objects) {
    if (o.shape === 'label') makeLabel(o);
    else if (o.shape === 'belt') makeBelt(o);
    else makeShape(o);
  }
  partSpec = def.parts;
  if (partSpec) {
    partGeo = new THREE.BoxGeometry(...partSpec.size);
    for (const [k, c] of Object.entries(partSpec.colors)) partMats[k] = new THREE.MeshStandardMaterial({ color: c, roughness: 0.5, metalness: 0.4 });
  }
}

// ---------------------------------------------------------------- 상태 반영
let state = null;
function applyBind(b, v, k) {
  const m = b.obj;
  switch (b.prop) {
    case 'x': case 'y': case 'z': {
      const target = b.from + (b.to - b.from) * clamp01(Number(v) || 0);
      b.cur = ease(b.cur ?? target, target, k); m.position[b.prop] = b.cur; break;
    }
    case 'visible': m.visible = !!v; break;
    case 'emissive': m.material.emissive.set(v ? b.on : b.off); m.material.emissiveIntensity = v ? 1.2 : 0; break;
    case 'lamp': {                         // 상태 이름 -> 색 (램프)
      const c = (b.map && b.map[v]) || '#222222';
      m.material.color.set(c); m.material.emissive.set(c); m.material.emissiveIntensity = 1.1; break;
    }
    case 'color': m.material.color.set((b.map && b.map[v]) || b.default || '#888888'); break;
    default: break;
  }
}

function partColor(p) {
  if (p.defect) return 'defect';
  if (p.painted) return 'painted';
  if (p.welded) return 'welded';
  if (p.pressed) return 'pressed';
  return 'normal';
}

function frame(dt) {
  const s = state; if (!s) return;
  const k = 1 - Math.exp(-dt * 12);
  binds.forEach(b => applyBind(b, get(s, b.path), k));
  belts.forEach(b => { if (get(s, b.path)) b.tex.offset.x -= dt * 0.9 * Math.max(1, s.speed || 1); });
  if (!partSpec) return;
  const list = s.parts || [];
  while (partMeshes.length < list.length) {
    const m = new THREE.Mesh(partGeo, partMats.normal); m.castShadow = true; m.receiveShadow = true;
    scene.add(m); partMeshes.push(m);
  }
  partMeshes.forEach((m, i) => {
    const p = list[i];
    m.visible = !!p;
    if (!p) return;
    const seg = partSpec.segments[p.stage];
    if (!seg) { m.visible = false; return; }
    const t = clamp01(p.t);
    const kk = m.userData.placed ? 1 - Math.exp(-dt * 14) : 1;
    m.position.x = ease(m.position.x, ease(seg[0][0], seg[1][0], t), kk);
    m.position.y = ease(m.position.y, ease(seg[0][1], seg[1][1], t), kk);
    m.position.z = ease(m.position.z, ease(seg[0][2], seg[1][2], t), kk);
    m.userData.placed = true;
    m.material = partMats[partColor(p)];
  });
}

const STATE_KO = { working: '작업 중', blocked: '막힘', starved: '대기', down: '정지' };
const STATE_COLOR = { working: '#33c27f', blocked: '#f2c230', starved: '#7a8696', down: '#ef4b4b' };
function applyHud(s) {
  $('c_in').textContent = s.counts.in; $('c_good').textContent = s.counts.good; $('c_scrap').textContent = s.counts.scrap;
  $('k_tput').textContent = s.kpi.throughput_per_min ? `${s.kpi.throughput_per_min} 개/분` : '-';
  $('k_bott').textContent = s.kpi.bottleneck_name || '-';
  for (const name of ['press', 'weld', 'paint']) {
    const st = s.stations[name], u = s.util[name];
    $('d_' + name).style.background = STATE_COLOR[st.state] || '#7a8696';
    $('u_' + name).textContent = `${STATE_KO[st.state] || st.state} (${Math.round(u.working * 100)}% / ${Math.round(u.blocked * 100)}%)`;
  }
  if (document.activeElement !== $('fault') && s.fault) $('fault').value = s.fault;
  if (document.activeElement !== $('speed') && s.speed) $('speed').value = String(s.speed);
}

async function poll() {
  try {
    const s = await (await fetch('/api/line/state')).json();
    state = s; applyHud(s);
  } catch (e) { /* 서버가 잠시 응답하지 않아도 다음 주기에 다시 시도한다 */ }
}

// ---------------------------------------------------------------- 시작
function resize() {
  const w = window.innerWidth, h = window.innerHeight;
  renderer.setSize(w, h); camera.aspect = w / h; camera.updateProjectionMatrix();
}
window.addEventListener('resize', resize);
document.querySelectorAll('button[data-act]').forEach(b => { b.onclick = () => post('/api/line/control', { action: b.dataset.act }); });
document.querySelectorAll('button[data-view]').forEach(b => { b.onclick = () => setView(b.dataset.view); });
$('speed').onchange = () => post('/api/line/speed', { value: Number($('speed').value) });
$('fault').onchange = () => post('/api/line/fault', { mode: $('fault').value });
$('labels').onchange = () => { labelSprites.forEach(l => { l.visible = $('labels').checked; }); };

let last = performance.now();
function loop(now) {
  const dt = Math.min(0.1, (now - last) / 1000); last = now;
  frame(dt);
  controls.update();
  renderer.render(scene, camera);
  requestAnimationFrame(loop);
}

(async () => {
  try {
    build(await (await fetch('/api/line/scene')).json());
  } catch (e) {
    $('msg').textContent = '장면 정의를 불러오지 못했습니다: ' + e;
    return;
  }
  resize();
  poll(); setInterval(poll, 100);
  window.__twin3dReady = true;
  $('msg').style.display = 'none';
  requestAnimationFrame(loop);
})();
