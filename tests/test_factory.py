"""스마트 팩토리 통합 화면: 장면 JSON, 라인별 상태, 뷰어(factory.js)를 확인합니다.

1) 가공 라인 장면 JSON 의 모든 path 가 서버 상태에 있고, 부품 구간이 모든 단계를 덮는지
2) 공장 배치(factory.json)가 가리키는 장면과 상태가 있는지, 서버 경로
3) 가짜 three.js 에서 뷰어 실행: 두 라인이 offset 대로 배치되고, 로드 길이, 부품 위치와 색, 램프, 경보 조명, 요약 카드, 용어 전환이 맞는지
(실제로 화면에 어떻게 보이는지는 브라우저에서 확인해야 합니다. Node.js 필요)

실행 (프로젝트 폴더에서):  python tests/test_factory.py
"""
import json
import math
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

# ---- 서버를 가짜 Flask 로 불러서 실제 상태를 만든다
try:
    import flask  # noqa: F401
    raise SystemExit("이 시험은 Flask 가 없는 환경용 가짜 Flask 를 씁니다 (실제 Flask 가 있으면 app.test_client() 로 바꿔 쓰세요)")
except ImportError:
    pass
fm = types.ModuleType("flask")


class _Req:
    args = {}; _j = None
    def get_json(self, silent=True): return self._j


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
import server as S  # noqa: E402
from logistics_sim import LAYOUT as _LL  # noqa: E402
LAYOUT_IN, LAYOUT_OUT = _LL["inbound_x"], _LL["out_x"]      # 트럭 중심 x 의 시작과 도크 위치
S.events.log_path = None
R = S.app.routes

S.sim.scan(["M101"])
for _ in range(700):                      # 가공 라인을 35초 돌린다
    S.sim.scan([]); S.tracker.update(S.sim.dev); S.view.update(S.sim.dev)
S.line.start(); S.line.advance(50)        # 프레스 라인을 50초 돌린다
for _ in range(60):                       # 물류 구역: 철판 재고를 바닥내서 입고 트럭이 오게 하고, 파렛트 2개를 만들어 AGV와 트럭이 움직이게 한다
    S.logi.consume("press")
for i in range(10):
    S.logi.add_exit(f"B-T-{i:03d}", "good")
S.logi.advance(12)                    # 입고 트럭이 하역 중이고, 첫 파렛트를 AGV가 옮기는 시점
S.cobot.reset()                       # 협동로봇 셀: 양품, 불량, 양품, 양품을 넣고 세 번째를 집어 든 순간까지 (파렛트에 1개, NG 상자에 1개, 하나는 들고 있음)
for i, r in enumerate(["good", "scrap", "good", "good"]):
    S.cobot.add_part(f"B-C-{i}", r)
for _ in range(4000):
    S.cobot.step(0.05)
    if S.cobot.counts["picks"] >= 3 and any(p["stage"] == "carried" for p in S.cobot.state()["parts"]):
        break
fs = R[("GET", "/api/factory/state")]()
mst, pst, lst, cst = fs["machining"], fs["press"], fs["logistics"], fs["cobot"]
assert any(p["stage"] == "carried" for p in cst["parts"]) and cst["pallet"]["count"] == 1 and len(S.cobot.ng) == 1
assert lst["parts"] and lst["inbound"]["state"] != "idle" and lst["stock"]["steel"]["level"] in ("low", "ok")
assert mst["pieces"] and pst["parts"] and set(mst["derived"]) == {"sup", "out", "ej", "tip"}

def _step(a, k):
    if isinstance(a, dict):
        return a.get(k, KeyError)
    if isinstance(a, list) and k.isdigit() and int(k) < len(a):        # cartons.0.p 처럼 리스트 인덱스도 읽는다 (뷰어의 get 과 같다)
        return a[int(k)]
    return KeyError


get = lambda o, p: __import__("functools").reduce(_step, p.split("."), o)
MSC = json.loads((ROOT / "src" / "scenes" / "machining.json").read_text(encoding="utf-8"))
PSC = json.loads((ROOT / "src" / "scenes" / "press_weld_paint.json").read_text(encoding="utf-8"))
LSC = json.loads((ROOT / "src" / "scenes" / "logistics.json").read_text(encoding="utf-8"))
CSC = json.loads((ROOT / "src" / "scenes" / "cobot.json").read_text(encoding="utf-8"))
terms = json.loads((ROOT / "src" / "terms.json").read_text(encoding="utf-8"))["terms"]


def walk(objs):                           # 그룹(관절)의 자식까지
    for o in objs:
        yield o
        yield from walk(o.get("children", []))


