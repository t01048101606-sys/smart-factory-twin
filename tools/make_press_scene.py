"""프레스 · 용접 · 도장 라인의 3D 장면 JSON(src/scenes/press_weld_paint.json)을 만든다.

근거 (docs/press_3d_reference.md):
  프레스   스트레이트 사이드 기계식 프레스 = 크라운(모터, 플라이휠, 클러치) + 4개 컬럼 + 베드와 볼스터 + 슬라이드(램). 코일 라인 = 언코일러 -> 슬랙 루프 -> 교정기 -> 서보 롤 피더.
           라이트 커튼과 양손 조작 (OSHA 1910.217)
  용접     6축 스폿 용접 로봇(가반 100~210kg, 리치 2.2~3.1m) + C형 서보 건(가압력 2~7kN) + 용접 지그(레스트 패드, 위치결정 핀, 공압 클램프, 3-2-1 원리) + 안전 펜스
  도장     전착 도장: 전처리(탈지, 수세, 인산아연) -> 전착조(행거가 부품을 담근다) -> 후수세 -> 건조로(경화 150~200도)
동작 상수는 src/weld_cell.py, src/paint_cell.py 와 같다. 로봇 어깨 관절 높이 = IK 가 가정하는 ARM_W["base"] 높이.

실행 (프로젝트 폴더에서):  python tools/make_press_scene.py
"""
import json
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
from paint_cell import DEPTH, STATION_X as PX, TOP_Y            # noqa: E402
from weld_cell import ARM_W, GAP, GUN_OPEN                      # noqa: E402

OUT = ROOT / "src" / "scenes" / "press_weld_paint.json"
old = json.loads(OUT.read_text(encoding="utf-8"))
HALF_PI = math.pi / 2

O = []
add = lambda **k: O.append(k)
box = lambda id, size, pos, color, **k: add(id=id, shape="box", size=size, pos=pos, color=color, **k)
cyl = lambda id, r, h, pos, color, **k: add(id=id, shape="cylinder", r=r, h=h, pos=pos, color=color, **k)
label = lambda text, pos, w=2.4: add(shape="label", text=text, pos=pos, w=w)
DARK, LIGHT, PRESS, YEL, GREY = "#39424f", "#8a94a3", "#4a5566", "#d8a020", "#c3ccd6"
ORANGE, BLUE_MOTOR, COPPER = "#e07b2a", "#2f6aa3", "#d8a060"
LAMP_MAP = old["objects"][[o.get("id") for o in old["objects"]].index("press_lamp")]["anim"][0]["map"]

box("floor", [42, 0.4, 17], [-0.7, -0.2, -1.0], "#2a323d")
box("walk_line0", [20, 0.03, 0.14], [-5, 0.02, 3.0], YEL)

# ================================================================ 프레스 (스트레이트 사이드)
CX = -9.0
# 재공품(WIP) 현황 띠: 바닥에 칸 6개 (프레스, 컨베이어1, 용접, 컨베이어2, 도장, 컨베이어3), 칸마다 부품 유무와 상태를 색으로 보여 준다
WIP_X = {"press": CX, "c1": -4.9, "weld": -0.5, "c2": 3.5, "paint": 7.8, "c3": 11.9}
WIP_MAP = {"empty": "#2c3440", "working": "#33c27f", "waiting": "#f2c230", "down": "#ef4b4b"}
for _k, _x in WIP_X.items():
    add(id=f"wip_{_k}", shape="box", size=[1.1, 0.06, 0.5], pos=[_x, 0.03, 4.5], color="#2c3440", anim=[{"prop": "lamp", "path": f"occ.{_k}", "map": WIP_MAP}])
