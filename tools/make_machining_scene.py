"""가공 라인(PLC)의 3D 장면 JSON(src/scenes/machining.json)을 만든다.
좌표는 src/static/twin3d.js 의 배치와 같다. 움직임은 상태 값(Y20 같은 PLC 출력, derived.* 같은 계산 값)에 연결한다.

실행 (프로젝트 폴더에서):  python tools/make_machining_scene.py
"""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
O = []
add = lambda **k: O.append(k)
box = lambda id, size, pos, color, **k: add(id=id, shape="box", size=size, pos=pos, color=color, **k)
cyl = lambda id, r, h, pos, color, **k: add(id=id, shape="cylinder", r=r, h=h, pos=pos, color=color, **k)
STEEL, DARK, LIGHT, BLUE = "#5a6677", "#39424f", "#8a94a3", "#2f9bff"

TOP, PY = 0.5, 0.8                 # 레일 윗면 높이, 작업물 중심 높이
MAG_X, ST_X = -6.9, -3.5
BELT_Z, BELT_START, BELT_LEN = 3.2, -3.5, 12.5
SORT_X, END_X, BIN_Z = BELT_START + 0.5 * BELT_LEN, BELT_START + BELT_LEN, 6.2

box("floor", [30, 0.4, 17], [0.5, -0.2, 2.2], "#2a323d")
box("rail", [5.4, TOP, 1.5], [-5.3, TOP / 2, 0], DARK)
box("transfer_plate", [2.0, TOP, 2.2], [ST_X, TOP / 2, 1.55], DARK)
cx = ((BELT_START - 0.9) + (END_X + 0.9)) / 2
box("conveyor_body", [BELT_LEN + 1.8, TOP, 1.7], [cx, TOP / 2, BELT_Z], "#2a4a44")
add(id="belt", shape="belt", size=[BELT_LEN + 1.6, 1.5], pos=[cx, TOP + 0.01, BELT_Z], path="Y27")
for dz in (-0.9, 0.9):
    box(f"belt_rail{dz}", [BELT_LEN + 1.8, 0.25, 0.12], [(BELT_START + END_X) / 2, TOP + 0.12, BELT_Z + dz], "#6a7686")

# 공급 푸셔 (왼쪽, X 방향으로 민다)
box("feed_body", [2.2, 0.9, 0.9], [-10.9, PY, 0], STEEL)
add(id="feed_rod", shape="rod", axis="x", dir=1, r=0.14, color=BLUE, start=[-9.8, PY, 0], len=2.1,
    anim=[{"prop": "len", "path": "derived.sup", "from": 2.1, "to": 5.5}])
box("feed_head", [0.3, 0.9, 0.9], [-7.7, PY, 0], LIGHT, anim=[{"prop": "x", "path": "derived.sup", "from": -7.7, "to": -4.3}])
# 부품 공급기 (투명한 통 + 쌓인 워크)
cyl("magazine_tube", 0.66, 2.4, [MAG_X, 2.4, 0], "#6fa8dc", opacity=0.22,
    anim=[{"prop": "color", "path": "X8", "map": {"1": "#33c27f", "0": "#6fa8dc"}}])
for i, y in enumerate((1.5, 2.1, 2.7)):
    cyl(f"magazine_part{i}", 0.45, 0.5, [MAG_X, y, 0], "#6fa8dc", anim=[{"prop": "visible", "path": "X8"}])
for dx in (-0.8, 0.8):
    box(f"magazine_post{dx}", [0.15, 1.0, 0.15], [MAG_X + dx, 0.95, 0], "#6a7686")
# 드릴링 유닛 (문형 지지대 + 모터 + 비트)
box("drill_post", [0.5, 4.6, 0.5], [-1.5, 2.3, 0], STEEL)
box("drill_arm", [2.5, 0.5, 0.5], [-2.5, 4.4, 0], STEEL)
box("drill_motor", [1.3, 1.0, 1.3], [ST_X, 4.05, 0], STEEL, anim=[{"prop": "emissive", "path": "Y28", "on": "#e08a2f", "off": "#000000", "ei": 0.7}])
add(id="drill_bit", shape="rod", axis="y", dir=-1, r=0.12, color="#c8d0da", start=[ST_X, 3.3, 0], len=0.5,
    anim=[{"prop": "len", "path": "derived.tip", "from": 0.5, "to": 2.15}])
cyl("drill_chuck", 0.3, 0.3, [ST_X, 3.4, 0], DARK)
# 이송 푸셔 (뒤쪽, Z 방향으로 가공 위치의 워크를 컨베이어 쪽으로 민다)
box("transfer_body", [0.9, 0.9, 2.2], [ST_X, PY, -4.3], STEEL)
add(id="transfer_rod", shape="rod", axis="z", dir=1, r=0.14, color=BLUE, start=[ST_X, PY, -3.2], len=2.4,
    anim=[{"prop": "len", "path": "derived.out", "from": 2.4, "to": 5.6}])
box("transfer_head", [0.9, 0.9, 0.3], [ST_X, PY, -0.8], LIGHT, anim=[{"prop": "z", "path": "derived.out", "from": -0.8, "to": 2.4}])
# 분류 푸셔 (컨베이어 뒤쪽, 정품을 앞쪽 수납함으로 민다)
box("sort_body", [0.9, 0.9, 1.8], [SORT_X, PY, 0.9], STEEL)
add(id="sort_rod", shape="rod", axis="z", dir=1, r=0.14, color=BLUE, start=[SORT_X, PY, 1.8], len=0.7,
    anim=[{"prop": "len", "path": "derived.ej", "from": 0.7, "to": 3.0}])
