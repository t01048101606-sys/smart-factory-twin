// 스마트 팩토리 통합 뷰어: 여러 라인의 3D 장면(JSON)을 위치(offset)만 달리해서 한 장면에 배치하고,
// 라인별 상태(/api/factory/state)로 움직인다. 장면 형식은 docs/scene_format.md.
import * as THREE from 'three';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';

const Terms = window.Terms;
await Terms.init();
const $ = id => document.getElementById(id);
const post = (u, b) => fetch(u, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(b) });
const embed = new URLSearchParams(location.search).get('embed');
if (embed) document.body.classList.add('embed');
if (embed === 'view') document.body.classList.add('view');
if (embed === 'scene') { document.body.classList.add('embed'); document.body.classList.add('scene'); }

const get = (obj, path) => path.split('.').reduce((o, k) => (o == null ? undefined : o[k]), obj);
const clamp01 = v => Math.max(0, Math.min(1, v));
const ease = (a, b, k) => a + (b - a) * k;
const AX = { x: 0, y: 1, z: 2 };

// ---------------------------------------------------------------- 기본 장면
const scene = new THREE.Scene();
const camera = new THREE.PerspectiveCamera(45, 1, 0.1, 400);
const renderer = new THREE.WebGLRenderer({ antialias: true });
renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
renderer.shadowMap.enabled = true;
document.body.appendChild(renderer.domElement);
const controls = new OrbitControls(camera, renderer.domElement);
controls.enableDamping = true;
scene.add(new THREE.AmbientLight(0xffffff, 0.8));
const sun = new THREE.DirectionalLight(0xffffff, 1.5);
sun.position.set(10, 30, 15); sun.castShadow = true;
sun.shadow.mapSize.width = 2048; sun.shadow.mapSize.height = 2048;
sun.shadow.camera.left = -40; sun.shadow.camera.right = 40; sun.shadow.camera.top = 40; sun.shadow.camera.bottom = -40;
scene.add(sun);

let fit = null, userMoved = false, views = {};
const bounds = { min: [1e9, 1e9, 1e9], max: [-1e9, -1e9, -1e9] };   // 모든 라인의 실제 범위 (전체 시점을 자동으로 맞추는 데 쓴다)
function addBounds(o, off) {
  let h;
  if (o.shape === 'box') h = o.size.map(v => v / 2);
  else if (o.shape === 'cylinder') h = [o.r ?? o.rt, o.h / 2, o.r ?? o.rt];
  else if (o.shape === 'sphere') h = [o.r, o.r, o.r];
  else if (o.shape === 'belt') h = [o.size[0] / 2, 0.05, o.size[1] / 2];
  else return;                                          // 이름표, 조명, 로드는 범위에 넣지 않는다
  for (let i = 0; i < 3; i++) {
    bounds.min[i] = Math.min(bounds.min[i], o.pos[i] - h[i] + off[i]); bounds.max[i] = Math.max(bounds.max[i], o.pos[i] + h[i] + off[i]);
  }
}
function applyView(v) { camera.position.set(...v.position); controls.target.set(...v.target); controls.update(); }
function fitOverview() {
  // 장면 범위의 모서리 8개가 모두 화면 안에 들어오는 가장 가까운 거리를 구한다 (원근 포함, 가장자리 여유 8%)
  if (!fit) return;
  const tanV = Math.tan((camera.fov || 45) / 2 * Math.PI / 180) * 0.92, tanH = tanV * (camera.aspect || 1.8);
  const f = fit.dir.map(v => -v);                                           // 카메라가 보는 방향
  const cross = (a, b) => [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]];
  const norm = v => { const l = Math.hypot(...v) || 1; return v.map(x => x / l); };
  const dot = (a, b) => a[0] * b[0] + a[1] * b[1] + a[2] * b[2];
  const right = norm(cross(f, [0, 1, 0])), up = cross(right, f);
  let d = 5;
  for (const x of [bounds.min[0], bounds.max[0]]) for (const y of [bounds.min[1], bounds.max[1]]) for (const z of [bounds.min[2], bounds.max[2]]) {
    const v = [x - fit.target[0], y - fit.target[1], z - fit.target[2]], depth = dot(v, f);
    d = Math.max(d, Math.abs(dot(v, right)) / tanH - depth, Math.abs(dot(v, up)) / tanV - depth);
  }
  d = Math.min(d, 400);
  camera.position.set(fit.target[0] + fit.dir[0] * d, fit.target[1] + fit.dir[1] * d, fit.target[2] + fit.dir[2] * d);
  controls.target.set(...fit.target); controls.update();
}
function setView(name) {
  if (name === 'overview') { userMoved = false; fitOverview(); return; }
  if (views[name]) { userMoved = true; applyView(views[name]); }
}
if (controls.addEventListener) controls.addEventListener('start', () => { userMoved = true; });

