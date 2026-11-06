"""협동로봇 팔레타이징 셀의 3D 장면 JSON(src/scenes/cobot.json)을 만든다.
치수와 위치는 src/cobot_sim.py 의 상수(ARM, PICK, SLOTS, NG_DROP)를 그대로 쓴다. 로봇팔은 그룹(관절) 구조: yaw -> shoulder -> elbow -> wrist.

실행 (프로젝트 폴더에서):  python tools/make_cobot_scene.py
"""
import json
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
from cobot_sim import ARM, PICK, SLOTS, NG_DROP, NG_SLOTS   # noqa: E402

O = []
add = lambda **k: O.append(k)
box = lambda id, size, pos, color, **k: add(id=id, shape="box", size=size, pos=pos, color=color, **k)
cyl = lambda id, r, h, pos, color, **k: add(id=id, shape="cylinder", r=r, h=h, pos=pos, color=color, **k)
STEEL, DARK, LIGHT = "#5a6677", "#39424f", "#8a94a3"
COBOT_WHITE, COBOT_GREY = "#e8edf2", "#c3ccd6"
BX, BY, BZ = ARM["base"]
L1, L2, L3 = ARM["L1"], ARM["L2"], ARM["L3"]
HALF_PI = math.pi / 2

# ---- 바닥, 안전 구역 표시
box("floor", [19, 0.3, 13.5], [-1.0, -0.15, -0.4], "#262d36")
for i, (size, pos) in enumerate((([11.4, 0.03, 0.14], [0.9, 0.02, 5.1]), ([11.4, 0.03, 0.14], [0.9, 0.02, -6.0]), ([0.14, 0.03, 11.2], [6.6, 0.02, -0.45]))):
    box(f"zone_line{i}", size, pos, "#d8a020")

# ---- 인피드 컨베이어 (왼쪽에서 들어와 정지 블록에서 멈춘다)
box("infeed_body", [6.4, 0.8, 1.6], [-6.3, 0.4, 0], "#2a4a44")
add(id="infeed_belt", shape="belt", size=[6.2, 1.4], pos=[-6.3, 0.81, 0], path="infeed.running")
for dz in (-0.8, 0.8):
    box(f"infeed_rail{dz}", [6.4, 0.2, 0.1], [-6.3, 0.9, dz], "#6a7686")
box("infeed_stop", [0.2, 0.5, 1.6], [PICK[0] + 0.55, 1.05, 0], "#c04a3a")
for dx in (-8.8, -3.8):
    for dz in (-0.7, 0.7):
        box(f"infeed_leg{dx}{dz}", [0.2, 0.4, 0.2], [dx, 0.2, dz], DARK)

# ---- 비전 검사: 옆에서 찍는 카메라와 반대편 백라이트 (로봇이 위에서 내려오는 길을 막지 않는다)
box("vision_post", [0.2, 1.8, 0.2], [PICK[0], 0.9, -1.75], DARK)
box("vision_cam", [0.7, 0.5, 0.6], [PICK[0], 1.75, -1.5], "#2d3541")
cyl("vision_lens", 0.18, 0.35, [PICK[0], 1.75, -1.1], "#111418", rot=[HALF_PI, 0, 0])
box("vision_back_post", [0.2, 1.4, 0.2], [PICK[0], 0.7, 1.55], DARK)
box("vision_backlight", [1.0, 0.7, 0.1], [PICK[0], 1.45, 1.2], "#2d3541", anim=[{"prop": "emissive", "path": "vision.active", "on": "#5ad6ff", "off": "#000000", "ei": 1.0}])