def check_scene(sc, st, stages):
    paths = []
    for o in walk(sc["objects"]):
        for a in o.get("anim", []):
            paths += [a["path"]] + ([a["blink_path"]] if "blink_path" in a else [])
        if o["shape"] == "belt":
            paths.append(o["path"])
        if o["shape"] == "label" and o.get("key"):
            assert o["key"] in terms, o["key"]
    for p in paths:
        assert get(st, p) is not KeyError, f"상태에 없는 path: {p}"
    assert set(sc["parts"]["segments"]) >= stages, set(sc["parts"]["segments"])
    for m in sc["summary"]["metrics"]:
        assert get(st, m["path"]) is not KeyError, m
    assert get(st, sc["summary"]["status"]["path"]) is not KeyError
    return len(paths)


n1 = check_scene(MSC, mst, {"feed", "drill", "out", "belt", "eject", "binm", "end"})
n2 = check_scene(PSC, pst, {"press", "c1", "weld", "c2", "paint", "c3"})
n3 = check_scene(LSC, lst, set())
n4 = check_scene(CSC, cst, set())
print(f"장면 JSON 확인: 가공 라인 오브젝트 {len(MSC['objects'])}개(연결 path {n1}개), 프레스 라인 {len(PSC['objects'])}개(path {n2}개), 물류 구역 {len(LSC['objects'])}개(path {n3}개), 협동로봇 셀 {len(CSC['objects'])}개(path {n4}개, 로봇팔 관절 그룹 포함) - 모두 서버 상태에 있음")

# ---- 2) 공장 배치와 서버 경로
layout = R[("GET", "/api/factory/layout")]()
assert [l["id"] for l in layout["lines"]] == ["machining", "press", "logistics", "cobot"]
for l in layout["lines"]:
    assert R[("GET", "/api/scene/<name>")](l["scene"])["title"] and l["state"] in fs
assert R[("GET", "/api/scene/<name>")]("nope")[1] == 404
assert "/static/factory.js" in R[("GET", "/3d/factory")]() and "__IMPORTMAP__" not in R[("GET", "/3d/factory")]()
html = (ROOT / "src" / "static" / "factory.html").read_text(encoding="utf-8"); fjs = (ROOT / "src" / "static" / "factory.js").read_text(encoding="utf-8")
assert "body.scene #bar, body.scene #cards { display:none; }" in html and "embed === 'scene'" in fjs      # MES 대시보드에 끼우는 3D 전용 모드
print("공장 배치/경로 확인: /3d/factory, /api/factory/layout, /api/scene/<name>, /api/factory/state")

if not shutil.which("node"):
    print("Node.js 가 없어 뷰어 실행 시험을 건너뜁니다"); sys.exit(0)

# ---- 3) 가짜 three.js 위에서 뷰어 실행
tmp = Path(tempfile.mkdtemp(prefix="factory_"))
(tmp / "package.json").write_text('{"type":"module"}')
nm = tmp / "node_modules" / "three"
(nm / "addons" / "controls").mkdir(parents=True)
(nm / "package.json").write_text(json.dumps({"name": "three", "type": "module", "main": "index.js", "exports": {".": "./index.js", "./addons/*": "./addons/*"}}))
FAKE = (ROOT / "tests" / "fake_three.js").read_text(encoding="utf-8")
(nm / "index.js").write_text(FAKE)
(nm / "addons" / "controls" / "OrbitControls.js").write_text("export class OrbitControls { constructor() { this.target = { x: 0, y: 0, z: 0, set(a, b, c) { this.x = a; this.y = b; this.z = c; }, toArray() { return [this.x, this.y, this.z]; }, copy(o) { this.x = o.x; this.y = o.y; this.z = o.z; }, clone() { return { ...this }; } }; } update() {} }")
JS = (ROOT / "src" / "static" / "factory.js").read_text(encoding="utf-8")
names = sorted(set(re.findall(r"THREE\.(\w+)", JS)))
missing = [n for n in names if f"export class {n}" not in FAKE and f"export const {n}" not in FAKE and f"{n} =" not in FAKE]
assert not missing, f"가짜 three.js 에 없는 이름: {missing}"
for f in ("factory.js", "terms.js"):
    shutil.copy(ROOT / "src" / "static" / f, tmp / f)