box("sort_head", [0.9, 0.9, 0.3], [SORT_X, PY, 2.5], LIGHT, anim=[{"prop": "z", "path": "derived.ej", "from": 2.5, "to": 4.8}])


def bin_(name, x, z, size):
    h, t, c = 0.6, 0.12, "#3a4452"
    box(f"{name}_floor", [size, 0.15, size], [x, 0.2, z], c)
    box(f"{name}_w0", [size, h, t], [x, 0.45, z - size / 2], c); box(f"{name}_w1", [size, h, t], [x, 0.45, z + size / 2], c)
    box(f"{name}_w2", [t, h, size], [x - size / 2, 0.45, z], c); box(f"{name}_w3", [t, h, size], [x + size / 2, 0.45, z], c)


bin_("ok_bin", SORT_X, BIN_Z, 2.4)
bin_("ng_bin", END_X + 1.0, BELT_Z, 1.8)
# 스택 라이트 (적색은 AI 이상 감지 경보 때 깜박인다)
cyl("stack_pole", 0.12, 3.8, [12.8, 1.9, 0.5], "#6a7686")
for id_, y, path, color, blink in (("stack_red", 3.7, "Y29", "#ef4b4b", "ai.alarm"), ("stack_yellow", 3.0, "Y2A", "#f2c230", None), ("stack_green", 2.3, "Y2B", "#33c27f", None)):
    a = {"prop": "lamp", "path": path, "map": {"1": color, "0": "#222222"}}
    if blink:
        a["blink_path"] = blink
    add(id=id_, shape="sphere", r=0.34, pos=[12.8, y, 0.5], color="#222222", anim=[a])
add(id="alarm_light", shape="light", pos=[12.8, 5.0, 0.5], color="#ff3030", intensity=0, distance=30,
    anim=[{"prop": "intensity", "path": "ai.alarm", "on": 40, "off": 0, "blink": True}])

for key, x, y, z, w in (("feed_pusher", -10.9, 2.0, 0, 2.7), ("magazine", MAG_X, 4.2, 0, 2.2), ("drill", ST_X, 5.5, 0, 2.2),
                        ("transfer_pusher", ST_X + 2.6, 1.2, -4.3, 2.7), ("conveyor", 6.8, 1.1, BELT_Z + 1.5, 2.6),
                        ("sort_pusher", SORT_X, 2.1, 0.9, 2.7), ("ok_bin", SORT_X, 1.35, BIN_Z + 0.2, 2.4),
                        ("ng_bin", END_X + 1.6, 2.5, BELT_Z - 0.3, 2.6)):
    add(shape="label", key=key, pos=[x, y, z], w=w)

scene = {
    "title": "가공 라인 (PLC)", "background": "#111418",
    "camera": {"position": [1.5, 10.5, 16.5], "target": [1.2, 0.8, 2.0]},
    "fit": {"width": 28.0, "height": 12.0},
    "views": {"diag": {"position": [1.5, 10.5, 16.5], "target": [1.2, 0.8, 2.0]}, "front": {"position": [1.5, 4.5, 19.0], "target": [1.2, 1.2, 2.0]},
              "top": {"position": [1.2, 24.0, 2.6], "target": [1.2, 0.0, 2.0]}, "side": {"position": [-17.0, 7.0, 6.0], "target": [1.2, 1.0, 2.0]}},
    "objects": O,
    "parts": {
        "shape": "cylinder", "r": 0.42, "h": 0.6,
        "colors": {"pre": "#9aa7b5", "metal": {"color": "#d5dbe3", "metalness": 0.9, "roughness": 0.25}, "nonmetal": "#6fa8dc"},
        "rules": [{"if": {"stage": ["feed", "drill", "out"]}, "color": "pre"}, {"if": {"metal": True}, "color": "metal"}], "default": "nonmetal",
        "segments": {
            "feed": [[MAG_X, PY, 0], [ST_X, PY, 0]], "drill": [[ST_X, PY, 0], [ST_X, PY, 0]], "out": [[ST_X, PY, 0], [ST_X, PY, BELT_Z]],
            "belt": [[BELT_START, PY, BELT_Z], [END_X, PY, BELT_Z]], "eject": [[SORT_X, PY, BELT_Z], [SORT_X, PY - 0.3, BIN_Z - 0.4]],
            "binm": [[SORT_X, 0.55, BIN_Z - 0.4], [SORT_X, 0.55, BIN_Z - 0.4]], "end": [[END_X + 1.0, PY, BELT_Z], [END_X + 1.0, PY, BELT_Z]],
        },
    },
    "summary": {
        "title": "가공 라인 (PLC)",
        "status": {"path": "Y2B", "map": {"1": "가동", "0": "대기"}, "alarm_path": "ai.alarm", "alarm_text": "AI 이상 감지"},
        "metrics": [{"key": "ok_part", "path": "D0"}, {"key": "ng_part", "path": "D2"}, {"key": "total", "path": "D4"},
                    {"label": "AI 이상 감지", "path": "ai", "format": "ai"}],
        "actions": [{"label": "연속동작", "post": "/api/press", "body": {"dev": "M101"}}, {"label": "연속정지", "post": "/api/press", "body": {"dev": "M102"}}],
    },
}
(ROOT / "src" / "scenes" / "machining.json").write_text(json.dumps(scene, ensure_ascii=False, indent=1), encoding="utf-8")
print("src/scenes/machining.json:", len(O), "개 오브젝트")
