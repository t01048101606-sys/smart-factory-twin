"""범용 3D 뷰어(src/static/linescene.js)와 장면 JSON(src/scenes/press_weld_paint.json)을 확인합니다.

1) 장면 JSON이 시뮬레이터 상태와 맞는지 (path 가 모두 상태에 있는지, 부품 구간이 모든 칸을 덮는지)
2) 가짜 three.js 위에서 뷰어를 실행: 오류, NaN, 부품과 램프 반영
3) 서버의 /3d/line, /api/line/* 경로
(실제로 화면에 어떻게 보이는지는 브라우저에서 확인해야 합니다. Node.js 필요)

실행 (프로젝트 폴더에서):  python tests/test_linescene.py
"""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
from line_sim import LineSim, ELEMENTS  # noqa: E402

SCENE = json.loads((ROOT / "src" / "scenes" / "press_weld_paint.json").read_text(encoding="utf-8"))


def get(obj, path):
    for k in path.split("."):
        if not isinstance(obj, dict) or k not in obj:
            return KeyError
        obj = obj[k]
    return obj


# ---- 1) 장면 JSON 일관성 -----------------------------------------------------------------
sim = LineSim(); sim.start(); sim.advance(45)
state = sim.state()
ids = [o["id"] for o in SCENE["objects"] if "id" in o]
assert len(ids) == len(set(ids)), "오브젝트 id 가 겹칩니다"
def check(o):
    assert o["shape"] in ("box", "cylinder", "sphere", "belt", "label", "group", "light"), o
    assert len(o["pos"]) == 3, o
    if o["shape"] == "box":
        assert len(o["size"]) == 3
    for a in o.get("anim", []):
        assert get(state, a["path"]) is not KeyError, f"상태에 없는 path: {a['path']} ({o.get('id')})"
        assert a["prop"] in ("x", "y", "z", "visible", "emissive", "lamp", "color", "rotate", "spin", "intensity"), a
        if a["prop"] in ("x", "y", "z"):
            assert "from" in a and "to" in a
        if a["prop"] in ("rotate", "spin"):
            assert a["axis"] in ("x", "y", "z"), a
        if a["prop"] == "lamp":
            need = {"empty", "working", "waiting", "down"} if a["path"].startswith("occ.") else {"working", "blocked", "starved", "down"}   # 재공품 띠 / 공정 램프
            assert set(a["map"]) >= need, a["path"]
    if o["shape"] == "belt":
        assert get(state, o["path"]) is not KeyError, o["path"]
    for c in o.get("children", []):
        check(c)


for o in SCENE["objects"]:
    check(o)
segs = SCENE["parts"]["segments"]
assert set(segs) == set(ELEMENTS), "부품 구간이 시뮬레이터의 칸과 다릅니다"
assert {"normal", "pressed", "welded", "painted", "defect"} <= set(SCENE["parts"]["colors"])
print(f"장면 JSON 확인: 오브젝트 {len(SCENE['objects'])}개, 모든 path 가 시뮬레이터 상태에 있음, 부품 구간 {len(segs)}개")

if not shutil.which("node"):
    print("Node.js 가 없어 뷰어 실행 시험을 건너뜁니다")
    sys.exit(0)

# ---- 2) 가짜 three.js 위에서 뷰어 실행 --------------------------------------------------------
sim = LineSim(); sim.start(); sim.advance(37.3)
st = sim.state()
assert any(p["stage"] == "press" for p in st["parts"]) and len(st["parts"]) >= 4
tmp = Path(tempfile.mkdtemp(prefix="linescene_"))
(tmp / "package.json").write_text('{"type":"module"}')
nm = tmp / "node_modules" / "three"
(nm / "addons" / "controls").mkdir(parents=True)
(nm / "package.json").write_text(json.dumps({"name": "three", "type": "module", "main": "index.js",
                                              "exports": {".": "./index.js", "./addons/*": "./addons/*"}}))
FAKE = (ROOT / "tests" / "fake_three.js").read_text(encoding="utf-8")
(nm / "index.js").write_text(FAKE)
(nm / "addons" / "controls" / "OrbitControls.js").write_text(
    "export class OrbitControls { constructor() { this.target = { set() {} }; } update() {} }")