# ---- 로봇 받침과 팔 (그룹 = 관절)
# 어깨 관절의 높이는 IK 가 가정하는 ARM["base"] 높이(BY)와 같아야 한다: 받침대 + 링 + 회전대 + 어깨 = BY (받침대 높이 = BY - 0.47)
PED = BY - 0.47
box("robot_pedestal", [2.2, PED, 2.2], [BX, PED / 2, BZ], DARK)
cyl("robot_base_ring", 1.05, 0.12, [BX, PED + 0.06, BZ], "#2d3541")
arm = {
    "id": "arm_yaw", "shape": "group", "pos": [BX, PED + 0.12, BZ], "anim": [{"prop": "rotate", "axis": "y", "path": "arm.yaw"}],
    "children": [
        {"shape": "cylinder", "r": 0.62, "h": 0.7, "pos": [0, 0.35, 0], "color": COBOT_GREY},
        {"id": "arm_shoulder", "shape": "group", "pos": [0, 0.35, 0], "anim": [{"prop": "rotate", "axis": "z", "path": "arm.shoulder"}], "children": [
            {"shape": "cylinder", "r": 0.5, "h": 0.95, "pos": [0, 0, 0], "color": COBOT_GREY, "rot": [HALF_PI, 0, 0]},
            {"shape": "box", "size": [L1, 0.5, 0.62], "pos": [L1 / 2, 0, 0], "color": COBOT_WHITE},
            {"id": "arm_elbow", "shape": "group", "pos": [L1, 0, 0], "anim": [{"prop": "rotate", "axis": "z", "path": "arm.elbow"}], "children": [
                {"shape": "cylinder", "r": 0.42, "h": 0.85, "pos": [0, 0, 0], "color": COBOT_GREY, "rot": [HALF_PI, 0, 0]},
                {"shape": "box", "size": [L2, 0.42, 0.52], "pos": [L2 / 2, 0, 0], "color": COBOT_WHITE},
                {"id": "arm_wrist", "shape": "group", "pos": [L2, 0, 0], "anim": [{"prop": "rotate", "axis": "z", "path": "arm.wrist"}], "children": [
                    {"shape": "cylinder", "r": 0.3, "h": 0.65, "pos": [0, 0, 0], "color": COBOT_GREY, "rot": [HALF_PI, 0, 0]},
                    {"shape": "box", "size": [0.5, 0.5, 0.5], "pos": [0.3, 0, 0], "color": DARK},
                    {"shape": "box", "size": [0.3, 0.6, 1.5], "pos": [0.65, 0, 0], "color": "#2d3541"},
                    # 그리퍼 손가락: 도구 방향(+x)으로 0.5 뻗고, 닫히면 (값 1) 워크(폭 0.9)를 양쪽에서 문다
                    {"shape": "box", "size": [0.5, 0.5, 0.1], "pos": [L3 - 0.25, 0, 0.7], "color": "#c8d0da", "anim": [{"prop": "z", "path": "arm.grip", "from": 0.7, "to": 0.5}]},
                    {"shape": "box", "size": [0.5, 0.5, 0.1], "pos": [L3 - 0.25, 0, -0.7], "color": "#c8d0da", "anim": [{"prop": "z", "path": "arm.grip", "from": -0.7, "to": -0.5}]},
                ]},
            ]},
        ]},
    ],
}
O.append(arm)

# ---- 파렛트 (나무 팔레트 + 칸 표시)
box("pallet_base", [4.4, 0.35, 3.2], [3.4, 0.175, 0], "#8a6b3f")
for i, sl in enumerate(SLOTS):
    box(f"slot_mark{i}", [1.02, 0.02, 1.02], [sl[0], 0.36, sl[2]], "#5a4a2a")
for dz in (-1.5, 0, 1.5):
    box(f"pallet_skid{dz}", [4.4, 0.2, 0.3], [3.4, 0.1, dz], "#6f542f")


def bin_(name, x, z, size):
    h, t, c = 0.6, 0.12, "#3a4452"
    box(f"{name}_floor", [size, 0.15, size], [x, 0.275, z], c)
    box(f"{name}_w0", [size, h, t], [x, 0.5, z - size / 2], c); box(f"{name}_w1", [size, h, t], [x, 0.5, z + size / 2], c)
    box(f"{name}_w2", [t, h, size], [x - size / 2, 0.5, z], c); box(f"{name}_w3", [t, h, size], [x + size / 2, 0.5, z], c)