// ---------------------------------------------------------------- 데모 모드: 카메라가 구역을 차례로 돌고, 단계마다 조작(라인 시작, 입고 요청, 결함 주입)을 자동으로 한다
const DEMO_STEPS = [
  { t: 5, view: 'overview', cap: '스마트 팩토리 전체: 가공 라인 · 프레스/용접/도장 · 협동로봇 · 물류 출하', act: () => { post('/api/line/control', { action: 'reset' }); post('/api/line/speed', { value: 3 }); } },
  { t: 8, view: 'machining', cap: '가공 라인 (PLC): 공급 → 판별 → 가공 → 분류', act: () => post('/api/press', { dev: 'M101' }) },
  { t: 8, view: 'press:press', cap: '프레스: 코일을 풀어 서보 피더로 보내고, 슬라이드가 금형에 닿아 성형', act: () => post('/api/line/control', { action: 'start' }) },
  { t: 8, view: 'press:weld', cap: '용접: 3-2-1 지그에 클램프로 고정 → 6축 로봇이 C형 서보 건으로 스폿 용접' },
  { t: 8, view: 'press:paint', cap: '도장: 행거가 전착조에 잠기고, 건조로에서 경화' },
  { t: 9, view: 'cobot', cap: '협동로봇 셀: 비전 검사 → 양품은 파렛트에, 불량은 NG 상자에' },
  { t: 9, view: 'logistics:inbound', cap: '입고: 만재 트럭이 하역하고 재고가 보충됨', act: () => post('/api/logistics/request_inbound', {}) },
  { t: 7, view: 'logistics', cap: 'AGV가 완제품 창고에서 출하 도크로 파렛트를 운반' },
  { t: 9, view: 'logistics:outbound', cap: '출하: 파렛트 4개가 가득 차야 트럭이 출발' },
  { t: 8, view: 'press', cap: '결함 주입: 용접 속도 저하 → 라인 효율(OEE)에 영향', act: () => post('/api/line/fault', { mode: 'weld_slow' }) },
  { t: 6, view: 'press', cap: '결함 해제: 정상 속도로 복귀', act: () => post('/api/line/fault', { mode: 'none' }) },
  { t: 5, view: 'overview', cap: '데모 끝: 모든 수치는 MES 화면에서 이어서 확인할 수 있습니다' },
];
let demoCam = null, demoTimer = null, demoIdx = -1;
const smooth = t => t < 0.5 ? 2 * t * t : 1 - Math.pow(-2 * t + 2, 2) / 2;
function overviewView() {
  if (!fit) return null;
  const keep = { p: camera.position.clone(), t: controls.target.clone() };
  fitOverview();
  const v = { position: camera.position.toArray(), target: controls.target.toArray() };
  camera.position.copy(keep.p); controls.target.copy(keep.t);
  return v;
}
function flyTo(name, dur = 2.5) {
  const v = name === 'overview' ? overviewView() : views[name];
  if (!v) return;
  userMoved = true;
  demoCam = { from: [camera.position.toArray(), controls.target.toArray()], to: [v.position, v.target], t0: clock.now, dur: dur * 1000 };
}
function stepCamera() {
  if (!demoCam) return;
  const k = Math.min(1, (clock.now - demoCam.t0) / demoCam.dur), e = smooth(k);
  camera.position.set(...demoCam.from[0].map((a, i) => a + (demoCam.to[0][i] - a) * e));
  controls.target.set(...demoCam.from[1].map((a, i) => a + (demoCam.to[1][i] - a) * e));
  if (k >= 1) demoCam = null;
}
function demoCaption(text) { const c = $('demoCap'); if (c) { c.textContent = text || ''; c.style.display = text ? 'block' : 'none'; } }
function demoStop() {
  clearTimeout(demoTimer); demoTimer = null; demoIdx = -1; demoCam = null; demoCaption('');
  const b = $('demoBtn'); if (b) b.textContent = '▶ 데모';
}
function demoNext() {
  demoIdx += 1;
  if (demoIdx >= DEMO_STEPS.length) { demoStop(); return; }
  const st = DEMO_STEPS[demoIdx];
  demoCaption(`${demoIdx + 1} / ${DEMO_STEPS.length}  ${st.cap}`);
  flyTo(st.view);
  if (st.act) st.act();
  demoTimer = setTimeout(demoNext, st.t * 1000);
}
function demoToggle() {
  if (demoTimer) { demoStop(); return; }
  const b = $('demoBtn'); if (b) b.textContent = '■ 데모 중지';
  demoIdx = -1; demoNext();
}