JS = (ROOT / "src" / "static" / "linescene.js").read_text(encoding="utf-8")
names = sorted(set(re.findall(r"THREE\.(\w+)", JS)))
missing = [n for n in names if f"export class {n}" not in FAKE and f"export const {n}" not in FAKE and f"{n} =" not in FAKE]
assert not missing, f"가짜 three.js 에 없는 이름: {missing}"
shutil.copy(ROOT / "src" / "static" / "linescene.js", tmp / "linescene.js")
(tmp / "run.mjs").write_text(r'''
import { registry, check } from 'three';
const scene = JSON.parse(process.env.SCENE), state = JSON.parse(process.env.STATE);
const els = {};
const el = id => (els[id] ||= { id, textContent: '', style: {}, classList: { add() {} }, value: '', href: '', checked: true });
const ctx = new Proxy({}, { get: () => () => {}, set: () => true });
globalThis.window = globalThis;
globalThis.addEventListener = () => {};
globalThis.innerWidth = 1000; globalThis.innerHeight = 700; globalThis.devicePixelRatio = 1;
globalThis.location = { search: '?embed=1' };
globalThis.document = {
  title: '', activeElement: null, body: { classList: { add() {} }, appendChild() {} },
  getElementById: el, createElement: () => ({ width: 0, height: 0, getContext: () => ctx }),
  querySelectorAll: () => [],
};
globalThis.fetch = async url => ({ json: async () => (String(url).includes('scene') ? scene : state) });
let frames = 0, t = 0;
globalThis.requestAnimationFrame = cb => { if (frames++ < 150) { t += 33; setTimeout(() => cb(t), 0); } };
await import('./linescene.js');
await new Promise(r => setTimeout(r, 500));
check();
const parts = registry.meshes.filter(m => m.geometry.type === 'Box' && m.geometry.args[0] === 0.9 && m.geometry.args[1] === 0.22);
const lamps = registry.meshes.filter(m => m.geometry.type === 'Sphere' && m.geometry.args[0] === 0.28);
const grp = id => registry.groups.find(g => g.userData.id === id);
const slide = grp('press_slide'), hanger = grp('hanger'), yaw = grp('robot_yaw'), shoulder = grp('robot_shoulder'), elbow = grp('robot_elbow'), wrist = grp('robot_wrist');
const clamp0 = grp('weld_clamp0').children[0], flywheel = grp('press_flywheel');
console.log(JSON.stringify({
  ready: !!globalThis.__twin3dReady, renders: registry.renders, meshes: registry.meshes.length, sprites: registry.sprites.length,
  parts: parts.map(m => [m.visible, +m.position.x.toFixed(2), +m.position.y.toFixed(2), +m.position.z.toFixed(2), m.material.color.hex ?? m.material.color.value]),
  lamps: lamps.map(m => [m.material.color.value, +m.material.emissiveIntensity.toFixed(1)]),
  ramY: +slide.position.y.toFixed(3), hangerY: +hanger.position.y.toFixed(3),
  joints: [yaw.rotation.y, shoulder.rotation.z, elbow.rotation.z, wrist.rotation.z].map(v => +v.toFixed(3)), clampZ: +clamp0.rotation.z.toFixed(3), flyX: +flywheel.rotation.x.toFixed(3),
  hud: { good: els.c_good.textContent, tput: els.k_tput.textContent, bott: els.k_bott.textContent, press: els.u_press.textContent },
  title: els.title.textContent, cam: registry.camera.position,
}));
process.exit(0);
''')
r = subprocess.run(["node", "run.mjs"], cwd=tmp, capture_output=True, text=True, timeout=60,
                   env={**os.environ, "SCENE": json.dumps(SCENE), "STATE": json.dumps(st)})
assert r.returncode == 0, f"실행 오류:\n{r.stderr[-1500:]}"
out = json.loads(r.stdout.strip().splitlines()[-1])
print("뷰어 실행:", {k: out[k] for k in ("ready", "renders", "meshes", "sprites")})
assert out["ready"] and out["renders"] > 50 and out["sprites"] == sum(1 for o in SCENE["objects"] if o["shape"] == "label") and out["title"] == SCENE["title"]

# 부품: 상태의 부품마다 하나씩, 의도한 구간 안의 좌표에 있다
visible = [p for p in out["parts"] if p[0]]
assert len(visible) == len(st["parts"]), (len(visible), len(st["parts"]))
for p, src in zip(visible, st["parts"]):
    a, b = segs[src["stage"]]
    for ax, i in (("x", 1), ("y", 2), ("z", 3)):
        if "pos" in src:        # 시뮬레이터가 위치를 직접 준 부품 (행거에 매달린 도장 부품)
            assert abs(p[i] - src["pos"]["xyz".index(ax)]) < 0.06, (src["stage"], ax, p[i], src["pos"])
            continue
        lo, hi = sorted((a["xyz".index(ax)], b["xyz".index(ax)]))
        assert lo - 0.06 <= p[i] <= hi + 0.06, (src["stage"], ax, p[i], (lo, hi))
colors = SCENE["parts"]["colors"]
for p, src in zip(visible, st["parts"]):
    want = "defect" if src["defect"] else "painted" if src["painted"] else "welded" if src["welded"] else "pressed" if src["pressed"] else "normal"
    assert str(p[4]).lower() in (colors[want].lower(), colors[want]), (want, p[4])