label("재공품 현황", [-12.2, 0.8, 4.5], 2.2)
box("press_pit", [4.2, 0.12, 3.8], [CX, 0.06, 0], "#1d232b")
box("press_bed", [3.0, 0.73, 2.8], [CX, 0.485, 0], PRESS)
box("press_bolster", [2.6, 0.15, 2.4], [CX, 0.925, 0], "#6a7686")
box("press_lowerdie_shoe", [1.8, 0.12, 1.8], [CX, 1.06, 0], "#3d4757")
box("press_lowerdie", [1.4, 0.18, 1.4], [CX, 1.21, 0], "#5f6c7d")
for i, (dx, dz) in enumerate(((-0.62, -0.62), (0.62, -0.62), (-0.62, 0.62), (0.62, 0.62))):
    cyl(f"press_guidepin{i}", 0.06, 0.4, [CX + dx, 1.5, dz], GREY)
for i, (sx, sz) in enumerate(((-1.2, -1.2), (1.2, -1.2), (-1.2, 1.2), (1.2, 1.2))):
    box(f"press_column{i}", [0.38, 3.45, 0.38], [CX + sx, 2.575, sz], DARK)
    cyl(f"press_tierod{i}", 0.11, 0.25, [CX + sx, 5.325, sz], "#2d3541")
box("press_crown", [3.0, 0.9, 3.0], [CX, 4.75, 0], PRESS)
box("press_motor", [1.1, 0.7, 0.8], [CX - 0.3, 5.55, -0.8], BLUE_MOTOR)
cyl("press_airtank", 0.28, 1.3, [CX - 0.3, 5.5, 0.8], LIGHT, rot=[0, 0, HALF_PI])
add(id="press_flywheel", shape="group", pos=[CX + 1.75, 4.75, 0], anim=[{"prop": "spin", "axis": "x", "speed": -2.2, "path": "running"}], children=[
    {"shape": "cylinder", "r": 0.9, "h": 0.25, "pos": [0, 0, 0], "rot": [0, 0, HALF_PI], "color": "#7b8798"},
    {"shape": "cylinder", "r": 0.3, "h": 0.4, "pos": [0, 0, 0], "rot": [0, 0, HALF_PI], "color": "#2d3541"},
    {"shape": "box", "size": [0.06, 1.6, 0.14], "pos": [0.14, 0, 0], "color": "#f2c230"},
])
for dx in (-0.7, 0.7):
    cyl(f"press_sleeve{dx}", 0.24, 0.9, [CX + dx, 3.85, 0], "#3a4452")
add(id="press_slide", shape="group", pos=[CX, TOP_Y + 0.11 + 1.0, 0], anim=[{"prop": "y", "path": "stations.press.ram", "from": TOP_Y + 0.11 + 1.0, "to": TOP_Y + 0.11}], children=[
    {"shape": "box", "size": [1.4, 0.18, 1.4], "pos": [0, 0.09, 0], "color": "#5f6c7d"},
    {"shape": "box", "size": [1.8, 0.12, 1.8], "pos": [0, 0.24, 0], "color": "#3d4757"},
    {"shape": "box", "size": [2.5, 0.5, 2.5], "pos": [0, 0.55, 0], "color": "#aab4c0"},
    {"shape": "cylinder", "r": 0.15, "h": 2.6, "pos": [-0.7, 2.1, 0], "color": LIGHT},
    {"shape": "cylinder", "r": 0.15, "h": 2.6, "pos": [0.7, 2.1, 0], "color": LIGHT},
])
for dx in (-1.55, 1.55):
    box(f"press_lc_post{dx}", [0.14, 2.3, 0.14], [CX + dx, 2.15, 1.75], YEL)
for i, y in enumerate((1.5, 2.2, 2.9)):
    box(f"press_lc_beam{i}", [2.96, 0.03, 0.03], [CX, y, 1.75], "#401010", anim=[{"prop": "emissive", "path": "running", "on": "#ff3030", "off": "#000000"}])