(tmp / "run.mjs").write_text(r'''
import { registry, check } from 'three';
const E = process.env, layout = JSON.parse(E.LAYOUT), scenes = JSON.parse(E.SCENES), state = JSON.parse(E.STATE), terms = JSON.parse(E.TERMS);
const els = {};
const el = id => (els[id] ||= { id, textContent: '', innerHTML: '', style: {}, classList: { add() {} }, value: '', href: '', checked: true, className: '' });
const texts = [];
const ctx = new Proxy({}, { get: (t, k) => (k === 'fillText' ? (txt) => { texts.push(txt); } : () => {}), set: () => true });
globalThis.window = globalThis;
globalThis.addEventListener = () => {};
globalThis.innerWidth = 1000; globalThis.innerHeight = 700; globalThis.devicePixelRatio = 1;
globalThis.location = { search: process.env.SEARCH || '?embed=1' };
globalThis.localStorage = { getItem: () => null, setItem() {} };
globalThis.document = { title: '', activeElement: null, body: { classList: { add() {} }, appendChild() {} }, getElementById: el,
  createElement: () => ({ width: 0, height: 0, getContext: () => ctx }), querySelectorAll: () => [] };
globalThis.fetch = async url => {
  url = String(url);
  const body = url.includes('layout') ? layout : url.includes('/api/scene/') ? scenes[url.split('/').pop()] : url.includes('terms') ? terms : state;
  return { json: async () => body };
};
let frames = 0, t = 0;
globalThis.requestAnimationFrame = cb => { if (frames++ < 200) { t += 33; setTimeout(() => cb(t), 0); } };
await import('./terms.js');
await import('./factory.js');
await new Promise(r => setTimeout(r, 600));
if (!els.termsMode) { console.error('뷰어 초기화 실패: ' + (els.msg && els.msg.textContent)); process.exit(2); }
check();
const cyls = registry.meshes.filter(m => m.geometry.type === 'Cylinder');
const rods = cyls.filter(m => m.geometry.args[2] === 1).map(m => ({ r: m.geometry.args[0], sy: +m.scale.y.toFixed(3), x: +m.position.x.toFixed(3), y: +m.position.y.toFixed(3), z: +m.position.z.toFixed(3), rx: m.rotation.x, rz: m.rotation.z }));
const machParts = registry.meshes.filter(m => m.geometry.type === 'Cylinder' && m.geometry.args[0] === 0.42 && m.geometry.args[2] === 0.6);   // 높이 0.6 = 가공 라인 워크 (같은 반지름의 협동로봇 팔꿈치 관절 제외)
const pressParts = registry.meshes.filter(m => m.geometry.type === 'Box' && m.geometry.args[0] === 0.9 && m.geometry.args[1] === 0.22);
const part = m => [m.visible, +m.position.x.toFixed(2), +m.position.y.toFixed(2), +m.position.z.toFixed(2), m.material.color.value];
const lamps = registry.meshes.filter(m => m.geometry.type === 'Sphere').map(m => [m.geometry.args[0], +m.position.x.toFixed(1), m.material.color.value]);
const partGroups = registry.groups.filter(g => g.userData && g.userData.part);
const pallets = partGroups.map(g => [g.visible, +g.position.x.toFixed(2), +g.position.y.toFixed(2), +g.position.z.toFixed(2), g.userData.kids.filter(k => k.mesh.visible && k.rule).length]);
const fills = registry.meshes.filter(m => m.geometry.type === 'Box' && m.geometry.args[0] === 1.0 && m.geometry.args[1] === 1.0 && m.geometry.args[2] === 1.0).map(m => [+m.scale.y.toFixed(3), +m.position.y.toFixed(3)]);
const cartons = registry.meshes.filter(m => m.geometry.type === 'Box' && m.geometry.args[0] === 0.5 && m.geometry.args[1] === 0.3 && m.geometry.args[2] === 0.4).map(m => [m.visible, +m.position.x.toFixed(3)]);
const telescopic = registry.meshes.filter(m => m.geometry.type === 'Box' && m.geometry.args[1] >= 0.34 && m.geometry.args[1] <= 0.42 && m.geometry.args[2] >= 0.7 && m.geometry.args[2] <= 0.84).map(m => [m.geometry.args[2], +m.position.x.toFixed(3)]);
const forks = registry.meshes.filter(m => m.geometry.type === 'Box' && m.geometry.args[0] === 1.15 && m.geometry.args[1] === 0.07).map(m => +m.position.y.toFixed(3));
const groups = Object.fromEntries(registry.groups.filter(g => g.userData && g.userData.id).map(g => [g.userData.id, { rot: [g.rotation.x, g.rotation.y, g.rotation.z], pos: [g.position.x, g.position.y, g.position.z] }]));
const fingers = registry.meshes.filter(m => m.geometry.type === 'Box' && m.geometry.args[0] === 0.5 && m.geometry.args[1] === 0.5 && m.geometry.args[2] === 0.1).map(m => +m.position.z.toFixed(3));
const wheelRot = registry.groups.filter(g => g.userData && g.userData.id && g.userData.id.includes('_wheel_')).map(g => [g.userData.id, +g.rotation.z.toFixed(3)]);
const labelsField = texts.slice(); texts.length = 0;
els.termsMode.value = 'lab'; els.termsMode.onchange();
const labelsLab = texts.slice();
const cam = registry.camera.position;
console.log(JSON.stringify({
  ready: !!globalThis.__twin3dReady, renders: registry.renders, meshes: registry.meshes.length, sprites: registry.sprites.length,
  groups, fingers, cartons, telescopic, forks, wheelRot, cst: els.st_cobot.textContent, cv: [0, 1, 2, 3, 4].map(i => els['mv_cobot_' + i].textContent),
  rods, machParts: machParts.map(part), pressParts: pressParts.map(part), pallets, fills, lamps, light: registry.lights[0] && registry.lights[0].intensity,
  st: { m: els.st_machining.textContent, p: els.st_press.textContent, mcls: els.st_machining.className },
  mv: [0, 1, 2, 3].map(i => els['mv_machining_' + i].textContent), pv: [0, 1, 2, 3, 4].map(i => els['mv_press_' + i].textContent),
  lv: [0, 1, 2, 3, 4, 5].map(i => els['mv_logistics_' + i].textContent), lst: els.st_logistics.textContent,
  ml: els.ml_machining_0.textContent, labelsField: labelsField.slice(0, 40), labelsLab, cam: [cam.x, cam.y, cam.z],
  demoCap: els.demoCap && els.demoCap.textContent, demoBtn: els.demoBtn && els.demoBtn.textContent,
  views: els.views.innerHTML.includes('v_overview') && els.views.innerHTML.includes('v_press'),
}));
process.exit(0);
''')