bin_("ng_bin", NG_DROP[0], NG_DROP[2], 2.4)
box("ng_bin_stripe", [2.4, 0.1, 0.05], [NG_DROP[0], 0.7, NG_DROP[2] + 1.22], "#ef4b4b")

# ---- 스택 라이트
cyl("stack_pole", 0.1, 3.8, [6.0, 1.9, 4.4], "#6a7686")
for id_, y, path, color in (("stack_red", 3.7, "lamp.red", "#ef4b4b"), ("stack_yellow", 3.0, "lamp.yellow", "#f2c230"), ("stack_green", 2.3, "lamp.green", "#33c27f")):
    add(id=id_, shape="sphere", r=0.3, pos=[6.0, y, 4.4], color="#222222", anim=[{"prop": "lamp", "path": path, "map": {"1": color, "0": "#222222"}}])

for key, x, y, z, w in (("cobot", BX, 0.8, 1.55, 2.0), ("vision_cam", PICK[0], 3.0, -1.6, 2.2), ("infeed", -6.3, 1.7, 1.5, 2.4),     # 팔이 가리지 않는 위치 (받침대 앞, 파렛트 앞 가장자리, NG 상자 옆)
                        ("pallet_station", 3.4, 0.75, 2.35, 2.7), ("ng_bin_cobot", NG_DROP[0] - 2.5, 1.1, NG_DROP[2] - 0.3, 2.8)):
    add(shape="label", key=key, pos=[x, y, z], w=w)

press = json.loads((ROOT / "src" / "scenes" / "press_weld_paint.json").read_text(encoding="utf-8"))["parts"]
scene = {
    "title": "협동로봇 팔레타이징 셀", "background": "#111418",
    "camera": {"position": [1.0, 11.0, 14.0], "target": [0.5, 1.3, 0.0]},
    "views": {"diag": {"position": [1.0, 11.0, 14.0], "target": [0.5, 1.3, 0.0]}, "front": {"position": [0.5, 4.5, 15.0], "target": [0.5, 1.3, 0.0]},
              "top": {"position": [0.5, 22.0, 0.5], "target": [0.5, 0.0, 0.0]}, "side": {"position": [-14.0, 6.0, 4.0], "target": [0.5, 1.3, 0.0]}},
    "objects": O,
    "parts": {
        "shape": "box", "size": press["size"], "colors": {"painted": press["colors"]["painted"], "defect": press["colors"]["defect"]},
        "rules": [{"if": {"result": "scrap"}, "color": "defect"}], "default": "painted", "segments": {},      # 위치는 상태의 pos 를 그대로 쓴다
    },
    "summary": {
        "title": "협동로봇 팔레타이징 셀",
        "status": {"path": "status_code", "map": {"1": "가동", "0": "대기"}},
        "metrics": [{"label": "비전 검사", "path": "counts.inspected", "suffix": " 개"}, {"label": "불량 검출", "path": "counts.ng", "suffix": " 개"},
                    {"label": "파렛트 적재", "path": "pallet.count", "suffix": " / 5"}, {"label": "완성 파렛트", "path": "counts.pallets"},
                    {"label": "집기 사이클", "path": "avg_cycle_s", "suffix": " 초", "zero": "-"}],
        "actions": [{"label": "파렛트 마감", "post": "/api/cobot/control", "body": {"action": "flush"}}],
    },
}
(ROOT / "src" / "scenes" / "cobot.json").write_text(json.dumps(scene, ensure_ascii=False, indent=1), encoding="utf-8")
print("src/scenes/cobot.json:", len(O), "개 최상위 오브젝트 (로봇팔은 그룹 4단계)")