label("라이트 커튼", [CX, 3.55, 1.75], 1.6)
cyl("press_2hand_post", 0.06, 1.2, [CX - 2.3, 0.6, 2.3], LIGHT)
box("press_2hand_head", [0.8, 0.2, 0.4], [CX - 2.3, 1.3, 2.3], DARK)
for dx in (-0.25, 0.25):
    cyl(f"press_2hand_btn{dx}", 0.1, 0.1, [CX - 2.3 + dx, 1.45, 2.3], "#33c27f")
label("양손 조작", [CX - 2.3, 2.0, 2.3], 1.6)
box("press_cabinet", [1.0, 1.8, 0.7], [CX + 3.0, 0.9, 1.3], "#3c4654")
box("press_cabinet_screen", [0.6, 0.35, 0.02], [CX + 3.0, 1.3, 1.66], "#1a3a5c")
cyl("press_pole", 0.08, 3.2, [CX + 2.3, 1.6, 2.3], LIGHT)
add(id="press_lamp", shape="sphere", r=0.28, pos=[CX + 2.3, 3.45, 2.3], color="#222222", anim=[{"prop": "lamp", "path": "stations.press.state", "map": LAMP_MAP}])
label("프레스", [CX, 6.4, 0], 2.4)

# ================================================================ 코일 라인
UX, SX, FX = -18.9, -14.2, -12.0
STRIP_Y = 1.325
box("uncoiler_base", [2.8, 0.15, 2.6], [UX, 0.075, 0], "#2a303a")
box("uncoiler_stand", [1.0, 1.4, 0.5], [UX, 0.85, -1.0], "#3c4a5c")
cyl("uncoiler_mandrel", 0.22, 1.6, [UX, 1.15, -0.2], LIGHT, rot=[HALF_PI, 0, 0])
add(id="uncoiler_coil", shape="group", pos=[UX, 1.15, 0], anim=[{"prop": "spin", "axis": "z", "speed": 0.35, "path": "running"}], children=[
    {"shape": "cylinder", "r": 0.85, "h": 1.0, "pos": [0, 0, 0], "rot": [HALF_PI, 0, 0], "color": "#8f98a6"},
    {"shape": "cylinder", "r": 0.3, "h": 1.06, "pos": [0, 0, 0], "rot": [HALF_PI, 0, 0], "color": "#2d3541"},
    {"shape": "box", "size": [0.08, 0.5, 0.02], "pos": [0, 0.58, 0.52], "color": "#f2c230"},
])


def strip(id, x0, y0, x1, y1):
    add(id=id, shape="box", size=[math.hypot(x1 - x0, y1 - y0), 0.03, 1.0], pos=[(x0 + x1) / 2, (y0 + y1) / 2, 0], color="#9aa7b5", rot=[0, 0, math.atan2(y1 - y0, x1 - x0)])


strip("strip_a", UX, 2.0, -16.9, 0.72)
strip("strip_b", -16.9, 0.72, -15.4, 0.72)
strip("strip_c", -15.4, 0.72, -14.75, STRIP_Y)
strip("strip_main", -14.75, STRIP_Y, CX - 0.8, STRIP_Y)
for dz in (-0.6, 0.6):
    for dx in (-16.8, -15.5):
        box(f"loop_post{dx}{dz}", [0.1, 0.65, 0.1], [dx, 0.325, dz], DARK)
for i, dx in enumerate((-16.5, -16.1, -15.7)):
    cyl(f"loop_roller{i}", 0.07, 1.1, [dx, 0.6, 0], GREY, rot=[HALF_PI, 0, 0])
label("슬랙 루프", [-16.1, 1.5, 0.9], 1.8)
box("straightener_stand", [1.7, 0.85, 1.7], [SX, 0.425, 0], "#3c4a5c")
for dz in (-0.78, 0.78):
    box(f"straightener_plate{dz}", [1.6, 0.9, 0.12], [SX, 1.3, dz], PRESS)
for i, dx in enumerate((-0.45, -0.15, 0.15, 0.45)):
    cyl(f"straightener_lroll{i}", 0.11, 1.4, [SX + dx, 1.2, 0], GREY, rot=[HALF_PI, 0, 0])