// ---------------------------------------------------------------- 라인 장면 만들기
const lines = [];
const labelSprites = [];
const drawLabel = s => {
  const c = s.userData.canvas, g = c.getContext('2d');
  g.clearRect(0, 0, 320, 80);
  g.fillStyle = 'rgba(20,24,30,0.78)'; g.fillRect(0, 0, 320, 80);
  g.fillStyle = '#e6e9ee'; g.font = 'bold 34px "Malgun Gothic", sans-serif'; g.textAlign = 'center'; g.textBaseline = 'middle';
  g.fillText(s.userData.key ? Terms.t(s.userData.key) : s.userData.text, 160, 42, 300);
  s.material.map.needsUpdate = true;
};

function buildLine(ln, def) {
  const off = ln.offset || [0, 0, 0];
  const P = p => [p[0] + off[0], p[1] + off[1], p[2] + off[2]];
  const ctx = { ln, def, off, binds: [], belts: [], parts: [], partMats: {}, state: null };
  def.objects.forEach(o => addBounds(o, off));
  const shapeMat = o => new THREE.MeshStandardMaterial({ color: o.color || '#888888', roughness: 0.55, metalness: 0.25, transparent: o.opacity != null, opacity: o.opacity ?? 1 });
  // 오브젝트를 만든다. 그룹(shape: 'group')은 자식을 가지는 관절/부착 단위이고, 그룹 안쪽 좌표는 그룹 기준 상대 좌표다 (라인 offset 은 맨 바깥 것에만 더한다).
  const make = (o, parent, nested) => {
    const PP = nested ? (p => p) : P, offN = nested ? [0, 0, 0] : off;
    const posBind = (obj, a) => {
      const b = { obj, ...a };
      if (['x', 'y', 'z'].includes(a.prop)) { b.from = a.from + offN[AX[a.prop]]; b.to = a.to + offN[AX[a.prop]]; }   // 위치는 라인 offset 을 더한다
      if (a.prop === 'fill') b.base_y = a.base_y + offN[1];
      return b;
    };
    if (o.shape === 'group') {
      const g = new THREE.Group();
      g.userData = { id: o.id || null };            // 시험과 디버깅에서 이름으로 찾는다
      g.position.set(...PP(o.pos || [0, 0, 0])); if (o.rot) g.rotation.set(...o.rot);
      parent.add(g);
      (o.anim || []).forEach(a => ctx.binds.push(posBind(g, a)));
      (o.children || []).forEach(c => make(c, g, true));
    } else if (o.shape === 'label') {
      const c = document.createElement('canvas'); c.width = 320; c.height = 80;
      const tex = new THREE.CanvasTexture(c); tex.colorSpace = THREE.SRGBColorSpace;
      const s = new THREE.Sprite(new THREE.SpriteMaterial({ map: tex, transparent: true, depthTest: true }));
      s.renderOrder = 10; s.userData = { key: o.key, text: o.text, canvas: c };
      s.position.set(...PP(o.pos)); const w = o.w || 2.4; s.scale.set(w, w / 4, 1);
      parent.add(s); labelSprites.push(s); drawLabel(s);
    } else if (o.shape === 'belt') {
      const c = document.createElement('canvas'); c.width = 64; c.height = 16;
      const g = c.getContext('2d');
      g.fillStyle = '#2f5a52'; g.fillRect(0, 0, 64, 16); g.fillStyle = '#5ad6bd'; g.fillRect(0, 6, 28, 4);
      const tex = new THREE.CanvasTexture(c); tex.wrapS = THREE.RepeatWrapping; tex.repeat.set(o.size[0], 1); tex.colorSpace = THREE.SRGBColorSpace;
      const m = new THREE.Mesh(new THREE.PlaneGeometry(o.size[0], o.size[1]), new THREE.MeshStandardMaterial({ map: tex, roughness: 0.8 }));
      m.rotation.x = -Math.PI / 2; m.position.set(...PP(o.pos)); m.receiveShadow = true; parent.add(m);
      ctx.belts.push({ tex, path: o.path });
    } else if (o.shape === 'light') {
      const l = new THREE.PointLight(o.color || 0xffffff, o.intensity || 0, o.distance || 30);
      l.position.set(...PP(o.pos)); parent.add(l);
      (o.anim || []).forEach(a => ctx.binds.push({ obj: l, ...a }));
    } else if (o.shape === 'rod') {
      const m = new THREE.Mesh(new THREE.CylinderGeometry(o.r, o.r, 1, 20), new THREE.MeshStandardMaterial({ color: o.color || '#2f9bff', roughness: 0.3, metalness: 0.6 }));
      if (o.axis === 'x') m.rotation.z = Math.PI / 2;
      if (o.axis === 'z') m.rotation.x = Math.PI / 2;
      m.castShadow = true; parent.add(m);
      const rod = { axis: o.axis, dir: o.dir || 1, start: PP(o.start) };
      setRod(m, rod, o.len ?? 1);
      (o.anim || []).forEach(a => ctx.binds.push({ obj: m, rod, ...a }));
    } else {
      let geo;
      if (o.shape === 'box') geo = new THREE.BoxGeometry(...o.size);
      else if (o.shape === 'cylinder') geo = new THREE.CylinderGeometry(o.rt ?? o.r, o.rb ?? o.r, o.h, 28);
      else if (o.shape === 'sphere') geo = new THREE.SphereGeometry(o.r, 24, 16);
      else return;
      const m = new THREE.Mesh(geo, shapeMat(o));
      m.position.set(...PP(o.pos)); if (o.rot) m.rotation.set(...o.rot);
      m.castShadow = o.opacity == null; m.receiveShadow = true; parent.add(m);
      (o.anim || []).forEach(a => ctx.binds.push(posBind(m, a)));
    }
  };
  def.objects.forEach(o => make(o, scene, false));
  if (def.parts) {
    const ps = def.parts;
    if (!ps.model) ctx.partGeo = ps.shape === 'cylinder' ? new THREE.CylinderGeometry(ps.r, ps.r, ps.h, 28) : new THREE.BoxGeometry(...ps.size);
    for (const [k, c] of Object.entries(ps.colors)) {
      const spec = typeof c === 'string' ? { color: c } : c;
      ctx.partMats[k] = new THREE.MeshStandardMaterial({ roughness: 0.5, metalness: 0.4, ...spec });
    }
  }
  return ctx;
}

