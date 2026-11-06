"""프레스 · 용접 · 도장 장면(src/scenes/press_weld_paint.json)의 기하를 점검한다. 3D 를 눈으로 볼 수 없으므로 수치로 확인한다.

 - id 중복 없음, 필요한 상태 경로(ram, robot.*, gun, clamp, dip, voltage, oven.heat)가 시뮬레이터 상태에 실제로 있다
 - 용접 로봇의 어깨 관절 높이 = IK 가정 높이, 용접 한 사이클 동안 C형 건이 작업대, 지그 베이스, 부품 밖의 어떤 것도 통과하지 않는다
 - 프레스: 부품 아랫면 = 하부 금형 윗면, 슬라이드가 내려오면 상부 금형 아랫면 = 부품 윗면
 - 도장: 행거 로드가 어느 높이에서도 호이스트 튜브와 이어져 있고, 부품은 액면 아래까지 내려간다
 - 컨베이어 통로(부품이 지나는 높이, |z| < 0.85)를 막는 불투명 고정물이 없다 (설비 자리 제외)
"""
import json
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
import weld_cell as W                                   # noqa: E402
import paint_cell as PC                                 # noqa: E402
from line_sim import LineSim                            # noqa: E402

scene = json.loads((ROOT / "src" / "scenes" / "press_weld_paint.json").read_text(encoding="utf-8"))
objs = scene["objects"]


def walk(o, depth=0):
    yield o, depth
    for c in o.get("children", []):
        yield from walk(c, depth + 1)


allo = [x for o in objs for x, _ in walk(o)]
ids = [o["id"] for o in allo if o.get("id")]
assert len(ids) == len(set(ids)), [i for i in ids if ids.count(i) > 1]
print(f"오브젝트 {len(allo)}개 (최상위 {len(objs)}), id 중복 없음")

# ---- 장면이 쓰는 상태 경로가 시뮬레이터 상태에 모두 있다
sim = LineSim(); sim.start()
for _ in range(400):
    sim.advance(0.1)
state = sim.state()
get = lambda obj, path: __import__("functools").reduce(lambda o, k: o[k], path.split("."), obj)
paths = sorted({a["path"] for o in allo for a in o.get("anim", [])})
missing = []
for pth in paths:
    try:
        get(state, pth)
    except (KeyError, TypeError):
        missing.append(pth)
assert not missing, f"시뮬레이터 상태에 없는 경로: {missing}"
print(f"장면이 쓰는 상태 경로 {len(paths)}개 모두 시뮬레이터 상태에 있음")

# ---- 용접 로봇: 어깨 관절 높이
yaw = next(o for o in objs if o.get("id") == "robot_yaw")
sh = next(c for c in yaw["children"] if c.get("id") == "robot_shoulder")
pivot = yaw["pos"][1] + sh["pos"][1]
assert abs(pivot - W.ARM_W["base"][1]) < 1e-9, (pivot, W.ARM_W["base"])
assert abs(yaw["pos"][0] - W.ARM_W["base"][0]) < 1e-9 and abs(yaw["pos"][2] - W.ARM_W["base"][2]) < 1e-9
print(f"로봇 어깨 높이 {pivot:.2f} m = IK 가정 {W.ARM_W['base'][1]}")

# ---- 용접 한 사이클 동안 C형 건의 아래 팔(로봇 쪽으로 0.55 떨어진 수직 막대)이 작업대, 지그 베이스를 지나는가
byid = {o["id"]: o for o in objs if o.get("id")}


def aabb(o):
    sx, sy, sz = o["size"]; x, y, z = o["pos"]
    return (x - sx / 2, x + sx / 2, y - sy / 2, y + sy / 2, z - sz / 2, z + sz / 2)