for i, dx in enumerate((-0.3, 0.0, 0.3)):
    cyl(f"straightener_uroll{i}", 0.11, 1.4, [SX + dx, 1.45, 0], GREY, rot=[HALF_PI, 0, 0])
    cyl(f"straightener_screw{i}", 0.05, 0.3, [SX + dx, 1.85, 0], "#2d3541")
box("straightener_motor", [0.6, 0.5, 0.5], [SX, 1.2, 1.15], BLUE_MOTOR)
box("feeder_stand", [0.8, 0.5, 1.2], [FX, 0.25, 0], DARK)
box("feeder_lower", [1.1, 0.8, 1.5], [FX, 0.9, 0], "#3c4a5c")
box("feeder_upper", [1.1, 0.55, 1.5], [FX, 1.625, 0], PRESS)
cyl("feeder_servo", 0.22, 0.7, [FX, 2.2, 0], BLUE_MOTOR, rot=[HALF_PI, 0, 0])
label("코일 라인", [-15.5, 3.4, 0], 2.4)

# ================================================================ 컨베이어 3개
for name, cx_, length in (("c1", -4.9, 5.6), ("c2", 3.5, 4.8), ("c3", 11.9, 4.4)):
    box(f"{name}_body", [length, 0.5, 1.7], [cx_, 0.75, 0], "#2a4a44")
    add(id=f"{name}_belt", shape="belt", size=[length - 0.1, 1.5], pos=[cx_, 1.012, 0], path=f"conveyors.{name}.moving")
    box(f"{name}_railA", [length, 0.25, 0.12], [cx_, 1.12, -0.9], "#6a7686")
    box(f"{name}_railB", [length, 0.25, 0.12], [cx_, 1.12, 0.9], "#6a7686")
    for dx in (-length / 2 + 0.3, length / 2 - 0.3):
        for dz in (-0.7, 0.7):
            box(f"{name}_leg{dx:.1f}{dz}", [0.2, 0.5, 0.2], [cx_ + dx, 0.25, dz], DARK)
    box(f"{name}_motor", [0.5, 0.4, 0.5], [cx_ + length / 2 - 0.5, 0.55, 1.15], BLUE_MOTOR)
label("컨베이어1", [-4.9, 2.1, 1.5], 2.2)
label("컨베이어2", [3.5, 2.1, 1.5], 2.2)

# ================================================================ 용접 셀
WX = -0.5
box("weld_table", [2.4, 1.0, 1.4], [WX, 0.5, 0], PRESS)            # 폭 1.4: C형 건의 아래 팔이 로봇 쪽(z=-0.93)에서 지나갈 틈
box("weld_basefix", [1.6, 0.06, 1.2], [WX, 1.03, 0], "#6a7686")
box("weld_fixture", [0.62, 0.19, 0.62], [WX, 1.155, 0], LIGHT)
for i, (dx, dz) in enumerate(((-0.2, -0.2), (0.2, -0.2), (0.0, 0.2))):
    box(f"weld_pad{i}", [0.14, 0.06, 0.14], [WX + dx, 1.28, dz], YEL)
for i, dx in enumerate((-0.22, 0.22)):
    add(id=f"weld_pin{i}", shape="cylinder", rt=0.03, rb=0.06, h=0.4, pos=[WX + dx, 1.45, 0.2], color="#e8edf2")