function setRod(m, rod, len) {          // 막대 길이를 정한다: 시작점에서 axis 방향으로 len 만큼
  m.scale.y = len;
  const c = rod.start.slice(); c[AX[rod.axis]] += rod.dir * len / 2;
  m.position.set(...c);
}

// ---------------------------------------------------------------- 상태 반영
const clock = { now: 0, dt: 0 };
function applyBind(b, v, k) {
  const m = b.obj;
  switch (b.prop) {
    case 'x': case 'y': case 'z': {
      const target = b.from + (b.to - b.from) * clamp01(Number(v) || 0);
      b.cur = b.snap ? target : ease(b.cur ?? target, target, k); m.position[b.prop] = b.cur; break;   // snap: 반복해서 흐르는 물체는 처음으로 돌아갈 때 미끄러지지 않게
    }
    case 'len': {
      const target = b.from + (b.to - b.from) * clamp01(Number(v) || 0);
      b.cur = ease(b.cur ?? target, target, k); setRod(m, b.rod, b.cur); break;
    }
    case 'fill': {   // 막대 높이: 값(0~1)만큼 아래에서부터 채운다 (재고 수준)
      const f = Math.max(0.03, clamp01(Number(v) || 0));
      b.cur = ease(b.cur ?? f, f, k); m.scale.y = b.cur; m.position.y = b.base_y + b.size_y * b.cur / 2; break;
    }
    case 'rotate': {   // 관절 회전: 값 x scale + bias (라디안). 로봇팔, 문, 바퀴 방향 등
      const target = (b.bias || 0) + (Number(v) || 0) * (b.scale ?? 1);
      b.cur = ease(b.cur ?? target, target, k); m.rotation[b.axis] = b.cur; break;
    }
    case 'spin': if (v) m.rotation[b.axis] += (b.speed || 1) * clock.dt; break;   // 값이 참인 동안 계속 회전 (바퀴, 모터, 드릴)
    case 'visible': m.visible = !!v; break;
    case 'emissive': m.material.emissive.set(v ? b.on : b.off); m.material.emissiveIntensity = v ? (b.ei ?? 1.2) : 0; break;
    case 'lamp': {
      const blink = b.blink_path && b.ctx && get(b.ctx.state, b.blink_path);
      const on = blink ? Math.sin(clock.now / 150) > 0 : null;
      const c = (b.map && b.map[blink ? (on ? '1' : '0') : String(v)]) || '#222222';
      m.material.color.set(c); m.material.emissive.set(c); m.material.emissiveIntensity = 1.1; break;
    }
    case 'color': m.material.color.set((b.map && b.map[String(v)]) || b.default || '#888888'); break;
    case 'intensity': m.intensity = v ? (b.blink && Math.sin(clock.now / 150) <= 0 ? b.on * 0.1 : b.on) : b.off; break;
    default: break;
  }
}

