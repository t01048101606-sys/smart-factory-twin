"""3D 트윈 화면(src/static/twin3d.js)을 가짜 three.js 위에서 실행해 봅니다.

가짜 three.js 는 twin3d.js 가 쓰는 부분만 흉내 냅니다. 그래서 오타, 정의되지 않은 변수, 계산 오류(NaN),
작업물이 의도한 위치로 가는지는 확인하지만, 실제로 화면에 어떻게 그려지는지는 확인하지 못합니다 (브라우저에서 직접 보세요).
서버의 /3d 경로(importmap 선택)도 함께 확인합니다.

실행 (프로젝트 폴더에서):  python tests/test_twin3d.py     (Node.js 필요)
"""
import json
import re
import shutil
import subprocess
import sys
import tempfile
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
JS = (ROOT / "src" / "static" / "twin3d.js").read_text(encoding="utf-8")

if not shutil.which("node"):
    print("Node.js 가 없어 3D 화면 시험을 건너뜁니다")
    sys.exit(0)

# ---- 1) 가짜 three.js 로 실행 -------------------------------------------------------------------
names = sorted(set(re.findall(r"THREE\.(\w+)", JS)))
tmp = Path(tempfile.mkdtemp(prefix="twin3d_"))
(tmp / "package.json").write_text('{"type":"module"}')
nm = tmp / "node_modules" / "three"
(nm / "addons" / "controls").mkdir(parents=True)
(nm / "package.json").write_text(json.dumps({"name": "three", "type": "module", "main": "index.js",
                                              "exports": {".": "./index.js", "./addons/*": "./addons/*"}}))
FAKE = r'''
export const registry = { meshes: [], lights: [], sprites: [] };
const vec = (x = 0, y = 0, z = 0) => ({ x, y, z, set(a, b, c) { this.x = a; this.y = b; this.z = c; return this; } });
class Obj { constructor() { this.position = vec(); this.scale = vec(1, 1, 1); this.rotation = vec(); this.visible = true; this.userData = {}; } }
const color = () => ({ setHex(v) { this.hex = v; } });
const asNum = (o, k) => { for (const key of ['position', 'scale']) { const v = o[key]; if (v && ![v.x, v.y, v.z].every(Number.isFinite)) throw new Error(`NaN in ${k}.${key}`); } };
export const RepeatWrapping = 1000, SRGBColorSpace = 'srgb';
export class Scene extends Obj { constructor() { super(); this.children = []; this.background = null; } add(o) { this.children.push(o); return o; } }
export class Color { constructor(v) { this.hex = v; } setHex(v) { this.hex = v; } }
export class PerspectiveCamera extends Obj { constructor() { super(); this.aspect = 1; } updateProjectionMatrix() {} }
export class WebGLRenderer { constructor() { this.shadowMap = {}; this.domElement = { addEventListener() {} }; } setPixelRatio() {} setSize() {} render() { registry.renders = (registry.renders || 0) + 1; } }
export class AmbientLight extends Obj {}
export class DirectionalLight extends Obj { constructor() { super(); this.shadow = { mapSize: {}, camera: {} }; } }
export class PointLight extends Obj { constructor() { super(); this.intensity = 0; registry.lights.push(this); } }
export class BoxGeometry { constructor(...a) { this.type = 'Box'; this.args = a; } }
export class CylinderGeometry { constructor(...a) { this.type = 'Cylinder'; this.args = a; } }
export class SphereGeometry { constructor(...a) { this.type = 'Sphere'; this.args = a; } }
export class PlaneGeometry { constructor(...a) { this.type = 'Plane'; this.args = a; } }
export class MeshStandardMaterial { constructor(o = {}) { Object.assign(this, o); this.color = color(); this.emissive = color(); if (this.emissiveIntensity === undefined) this.emissiveIntensity = 0; } }
export class SpriteMaterial { constructor(o = {}) { Object.assign(this, o); } }
export class CanvasTexture { constructor(c) { this.canvas = c; this.repeat = { set() {} }; this.offset = { x: 0, y: 0 }; } }
export class Mesh extends Obj { constructor(g, m) { super(); this.geometry = g; this.material = m; registry.meshes.push(this); } }
export class Sprite extends Obj { constructor(m) { super(); this.material = m; registry.sprites.push(this); } }
export function check() { for (const m of [...registry.meshes, ...registry.lights, ...registry.sprites]) asNum(m, m.geometry ? m.geometry.type : 'obj'); }
'''
(nm / "index.js").write_text(FAKE)
(nm / "addons" / "controls" / "OrbitControls.js").write_text(
    "export class OrbitControls { constructor() { this.target = { set() {} }; } update() {} }")