for i, (hx, hz, ry) in enumerate(((-1.12, 0.15, 0.0), (0.12, 0.15, math.pi), (-0.5, 0.62, HALF_PI))):
    box(f"weld_clampstand{i}", [0.2, 0.55, 0.25], [hx, 1.275, hz], DARK)
    add(id=f"weld_clamp{i}", shape="group", pos=[hx + (0.07 if i == 0 else -0.07 if i == 1 else 0), 1.58, hz], rot=[0, ry, 0], children=[
        {"shape": "group", "pos": [0, 0, 0], "anim": [{"prop": "rotate", "axis": "z", "path": "stations.weld.clamp", "scale": -1.35, "bias": 1.35}], "children": [
            {"shape": "box", "size": [0.5, 0.1, 0.14], "pos": [0.25, 0, 0], "color": "#d4352c"},
            {"shape": "cylinder", "r": 0.05, "h": 0.06, "pos": [0.45, -0.08, 0], "color": "#2d3541"},
            {"shape": "cylinder", "r": 0.08, "h": 0.18, "pos": [0, 0, 0], "rot": [HALF_PI, 0, 0], "color": "#2d3541"},
        ]},
    ])
label("용접 지그", [WX, 2.45, 1.4], 2.2)

BX, BY, BZ = ARM_W["base"]
L1, L2, L3 = ARM_W["L1"], ARM_W["L2"], ARM_W["L3"]
PED = BY - 0.47
box("robot_pedestal", [1.5, PED, 1.5], [BX, PED / 2, BZ], DARK)
cyl("robot_base_ring", 0.85, 0.12, [BX, PED + 0.06, BZ], "#2d3541")
gun_upper = {"shape": "group", "pos": [0, 0, 0], "anim": [{"prop": "x", "path": "stations.weld.gun", "from": -GUN_OPEN, "to": 0.0}], "children": [
    {"shape": "box", "size": [0.14, 0.64, 0.2], "pos": [1.0, -0.27, 0], "color": "#aab4c0"},
    {"shape": "cylinder", "r": 0.07, "h": 0.5, "pos": [L3 - 0.25, 0, 0], "rot": [0, 0, HALF_PI], "color": COPPER},
]}
arm = {
    "id": "robot_yaw", "shape": "group", "pos": [BX, PED + 0.12, BZ], "anim": [{"prop": "rotate", "axis": "y", "path": "stations.weld.robot.yaw"}],
    "children": [
        {"shape": "cylinder", "r": 0.62, "h": 0.36, "pos": [0, 0.18, 0], "color": "#2d3541"},
        {"id": "robot_shoulder", "shape": "group", "pos": [0, 0.35, 0], "anim": [{"prop": "rotate", "axis": "z", "path": "stations.weld.robot.shoulder"}], "children": [
            {"shape": "cylinder", "r": 0.46, "h": 0.9, "pos": [0, 0, 0], "rot": [HALF_PI, 0, 0], "color": "#2d3541"},
            {"shape": "box", "size": [L1, 0.7, 0.8], "pos": [L1 / 2, 0, 0], "color": ORANGE},
            {"id": "robot_elbow", "shape": "group", "pos": [L1, 0, 0], "anim": [{"prop": "rotate", "axis": "z", "path": "stations.weld.robot.elbow"}], "children": [
                {"shape": "cylinder", "r": 0.4, "h": 0.85, "pos": [0, 0, 0], "rot": [HALF_PI, 0, 0], "color": "#2d3541"},
                {"shape": "box", "size": [L2, 0.55, 0.65], "pos": [L2 / 2, 0, 0], "color": ORANGE},
                {"id": "robot_wrist", "shape": "group", "pos": [L2, 0, 0], "anim": [{"prop": "rotate", "axis": "z", "path": "stations.weld.robot.wrist"}], "children": [
                    {"shape": "cylinder", "r": 0.28, "h": 0.6, "pos": [0, 0, 0], "rot": [HALF_PI, 0, 0], "color": "#2d3541"},
                    {"shape": "cylinder", "r": 0.22, "h": 0.5, "pos": [0.4, 0, 0], "rot": [0, 0, HALF_PI], "color": ORANGE},
                    {"shape": "box", "size": [0.14, 0.9, 0.55], "pos": [0.72, -0.25, 0], "color": DARK},
                    {"shape": "box", "size": [0.9, 0.55, 0.5], "pos": [1.2, -0.55, 0], "color": "#c8d0da"},
                    {"shape": "box", "size": [0.65, 0.14, 0.2], "pos": [1.82, -0.55, 0], "color": LIGHT},
                    {"shape": "box", "size": [0.14, 0.64, 0.2], "pos": [2.07, -0.27, 0], "color": LIGHT},
                    {"shape": "cylinder", "r": 0.06, "h": 0.28, "pos": [L3 + GAP + 0.14, 0, 0], "rot": [0, 0, HALF_PI], "color": COPPER},
                    gun_upper,
                    {"shape": "sphere", "r": 0.2, "pos": [L3 + GAP / 2, 0, 0], "color": "#ffd070", "anim": [
                        {"prop": "visible", "path": "stations.weld.spark"}, {"prop": "emissive", "path": "stations.weld.spark", "on": "#ffd070", "off": "#000000"}]},
                    {"shape": "light", "pos": [L3 + GAP / 2, 0, 0], "color": "#ffd070", "intensity": 0, "distance": 7, "anim": [{"prop": "intensity", "path": "stations.weld.spark", "on": 5, "off": 0}]},
                ]},
            ]},
        ]},
    ],
}
O.append(arm)
label("용접 로봇", [BX, 5.6, BZ + 0.6], 2.4)