solid = [aabb(byid[i]) for i in ("weld_table", "weld_basefix", "weld_fixture")]
hit = 0
n = 2000
for i in range(n + 1):
    ps = W.pose(i / n, True)
    x, y, z = W.fk(ps, W.ARM_W)                           # TCP
    r = (math.cos(ps["yaw"]), -math.sin(ps["yaw"]))       # 수평 반경 방향 (x, z)
    # 아래 팔 막대: TCP 에서 아래로 0.65, 로봇 쪽으로 0.55, 굵기 0.2
    bx, bz = x - 0.55 * r[0], z - 0.55 * r[1]
    for (x0, x1, y0, y1, z0, z1) in solid:
        if bx + 0.1 > x0 and bx - 0.1 < x1 and bz + 0.1 > z0 and bz - 0.1 < z1 and y > y0 - 0.0 and (y - 0.65) < y1:
            hit += 1
            break
assert hit == 0, f"C형 건의 아래 팔이 작업대, 지그를 지나는 표본 {hit}/{n}"
print(f"용접 한 사이클 {n}개 표본에서 C형 건의 아래 팔이 작업대와 지그에 닿지 않음")

# ---- 프레스: 부품 아랫면 = 하부 금형 윗면, 슬라이드가 내려오면 상부 금형 아랫면 = 부품 윗면
part_h = scene["parts"]["size"][1]
seg_y = scene["parts"]["segments"]["press"][0][1]
die = byid["press_lowerdie"]
assert abs((seg_y - part_h / 2) - (die["pos"][1] + die["size"][1] / 2 + 0.01)) < 0.011, (seg_y, die)
slide = byid["press_slide"]; a = slide["anim"][0]
assert abs(a["to"] - (seg_y + part_h / 2)) < 1e-9, (a, seg_y)
print(f"프레스: 부품 아랫면 {seg_y - part_h / 2:.2f} = 하부 금형 윗면, 슬라이드가 내려오면 상부 금형 아랫면 {a['to']:.2f} = 부품 윗면")

# ---- 도장: 행거 로드와 호이스트 튜브
tube = byid["hoist_tube"]; hanger = byid["hanger"]; rod = next(c for c in hanger["children"] if c.get("shape") == "cylinder" and c.get("h", 0) > 2)
tube_bottom, tube_top = tube["pos"][1] - tube["h"] / 2, tube["pos"][1] + tube["h"] / 2
for d in (0.0, 1.0):
    gy = PC.TOP_Y - PC.DEPTH * d
    rod_top = gy + rod["pos"][1] + rod["h"] / 2
    assert tube_bottom < rod_top < tube_top + 0.01, (d, rod_top, tube_bottom, tube_top)
liquid = byid["paint_liquid"]; surface = liquid["pos"][1] + liquid["size"][1] / 2
assert PC.part_y(1.0) + part_h / 2 < surface, (PC.part_y(1.0), surface)
print(f"도장: 행거 로드가 내려가도 튜브(바닥 {tube_bottom:.2f}~{tube_top:.2f}) 안에 걸쳐 있고, 부품이 액면 {surface:.2f} 아래({PC.part_y(1.0):.2f})까지 내려감")

# ---- 컨베이어 통로가 막히지 않는다: 부품이 다니는 높이(1.01~1.55), |z| < 0.85, x 가 컨베이어 3개 구간 안인 불투명 고정 상자는 컨베이어 자신뿐
conv = [(o["pos"][0] - o["size"][0] / 2, o["pos"][0] + o["size"][0] / 2) for o in objs if o.get("id", "").endswith("_body") and o["id"][0] == "c"]
bad = []
for o in objs:
    if o["shape"] != "box" or o.get("opacity") is not None or "rot" in o:
        continue
    x0, x1, y0, y1, z0, z1 = aabb(o)
    if o["id"].startswith(("c1_", "c2_", "c3_")):
        continue
    in_conv = any(x1 > c0 and x0 < c1 for c0, c1 in conv)
    if in_conv and y1 > 1.02 and y0 < 1.55 and z0 < 0.85 and z1 > -0.85:
        bad.append((o["id"], round(x0, 2), round(x1, 2)))
assert not bad, f"컨베이어 통로를 막는 상자: {bad}"
print("컨베이어 통로(3개 구간)를 막는 불투명 고정물 없음")
print("\n테스트 통과")