function makeModelPart(ctx) {      // parts.model: [{size, pos, color | rule: true, min_qty}] 조각들을 묶은 그룹
  const ps = ctx.def.parts, g = new THREE.Group();
  g.userData = { part: true, kids: [] };
  for (const c of ps.model) {
    const mat = c.rule ? ctx.partMats[ps.default || 'normal'] : new THREE.MeshStandardMaterial({ color: c.color || '#888888', roughness: 0.6, metalness: 0.2 });
    const mesh = new THREE.Mesh(new THREE.BoxGeometry(...c.size), mat);
    mesh.position.set(...c.pos); mesh.castShadow = true; mesh.receiveShadow = true; g.add(mesh);
    g.userData.kids.push({ mesh, min_qty: c.min_qty || 0, rule: !!c.rule });
  }
  scene.add(g);
  return g;
}

function partMaterial(ctx, p) {
  const ps = ctx.def.parts;
  for (const r of ps.rules || []) {
    if (Object.entries(r.if).every(([k, want]) => (Array.isArray(want) ? want.includes(p[k]) : p[k] === want))) return ctx.partMats[r.color];
  }
  return ctx.partMats[ps.default || 'normal'];
}

function frame(dt) {
  const k = 1 - Math.exp(-dt * 12);
  for (const ctx of lines) {
    const s = ctx.state; if (!s) continue;
    ctx.binds.forEach(b => applyBind(b, get(s, b.path), k));
    ctx.belts.forEach(b => { if (get(s, b.path)) b.tex.offset.x -= dt * 0.9 * Math.max(1, s.speed || 1); });
    const ps = ctx.def.parts; if (!ps) continue;
    const list = s.pieces || s.parts || [];
    while (ctx.parts.length < list.length) {
      if (ps.model) { ctx.parts.push(makeModelPart(ctx)); continue; }
      const m = new THREE.Mesh(ctx.partGeo, ctx.partMats[ps.default || 'normal']); m.castShadow = true; m.receiveShadow = true;
      scene.add(m); ctx.parts.push(m);
    }
    ctx.parts.forEach((m, i) => {
      const p = list[i]; m.visible = !!p; if (!p) return;
      const seg = ps.segments[p.stage];
      if (!seg && !p.pos) { m.visible = false; return; }
      const t = clamp01(p.t ?? 0), kk = m.userData.placed ? 1 - Math.exp(-dt * 14) : 1;
      // 부품이 pos 를 직접 알려 주면 그 좌표를, 아니면 단계(stage)의 구간을 t 로 보간한다
      for (const a of ['x', 'y', 'z']) {
        const target = p.pos ? p.pos[AX[a]] : ease(seg[0][AX[a]], seg[1][AX[a]], t);
        m.position[a] = ease(m.position[a], target + ctx.off[AX[a]], kk);
      }
      m.userData.placed = true;
      if (m.userData.part) {            // 조각으로 조립한 부품: 수량에 따라 조각이 보이고, 규칙 색은 rule 조각에만
        m.userData.kids.forEach(k => { k.mesh.visible = (p.qty ?? 99) >= k.min_qty; if (k.rule) k.mesh.material = partMaterial(ctx, p); });
      } else m.material = partMaterial(ctx, p);
    });
  }
}

