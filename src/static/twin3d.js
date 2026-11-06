// 가공 공정 3D 트윈: /api/state 의 PLC 상태(센서 X, 출력 Y, 작업물 위치)를 three.js 장면에 그대로 반영한다.
// 단위: 1 = 약 10 cm.  배치(위에서 본 모습): 왼쪽 매거진 -> 가공 위치 -> (앞쪽으로 송출) -> 컨베이어 -> 금속은 앞쪽 박스, 비금속은 끝까지
import * as THREE from 'three';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';

const $ = id => document.getElementById(id);
const post = (u, b) => fetch(u, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(b) });
const embed = new URLSearchParams(location.search).get('embed');
if (embed) document.body.classList.add('embed');
if (embed === 'view') document.body.classList.add('view');
$('to2d').href = '/' + location.search;

// ---------------------------------------------------------------- 배치
const TOP = 0.5;                       // 레일, 컨베이어 윗면 높이
const PIECE_Y = TOP + 0.3;             // 작업물 중심 높이
const MAG_X = -6.9, ST_X = -3.5;       // 매거진, 가공 위치(드릴 아래)
const BELT_Z = 3.2, BELT_START = -3.5, BELT_LEN = 12.5;
const SORT_X = BELT_START + 0.5 * BELT_LEN;   // 금속 분류 위치 (workpiece.py 의 SORT_T = 0.5)
const END_X = BELT_START + BELT_LEN;          // 비금속이 도착하는 컨베이어 끝
const BIN_Z = 6.2;                     // 금속 배출 박스

// ---------------------------------------------------------------- 장면
const scene = new THREE.Scene();
scene.background = new THREE.Color(0x111418);
const camera = new THREE.PerspectiveCamera(45, 1, 0.1, 200);
camera.position.set(1.5, 10.5, 16.5);
const renderer = new THREE.WebGLRenderer({ antialias: true });
renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
renderer.shadowMap.enabled = true;
document.body.appendChild(renderer.domElement);
const controls = new OrbitControls(camera, renderer.domElement);
controls.target.set(1.2, 0.8, 2.0);
controls.enableDamping = true;
controls.update();

scene.add(new THREE.AmbientLight(0xffffff, 0.75));
const sun = new THREE.DirectionalLight(0xffffff, 1.6);
sun.position.set(8, 18, 10);
sun.castShadow = true;
sun.shadow.mapSize.width = 2048;
sun.shadow.mapSize.height = 2048;
sun.shadow.camera.left = -20; sun.shadow.camera.right = 20; sun.shadow.camera.top = 20; sun.shadow.camera.bottom = -20;
scene.add(sun);
const alarmLight = new THREE.PointLight(0xff3030, 0, 30);
alarmLight.position.set(12.8, 5, 0.5);
scene.add(alarmLight);

const mat = (color, opts = {}) => new THREE.MeshStandardMaterial({ color, roughness: 0.55, metalness: 0.25, ...opts });
function box(w, h, d, color, x, y, z, opts) {
  const m = new THREE.Mesh(new THREE.BoxGeometry(w, h, d), mat(color, opts));
  m.position.set(x, y, z); m.castShadow = true; m.receiveShadow = true; scene.add(m); return m;
}
function cyl(r, h, color, x, y, z, opts) {
  const m = new THREE.Mesh(new THREE.CylinderGeometry(r, r, h, 32), mat(color, opts));
  m.position.set(x, y, z); m.castShadow = true; m.receiveShadow = true; scene.add(m); return m;
}
// 길이를 바꿀 수 있는 막대 (실린더 로드). 높이 1짜리 원기둥을 늘려서 쓴다.
function rod(r, color, axis) {
  const m = new THREE.Mesh(new THREE.CylinderGeometry(r, r, 1, 20), mat(color, { metalness: 0.6, roughness: 0.3 }));
  if (axis === 'x') m.rotation.z = Math.PI / 2;
  if (axis === 'z') m.rotation.x = Math.PI / 2;
  m.castShadow = true; scene.add(m); return m;
}
function label(text, x, y, z, w = 2.7) {
  const c = document.createElement('canvas'); c.width = 320; c.height = 80;
  const g = c.getContext('2d');
  g.fillStyle = 'rgba(20,24,30,0.78)'; g.fillRect(0, 0, 320, 80);
  g.fillStyle = '#e6e9ee'; g.font = 'bold 34px "Malgun Gothic", sans-serif'; g.textAlign = 'center'; g.textBaseline = 'middle';
  g.fillText(text, 160, 42);
  const tex = new THREE.CanvasTexture(c); tex.colorSpace = THREE.SRGBColorSpace;
  const s = new THREE.Sprite(new THREE.SpriteMaterial({ map: tex, transparent: true, depthTest: true }));
  s.renderOrder = 10;
  s.position.set(x, y, z); s.scale.set(w, w / 4, 1); scene.add(s); return s;
}