def run(st, tag, search='?embed=1'):
    r = subprocess.run(["node", "run.mjs"], cwd=tmp, capture_output=True, text=True, timeout=60, env={
        **os.environ, "LAYOUT": json.dumps(layout), "SCENES": json.dumps({"machining": MSC, "press_weld_paint": PSC, "logistics": LSC, "cobot": CSC}),
        "STATE": json.dumps(st), "SEARCH": search, "TERMS": (ROOT / "src" / "terms.json").read_text(encoding="utf-8")})
    assert r.returncode == 0, f"실행 오류({tag}):\n{r.stderr[-1800:]}"
    return json.loads(r.stdout.strip().splitlines()[-1])


out = run(fs, "정상")
print("뷰어 실행:", {k: out[k] for k in ("ready", "renders", "meshes", "sprites")})
n_labels = sum(1 for sc in (MSC, PSC, LSC, CSC) for o in walk(sc["objects"]) if o["shape"] == "label")
assert out["ready"] and out["renders"] > 50 and out["sprites"] == n_labels + len(layout["lines"]), (out["sprites"], n_labels)   # 이름표 + 라인 이름판

# 로드: derived 값에 따라 길이와 위치가 정해진다 (가공 라인 offset z = -12)
d = mst["derived"]
exp_sup = 2.1 + (5.5 - 2.1) * d["sup"]; exp_out = 2.4 + 3.2 * d["out"]; exp_ej = 0.7 + 2.3 * d["ej"]; exp_tip = 0.5 + 1.65 * d["tip"]
rods = out["rods"]
sup = next(r for r in rods if r["rz"] and abs(r["r"] - 0.14) < 1e-9)
tr = next(r for r in rods if r["rx"] and abs(r["x"] - (-3.5)) < 1e-6)
so = next(r for r in rods if r["rx"] and abs(r["x"] - 2.75) < 1e-6)
bit = next(r for r in rods if abs(r["r"] - 0.12) < 1e-9)
assert abs(sup["sy"] - exp_sup) < 0.05 and abs(sup["x"] - (-9.8 + exp_sup / 2)) < 0.05 and abs(sup["z"] - (-12)) < 1e-6, (sup, exp_sup)
assert abs(tr["sy"] - exp_out) < 0.05 and abs(tr["z"] - (-3.2 - 12 + exp_out / 2)) < 0.05, (tr, exp_out)
assert abs(so["sy"] - exp_ej) < 0.05 and abs(so["z"] - (1.8 - 12 + exp_ej / 2)) < 0.05, (so, exp_ej)
assert abs(bit["sy"] - exp_tip) < 0.05 and abs(bit["y"] - (3.3 - exp_tip / 2)) < 0.05, (bit, exp_tip)
print(f"가공 라인 로드 4개: 공급 {exp_sup:.2f}, 이송 {exp_out:.2f}, 분류 {exp_ej:.2f}, 드릴 {exp_tip:.2f} (derived 값에 맞고 offset 이 더해짐)")

# 부품: 두 라인 모두 구간 + offset 안의 좌표, 색
def in_seg(p, seg, off):
    for i, ax in enumerate("xyz"):
        lo, hi = sorted((seg[0][i] + off[i], seg[1][i] + off[i]))
        assert lo - 0.06 <= p[1 + i] <= hi + 0.06, (ax, p, seg, off)