// ---------------------------------------------------------------- 요약 카드 (라인별 상태)
function fmtMetric(m, s) {
  const v = get(s, m.path);
  if (m.format === 'ai') return !v ? '-' : (v.phase === 'learning' ? `학습 중 ${v.learned}/${v.warmup}` : (v.alarm ? '이상 감지!' : '정상'));
  if (m.zero !== undefined && (!v || v === 0)) return m.zero;
  return (v ?? '-') + (m.suffix || '');
}
function buildCards() {
  $('cards').innerHTML = lines.map(ctx => {
    const sm = ctx.def.summary || { title: ctx.ln.name, metrics: [], actions: [] };
    const id = ctx.ln.id;
    return `<div class="card"><h2><span>${ctx.ln.name || sm.title}</span><span class="chip" id="st_${id}">-</span></h2>
      ${(sm.metrics || []).map((m, i) => `<div class="row"><span id="ml_${id}_${i}"></span><b id="mv_${id}_${i}">-</b></div>`).join('')}
      <div class="acts">${(sm.actions || []).map((a, i) => `<button id="ac_${id}_${i}">${a.label}</button>`).join('')}</div></div>`;
  }).join('');
  lines.forEach(ctx => {
    const sm = ctx.def.summary || { metrics: [], actions: [] };
    (sm.actions || []).forEach((a, i) => { $(`ac_${ctx.ln.id}_${i}`).onclick = () => post(a.post, a.body || {}); });
  });
  renderLabels();
}
function renderLabels() {
  lines.forEach(ctx => (ctx.def.summary?.metrics || []).forEach((m, i) => { $(`ml_${ctx.ln.id}_${i}`).textContent = m.key ? Terms.t(m.key) : m.label; }));
}
function applyCards() {
  lines.forEach(ctx => {
    const s = ctx.state, sm = ctx.def.summary; if (!s || !sm) return;
    const st = sm.status || {}, alarm = st.alarm_path && get(s, st.alarm_path);
    const chip = $('st_' + ctx.ln.id);
    chip.textContent = alarm ? st.alarm_text : ((st.map || {})[String(get(s, st.path))] || '-');
    chip.className = 'chip' + (alarm ? ' alarm' : (String(get(s, st.path)) === '1' || get(s, st.path) === true ? ' on' : ''));
    (sm.metrics || []).forEach((m, i) => { $(`mv_${ctx.ln.id}_${i}`).textContent = fmtMetric(m, s); });
  });
}