def fence(id, x0, z0, x1, z1):
    length = math.hypot(x1 - x0, z1 - z0)
    cx_, cz_ = (x0 + x1) / 2, (z0 + z1) / 2
    along_x = abs(z1 - z0) < 1e-9
    size = lambda h, t: [length, h, t] if along_x else [t, h, length]
    box(f"{id}_mesh", size(1.5, 0.04), [cx_, 1.2, cz_], "#c8d0da", opacity=0.2)
    box(f"{id}_top", size(0.06, 0.06), [cx_, 1.95, cz_], YEL)
    box(f"{id}_bottom", size(0.06, 0.06), [cx_, 0.1, cz_], YEL)
    n = max(1, round(length / 1.8))
    for i in range(n + 1):
        t = i / n
        box(f"{id}_post{i}", [0.1, 2.0, 0.1], [x0 + (x1 - x0) * t, 1.0, z0 + (z1 - z0) * t], YEL)


fence("fence_back", -3.0, -4.0, 2.0, -4.0)
fence("fence_front", -3.0, 2.4, 2.0, 2.4)
fence("fence_left0", -3.0, -4.0, -3.0, -1.2); fence("fence_left1", -3.0, 1.2, -3.0, 2.4)
fence("fence_right0", 2.0, -4.0, 2.0, -1.2); fence("fence_right1", 2.0, 1.2, 2.0, 2.4)
box("weld_door_lock", [0.2, 0.3, 0.1], [0.5, 1.0, 2.4], "#d4352c")
box("weld_controller", [0.9, 2.0, 0.7], [-3.9, 1.0, -3.0], "#3c4654")
box("weld_controller_screen", [0.5, 0.3, 0.02], [-3.9, 1.4, -2.64], "#1a3a5c")
cyl("weld_pole", 0.08, 3.2, [WX, 1.6, 2.9], LIGHT)
add(id="weld_lamp", shape="sphere", r=0.28, pos=[WX, 3.45, 2.9], color="#222222", anim=[{"prop": "lamp", "path": "stations.weld.state", "map": LAMP_MAP}])
label("용접", [WX, 4.2, 2.9], 1.6)

# ================================================================ 도장 (전착)
box("paint_tank_floor", [3.6, 0.1, 3.2], [PX, 0.05, 0], "#2a303a")
for dz in (-1.525, 1.525):
    box(f"paint_tank_wall{dz}", [3.6, 0.95, 0.15], [PX, 0.475, dz], PRESS)
