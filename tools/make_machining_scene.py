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
# ================================================================ 디테일링 (센서, 실린더 부속, 제어반, 컨베이어 모터)
HALF_PI = 1.5707963
GREEN_ON, LED_OFF = "#33c27f", "#13201a"
led = lambda id, pos, path, on=GREEN_ON, off=LED_OFF, size=(0.16, 0.1, 0.16): box(id, list(size), pos, off, anim=[{"prop": "emissive", "path": path, "on": on, "off": "#000000", "ei": 1.2},
                                                                                 {"prop": "color", "path": path, "map": {"1": on, "0": off}}])
# 실린더(공급, 이송, 분류): 양쪽 끝 캡, 에어 포트, 리드 스위치 LED (X0/X1 공급, X4/X5 이송, X6/X7 분류). 켜진 쪽이 지금 실린더 위치
for nm, ax, c, ln, back, front in (("feed", "x", (-10.9, PY, 0.0), 2.2, "X0", "X1"), ("transfer", "z", (ST_X, PY, -4.3), 2.2, "X4", "X5"), ("sort", "z", (SORT_X, PY, 0.9), 1.8, "X6", "X7")):
    k = 0 if ax == "x" else 1
    def at(d, y=0.0, side=0.0):
        p = [c[0], c[1] + y, c[2]]
        p[0 if ax == "x" else 2] += d
        p[2 if ax == "x" else 0] += side
        return p
    sz = lambda a, b, cc: [a, b, cc] if ax == "x" else [cc, b, a]
    box(f"{nm}_cap_back", sz(0.14, 1.0, 1.0), at(-ln / 2 - 0.07), "#2b333d")
    box(f"{nm}_cap_front", sz(0.14, 1.0, 1.0), at(ln / 2 + 0.07), "#2b333d")
    for i, d in enumerate((-ln / 2 + 0.25, ln / 2 - 0.25)):                       # 에어 포트 (피팅)
        box(f"{nm}_port{i}", [0.14, 0.18, 0.14], at(d, 0.54), BLUE)
    led(f"{nm}_led_back", at(-ln / 2 + 0.35, 0.5), back)
    led(f"{nm}_led_front", at(ln / 2 - 0.35, 0.5), front)
# 드릴링 유닛: 모터 냉각 핀, 상단 캡, 척 아래 스핀들 슬리브, 지지대의 상하 한계 LED (X2 아래, X3 위)
for i in range(3):                                                             # 냉각 핀 (지지 팔 아래쪽까지만)
    box(f"drill_fin{i}", [1.5, 0.06, 1.5], [ST_X, 3.68 + i * 0.2, 0], "#4a5566")
cyl("drill_cap", 0.4, 0.2, [ST_X, 4.65, 0], "#2b333d")
cyl("drill_sleeve", 0.22, 0.25, [ST_X, 3.12, 0], "#8a94a3")
led("drill_led_down", [-1.5, 1.8, 0.31], "X2", size=(0.14, 0.14, 0.08))
led("drill_led_up", [-1.5, 3.8, 0.31], "X3", size=(0.14, 0.14, 0.08))
# 센서 스테이션: 컨베이어 입구 위 (금속 판별용 유도형 센서 X9 = 빨강, 비금속용 정전용량형 센서 X0A = 파랑)
box("sensor_post", [0.15, 2.0, 0.15], [-2.0, 1.5, 4.5], "#6a7686")
box("sensor_arm", [0.15, 0.15, 1.4], [-2.0, 2.4, 3.8], "#6a7686")
box("sensor_bar", [1.2, 0.12, 0.12], [-2.0, 2.4, 3.2], "#6a7686")
for id_, x, path, col, body in (("sensor_metal", -2.4, "X9", "#ef4b4b", "#c9a66b"), ("sensor_nonmetal", -1.6, "X0A", "#2f9bff", "#7d8a99")):
    cyl(id_, 0.14, 0.6, [x, 2.0, 3.2], body)
    add(id=id_ + "_led", shape="sphere", r=0.07, pos=[x, 2.36, 3.2], color=LED_OFF, anim=[{"prop": "lamp", "path": path, "map": {"1": col, "0": "#222222"}}])