// ---------------------------------------------------------------- 공장 전체 수치 (화면 오른쪽 위) + 캡처
const FAULT_NAMES = { weld_slow: '용접 속도 저하', press_down: '프레스 정지', paint_down: '도장 정지' };
function hudLines() {
  const by = id => lines.find(c => c.ln.id === id)?.state;
  const p = by('press'), l = by('logistics'), c = by('cobot'), m = by('machining');
  if (!p || !l || !c || !m) return [];
  const good = p.counts?.good ?? 0, scrap = p.counts?.scrap ?? 0, tot = good + scrap;
  const low = (l.kpi?.low_stock || []).map(k => l.stock?.[k]?.name || k);
  const o = l.outbound || {};
  const out = [
    ['프레스 라인', `양품 ${good} · 불량 ${scrap}${tot ? ` (${(scrap / tot * 100).toFixed(1)}%)` : ''} · ${p.running ? '가동' : '정지'}`],
    ['가공 라인', `양품 ${m.D0 ?? 0} · 불량 ${m.D2 ?? 0} · ${m.ai?.alarm ? 'AI 이상 감지' : 'AI 정상'}`],
    ['협동로봇 셀', `검사 ${c.counts?.inspected ?? 0} · 불량 ${c.counts?.ng ?? 0} · 파렛트 ${c.counts?.pallets ?? 0}`],
    ['출하', `${l.counts?.shipped_pcs ?? 0}개 출하 · 트럭 ${o.loaded ?? 0}/${o.capacity ?? 4}`],
    ['원자재', low.length ? `부족: ${low.join(', ')}` : '재고 정상'],
    ['재공품', `프레스 라인 ${p.kpi?.wip ?? 0}개 (기다림 ${p.kpi?.waiting ?? 0})`],
  ];
  const f = FAULT_NAMES[p.fault];
  if (f) out.push(['결함', f + ' 주입 중']);
  return out;
}
function applyHud() {
  const h = $('hud'); if (!h) return;
  const rows = hudLines();
  h.innerHTML = rows.map(([k, v]) => `<div class="row"><span>${k}</span><b>${v}</b></div>`).join('');
  h.style.display = rows.length && (!$('hudOn') || $('hudOn').checked) ? 'block' : 'none';
}
function capture() {
  // 3D 화면에 수치 박스와 데모 설명을 그려 넣은 한 장의 그림으로 저장한다 (README, 보고서용)
  renderer.render(scene, camera);
  const src = renderer.domElement, w = src.width || window.innerWidth, h = src.height || window.innerHeight;
  const cv = document.createElement('canvas'); cv.width = w; cv.height = h;
  const g = cv.getContext('2d'), k = w / (window.innerWidth || w);
  g.drawImage(src, 0, 0, w, h);
  g.font = `${Math.round(13 * k)}px "Malgun Gothic", sans-serif`;
  const rows = ($('hud') && $('hud').style.display !== 'none') ? hudLines() : [];
  if (rows.length) {
    const bw = 330 * k, lh = 20 * k, bh = rows.length * lh + 14 * k, x0 = w - bw - 12 * k, y0 = 12 * k;
    g.fillStyle = 'rgba(27,32,39,0.88)'; g.fillRect(x0, y0, bw, bh);
    rows.forEach(([a, b], i) => { g.fillStyle = '#8a94a3'; g.fillText(a, x0 + 10 * k, y0 + 20 * k + i * lh); g.fillStyle = '#e6e9ee'; g.fillText(b, x0 + 86 * k, y0 + 20 * k + i * lh); });
  }
  const cap = $('demoCap') && $('demoCap').style.display !== 'none' ? $('demoCap').textContent : '';
  if (cap) {
    g.font = `bold ${Math.round(17 * k)}px "Malgun Gothic", sans-serif`;
    const tw = g.measureText(cap).width + 40 * k;
    g.fillStyle = 'rgba(27,32,39,0.88)'; g.fillRect((w - tw) / 2, 14 * k, tw, 38 * k);
    g.fillStyle = '#e6e9ee'; g.fillText(cap, (w - tw) / 2 + 20 * k, 40 * k);
  }
  const d = new Date(), z = n => String(n).padStart(2, '0');
  const a = document.createElement('a');
  a.download = `smart-factory_${d.getFullYear()}${z(d.getMonth() + 1)}${z(d.getDate())}_${z(d.getHours())}${z(d.getMinutes())}${z(d.getSeconds())}.png`;
  a.href = cv.toDataURL('image/png'); a.click();
}

// ---------------------------------------------------------------- 시작
async function poll() {
  try {
    const all = await (await fetch('/api/factory/state')).json();
    lines.forEach(ctx => { ctx.state = all[ctx.ln.state]; });
    applyCards();
    applyHud();
  } catch (e) { /* 서버가 잠시 응답하지 않아도 다음 주기에 다시 시도한다 */ }
}
function resize() {
  const w = window.innerWidth, h = window.innerHeight;
  renderer.setSize(w, h); camera.aspect = w / h; camera.updateProjectionMatrix();
  if (fit && !userMoved) fitOverview();
}
window.addEventListener('resize', resize);

