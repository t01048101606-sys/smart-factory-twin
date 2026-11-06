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
  for (const o of def.objects) {
    if (o.shape === 'label') {
      const c = document.createElement('canvas'); c.width = 320; c.height = 80;
      const tex = new THREE.CanvasTexture(c); tex.colorSpace = THREE.SRGBColorSpace;
      const s = new THREE.Sprite(new THREE.SpriteMaterial({ map: tex, transparent: true, depthTest: true }));
      s.renderOrder = 10; s.userData = { key: o.key, text: o.text, canvas: c };
      s.position.set(...P(o.pos)); const w = o.w || 2.4; s.scale.set(w, w / 4, 1);
      scene.add(s); labelSprites.push(s); drawLabel(s);
    } else if (o.shape === 'belt') {
      const c = document.createElement('canvas'); c.width = 64; c.height = 16;
      const g = c.getContext('2d');
      g.fillStyle = '#2f5a52'; g.fillRect(0, 0, 64, 16); g.fillStyle = '#5ad6bd'; g.fillRect(0, 6, 28, 4);
      const tex = new THREE.CanvasTexture(c); tex.wrapS = THREE.RepeatWrapping; tex.repeat.set(o.size[0], 1); tex.colorSpace = THREE.SRGBColorSpace;
      const m = new THREE.Mesh(new THREE.PlaneGeometry(o.size[0], o.size[1]), new THREE.MeshStandardMaterial({ map: tex, roughness: 0.8 }));
      m.rotation.x = -Math.PI / 2; m.position.set(...P(o.pos)); m.receiveShadow = true; scene.add(m);
      ctx.belts.push({ tex, path: o.path });
    } else if (o.shape === 'light') {
      const l = new THREE.PointLight(o.color || 0xffffff, o.intensity || 0, o.distance || 30);
      l.position.set(...P(o.pos)); scene.add(l);
      (o.anim || []).forEach(a => ctx.binds.push({ obj: l, ...a }));
    } else if (o.shape === 'rod') {
      const m = new THREE.Mesh(new THREE.CylinderGeometry(o.r, o.r, 1, 20), new THREE.MeshStandardMaterial({ color: o.color || '#2f9bff', roughness: 0.3, metalness: 0.6 }));
      if (o.axis === 'x') m.rotation.z = Math.PI / 2;
      if (o.axis === 'z') m.rotation.x = Math.PI / 2;
      m.castShadow = true; scene.add(m);
      const rod = { axis: o.axis, dir: o.dir || 1, start: P(o.start) };
      setRod(m, rod, o.len ?? 1);
      (o.anim || []).forEach(a => ctx.binds.push({ obj: m, rod, ...a }));
    } else {
      let geo;
      if (o.shape === 'box') geo = new THREE.BoxGeometry(...o.size);
      else if (o.shape === 'cylinder') geo = new THREE.CylinderGeometry(o.rt ?? o.r, o.rb ?? o.r, o.h, 28);
      else if (o.shape === 'sphere') geo = new THREE.SphereGeometry(o.r, 24, 16);
      else continue;
      const m = new THREE.Mesh(geo, shapeMat(o));
      m.position.set(...P(o.pos)); if (o.rot) m.rotation.set(...o.rot);
      m.castShadow = o.opacity == null; m.receiveShadow = true; scene.add(m);
      (o.anim || []).forEach(a => {
        const b = { obj: m, ...a };
        if (['x', 'y', 'z'].includes(a.prop)) { b.from = a.from + off[AX[a.prop]]; b.to = a.to + off[AX[a.prop]]; }   // 위치는 라인 offset 을 더한다
        if (a.prop === 'fill') b.base_y = a.base_y + off[1];
        ctx.binds.push(b);
      });
    }
  }
  if (def.parts) {
    const ps = def.parts;
    ctx.partGeo = ps.shape === 'cylinder' ? new THREE.CylinderGeometry(ps.r, ps.r, ps.h, 28) : new THREE.BoxGeometry(...ps.size);
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
const clock = { now: 0 };
function applyBind(b, v, k) {
  const m = b.obj;
  switch (b.prop) {
    case 'x': case 'y': case 'z': {
      const target = b.from + (b.to - b.from) * clamp01(Number(v) || 0);
      b.cur = ease(b.cur ?? target, target, k); m.position[b.prop] = b.cur; break;
    }
    case 'len': {
      const target = b.from + (b.to - b.from) * clamp01(Number(v) || 0);
      b.cur = ease(b.cur ?? target, target, k); setRod(m, b.rod, b.cur); break;
    }
    case 'fill': {   // 막대 높이: 값(0~1)만큼 아래에서부터 채운다 (재고 수준)
      const f = Math.max(0.03, clamp01(Number(v) || 0));
      b.cur = ease(b.cur ?? f, f, k); m.scale.y = b.cur; m.position.y = b.base_y + b.size_y * b.cur / 2; break;
    }
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
      m.userData.placed = true; m.material = partMaterial(ctx, p);
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

// ---------------------------------------------------------------- 시작
async function poll() {
  try {
    const all = await (await fetch('/api/factory/state')).json();
    lines.forEach(ctx => { ctx.state = all[ctx.ln.state]; });
    applyCards();
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
  const dt = Math.min(0.1, (now - last) / 1000); last = now; clock.now = now;
  frame(dt);
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
    const dir = layout.camera.position.map((v, i) => v - layout.camera.target[i]), len = Math.hypot(...dir) || 1;
    const target = [(bounds.min[0] + bounds.max[0]) / 2, 0, (bounds.min[2] + bounds.max[2]) / 2];   // 전체 범위의 가운데를 바라본다
    fit = { target, dir: dir.map(v => v / len) };
    $('views').innerHTML = `<button id="v_overview">전체</button>` + lines.map(c => `<button id="v_${c.ln.id}">${c.ln.name}</button>`).join('');
    $('v_overview').onclick = () => setView('overview');
    lines.forEach(c => { $('v_' + c.ln.id).onclick = () => setView(c.ln.id); });
    buildCards();
  } catch (e) {
    $('msg').textContent = '공장 장면을 불러오지 못했습니다: ' + e;
    return;
  }
  $('labels').onchange = () => { labelSprites.forEach(l => { l.visible = $('labels').checked; }); };
  $('termsMode').value = Terms.mode();
  Terms.apply(document);
  $('termsMode').onchange = () => { Terms.setMode($('termsMode').value); Terms.apply(document); labelSprites.forEach(drawLabel); renderLabels(); };
  resize(); fitOverview();
  poll(); setInterval(poll, 100);
  window.__twin3dReady = true;
  $('msg').style.display = 'none';
  requestAnimationFrame(loop);
})();