missing = [n for n in names if f"export class {n}" not in FAKE and f"export const {n}" not in FAKE and f"{n} =" not in FAKE]
assert not missing, f"가짜 three.js 에 없는 이름: {missing} (twin3d.js 가 새 API를 쓰기 시작했다면 가짜에도 추가하세요)"
shutil.copy(ROOT / "src" / "static" / "twin3d.js", tmp / "twin3d.js")

STATE = {
    "X0": 0, "X1": 1, "X2": 1, "X3": 0, "X4": 1, "X5": 0, "X6": 1, "X7": 0, "X8": 1, "X9": 1, "X0A": 0,
    "Y20": 0, "Y21": 0, "Y22": 1, "Y23": 0, "Y24": 0, "Y25": 0, "Y26": 0, "Y27": 1, "Y28": 1, "Y29": 0, "Y2A": 1, "Y2B": 1,
    "D0": 5, "D2": 4, "D4": 9, "D10": 30, "mode": "alternate", "fault": "cyl_slow",
    "ai": {"phase": "monitoring", "learned": 8, "warmup": 8, "alarm": True, "baseline": 3.6},
    "pieces": [
        {"stage": "feed", "t": 0.5, "metal": False}, {"stage": "drill", "t": 0, "metal": False},
        {"stage": "out", "t": 0.5, "metal": False}, {"stage": "belt", "t": 0.5, "metal": True},
        {"stage": "belt", "t": 1.0, "metal": False}, {"stage": "eject", "t": 1.0, "metal": True},
        {"stage": "binm", "t": 1.0, "metal": True}, {"stage": "end", "t": 1.0, "metal": False},
    ],
}
HARNESS = r'''
import { registry, check } from 'three';
const state = JSON.parse(process.env.STATE);
const els = {};
const el = id => (els[id] ||= { id, textContent: '', style: {}, classList: { add() {} }, value: '', href: '' });
const ctx = new Proxy({}, { get: () => () => {}, set: () => true });
globalThis.window = globalThis;
globalThis.addEventListener = () => {};
globalThis.innerWidth = 1000; globalThis.innerHeight = 700; globalThis.devicePixelRatio = 1;
globalThis.location = { search: '?embed=1' };
globalThis.document = {
  activeElement: null, body: { classList: { add() {} }, appendChild() {} },
  getElementById: el, createElement: () => ({ width: 0, height: 0, getContext: () => ctx }),
  querySelectorAll: () => [{ dataset: { dev: 'M101' } }],
};
globalThis.fetch = async () => ({ json: async () => state });
let frames = 0, t = 0; const pending = [];
globalThis.requestAnimationFrame = cb => { if (frames++ < 150) { t += 33; setTimeout(() => cb(t), 0); } };
await import('./twin3d.js');
await new Promise(r => setTimeout(r, 400));
check();
const pieces = registry.meshes.filter(m => m.geometry.type === 'Cylinder' && m.geometry.args[0] === 0.42);
const out = {
  ready: !!globalThis.__twin3dReady, renders: registry.renders, meshes: registry.meshes.length, sprites: registry.sprites.length,
  pieces: pieces.map(m => [m.visible, +m.position.x.toFixed(2), +m.position.y.toFixed(2), +m.position.z.toFixed(2)]),
  hud: { d0: els.d0.textContent, d4: els.d4.textContent, ai: els.aiState.textContent, fault: els.faultTxt.textContent },
  alarmLight: registry.lights[0].intensity,
  lampsEmissive: registry.meshes.filter(m => m.geometry.type === 'Sphere').map(m => +m.material.emissiveIntensity.toFixed(2)),
  to2d: els.to2d.href,
};
console.log(JSON.stringify(out));
process.exit(0);
'''
(tmp / "run.mjs").write_text(HARNESS)
import os
r = subprocess.run(["node", "run.mjs"], cwd=tmp, capture_output=True, text=True, timeout=60,
                   env={**os.environ, "STATE": json.dumps(STATE)})