moff = [l for l in layout["lines"] if l["id"] == "machining"][0]["offset"]; poff = [l for l in layout["lines"] if l["id"] == "press"][0]["offset"]
npress = len(pst["parts"])
mv = [p for p in out["machParts"] if p[0]]; pv = [p for p in out["pressParts"][:npress] if p[0]]; cv_all = out["pressParts"][npress:]      # 프레스 라인 부품 다음에 협동로봇 셀 부품이 만들어진다
assert len(mv) == len(mst["pieces"]) and len(pv) == len(pst["parts"]), (len(mv), len(mst["pieces"]), len(pv), len(pst["parts"]))
for p, src in zip(mv, mst["pieces"]):
    in_seg(p, MSC["parts"]["segments"][src["stage"]], moff)
    want = "pre" if src["stage"] in ("feed", "drill", "out") else ("metal" if src["metal"] else "nonmetal")
    c = MSC["parts"]["colors"][want]
    assert str(p[4]).lower() == (c if isinstance(c, str) else c["color"]).lower(), (want, p[4])
for p, src in zip(pv, pst["parts"]):
    if "pos" in src:                                  # 시뮬레이터가 위치를 직접 준 부품 (행거에 매달려 액 속으로 내려가는 도장 부품): pos + offset
        for i in range(3):
            assert abs(p[1 + i] - (src["pos"][i] + poff[i])) < 0.06, (src, p, poff)
    else:
        in_seg(p, PSC["parts"]["segments"][src["stage"]], poff)
print(f"부품: 가공 라인 {len(mv)}개, 프레스 라인 {len(pv)}개가 각자의 구간 + offset 안에 있고 색 규칙이 맞음")

# 프레스 라인의 새 동작: 슬라이드와 행거의 높이(+offset), 용접 로봇 관절, 클램프는 상태를 따라간다 (그룹 위치/회전)
G = out["groups"]
anim_of = lambda oid: next(o for o in PSC["objects"] if o.get("id") == oid)["anim"][0]
sl, hg = anim_of("press_slide"), anim_of("hanger")
exp_sl = sl["from"] + (sl["to"] - sl["from"]) * pst["stations"]["press"]["ram"] + poff[1]
exp_hg = hg["from"] + (hg["to"] - hg["from"]) * pst["stations"]["paint"]["dip"] + poff[1]
assert abs(G["press_slide"]["pos"][1] - exp_sl) < 0.05 and abs(G["hanger"]["pos"][1] - exp_hg) < 0.05, (G["press_slide"], exp_sl, G["hanger"], exp_hg)
rb = pst["stations"]["weld"]["robot"]
for gid, axis, key in (("robot_yaw", 1, "yaw"), ("robot_shoulder", 2, "shoulder"), ("robot_elbow", 2, "elbow"), ("robot_wrist", 2, "wrist")):
    assert abs(G[gid]["rot"][axis] - rb[key]) < 2e-3, (gid, G[gid], rb)
print(f"프레스 라인 동작: 슬라이드 {G['press_slide']['pos'][1]:.2f}, 행거 {G['hanger']['pos'][1]:.2f} (offset 포함), 용접 로봇 관절 4개가 상태의 각도를 따라감")

# 협동로봇 셀: 관절 그룹 회전 = 상태의 각도, 손가락 간격 = 그리퍼, 부품 위치(pos + offset)와 색, 스택 라이트, 요약 카드
coff = [l for l in layout["lines"] if l["id"] == "cobot"][0]["offset"]
a = cst["arm"]
gr = out["groups"]
yaw, sh, el, wr = (gr[k]["rot"] for k in ("arm_yaw", "arm_shoulder", "arm_elbow", "arm_wrist"))
assert abs(yaw[1] - a["yaw"]) < 2e-3 and abs(sh[2] - a["shoulder"]) < 2e-3 and abs(el[2] - a["elbow"]) < 2e-3 and abs(wr[2] - a["wrist"]) < 2e-3, (yaw, sh, el, wr, a)
assert abs(yaw[0]) < 1e-9 and abs(sh[0]) < 1e-9 and abs(sh[1]) < 1e-9                         # 다른 축은 돌지 않는다
fz = sorted(out["fingers"])
assert abs(fz[1] - (0.7 - 0.2 * a["grip"])) < 2e-3 and abs(fz[0] + (0.7 - 0.2 * a["grip"])) < 2e-3, (fz, a["grip"])      # 손가락 간격 = 그리퍼 열림
cv = [p for p in cv_all if p[0]]
assert len(cv) == len(cst["parts"]) and len(cv) >= 3, (len(cv), len(cst["parts"]))
for p, src in zip(cv, cst["parts"]):
    for i in range(3):
        assert abs(p[1 + i] - (src["pos"][i] + coff[i])) < 0.02, (p, src["pos"], coff)
    want = PSC["parts"]["colors"]["defect"] if src["result"] == "scrap" else PSC["parts"]["colors"]["painted"]
    assert str(p[4]).lower() == (want if isinstance(want, str) else want["color"]).lower(), (src, p[4])
