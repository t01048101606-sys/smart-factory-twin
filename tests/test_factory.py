"""스마트 팩토리 통합 화면: 장면 JSON, 라인별 상태, 뷰어(factory.js)를 확인합니다.

1) 가공 라인 장면 JSON 의 모든 path 가 서버 상태에 있고, 부품 구간이 모든 단계를 덮는지
2) 공장 배치(factory.json)가 가리키는 장면과 상태가 있는지, 서버 경로
3) 가짜 three.js 에서 뷰어 실행: 두 라인이 offset 대로 배치되고, 로드 길이, 부품 위치와 색, 램프, 경보 조명, 요약 카드, 용어 전환이 맞는지
(실제로 화면에 어떻게 보이는지는 브라우저에서 확인해야 합니다. Node.js 필요)

실행 (프로젝트 폴더에서):  python tests/test_factory.py
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
fs = R[("GET", "/api/factory/state")]()
mst, pst, lst = fs["machining"], fs["press"], fs["logistics"]
assert lst["parts"] and lst["inbound"]["state"] != "idle" and lst["stock"]["steel"]["level"] in ("low", "ok")
assert mst["pieces"] and pst["parts"] and set(mst["derived"]) == {"sup", "out", "ej", "tip"}

get = lambda o, p: __import__("functools").reduce(lambda a, k: a.get(k, KeyError) if isinstance(a, dict) else KeyError, p.split("."), o)
MSC = json.loads((ROOT / "src" / "scenes" / "machining.json").read_text(encoding="utf-8"))
PSC = json.loads((ROOT / "src" / "scenes" / "press_weld_paint.json").read_text(encoding="utf-8"))
LSC = json.loads((ROOT / "src" / "scenes" / "logistics.json").read_text(encoding="utf-8"))
terms = json.loads((ROOT / "src" / "terms.json").read_text(encoding="utf-8"))["terms"]


def check_scene(sc, st, stages):
    paths = []
    for o in sc["objects"]:
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
print(f"장면 JSON 확인: 가공 라인 오브젝트 {len(MSC['objects'])}개(연결 path {n1}개), 프레스 라인 {len(PSC['objects'])}개(path {n2}개), 물류 구역 {len(LSC['objects'])}개(path {n3}개) - 모두 서버 상태에 있음")

# ---- 2) 공장 배치와 서버 경로
layout = R[("GET", "/api/factory/layout")]()
assert [l["id"] for l in layout["lines"]] == ["machining", "press", "logistics"]
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
(nm / "addons" / "controls" / "OrbitControls.js").write_text("export class OrbitControls { constructor() { this.target = { set() {} }; } update() {} }")
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
globalThis.location = { search: '?embed=1' };
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
const machParts = registry.meshes.filter(m => m.geometry.type === 'Cylinder' && m.geometry.args[0] === 0.42);
const pressParts = registry.meshes.filter(m => m.geometry.type === 'Box' && m.geometry.args[0] === 0.9 && m.geometry.args[1] === 0.22);
const part = m => [m.visible, +m.position.x.toFixed(2), +m.position.y.toFixed(2), +m.position.z.toFixed(2), m.material.color.value];
const lamps = registry.meshes.filter(m => m.geometry.type === 'Sphere').map(m => [m.geometry.args[0], +m.position.x.toFixed(1), m.material.color.value]);
const pallets = registry.meshes.filter(m => m.geometry.type === 'Box' && m.geometry.args[0] === 1.3 && m.geometry.args[1] === 0.6).map(m => [m.visible, +m.position.x.toFixed(2), +m.position.y.toFixed(2), +m.position.z.toFixed(2)]);
const fills = registry.meshes.filter(m => m.geometry.type === 'Box' && m.geometry.args[0] === 1.5 && m.geometry.args[1] === 1.0 && m.geometry.args[2] === 0.3).map(m => [+m.scale.y.toFixed(3), +m.position.y.toFixed(3)]);
const trucks = registry.meshes.filter(m => m.geometry.type === 'Box' && ((m.geometry.args[0] === 6.0 && m.geometry.args[1] === 2.0) || (m.geometry.args[0] === 6.4 && m.geometry.args[1] === 0.4))).map(m => [m.geometry.args[0], +m.position.x.toFixed(2)]);
const labelsField = texts.slice(); texts.length = 0;
els.termsMode.value = 'lab'; els.termsMode.onchange();
const labelsLab = texts.slice();
const cam = registry.camera.position;
console.log(JSON.stringify({
  ready: !!globalThis.__twin3dReady, renders: registry.renders, meshes: registry.meshes.length, sprites: registry.sprites.length,
  rods, machParts: machParts.map(part), pressParts: pressParts.map(part), pallets, fills, trucks, lamps, light: registry.lights[0] && registry.lights[0].intensity,
  st: { m: els.st_machining.textContent, p: els.st_press.textContent, mcls: els.st_machining.className },
  mv: [0, 1, 2, 3].map(i => els['mv_machining_' + i].textContent), pv: [0, 1, 2, 3, 4].map(i => els['mv_press_' + i].textContent),
  lv: [0, 1, 2, 3, 4, 5].map(i => els['mv_logistics_' + i].textContent), lst: els.st_logistics.textContent,
  ml: els.ml_machining_0.textContent, labelsField: labelsField.slice(0, 40), labelsLab, cam: [cam.x, cam.y, cam.z],
  views: els.views.innerHTML.includes('v_overview') && els.views.innerHTML.includes('v_press'),
}));
process.exit(0);
''')


def run(st, tag):
    r = subprocess.run(["node", "run.mjs"], cwd=tmp, capture_output=True, text=True, timeout=60, env={
        **os.environ, "LAYOUT": json.dumps(layout), "SCENES": json.dumps({"machining": MSC, "press_weld_paint": PSC, "logistics": LSC}),
        "STATE": json.dumps(st), "TERMS": (ROOT / "src" / "terms.json").read_text(encoding="utf-8")})
    assert r.returncode == 0, f"실행 오류({tag}):\n{r.stderr[-1800:]}"
    return json.loads(r.stdout.strip().splitlines()[-1])


out = run(fs, "정상")
print("뷰어 실행:", {k: out[k] for k in ("ready", "renders", "meshes", "sprites")})
n_labels = sum(1 for sc in (MSC, PSC, LSC) for o in sc["objects"] if o["shape"] == "label")
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
mv = [p for p in out["machParts"] if p[0]]; pv = [p for p in out["pressParts"] if p[0]]
assert len(mv) == len(mst["pieces"]) and len(pv) == len(pst["parts"]), (len(mv), len(mst["pieces"]), len(pv), len(pst["parts"]))
for p, src in zip(mv, mst["pieces"]):
    in_seg(p, MSC["parts"]["segments"][src["stage"]], moff)
    want = "pre" if src["stage"] in ("feed", "drill", "out") else ("metal" if src["metal"] else "nonmetal")
    c = MSC["parts"]["colors"][want]
    assert str(p[4]).lower() == (c if isinstance(c, str) else c["color"]).lower(), (want, p[4])
for p, src in zip(pv, pst["parts"]):
    in_seg(p, PSC["parts"]["segments"][src["stage"]], poff)
print(f"부품: 가공 라인 {len(mv)}개, 프레스 라인 {len(pv)}개가 각자의 구간 + offset 안에 있고 색 규칙이 맞음")

# 물류 구역: 파렛트(직접 좌표 + offset), 재고 막대, 트럭 위치, 요약 카드
loff = [l for l in layout["lines"] if l["id"] == "logistics"][0]["offset"]
pv_l = [p for p in out["pallets"] if p[0]]
assert len(pv_l) == len(lst["parts"]) and len(pv_l) >= 2, (len(pv_l), len(lst["parts"]))
for p, src in zip(pv_l, lst["parts"]):
    assert all(abs(p[1 + i] - (src["pos"][i] + loff[i])) < 0.02 for i in range(3)), (p, src["pos"], loff)
fl = sorted(out["fills"])
exp_fill = sorted((max(0.03, lst["stock"][k]["pct"]), round(0.1 + 1.0 * max(0.03, lst["stock"][k]["pct"]) / 2 + loff[1], 3)) for k in ("steel", "bolt", "paint"))
assert all(abs(a[0] - b[0]) < 0.02 and abs(a[1] - b[1]) < 0.02 for a, b in zip(fl, exp_fill)), (fl, exp_fill)
tin = next(t for t in out["trucks"] if t[0] == 6.0)[1]
assert abs(tin - (-15.0 + 9.5 * lst["inbound"]["truck"] + loff[0])) < 0.1, (tin, lst["inbound"])
assert out["lv"][3] == f"{lst['counts']['rack']} 파렛트" and out["lst"] in ("AGV 대기", "AGV 적재", "AGV 운반", "AGV 하역", "AGV 복귀"), (out["lv"], out["lst"])
print(f"물류 구역: 파렛트 {len(pv_l)}개 좌표(+offset), 재고 막대 높이, 입고 트럭 위치(pos {lst['inbound']['truck']:.2f}), 요약 카드({out['lst']}) 확인")

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
        sc = {"machining": MSC, "press_weld_paint": PSC, "logistics": LSC}[l["scene"]]
        for o in sc["objects"]:
            if o["shape"] == "box": h = [v / 2 for v in o["size"]]
            elif o["shape"] == "cylinder": h = [o["r"], o["h"] / 2, o["r"]]
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
print("\n테스트 통과")