let last = performance.now();
function loop(now) {
  const dt = Math.min(0.1, (now - last) / 1000); last = now; clock.now = now; clock.dt = dt;
  frame(dt);
  stepCamera();
  controls.update();
  renderer.render(scene, camera);
  requestAnimationFrame(loop);
}

(async () => {
  try {
    const layout = await (await fetch('/api/factory/layout')).json();
    document.title = layout.title || '스마트 팩토리';
    scene.background = new THREE.Color(layout.background || '#0f1216');
    for (const ln of layout.lines) {
      const ctx = buildLine(ln, await (await fetch('/api/scene/' + ln.scene)).json());
      ctx.binds.forEach(b => { b.ctx = ctx; });
      lines.push(ctx);
      if (ln.title_pos) {         // 라인 이름판
        const c = document.createElement('canvas'); c.width = 320; c.height = 80;
        const tex = new THREE.CanvasTexture(c); tex.colorSpace = THREE.SRGBColorSpace;
        const sp = new THREE.Sprite(new THREE.SpriteMaterial({ map: tex, transparent: true, depthTest: true }));
        sp.userData = { text: ln.name, canvas: c }; sp.renderOrder = 10;
        sp.position.set(...ln.title_pos); sp.scale.set(4.4, 1.1, 1); scene.add(sp); drawLabel(sp);
      }
      views[ln.id] = { position: [ln.offset[0] + ctx.def.camera.position[0], ln.offset[1] + ctx.def.camera.position[1], ln.offset[2] + ctx.def.camera.position[2]],
                       target: [ln.offset[0] + ctx.def.camera.target[0], ln.offset[1] + ctx.def.camera.target[1], ln.offset[2] + ctx.def.camera.target[2]] };
    }
    for (const ln of layout.lines) {          // 장면 안의 세부 시점(press, weld, paint, inbound, outbound ...)도 'press:weld' 같은 이름으로 쓸 수 있다
      const ctx = lines.find(c => c.ln.id === ln.id);
      for (const [nm, v] of Object.entries(ctx.def.views || {})) {
        views[`${ln.id}:${nm}`] = { position: v.position.map((x, i) => x + ln.offset[i]), target: v.target.map((x, i) => x + ln.offset[i]) };
      }
    }
    const dir = layout.camera.position.map((v, i) => v - layout.camera.target[i]), len = Math.hypot(...dir) || 1;
    const target = [(bounds.min[0] + bounds.max[0]) / 2, 0, (bounds.min[2] + bounds.max[2]) / 2];   // 전체 범위의 가운데를 바라본다
    fit = { target, dir: dir.map(v => v / len) };
    $('views').innerHTML = `<button id="v_overview">전체</button>` + lines.map(c => `<button id="v_${c.ln.id}">${c.ln.name}</button>`).join('');
    $('v_overview').onclick = () => setView('overview');
    lines.forEach(c => { $('v_' + c.ln.id).onclick = () => setView(c.ln.id); });
    buildCards();
    if ($('demoBtn')) $('demoBtn').onclick = demoToggle;
    if ($('capBtn')) $('capBtn').onclick = capture;
  } catch (e) {
    $('msg').textContent = '공장 장면을 불러오지 못했습니다: ' + e;
    return;
  }
  $('labels').onchange = () => { labelSprites.forEach(l => { l.visible = $('labels').checked; }); };
  $('termsMode').value = Terms.mode();
  Terms.apply(document);
  $('termsMode').onchange = () => { Terms.setMode($('termsMode').value); Terms.apply(document); labelSprites.forEach(drawLabel); renderLabels(); };
  resize(); fitOverview();
  const focus = new URLSearchParams(location.search).get('focus');          // 예: ?focus=cobot (MES 라인별 페이지에 끼울 때)
  if (focus && views[focus]) setView(focus);
  if (new URLSearchParams(location.search).get('demo') === '1') demoToggle();      // ?demo=1 : 열자마자 데모 시작 (영상 녹화용)
  poll(); setInterval(poll, 100);
  window.__twin3dReady = true;
  $('msg').style.display = 'none';
  requestAnimationFrame(loop);
})();