print(f"부품 {len(visible)}개: 칸(구간) 안의 좌표와 공정 진행에 따른 색 확인")

# 램프: 공정 상태 색 / 프레스 램 높이: 상태의 ram 값에 대응
lamp_obj = {o["id"]: o for o in SCENE["objects"] if o.get("id", "").endswith("_lamp")}
want = sorted(lamp_obj["%s_lamp" % n]["anim"][0]["map"][st["stations"][n]["state"]] for n in ("press", "weld", "paint"))
assert sorted(l[0] for l in out["lamps"]) == want, (out["lamps"], want)
ramo = next(o for o in SCENE["objects"] if o.get("id") == "press_slide")["anim"][0]
exp = ramo["from"] + (ramo["to"] - ramo["from"]) * st["stations"]["press"]["ram"]
assert abs(out["ramY"] - exp) < 0.05, (out["ramY"], exp)
print(f"램프 색 3개, 프레스 슬라이드 높이({out['ramY']}) 반영 확인")
# 용접 로봇 관절, 클램프, 행거, 플라이휠이 상태를 따라간다 (뷰어 안의 값 = 장면 규칙으로 계산한 값)
rb = st["stations"]["weld"]["robot"]
for got, want_ in zip(out["joints"], (rb["yaw"], rb["shoulder"], rb["elbow"], rb["wrist"])):
    assert abs(got - want_) < 0.02, (out["joints"], rb)
clamp_anim = next(c for c in next(o for o in SCENE["objects"] if o.get("id") == "weld_clamp0")["children"][0]["anim"])
exp_clamp = clamp_anim["bias"] + st["stations"]["weld"]["clamp"] * clamp_anim["scale"]
assert abs(out["clampZ"] - exp_clamp) < 0.03, (out["clampZ"], exp_clamp)
han = next(o for o in SCENE["objects"] if o.get("id") == "hanger")["anim"][0]
exp_h = han["from"] + (han["to"] - han["from"]) * st["stations"]["paint"]["dip"]
assert abs(out["hangerY"] - exp_h) < 0.05, (out["hangerY"], exp_h)
assert out["flyX"] != 0 if st["running"] else True
print(f"용접 로봇 관절 {out['joints']}, 클램프 {out['clampZ']}, 행거 높이 {out['hangerY']}, 플라이휠 회전 반영 확인")
# 시점 맞춤: 창 비율(1000x700)에서 장면 폭(30)이 가로 화각 안에 들어오는 거리
import math
tan_v = math.tan(math.radians(45 / 2)); aspect = 1000 / 700
need = SCENE["fit"]["width"] / 2 / (tan_v * aspect)
tgt = SCENE["camera"]["target"]; cam = out["cam"]
dist = math.dist((cam["x"], cam["y"], cam["z"]), tgt)
assert need <= dist <= need * 1.3, (dist, need)
assert abs(cam["x"] - tgt[0]) < 1e-6      # 장면 중심을 정면으로 보는 방향 (옆으로 치우치지 않음)
print(f"시점 맞춤: 카메라 거리 {dist:.1f} (장면 폭이 들어오는 최소 거리 {need:.1f})")
print("HUD:", out["hud"])

# ---- 3) 서버 경로 ---------------------------------------------------------------------------------
class _Req:
    args = {}; _j = None
    def get_json(self, silent=True): return self._j
try:
    import flask  # noqa: F401
    real = True
except ImportError:
    real = False
if not real:
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
    sys.argv = ["server.py", "plc/1102"]
    import server as S
    S.events.log_path = None
    R, rq = S.app.routes, fm.request
    html = R[("GET", "/3d/line")]()
    assert "__IMPORTMAP__" not in html and "/static/linescene.js" in html
    assert R[("GET", "/api/line/scene")]()["title"] == SCENE["title"]
    post = lambda path, body: (setattr(rq, "_j", body), R[("POST", path)]())[1]
    assert post("/api/line/control", {"action": "start"}) == {"ok": True} and S.line.running
    assert post("/api/line/fault", {"mode": "weld_slow"}) == {"ok": True} and S.line.fault == "weld_slow"
    assert post("/api/line/speed", {"value": 4}) == {"ok": True} and S.line.speed == 4
    assert post("/api/line/fault", {"mode": "xx"})[1] == 400 and post("/api/line/speed", {"value": 99})[1] == 400
    assert post("/api/line/control", {"action": "reset"}) == {"ok": True} and not S.line.running
    S.line.start(); S.line.advance(30)
    assert R[("GET", "/api/line/state")]()["time"] > 0
    print("서버 경로 확인: /3d/line, scene, state, control, fault, speed (잘못된 값은 400)")
print("\n테스트 통과")