cl = sorted(l[2] for l in out["lamps"] if abs(l[0] - 0.3) < 1e-9 and abs(l[1] - (6.0 + coff[0])) < 0.11)
cl_exp = sorted(("#ef4b4b" if cst["lamp"]["red"] else "#222222", "#f2c230" if cst["lamp"]["yellow"] else "#222222", "#33c27f" if cst["lamp"]["green"] else "#222222"))
assert cl == cl_exp, (cl, cl_exp)
assert out["cst"] == "가동" and out["cv"][0] == f"{cst['counts']['inspected']} 개" and out["cv"][2] == f"{cst['pallet']['count']} / 5", (out["cst"], out["cv"])
carried = next(p for p in cst["parts"] if p["stage"] == "carried")
print(f"협동로봇 셀: 관절 4개 회전(yaw {a['yaw'] * 57.3:.0f}도, 어깨 {a['shoulder'] * 57.3:.0f}도, 팔꿈치 {a['elbow'] * 57.3:.0f}도, 손목 {a['wrist'] * 57.3:.0f}도)이 상태와 일치, 그리퍼 {a['grip']:.2f}, "
      f"들고 있는 워크 {carried['id']}, 파렛트 {cst['pallet']['count']}개, 부품 {len(cv)}개(색 규칙 포함), 스택 라이트, 요약 카드 확인")

# 물류 구역: 파렛트(조각 모델, 직접 좌표 + offset), 재고 막대, 트럭(그룹 위치, 바퀴, 문, 레벨러 립), 신축 컨베이어, 박스 흐름, AGV, 요약 카드
loff = [l for l in layout["lines"] if l["id"] == "logistics"][0]["offset"]
pv_l = [p for p in out["pallets"] if p[0]]
assert len(pv_l) == len(lst["parts"]) and len(pv_l) >= 2, (len(pv_l), len(lst["parts"]))
for p, src in zip(pv_l, lst["parts"]):
    assert all(abs(p[1 + i] - (src["pos"][i] + loff[i])) < 0.02 for i in range(3)), (p, src["pos"], loff)
    assert p[4] == min(5, src["qty"]), (p, src["qty"])                          # 수량만큼 박스 조각이 보인다 (5개 = 아래 4 + 위 1)
fl = sorted(out["fills"])
exp_fill = sorted((max(0.03, lst["stock"][k]["pct"]), round(0.15 + max(0.03, lst["stock"][k]["pct"]) / 2 + loff[1], 3)) for k in ("steel", "bolt", "paint"))
assert len(fl) == 3 and all(abs(a_[0] - b_[0]) < 0.02 and abs(a_[1] - b_[1]) < 0.02 for a_, b_ in zip(fl, exp_fill)), (fl, exp_fill)   # 파렛트 위 자재 높이 = 재고 비율
gr = out["groups"]
IN, OUT = lst["inbound"], lst["outbound"]
assert abs(gr["inbound"]["pos"][0] - (LAYOUT_IN[0] + (LAYOUT_IN[1] - LAYOUT_IN[0]) * IN["truck"] + loff[0])) < 0.1, (gr["inbound"], IN)
assert abs(gr["outbound"]["pos"][0] - (LAYOUT_OUT[0] + (LAYOUT_OUT[1] - LAYOUT_OUT[0]) * OUT["truck"] + loff[0])) < 0.1, (gr["outbound"], OUT)
# 바퀴: 트럭이 움직이는 동안만 굴러간다 (회전 각도가 0 이 아님)
spun = {k: any(abs(r) > 1e-6 for n, r in out["wheelRot"] if n.startswith(k)) for k in ("inbound", "outbound")}
assert spun["inbound"] == bool(IN["moving"]) and spun["outbound"] == bool(OUT["moving"]), (spun, IN["moving"], OUT["moving"])
# 입고 트럭 뒷문(양쪽 대칭으로 열림), 도크 레벨러 립, 신축 컨베이어, 박스 흐름
dl, dr = gr["inbound_door-1.15"]["rot"][1], gr["inbound_door+1.15"]["rot"][1]
assert abs(dl - 1.75 * IN["door"]) < 2e-3 and abs(dr + 1.75 * IN["door"]) < 2e-3, (dl, dr, IN["door"])
assert abs(gr["inbound_lip"]["rot"][2] - (math.pi / 2) * (1 - IN["docked"])) < 2e-3 and abs(gr["outbound_lip"]["rot"][2] + (math.pi / 2) * (1 - OUT["docked"])) < 2e-3
assert abs(gr["outbound_tailgate"]["rot"][2] - (math.pi / 2) * OUT["docked"]) < 2e-3
s2 = [x for w, x in out["telescopic"] if abs(w - 0.84) < 1e-6][0]; s3 = [x for w, x in out["telescopic"] if abs(w - 0.7) < 1e-6][0]
sc_obj = {o["id"]: o for o in LSC["objects"] if o.get("id")}
exp2 = sc_obj["telescopic_s2"]["anim"][0]; exp3 = sc_obj["telescopic_s3"]["anim"][0]
assert abs(s2 - (exp2["from"] + (exp2["to"] - exp2["from"]) * IN["boom"] + loff[0])) < 0.02 and abs(s3 - (exp3["from"] + (exp3["to"] - exp3["from"]) * IN["boom"] + loff[0])) < 0.02, (s2, s3, IN["boom"])   # 신축 구간이 트럭 안으로 뻗는다
assert IN["boom"] > 0.99 and IN["door"] == 1 and IN["docked"] == 1, IN                       # 시험 시점은 하역 중: 문 열림, 컨베이어 뻗음
cv = out["cartons"]
assert len(cv) == 4 and [c[0] for c in cv] == [c["on"] for c in IN["cartons"]] and any(c[0] for c in cv)
for (vis, x), c in zip(cv, IN["cartons"]):
    assert abs(x - (-7.0 + 9.8 * c["p"] + loff[0])) < 0.02, (x, c)                           # 박스 위치 = 컨베이어 위 진행도(snap)