for dx in (-1.725, 1.725):
    box(f"paint_tank_wall_x{dx}", [0.15, 0.95, 3.2], [PX + dx, 0.475, 0], PRESS)
box("paint_liquid", [3.3, 0.8, 2.9], [PX, 0.5, 0], "#41546e", opacity=0.55)
for dx in (-1.45, 1.45):
    box(f"paint_anode{dx}", [0.1, 0.7, 2.2], [PX + dx, 0.5, 0], GREY)
box("paint_rectifier", [0.8, 1.8, 0.7], [PX + 2.6, 0.9, -2.0], "#3c4654")
add(id="paint_rectifier_lamp", shape="sphere", r=0.1, pos=[PX + 2.6, 1.6, -1.63], color="#103018",
    anim=[{"prop": "emissive", "path": "stations.paint.voltage", "on": "#33ff88", "off": "#000000"}])
for dx in (-3.0, 2.4):
    for dz in (-1.9, 1.9):
        box(f"monorail_post{dx}{dz}", [0.25, 4.7, 0.25], [PX + dx, 2.35, dz], DARK)
box("monorail_beam", [5.9, 0.25, 0.3], [PX - 0.3, 4.7, 0], "#6a7686")
box("monorail_trolley", [0.7, 0.4, 0.6], [PX, 4.4, 0], "#2d3541")
cyl("hoist_tube", 0.13, 1.3, [PX, 3.55, 0], "#3a4452")
add(id="hanger", shape="group", pos=[PX, TOP_Y, 0], anim=[{"prop": "y", "path": "stations.paint.dip", "from": TOP_Y, "to": TOP_Y - DEPTH}], children=[
    {"shape": "cylinder", "r": 0.05, "h": 2.33, "pos": [0, 1.515, 0], "color": LIGHT},    # 로드 (그룹 원점 = 부품 중심 기준 0.35~2.68): 올렸을 때 위 끝 4.1, 내렸을 때 3.15 로 튜브(2.9~4.2) 안에 걸친다
    {"shape": "box", "size": [1.3, 0.08, 0.1], "pos": [0, 0.35, 0], "color": "#d8a020"},
    {"shape": "cylinder", "r": 0.03, "h": 0.24, "pos": [-0.4, 0.23, 0], "color": LIGHT},
    {"shape": "cylinder", "r": 0.03, "h": 0.24, "pos": [0.4, 0.23, 0], "color": LIGHT},
])
cyl("paint_pole", 0.08, 3.2, [PX + 2.2, 1.6, 2.3], LIGHT)
add(id="paint_lamp", shape="sphere", r=0.28, pos=[PX + 2.2, 3.45, 2.3], color="#222222", anim=[{"prop": "lamp", "path": "stations.paint.state", "map": LAMP_MAP}])
label("전착조", [PX, 5.6, 0], 2.0)
for i, (x, name, col) in enumerate(((4.4, "탈지", "#c9b458"), (7.0, "수세", "#6ea8c8"), (9.6, "인산아연", "#7aa07a"))):
    box(f"pre_tank{i}", [2.4, 1.05, 2.0], [x, 0.525, -4.6], PRESS)
    box(f"pre_liquid{i}", [2.2, 0.03, 1.8], [x, 1.065, -4.6], col)
    label(name, [x, 1.8, -4.6], 1.4)
for i, x in enumerate((10.5, 11.0)):
    box(f"rinse_pipe{i}", [0.08, 0.08, 1.6], [x, 1.9, 0], "#6ea8c8")
    for dz in (-0.5, 0, 0.5):
        cyl(f"rinse_nozzle{i}{dz}", 0.03, 0.15, [x, 1.78, dz], GREY)
label("후수세", [10.75, 2.6, -1.1], 1.6)
box("oven_shell", [2.0, 1.8, 2.1], [12.7, 1.9, 0], "#c06a2a", opacity=0.22)
for dz in (-0.9, 0.9):
    box(f"oven_heater{dz}", [1.6, 0.5, 0.06], [12.7, 1.7, dz], "#331a08", anim=[{"prop": "emissive", "path": "oven.heat", "on": "#ff8a30", "off": "#000000"}])