# 컨베이어 구동 모터 (벨트가 돌 때 불이 들어온다 Y27)
box("belt_gearbox", [0.8, 0.5, 0.5], [7.8, 0.6, 4.55], "#2b333d")
cyl("belt_motor", 0.25, 0.9, [7.8, 0.6, 5.2], "#4a5566", rot=[HALF_PI, 0, 0], anim=[{"prop": "emissive", "path": "Y27", "on": "#33c27f", "off": "#000000", "ei": 0.5}])
# 제어반: 문, 창, 시작 / 정지 / 비상정지 버튼, 가동 표시등 (녹색 Y2B, 적색 Y29)
box("panel_body", [1.6, 2.4, 0.8], [6.2, 1.2, -3.2], "#4a5566")
box("panel_window", [1.3, 0.8, 0.05], [6.2, 1.8, -2.77], "#1c2a3a")
cyl("panel_start", 0.1, 0.08, [5.8, 1.1, -2.77], "#33c27f", rot=[HALF_PI, 0, 0])
cyl("panel_stop", 0.1, 0.08, [6.2, 1.1, -2.77], "#ef4b4b", rot=[HALF_PI, 0, 0])
cyl("panel_estop_base", 0.17, 0.05, [6.65, 1.1, -2.78], "#d8a020", rot=[HALF_PI, 0, 0])
cyl("panel_estop", 0.12, 0.1, [6.65, 1.1, -2.72], "#d02020", rot=[HALF_PI, 0, 0])
add(id="panel_lamp_run", shape="sphere", r=0.08, pos=[5.8, 0.75, -2.76], color="#222222", anim=[{"prop": "lamp", "path": "Y2B", "map": {"1": "#33c27f", "0": "#222222"}}])
add(id="panel_lamp_alarm", shape="sphere", r=0.08, pos=[6.2, 0.75, -2.76], color="#222222", anim=[{"prop": "lamp", "path": "Y29", "map": {"1": "#ef4b4b", "0": "#222222"}}])
# 에어 유닛 (필터 · 레귤레이터 · 윤활기): 공급 실린더 뒤쪽 바닥
box("frl_stand", [0.5, 0.9, 0.4], [-12.9, 0.45, 1.6], "#6a7686")
cyl("frl_bowl1", 0.17, 0.45, [-13.1, 1.12, 1.6], "#9fc4e0", opacity=0.6)
cyl("frl_bowl2", 0.17, 0.45, [-12.75, 1.12, 1.6], "#9fc4e0", opacity=0.6)
cyl("frl_gauge", 0.14, 0.06, [-12.9, 1.5, 1.85], "#e6e9ee", rot=[HALF_PI, 0, 0])

# 스택 라이트 (적색은 AI 이상 감지 경보 때 깜박인다)
cyl("stack_pole", 0.12, 3.8, [12.8, 1.9, 0.5], "#6a7686")
for id_, y, path, color, blink in (("stack_red", 3.7, "Y29", "#ef4b4b", "ai.alarm"), ("stack_yellow", 3.0, "Y2A", "#f2c230", None), ("stack_green", 2.3, "Y2B", "#33c27f", None)):
    a = {"prop": "lamp", "path": path, "map": {"1": color, "0": "#222222"}}
    if blink:
        a["blink_path"] = blink
    add(id=id_, shape="sphere", r=0.34, pos=[12.8, y, 0.5], color="#222222", anim=[a])
add(id="alarm_light", shape="light", pos=[12.8, 5.0, 0.5], color="#ff3030", intensity=0, distance=30,
    anim=[{"prop": "intensity", "path": "ai.alarm", "on": 40, "off": 0, "blink": True}])

for text, x, y, z, w in (("금속 센서", -2.4, 2.9, 3.2, 1.5), ("비금속 센서", -1.6, 2.65, 3.2, 1.7), ("제어반", 6.2, 2.8, -3.2, 1.4), ("에어 유닛", -12.9, 1.9, 1.6, 1.5)):
    add(shape="label", text=text, pos=[x, y, z], w=w)
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