// 바닥과 작업대
box(30, 0.4, 17, 0x2a323d, 0.5, -0.2, 2.2);
// 매거진 -> 가공 위치 레일
box(5.4, TOP, 1.5, 0x39424f, -5.3, TOP / 2, 0);
// 송출 이송판 (가공 위치 -> 컨베이어)
box(2.0, TOP, 2.2, 0x39424f, ST_X, TOP / 2, 1.55);
// 컨베이어
box(BELT_LEN + 1.8, TOP, 1.7, 0x2a4a44, (BELT_START - 0.9 + END_X + 0.9) / 2, TOP / 2, BELT_Z);
const beltTex = (() => {
  const c = document.createElement('canvas'); c.width = 64; c.height = 16;
  const g = c.getContext('2d');
  g.fillStyle = '#2f5a52'; g.fillRect(0, 0, 64, 16); g.fillStyle = '#5ad6bd'; g.fillRect(0, 6, 28, 4);
  const t = new THREE.CanvasTexture(c); t.wrapS = THREE.RepeatWrapping; t.repeat.set(BELT_LEN, 1); t.colorSpace = THREE.SRGBColorSpace; return t;
})();
const belt = new THREE.Mesh(new THREE.PlaneGeometry(BELT_LEN + 1.6, 1.5), new THREE.MeshStandardMaterial({ map: beltTex, roughness: 0.8 }));
belt.rotation.x = -Math.PI / 2; belt.position.set((BELT_START - 0.8 + END_X + 0.8) / 2, TOP + 0.01, BELT_Z); belt.receiveShadow = true; scene.add(belt);
box(BELT_LEN + 1.8, 0.25, 0.12, 0x6a7686, (BELT_START + END_X) / 2, TOP + 0.12, BELT_Z - 0.9);
box(BELT_LEN + 1.8, 0.25, 0.12, 0x6a7686, (BELT_START + END_X) / 2, TOP + 0.12, BELT_Z + 0.9);

