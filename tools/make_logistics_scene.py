"""물류 · 출하 구역의 3D 장면 JSON(src/scenes/logistics.json)을 만든다. 위치는 src/logistics_sim.py 의 LAYOUT 과 같다.

실행 (프로젝트 폴더에서):  python tools/make_logistics_scene.py
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
from logistics_sim import LAYOUT  # noqa: E402

O = []
add = lambda **k: O.append(k)
box = lambda id, size, pos, color, **k: add(id=id, shape="box", size=size, pos=pos, color=color, **k)
STEEL, DARK, ROAD = "#5a6677", "#39424f", "#2d323b"
IN0, IN1 = LAYOUT["inbound_x"]
OUT0, OUT1 = LAYOUT["out_x"]

box("floor", [56, 0.4, 24], [10, -0.2, 0], "#2a323d")

# ---- 입고: 도로, 도크, 입고 트럭, 자재 창고(재고 막대)
box("in_road", [20, 0.06, 3.6], [-8, 0.03, 5], ROAD)
box("in_dock", [4.0, 0.3, 3.8], [-3.0, 0.15, 5], DARK)
TR_CARGO, TR_CAB = "#8a94a3", "#2f6fb0"
box("in_truck_cargo", [6.0, 2.0, 2.8], [IN0, 1.4, 5], TR_CARGO, anim=[{"prop": "x", "path": "inbound.truck", "from": IN0, "to": IN1}])
box("in_truck_cab", [2.0, 1.6, 2.6], [IN0 + 4.0, 1.0, 5], TR_CAB, anim=[{"prop": "x", "path": "inbound.truck", "from": IN0 + 4.0, "to": IN1 + 4.0}])
for i, (key, x, color) in enumerate((("steel", -8.5, "#9aa7b5"), ("bolt", -6.0, "#d8a060"), ("paint", -3.5, "#4aa3ff"))):
    box(f"raw_bin_{key}", [2.0, 1.2, 1.4], [x, 0.6, 1.0], "#3a4452", opacity=0.55)
    box(f"raw_fill_{key}", [1.5, 1.0, 0.3], [x, 0.15, 1.85], color,
        anim=[{"prop": "fill", "path": f"stock.{key}.pct", "base_y": 0.1, "size_y": 1.0}])
    add(id=f"raw_lamp_{key}", shape="sphere", r=0.2, pos=[x, 1.55, 1.0], color="#222222",
        anim=[{"prop": "lamp", "path": f"stock.{key}.level", "map": {"ok": "#33c27f", "low": "#ef4b4b"}}])

# ---- 완제품 창고 (6칸)
box("fg_mat", [8.2, 0.1, 5.6], [4.6, 0.05, -3.6], "#26362c")
for dx in (-4.0, 4.0):
    for dz in (-2.6, 2.6):
        box(f"fg_post_{dx}_{dz}", [0.2, 1.8, 0.2], [4.6 + dx, 0.9, -3.6 + dz], "#6a7686")
for i, (x, y, z) in enumerate(LAYOUT["rack"]):
    box(f"fg_slot{i}", [1.5, 0.04, 1.5], [x, 0.12, z], "#3d5a47")

# ---- AGV: 경로와 차체
sx, ex = LAYOUT["agv_x"]
box("agv_path", [ex - sx + 1.0, 0.04, 0.5], [(sx + ex) / 2, 0.02, LAYOUT["agv_z"]], "#d8a020")
box("agv_body", [1.8, 0.45, 1.3], [sx, 0.3, LAYOUT["agv_z"]], "#d8a020", anim=[{"prop": "x", "path": "agv.pos", "from": sx, "to": ex}])
add(id="agv_light", shape="sphere", r=0.15, pos=[sx, 0.7, LAYOUT["agv_z"]], color="#222222",
    anim=[{"prop": "x", "path": "agv.pos", "from": sx, "to": ex},
          {"prop": "lamp", "path": "agv.state", "map": {"idle": "#7a8696", "loading": "#f2c230", "moving": "#33c27f", "unloading": "#f2c230", "returning": "#2f9bff"}}])

# ---- 출하: 도크, 도로, 출하 트럭 (후진해서 도크에 붙는다: 운전석이 도크 반대편)
box("out_dock", [2.6, 0.3, 6.8], [LAYOUT["dock"][0][0], 0.15, 0], DARK)
for j, (x, y, z) in enumerate(LAYOUT["dock"]):
    box(f"dock_slot{j}", [1.5, 0.04, 1.5], [x, 0.32, z], "#5a4a2a")
box("out_road", [20, 0.06, 5.4], [27, 0.03, 0], ROAD)
box("out_truck_bed", [6.4, 0.4, 3.2], [OUT0, 0.9, 0], TR_CARGO, anim=[{"prop": "x", "path": "outbound.truck", "from": OUT0, "to": OUT1}])
box("out_truck_cab", [2.0, 1.6, 2.8], [OUT0 + 4.2, 1.0, 0], TR_CAB, anim=[{"prop": "x", "path": "outbound.truck", "from": OUT0 + 4.2, "to": OUT1 + 4.2}])

for key, x, y, z, w in (("inbound_dock", -3.0, 3.2, 5.0, 2.6), ("raw_rack", -6.0, 2.4, 1.0, 2.6), ("fg_rack", 4.6, 2.6, -3.6, 2.6),
                        ("agv", 10.1, 1.6, 0.0, 2.6), ("outbound_dock", 17.4, 2.6, 0.0, 2.6)):
    add(shape="label", key=key, pos=[x, y, z], w=w)

scene = {
    "title": "물류 · 출하 구역", "background": "#111418",
    "camera": {"position": [10, 18, 22], "target": [9, 0.6, 0]},
    "fit": {"width": 54.0, "height": 22.0},
    "views": {"diag": {"position": [10, 18, 22], "target": [9, 0.6, 0]}, "top": {"position": [10, 34, 1], "target": [10, 0, 0]}},
    "objects": O,
    "parts": {"shape": "box", "size": [1.3, 0.6, 1.3], "colors": {"normal": "#c9a76a", "wait": "#8a6f3a"},
              "rules": [{"if": {"stage": ["wait"]}, "color": "wait"}], "default": "normal", "segments": {}},
    "summary": {
        "title": "물류 · 출하 구역",
        "status": {"path": "agv.state", "map": {"idle": "AGV 대기", "loading": "AGV 적재", "moving": "AGV 운반", "unloading": "AGV 하역", "returning": "AGV 복귀"}},
        "metrics": [{"key": "steel_stock", "path": "stock.steel.qty", "suffix": " kg"}, {"key": "bolt_stock", "path": "stock.bolt.qty", "suffix": " 개"},
                    {"key": "paint_stock", "path": "stock.paint.qty", "suffix": " L"}, {"label": "완제품 창고", "path": "counts.rack", "suffix": " 파렛트"},
                    {"label": "출하 완료", "path": "counts.shipped_pcs", "suffix": " 개"}, {"label": "입고 횟수", "path": "counts.received"}],
        "actions": [{"label": "입고 요청", "post": "/api/logistics/request_inbound", "body": {}}],
    },
}
(ROOT / "src" / "scenes" / "logistics.json").write_text(json.dumps(scene, ensure_ascii=False, indent=1), encoding="utf-8")
print("src/scenes/logistics.json:", len(O), "개 오브젝트")