assert r.returncode == 0, f"실행 오류:\n{r.stderr[-1500:]}"
out = json.loads(r.stdout.strip().splitlines()[-1])
print("3D 화면 실행:", {k: out[k] for k in ("ready", "renders", "meshes", "sprites")})
assert out["ready"] and out["renders"] > 50 and out["sprites"] == 8
assert {k: str(v) for k, v in out["hud"].items()} == {"d0": "5", "d4": "9", "ai": "이상 감지!", "fault": "실린더 속도 저하"}, out["hud"]
assert out["to2d"] == "/?embed=1"

# 작업물 위치: workpiece.py 단계와 같은 규칙. (x, y, z) 허용 오차 0.05
exp = [(-5.2, 0.8, 0), (-3.5, 0.8, 0), (-3.5, 0.8, 1.6), (2.75, 0.8, 3.2), (9.0, 0.8, 3.2),
       (2.75, 0.5, 5.8), (2.75, 0.55, 5.8), (10.0, 0.8, 3.2)]
for i, (vis, x, y, z) in enumerate(out["pieces"]):
    ex, ey, ez = exp[i]
    assert vis and abs(x - ex) < .05 and abs(y - ey) < .05 and abs(z - ez) < .05, (i, (x, y, z), exp[i])
print("작업물 위치 8개(feed, drill, out, belt x2, eject, binm, end)가 의도한 좌표에 도달")
assert out["alarmLight"] > 0 and out["lampsEmissive"][1] > 1 and out["lampsEmissive"][2] > 1, out
print("경보 조명, 황색/녹색 램프 반영 확인")

# ---- 2) 서버 /3d 경로 -----------------------------------------------------------------------------
class _Req:
    args = {}
    def get_json(self, silent=True): return None
try:
    import flask  # noqa: F401
    real = True
except ImportError:
    real = False
    fm = types.ModuleType("flask")
    class Flask:
        def __init__(self, name, static_folder=None):
            self.routes, self.static_folder = {}, static_folder
        def get(self, p): return self._r(("GET", p))
        def post(self, p): return self._r(("POST", p))
        def _r(self, k):
            def d(fn): self.routes[k] = fn; return fn
            return d
        def run(self, *a, **k): pass
    fm.Flask, fm.request = Flask, _Req()
    fm.jsonify = lambda *a, **k: (a[0] if a else k)
    fm.send_from_directory = lambda *a, **k: "html"
    sys.modules["flask"] = fm
if not real:
    sys.path.insert(0, str(ROOT / "src"))
    sys.argv = ["server.py", "plc/1102"]
    import server as S
    S.events.log_path = None
    html = S.app.routes[("GET", "/3d")]()
    assert "__IMPORTMAP__" not in html
    imap = json.loads(re.search(r'<script type="importmap">(.*?)</script>', html, re.S).group(1))["imports"]
    vendor = ROOT / "src" / "static" / "vendor"
    if (vendor / "three.module.js").exists():
        assert imap["three"] == "/static/vendor/three.module.js"
        print("/3d: 로컬 three.js 사용 (오프라인 가능)")
    else:
        assert imap["three"].startswith("https://cdn.jsdelivr.net/npm/three@") and imap["three/addons/"].endswith("/examples/jsm/")
        print("/3d: 로컬 파일이 없어 CDN 사용:", imap["three"])
    assert "/static/twin3d.js" in html and '<div id="hud"' in html
print("\n테스트 통과")