// 공급 실린더 (왼쪽, X 방향으로 민다)
box(2.2, 0.9, 0.9, 0x5a6677, -10.9, PIECE_Y, 0);
const supRod = rod(0.14, 0x2f9bff, 'x');
const supHead = box(0.3, 0.9, 0.9, 0x8a94a3, 0, PIECE_Y, 0);
// 매거진 (투명한 통 + 쌓인 작업물)
const tube = cyl(0.66, 2.4, 0x6fa8dc, MAG_X, 2.4, 0, { transparent: true, opacity: 0.22 });
const magParts = [1.5, 2.1, 2.7].map(y => cyl(0.45, 0.5, 0x6fa8dc, MAG_X, y, 0));
box(0.15, 1.0, 0.15, 0x6a7686, MAG_X - 0.8, 0.95, 0); box(0.15, 1.0, 0.15, 0x6a7686, MAG_X + 0.8, 0.95, 0);
// 드릴 (문형 지지대 + 모터 + 비트)
box(0.5, 4.6, 0.5, 0x5a6677, -1.5, 2.3, 0);
box(2.5, 0.5, 0.5, 0x5a6677, -2.5, 4.4, 0);
const motor = box(1.3, 1.0, 1.3, 0x5a6677, ST_X, 4.05, 0);
const bit = rod(0.12, 0xc8d0da, 'y');
const chuck = cyl(0.3, 0.3, 0x39424f, ST_X, 3.4, 0);
// 송출 실린더 (뒤쪽, Z 방향으로 가공 위치의 작업물을 컨베이어 쪽으로 민다)
box(0.9, 0.9, 2.2, 0x5a6677, ST_X, PIECE_Y, -4.3);
const outRod = rod(0.14, 0x2f9bff, 'z');
const outHead = box(0.9, 0.9, 0.3, 0x8a94a3, ST_X, PIECE_Y, 0);
// 배출 실린더 (컨베이어 뒤쪽, 금속을 앞쪽 박스로 민다)
box(0.9, 0.9, 1.8, 0x5a6677, SORT_X, PIECE_Y, 0.9);
const ejRod = rod(0.14, 0x2f9bff, 'z');
const ejHead = box(0.9, 0.9, 0.3, 0x8a94a3, SORT_X, PIECE_Y, 0);
// 금속 배출 박스, 비금속 끝 박스
function bin(x, z, size) {
  const h = 0.6, t = 0.12, c = 0x3a4452;
  box(size, 0.15, size, c, x, 0.2, z);
  box(size, h, t, c, x, 0.45, z - size / 2); box(size, h, t, c, x, 0.45, z + size / 2);
  box(t, h, size, c, x - size / 2, 0.45, z); box(t, h, size, c, x + size / 2, 0.45, z);
}
bin(SORT_X, BIN_Z, 2.4);
bin(END_X + 1.0, BELT_Z, 1.8);
// 신호등
cyl(0.12, 3.8, 0x6a7686, 12.8, 1.9, 0.5);
const lamps = [[0xef4b4b, 3.7], [0xf2c230, 3.0], [0x33c27f, 2.3]].map(([c, y]) => {
  const m = new THREE.Mesh(new THREE.SphereGeometry(0.34, 24, 16), new THREE.MeshStandardMaterial({ color: 0x222222, emissive: c, emissiveIntensity: 0 }));
  m.position.set(12.8, y, 0.5); scene.add(m); return m;
});

const labels = [
  label('공급 실린더', -10.9, 2.0, 0), label('매거진', MAG_X, 4.2, 0, 2.0), label('드릴', ST_X, 5.5, 0, 1.8),
  label('송출 실린더', ST_X + 2.6, 1.2, -4.3), label('컨베이어', 6.8, 1.1, BELT_Z + 1.5, 2.2),
  label('배출 실린더', SORT_X, 2.1, 0.9), label('금속 배출 박스', SORT_X, 1.7, BIN_Z, 3.0),
  label('비금속 끝', END_X + 1.0, 1.7, BELT_Z + 1.3, 2.2),
];

// ---------------------------------------------------------------- 작업물
const pieceMat = { pre: mat(0x9aa7b5), metal: mat(0xd5dbe3, { metalness: 0.9, roughness: 0.25 }), non: mat(0x6fa8dc) };
const pieceGeo = new THREE.CylinderGeometry(0.42, 0.42, 0.6, 28);
const pieceMeshes = [];
function piecePos(p) {            // workpiece.py 의 단계와 같은 이름: feed -> drill -> out -> belt -> eject -> binm / end
  const t = p.t;
  switch (p.stage) {
    case 'feed': return [MAG_X + t * (ST_X - MAG_X), PIECE_Y, 0];
    case 'drill': return [ST_X, PIECE_Y, 0];
    case 'out': return [ST_X, PIECE_Y, t * BELT_Z];
    case 'belt': return [BELT_START + t * BELT_LEN, PIECE_Y, BELT_Z];
    case 'eject': return [SORT_X, PIECE_Y - 0.3 * t, BELT_Z + t * (BIN_Z - 0.4 - BELT_Z)];
    case 'binm': return [SORT_X, 0.55, BIN_Z - 0.4];
    case 'end': return [END_X + 1.0, PIECE_Y, BELT_Z];
    default: return [ST_X, PIECE_Y, 0];
  }
}