for dx in (-1.0, 1.0):
    for dz in (-1.0, 1.0):
        box(f"oven_post{dx}{dz}", [0.1, 1.9, 0.1], [12.7 + dx, 1.95, dz], DARK)           # 부품이 지나가는 통로(z 0.9 이내)는 비워 둔다
cyl("oven_stack", 0.15, 1.8, [12.7, 3.7, 0], "#6a7686")
label("건조로", [12.7, 5.0, 0], 2.0)
label("컨베이어3", [11.9, 2.1, 1.5], 2.2)


def bin_(name, x, z, color):
    box(f"{name}_floor", [2.2, 0.15, 2.2], [x, 0.2, z], color)
    box(f"{name}_w0", [2.2, 0.7, 0.12], [x, 0.5, z - 1.1], color); box(f"{name}_w1", [2.2, 0.7, 0.12], [x, 0.5, z + 1.1], color)
    box(f"{name}_w2", [0.12, 0.7, 2.2], [x - 1.1, 0.5, z], color); box(f"{name}_w3", [0.12, 0.7, 2.2], [x + 1.1, 0.5, z], color)


bin_("good", 15.8, -1.4, "#2f5a4a")
bin_("scrap", 15.8, 1.6, "#6a3a3a")
label("양품", [15.8, 1.9, -1.4], 1.6)
label("불량", [15.8, 1.9, 1.6], 1.6)

scene = {k: v for k, v in old.items() if k not in ("objects", "camera", "views", "fit")}
scene["objects"] = O
# 일을 마치고 다음 칸이 차서 기다리는 부품(waiting)은 노란색으로, 재공품 수는 카드에 보인다 (이미 들어 있으면 다시 넣지 않는다)
scene["parts"] = json.loads(json.dumps(scene["parts"]))
scene["parts"]["colors"]["waiting"] = "#f2c230"
if not any(r["if"].get("waiting") for r in scene["parts"]["rules"]):
    scene["parts"]["rules"].insert(1, {"if": {"waiting": True}, "color": "waiting"})
scene["summary"] = json.loads(json.dumps(scene["summary"]))
if not any(m.get("path") == "kpi.wip" for m in scene["summary"]["metrics"]):
    scene["summary"]["metrics"].insert(3, {"label": "재공품 (대기)", "path": "kpi.wip", "suffix": " 개"})
scene["camera"] = {"position": [-1.0, 12.0, 20.0], "target": [-1.0, 1.5, -0.5]}
scene["views"] = {
    "diag": {"position": [-1.0, 12.0, 20.0], "target": [-1.0, 1.5, -0.5]},
    "front": {"position": [-1.0, 5.0, 24.0], "target": [-1.0, 1.8, -0.5]},
    "top": {"position": [-1.0, 30.0, 0.5], "target": [-1.0, 0.0, -0.5]},
    "side": {"position": [-30.0, 9.0, 8.0], "target": [-1.0, 1.5, -0.5]},
    "press": {"position": [-12.5, 6.5, 11.0], "target": [-10.0, 2.2, 0.0]},
    "weld": {"position": [-0.5, 6.0, 9.5], "target": [-0.5, 1.8, -1.0]},
    "paint": {"position": [9.5, 7.0, 10.5], "target": [9.5, 1.5, -0.5]},
}
scene["fit"] = {"width": 40.0, "height": 12.0}
OUT.write_text(json.dumps(scene, ensure_ascii=False, indent=1), encoding="utf-8")
ids = [o.get("id") for o in O if o.get("id")]
assert len(ids) == len(set(ids)), [i for i in ids if ids.count(i) > 1][:5]
print(f"{OUT.relative_to(ROOT)}: {len(O)}개 최상위 오브젝트, id 중복 없음")