# AGV: 위치와 포크 높이(들면 0.1 올라감)
agvx = gr["agv"]["pos"][0]
assert abs(agvx - (4.6 + 11.0 * lst["agv"]["pos"] + loff[0])) < 0.05, (agvx, lst["agv"])
assert all(abs(f - (0.07 + 0.1 * lst["agv"]["lift"] + loff[1])) < 0.01 for f in out["forks"]) and len(out["forks"]) == 2, (out["forks"], lst["agv"])
assert out["lv"][3] == f"{lst['counts']['rack']} 파렛트" and out["lst"] in ("AGV 대기", "AGV 적재", "AGV 운반", "AGV 하역", "AGV 복귀"), (out["lv"], out["lst"])
print(f"물류 구역: 파렛트 {len(pv_l)}개(박스 조각 수량 일치), 재고 막대, 트럭 위치(입고 {IN['truck']:.2f}, 출하 {OUT['truck']:.2f}), 바퀴, 뒷문 {IN['door']}, 레벨러 립, 신축 컨베이어 {IN['boom']:.2f}, 박스 흐름, AGV 포크 확인")

# 램프(스택 라이트): Y29/Y2A/Y2B 상태에 따른 색, 요약 카드, 용어 전환
lamp_exp = sorted(("#ef4b4b" if mst["Y29"] else "#222222", "#f2c230" if mst["Y2A"] else "#222222", "#33c27f" if mst["Y2B"] else "#222222"))
stack = sorted(l[2] for l in out["lamps"] if abs(l[0] - 0.34) < 1e-9)
assert stack == lamp_exp, (stack, lamp_exp)
assert out["st"]["m"] == ("가동" if mst["Y2B"] else "대기") and out["st"]["p"] == ("가동" if pst["running"] else "정지")
assert out["mv"][:3] == [str(mst["D0"]), str(mst["D2"]), str(mst["D4"])] and out["pv"][:3] == [str(pst["counts"]["in"]), str(pst["counts"]["good"]), str(pst["counts"]["scrap"])]
assert out["ml"] == "금속" and out["views"], out["ml"]                # 전환 뒤(장비 원명칭) 카드 이름
assert set(terms[k]["field"] for k in ("feed_pusher", "magazine", "ok_bin")) <= set(out["labelsField"])
assert set(terms[k]["lab"] for k in ("feed_pusher", "magazine", "ok_bin")) <= set(out["labelsLab"])
import math
def scene_bounds():
    mn, mx = [1e9] * 3, [-1e9] * 3
    for l in layout["lines"]:
        sc = {"machining": MSC, "press_weld_paint": PSC, "logistics": LSC, "cobot": CSC}[l["scene"]]
        for o in sc["objects"]:
            if o["shape"] == "box": h = [v / 2 for v in o["size"]]
            elif o["shape"] == "cylinder": h = [o.get("r", o.get("rt")), o["h"] / 2, o.get("r", o.get("rt"))]
            elif o["shape"] == "sphere": h = [o["r"]] * 3
            elif o["shape"] == "belt": h = [o["size"][0] / 2, 0.05, o["size"][1] / 2]
            else: continue
            for i in range(3):
                mn[i] = min(mn[i], o["pos"][i] - h[i] + l["offset"][i]); mx[i] = max(mx[i], o["pos"][i] + h[i] + l["offset"][i])
    return mn, mx