// ---------------------------------------------------------------- 상태 반영
let state = null;
const cur = { sup: 0, out: 0, ej: 0, tip: 2.8, red: 0, yel: 0, grn: 0 };
const ease = (a, b, k) => a + (b - a) * k;
const VIEWS = {                       // [카메라 위치], [바라보는 점]
  diag: [[1.5, 10.5, 16.5], [1.2, 0.8, 2.0]],
  front: [[1.5, 4.5, 19.0], [1.2, 1.2, 2.0]],
  top: [[1.2, 24.0, 2.6], [1.2, 0.0, 2.0]],
  side: [[-17.0, 7.0, 6.0], [1.2, 1.0, 2.0]],
};
function setView(name) {
  const v = VIEWS[name]; if (!v) return;
  camera.position.set(...v[0]); controls.target.set(...v[1]); controls.update();
}

function applyHud(s) {
  $('d0').textContent = s.D0; $('d2').textContent = s.D2; $('d4').textContent = s.D4; $('d10').textContent = s.D10;
  const ai = s.ai || {};
  $('aiState').textContent = ai.phase === 'learning' ? `학습 중 ${ai.learned}/${ai.warmup}` : (ai.alarm ? '이상 감지!' : '정상');
  $('aiState').style.color = ai.alarm ? '#ef4b4b' : '';
  const names = { none: '정상', cyl_slow: '실린더 속도 저하', cyl_degrade: '실린더 점진 열화', sensor_flaky: '센서 응답 지연' };
  $('faultTxt').textContent = names[s.fault] || '정상';
  if (document.activeElement !== $('mode') && s.mode) $('mode').value = s.mode;
  if (document.activeElement !== $('fault') && s.fault) $('fault').value = s.fault;
}

function frame(now, dt) {
  const s = state; if (!s) return;
  const k = 1 - Math.exp(-dt * 12);
  // 실린더 위치 (0 = 후진, 1 = 전진). 솔레노이드 출력을 먼저 보고, 꺼져 있으면 센서를 본다.
  cur.sup = ease(cur.sup, s.Y20 ? 1 : s.Y21 ? 0 : s.X1 ? 1 : s.X0 ? 0 : cur.sup, k);
  cur.out = ease(cur.out, s.Y23 ? 1 : s.Y24 ? 0 : s.X5 ? 1 : s.X4 ? 0 : cur.out, k);
  cur.ej = ease(cur.ej, s.Y25 ? 1 : s.Y26 ? 0 : s.X7 ? 1 : s.X6 ? 0 : cur.ej, k);
  cur.tip = ease(cur.tip, s.Y22 ? 1.15 : 2.8, k);

  // 로드 길이와 머리 위치
  const supEnd = -7.7 + 3.4 * cur.sup;                    // 공급 로드 끝 (x)
  supRod.scale.y = supEnd + 9.8; supRod.position.set(-9.8 + (supEnd + 9.8) / 2, PIECE_Y, 0); supHead.position.x = supEnd;
  const outEnd = -0.8 + 3.2 * cur.out;                    // 송출 로드 끝 (z)
  outRod.scale.y = outEnd + 3.2; outRod.position.set(ST_X, PIECE_Y, -3.2 + (outEnd + 3.2) / 2); outHead.position.z = outEnd;
  const ejEnd = 2.5 + 2.3 * cur.ej;                       // 배출 로드 끝 (z)
  ejRod.scale.y = ejEnd - 1.8; ejRod.position.set(SORT_X, PIECE_Y, 1.8 + (ejEnd - 1.8) / 2); ejHead.position.z = ejEnd;
  bit.scale.y = 3.3 - cur.tip; bit.position.set(ST_X, cur.tip + (3.3 - cur.tip) / 2, 0);
  motor.material.emissive.setHex(s.Y28 ? 0xe08a2f : 0x000000);
  motor.material.emissiveIntensity = s.Y28 ? 0.7 : 0;

  magParts.forEach(m => { m.visible = !!s.X8; });
  tube.material.color.setHex(s.X8 ? 0x33c27f : 0x6fa8dc);

  // 컨베이어 줄무늬
  if (s.Y27) beltTex.offset.x -= dt * 0.9;

  // 신호등 (AI 이상 감지 중에는 빨간 불이 깜박인다)
  const alarm = !!(s.ai && s.ai.alarm);
  const blink = Math.sin(now / 150) > 0;
  const red = alarm ? (blink ? 1 : 0.1) : (s.Y29 ? 1 : 0);
  cur.red = ease(cur.red, red, k); cur.yel = ease(cur.yel, s.Y2A ? 1 : 0, k); cur.grn = ease(cur.grn, s.Y2B ? 1 : 0, k);
  lamps[0].material.emissiveIntensity = cur.red * 1.5;
  lamps[1].material.emissiveIntensity = cur.yel * 1.5;
  lamps[2].material.emissiveIntensity = cur.grn * 1.5;
  alarmLight.intensity = alarm ? (blink ? 40 : 4) : 0;

  // 작업물
  const list = s.pieces || [];
  while (pieceMeshes.length < list.length) {
    const m = new THREE.Mesh(pieceGeo, pieceMat.pre); m.castShadow = true; m.receiveShadow = true;
    scene.add(m); pieceMeshes.push(m);
  }
  pieceMeshes.forEach((m, i) => {
    const p = list[i];
    m.visible = !!p;
    if (!p) return;
    const [x, y, z] = piecePos(p);
    const kk = m.userData.placed ? 1 - Math.exp(-dt * 20) : 1;
    m.position.x = ease(m.position.x, x, kk); m.position.y = ease(m.position.y, y, kk); m.position.z = ease(m.position.z, z, kk);
    m.userData.placed = true;
    const pre = p.stage === 'feed' || p.stage === 'drill' || p.stage === 'out';
    m.material = pre ? pieceMat.pre : (p.metal ? pieceMat.metal : pieceMat.non);
  });
}

// ---------------------------------------------------------------- 통신과 조작
async function poll() {
  try {
    const s = await (await fetch('/api/state')).json();
    state = s; applyHud(s);
  } catch (e) { /* 서버가 잠시 응답하지 않아도 다음 주기에 다시 시도한다 */ }
}
document.querySelectorAll('button[data-dev]').forEach(b => { b.onclick = () => post('/api/press', { dev: b.dataset.dev }); });
$('mode').onchange = () => post('/api/mode', { mode: $('mode').value });
$('fault').onchange = () => post('/api/fault', { mode: $('fault').value });
$('relearn').onclick = () => post('/api/ai/relearn', {});
document.querySelectorAll('button[data-view]').forEach(b => { b.onclick = () => setView(b.dataset.view); });
$('labels').onchange = () => { labels.forEach(l => { l.visible = $('labels').checked; }); };

function resize() {
  const w = window.innerWidth, h = window.innerHeight;
  renderer.setSize(w, h); camera.aspect = w / h; camera.updateProjectionMatrix();
}
window.addEventListener('resize', resize);
resize();

let last = performance.now();
function loop(now) {
  const dt = Math.min(0.1, (now - last) / 1000); last = now;
  frame(now, dt);
  controls.update();
  renderer.render(scene, camera);
  requestAnimationFrame(loop);
}
poll(); setInterval(poll, 100);
window.__twin3dReady = true;
$('msg').style.display = 'none';
requestAnimationFrame(loop);