mn, mx = scene_bounds()
tgt = [(mn[0] + mx[0]) / 2, 0, (mn[2] + mx[2]) / 2]
cam = out["cam"]
f = [t - c for t, c in zip(tgt, cam)]; fl = math.sqrt(sum(v * v for v in f)); f = [v / fl for v in f]
cr = lambda a, b: [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]]
rt = cr(f, [0, 1, 0]); rl = math.sqrt(sum(v * v for v in rt)); rt = [v / rl for v in rt]; up = cr(rt, f)
tan_v = math.tan(math.radians(22.5)); worst = 0.0
for x in (mn[0], mx[0]):
    for y in (mn[1], mx[1]):
        for z in (mn[2], mx[2]):
            v = [x - cam[0], y - cam[1], z - cam[2]]
            depth = sum(a * b for a, b in zip(v, f))
            nx = abs(sum(a * b for a, b in zip(v, rt))) / depth / (tan_v * (1000 / 700)); ny = abs(sum(a * b for a, b in zip(v, up))) / depth / tan_v
            worst = max(worst, nx, ny)
assert worst <= 1.0, f"장면 모서리가 화면 밖으로 나갑니다 (화면 대비 {worst:.2f})"
assert worst >= 0.8, f"카메라가 너무 멀어 장면이 작게 보입니다 (화면 대비 {worst:.2f})"
dist = math.dist(cam, tgt)
print(f"스택 라이트 색, 요약 카드({out['st']}), 용어 전환(현장 용어 -> 장비 원명칭), 시점 자동 맞춤(거리 {dist:.1f}, 가장 바깥 모서리가 화면의 {worst:.0%}) 확인")

# AI 경보 중: 빨간 불이 깜박이고 경보 조명이 켜진다
alarm = json.loads(json.dumps(fs)); alarm["machining"]["ai"] = {"phase": "monitoring", "learned": 8, "warmup": 8, "alarm": True, "baseline": 3.6}
o2 = run(alarm, "경보")
assert o2["light"] in (40, 4), o2["light"]
assert o2["st"]["m"] == "AI 이상 감지" and o2["st"]["mcls"] == "chip alarm", o2["st"]
print(f"AI 경보 중: 경보 조명 {o2['light']}(깜박임), 라인 카드 '{o2['st']['m']}'")

# 구역으로 바로 열기 (?focus=): MES 라인별 페이지에 3D 를 끼울 때. 카메라가 그 구역의 시점(장면 카메라 + offset)에 있다
for line_id, scene in (("cobot", CSC), ("logistics", LSC), ("press", PSC)):
    lo = [l for l in layout["lines"] if l["id"] == line_id][0]["offset"]
    exp = [scene["camera"]["position"][i] + lo[i] for i in range(3)]
    got = run(fs, "focus " + line_id, f"?embed=scene&focus={line_id}")["cam"]
    assert math.dist(got, exp) < 1e-6, (line_id, got, exp)
ov = run(fs, "전체", "?embed=scene")["cam"]
assert math.dist(ov, exp) > 10                                    # focus 가 없으면 전체 시점
print("?focus= 로 열면 그 구역 시점(cobot, logistics, press), 없으면 전체 시점")

# 세부 시점: ?focus=press:weld 는 장면의 weld 시점 + 구역 offset
lo = [l for l in layout["lines"] if l["id"] == "press"][0]["offset"]
exp = [PSC["views"]["weld"]["position"][i] + lo[i] for i in range(3)]
assert math.dist(run(fs, "focus press:weld", "?embed=scene&focus=press:weld")["cam"], exp) < 1e-6
# 데모 모드: 시나리오가 가리키는 시점이 모두 실제로 있고(전체, 구역, 구역:세부), ?demo=1 로 열면 바로 시작한다
scene_of = {"machining": MSC if "MSC" in globals() else None, "press": PSC, "logistics": LSC, "cobot": CSC}
steps = re.findall(r"\{ t: (\d+), view: '([^']+)', cap: '([^']+)'", JS)
assert len(steps) == 12 and all(int(t) >= 5 for t, _, _ in steps)
for _, view, _ in steps:
    if view == "overview":
        continue
    ln, _, sub = view.partition(":")
    assert ln in {l["id"] for l in layout["lines"]}, view
    if sub:
        assert sub in scene_of[ln]["views"], view
od = run(fs, "demo", "?embed=1&demo=1")
assert od["demoCap"].startswith("1 / 12") and od["demoBtn"] == "■ 데모 중지", (od["demoCap"], od["demoBtn"])
print(f"데모 모드: {len(steps)}단계, 모든 시점 존재, ?demo=1 로 바로 시작 ('{od['demoCap'][:30]}...')")
print("\n테스트 통과")
