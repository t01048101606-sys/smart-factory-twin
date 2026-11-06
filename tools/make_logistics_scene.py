"""물류 · 출하 구역의 3D 장면 JSON(src/scenes/logistics.json)을 만든다. 위치는 src/logistics_sim.py 의 LAYOUT 과 같다.
치수는 실제 현장 규격을 따른다 (조사 자료와 근거는 docs/logistics_3d_reference.md). 단위는 미터에 가깝다.

  - 도크: 도크 바닥(건물 바닥, y=0)이 트럭 적재함 높이(5톤 트럭 상면지상고 1.05~1.08m)만큼 높다. 트럭이 서는 마당은 y=-1.08.
    도크 문 2.6 x 3.0m (셔터), 도크 레벨러(폭 2.0~2.2m, 접히는 립 0.45m), 범퍼, 도크 쉘터, 도크 신호등
  - 입고 트럭: 5톤 탑차 적재함 6.8 x 2.3 x 2.3m, 뒷문 양쪽 개방, 후진해서 뒷문을 도크에 붙임. 신축(텔레스코픽) 컨베이어가 트럭 안으로 뻗어 박스를 내림
  - 출하 트럭: 5톤 카고 적재함 5.5 x 2.28m, 사이드 보드 0.4m, 후진해서 도크에 붙이면 테일게이트가 내려감
  - 파렛트: 한국 표준 T-11 1.1 x 1.1m, 플라스틱 파렛트 높이 0.15m(러너 3개) + 박스 (수량만큼 보임)
  - 자재 랙: 선택형 파렛트 랙 (업라이트 + 빔), 파렛트 위 자재 높이가 재고 비율
  - AGV: 파렛트 잭형 (구동부 0.8 x 0.7m, 포크 1.15m, 안전 라이다, 경고 비콘, LED 띠, 비상정지), 파렛트를 들면 포크가 0.1m 올라감

실행 (프로젝트 폴더에서):  python tools/make_logistics_scene.py
"""
import json
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
from logistics_sim import LAYOUT  # noqa: E402

HALF_PI = math.pi / 2
O = []


def B(id, size, pos, color, **k):
    return dict(id=id, shape="box", size=size, pos=pos, color=color, **k)


def C(id, r, h, pos, color, **k):
    return dict(id=id, shape="cylinder", r=r, h=h, pos=pos, color=color, **k)


def S(id, r, pos, color, **k):
    return dict(id=id, shape="sphere", r=r, pos=pos, color=color, **k)


def G(id, pos, children, anim=None, **k):
    return dict(id=id, shape="group", pos=pos, children=children, anim=anim or [], **k)


def add(o):
    O.append(o)
    return o


STEEL, DARK, ASPHALT = "#5a6677", "#2d343e", "#1b2028"
TIRE, RIM, GLASS, WHITE = "#15181c", "#9aa4b1", "#1c2a3a", "#e7ecf2"
DOCK_Y = 1.08                     # 도크 높이 = 5톤 트럭 상면지상고 (현대 마이티 1,050~1,080mm)
WX_IN, WX_OUT = -2.2, 18.4        # 입고 도크 벽(서쪽), 출하 도크 벽(동쪽). 벽 두께 0.3m
OUT_IN, OUT_OUT = WX_IN - 0.15, WX_OUT + 0.15     # 벽 바깥면: 범퍼(0.22m 돌출)와 레벨러 립 힌지 기준
IN_Z = 5.0                        # 입고 도크의 z (문 중심), 출하 도크는 z=0

# ---------------------------------------------------------------- 바닥: 마당(낮음), 건물 바닥(도크 높이), 도로 표시
add(B("yard", [70, 0.3, 21], [8.0, -DOCK_Y - 0.15, -0.5], "#20262e"))
add(B("podium", [WX_OUT - WX_IN, DOCK_Y, 17.0], [(WX_IN + WX_OUT) / 2, -DOCK_Y / 2, -0.5], DARK))
add(B("floor_tile", [WX_OUT - WX_IN, 0.02, 17.0], [(WX_IN + WX_OUT) / 2, 0.01, -0.5], "#38414d"))
add(B("road_in", [24, 0.03, 4.4], [-14.2, -DOCK_Y + 0.016, IN_Z], ASPHALT))
add(B("road_out", [22, 0.03, 4.4], [29.8, -DOCK_Y + 0.016, 0], ASPHALT))
for i, x in enumerate((-20.0, -15.0, -10.0)):                     # 진입 도로 중앙선
    add(B(f"road_in_mark{i}", [2.0, 0.01, 0.1], [x, -DOCK_Y + 0.035, IN_Z], "#8a94a3"))
for i, x in enumerate((24.0, 29.0, 34.0)):
    add(B(f"road_out_mark{i}", [2.0, 0.01, 0.1], [x, -DOCK_Y + 0.035, 0], "#8a94a3"))

# ---------------------------------------------------------------- 건물 벽과 도크 문 (문 2.6 x 3.0m)
def wall_and_door(tag, wx, zc, face):          # face: 벽 바깥 방향 (-1: 서쪽, +1: 동쪽)
    half = 1.3
    lo, hi = -9.0, 8.0
    add(B(f"{tag}_wall_a", [0.3, 3.5, (zc - half) - lo], [wx, 1.75, (lo + zc - half) / 2], "#46505e"))
    add(B(f"{tag}_wall_b", [0.3, 3.5, hi - (zc + half)], [wx, 1.75, (zc + half + hi) / 2], "#46505e"))
    add(B(f"{tag}_header", [0.3, 0.5, 2 * half], [wx, 3.25, zc], "#46505e"))
    for dz in (-half - 0.12, half + 0.12):
        add(B(f"{tag}_frame{dz:+.2f}", [0.4, 3.0, 0.24], [wx, 1.5, zc + dz], "#2b3340"))
    # 도크 쉘터: 문 둘레에 트럭 쪽으로 튀어나온 고무 씰
    add(B(f"{tag}_shelter_top", [0.55, 0.35, 2 * half + 0.9], [wx + face * 0.42, 3.15, zc], "#27364d"))
    for dz in (-half - 0.32, half + 0.32):
        add(B(f"{tag}_shelter_side{dz:+.2f}", [0.55, 3.0, 0.3], [wx + face * 0.42, 1.5, zc + dz], "#27364d"))
    for dz in (-1.1, 1.1):                      # 범퍼: 트럭 뒤가 닿는 고무
        add(B(f"{tag}_bumper{dz:+.1f}", [0.22, 0.4, 0.32], [wx + face * 0.26, -0.28, zc + dz], "#0e0f11"))
    # 도크 신호등: 트럭이 붙으면 녹색, 아니면 적색
    add(S(f"{tag}_light_red", 0.12, [wx - face * 0.2, 3.7, zc - 0.5], "#222222",
          anim=[{"prop": "lamp", "path": f"{tag}.docked", "map": {"1": "#222222", "0": "#ef4b4b"}}]))
    add(S(f"{tag}_light_green", 0.12, [wx - face * 0.2, 3.7, zc + 0.5], "#222222",
          anim=[{"prop": "lamp", "path": f"{tag}.docked", "map": {"1": "#33c27f", "0": "#222222"}}]))


wall_and_door("inbound", WX_IN, IN_Z, -1)
wall_and_door("outbound", WX_OUT, 0.0, +1)
# 셔터 (트럭이 붙어 있는 동안 올라간다)
add(B("inbound_shutter", [0.12, 3.0, 2.6], [WX_IN, 1.5, IN_Z], "#8a94a3", anim=[{"prop": "y", "path": "inbound.door", "from": 1.5, "to": 4.7}]))
add(B("outbound_shutter", [0.12, 3.0, 2.6], [WX_OUT, 1.5, 0.0], "#8a94a3", anim=[{"prop": "y", "path": "outbound.docked", "from": 1.5, "to": 4.7}]))

# ---------------------------------------------------------------- 도크 레벨러: 판 + 접히는 립 (벽 바깥면에서 트럭 적재함 위에 0.23m 걸친다)
add(B("inbound_leveler", [2.0, 0.12, 2.2], [OUT_IN + 1.0, -0.06, IN_Z], "#8f98a5"))
add(B("inbound_leveler_stripe", [2.0, 0.014, 0.12], [OUT_IN + 1.0, 0.007, IN_Z - 1.0], "#d8a020"))
add(B("inbound_leveler_stripe2", [2.0, 0.014, 0.12], [OUT_IN + 1.0, 0.007, IN_Z + 1.0], "#d8a020"))
add(G("inbound_lip", [OUT_IN, 0.0, IN_Z], [B("inbound_lip_plate", [0.45, 0.08, 2.2], [-0.225, 0, 0], "#7d8794")],
      anim=[{"prop": "rotate", "axis": "z", "path": "inbound.docked", "bias": HALF_PI, "scale": -HALF_PI}]))   # 서 있지 않을 때는 아래로 접혀 있다가 뻗는다
add(B("outbound_leveler", [2.0, 0.12, 2.2], [OUT_OUT - 1.0, -0.06, 0.0], "#8f98a5"))
add(B("outbound_leveler_stripe", [2.0, 0.014, 0.12], [OUT_OUT - 1.0, 0.007, -1.0], "#d8a020"))
add(B("outbound_leveler_stripe2", [2.0, 0.014, 0.12], [OUT_OUT - 1.0, 0.007, 1.0], "#d8a020"))
add(G("outbound_lip", [OUT_OUT, 0.0, 0.0], [B("outbound_lip_plate", [0.45, 0.08, 2.2], [0.225, 0, 0], "#7d8794")],
      anim=[{"prop": "rotate", "axis": "z", "path": "outbound.docked", "bias": -HALF_PI, "scale": HALF_PI}]))


# ---------------------------------------------------------------- 트럭 (적재함 바닥이 y=0, 도크 바닥과 같은 높이)
def wheel(id, x, z, spin_speed, wide=0.3):
    return G(id, [x, -DOCK_Y + 0.42, z], [C(f"{id}_tire", 0.42, wide, [0, 0, 0], TIRE, rot=[HALF_PI, 0, 0]), C(f"{id}_hub", 0.22, wide + 0.03, [0, 0, 0], RIM, rot=[HALF_PI, 0, 0])],
             anim=[{"prop": "spin", "axis": "z", "path": "__MOVING__", "speed": spin_speed}])


def truck(tag, kind, s, z, x_from, x_to, moving_path, door_path, docked_path):
    """s = +1: 운전석이 +x 쪽 (뒤가 -x), s = -1: 운전석이 -x 쪽. kind: 'box'(5톤 탑차) 또는 'cargo'(5톤 카고)."""
    X = lambda v: s * v
    ch = []
    for zz in (-0.55, 0.55):                                  # 새시 프레임
        ch.append(B(f"{tag}_rail{zz}", [8.4, 0.2, 0.15], [X(0.7), -0.3, zz], "#2a2f36"))
    # 운전실 (캡오버형): 차체, 앞유리, 옆유리, 전조등, 그릴, 범퍼, 사이드미러, 띠
    ch += [B(f"{tag}_cab", [1.9, 2.1, 2.2], [X(4.5), 0.55, 0], "#f1f4f7"),
           B(f"{tag}_cab_stripe", [1.92, 0.16, 2.22], [X(4.5), 0.18, 0], "#1f5fa8"),
           B(f"{tag}_windshield", [0.05, 0.95, 1.9], [X(5.46), 1.0, 0], GLASS),
           B(f"{tag}_window_l", [1.1, 0.75, 0.05], [X(4.6), 1.0, -1.11], GLASS), B(f"{tag}_window_r", [1.1, 0.75, 0.05], [X(4.6), 1.0, 1.11], GLASS),
           B(f"{tag}_grille", [0.05, 0.4, 1.0], [X(5.46), -0.2, 0], "#202428"),
           B(f"{tag}_bumper", [0.3, 0.28, 2.2], [X(5.55), -0.62, 0], "#3a414b"),
           B(f"{tag}_mirror_l", [0.14, 0.34, 0.1], [X(5.25), 0.9, -1.28], "#1c1f24"), B(f"{tag}_mirror_r", [0.14, 0.34, 0.1], [X(5.25), 0.9, 1.28], "#1c1f24")]
    for zz in (-0.7, 0.7):
        ch.append(B(f"{tag}_headlight{zz}", [0.06, 0.24, 0.38], [X(5.48), -0.2, zz], "#444444",
                    anim=[{"prop": "emissive", "path": moving_path, "on": "#fff2c0", "off": "#202020", "ei": 1.2}]))
    # 바퀴 (앞축은 운전실 아래, 뒷축은 적재함 뒤쪽): 움직이는 동안 굴러간다
    for nm, ax in (("f", 4.3), ("r", -1.2)):
        for zz in (-1.0, 1.0):
            w = wheel(f"{tag}_wheel_{nm}{zz:+.0f}", X(ax), zz, 4.0 * s, 0.34 if nm == "r" else 0.28)
            w["anim"][0]["path"] = moving_path
            ch.append(w)
    if kind == "box":                                         # 5톤 탑차: 적재함 6.8 x 2.3 x 2.3 (뒷문 쪽이 열려 있고 양쪽 문이 열린다)
        ch += [B(f"{tag}_floor", [6.8, 0.12, 2.3], [0, -0.06, 0], "#cfd5dc"), B(f"{tag}_ceiling", [6.8, 0.1, 2.3], [0, 2.25, 0], WHITE, opacity=0.3),
               B(f"{tag}_wall_l", [6.8, 2.3, 0.08], [0, 1.15, -1.11], WHITE, opacity=0.3), B(f"{tag}_wall_r", [6.8, 2.3, 0.08], [0, 1.15, 1.11], WHITE, opacity=0.3),
               B(f"{tag}_wall_front", [0.08, 2.3, 2.3], [X(3.36), 1.15, 0], WHITE)]
        # 짐: 6열 x 2줄 (0.9m 상자, 가운데 0.8m 통로로 신축 컨베이어가 들어온다). 뒷문(트럭 로컬 x=-3.4 쪽) 칸부터 비워진다 (inbound.cargo.i = 1 이면 보인다)
        for i in range(12):
            col, row = i // 2, i % 2
            ch.append(B(f"{tag}_cargo{i}", [0.9, 0.9, 0.65], [X(-2.85 + col * 1.05), 0.45, -0.72 + row * 1.44], "#c9a76a" if (col + row) % 2 == 0 else "#b8935a",
                        anim=[{"prop": "visible", "path": f"inbound.cargo.{i}"}]))
        for zz, sign in ((-1.15, -s), (1.15, s)):             # 뒷문: 바깥쪽(뒤)으로 약 100도 열린다
            ch.append(G(f"{tag}_door{zz:+.2f}", [X(-3.4), 1.15, zz], [B(f"{tag}_door_panel{zz:+.2f}", [0.06, 2.2, 1.12], [0, 0, -zz / abs(zz) * 0.56], "#dfe5ec")],
                        anim=[{"prop": "rotate", "axis": "y", "path": door_path, "scale": sign * 1.75}]))
    else:                                                     # 5톤 카고: 적재함 5.5 x 2.28, 사이드 보드 0.4, 테일게이트
        ch += [B(f"{tag}_bed", [5.5, 0.15, 2.28], [0, -0.075, 0], "#6b7280"),
               B(f"{tag}_board_l", [5.5, 0.4, 0.06], [0, 0.2, -1.11], "#8a94a3"), B(f"{tag}_board_r", [5.5, 0.4, 0.06], [0, 0.2, 1.11], "#8a94a3"),
               B(f"{tag}_board_front", [0.06, 0.4, 2.28], [X(2.72), 0.2, 0], "#8a94a3")]
        ch.append(G(f"{tag}_tailgate", [X(-2.75), 0.0, 0.0], [B(f"{tag}_tailgate_panel", [0.06, 0.4, 2.28], [0, 0.2, 0], "#8a94a3")],
                    anim=[{"prop": "rotate", "axis": "z", "path": docked_path, "scale": s * HALF_PI}]))      # 도크에 붙으면 뒤로 눕는다
    return G(tag, [x_from, 0.0, z], ch, anim=[{"prop": "x", "path": f"{tag}.truck", "from": x_from, "to": x_to}])


# 입고 트럭: 운전석이 -x 쪽 (뒷문이 도크 쪽), 후진해서 뒷문 끝이 도크 범퍼(x=-2.42)에 닿는다
add(truck("inbound", "box", -1, IN_Z, LAYOUT["inbound_x"][0], LAYOUT["inbound_x"][1], "inbound.moving", "inbound.door", "inbound.docked"))
# 출하 트럭: 운전석이 +x 쪽 (뒤가 도크 쪽)
add(truck("outbound", "cargo", +1, 0.0, LAYOUT["out_x"][0], LAYOUT["out_x"][1], "outbound.moving", "outbound.docked", "outbound.docked"))

# ---------------------------------------------------------------- 입고: 신축(텔레스코픽) 컨베이어 + 검수 컨베이어, 박스가 트럭 안에서 도크로 흘러온다
BELT_Y = 0.75
TX = OUT_IN + 1.3                                                           # 첫 구간 중심 (벽 바깥면에서 안쪽으로 2.6m)
add(B("telescopic_s1", [2.6, 0.5, 1.0], [TX, 0.5, IN_Z], "#4b5563"))                                                  # 도크에 고정된 첫 구간
add(B("telescopic_s2", [2.4, 0.42, 0.84], [TX, 0.52, IN_Z], "#5b6573", anim=[{"prop": "x", "path": "inbound.boom", "from": TX, "to": TX - 2.5}]))
add(B("telescopic_s3", [2.4, 0.34, 0.7], [TX, 0.5, IN_Z], "#6b7583", anim=[{"prop": "x", "path": "inbound.boom", "from": TX, "to": TX - 4.9}]))
add(B("receiving_body", [2.6, 0.5, 1.0], [OUT_IN + 3.9, 0.5, IN_Z], "#2a4a44"))
add(dict(id="receiving_belt", shape="belt", size=[2.5, 0.9], pos=[OUT_IN + 3.9, BELT_Y + 0.01, IN_Z], path="inbound.docked"))
for i in range(4):                                                         # 박스: 트럭 안(x=-7.0)에서 검수 컨베이어 끝(2.8)까지 흐른다
    add(B(f"carton{i}", [0.5, 0.3, 0.4], [-7.0, BELT_Y + 0.17, IN_Z], "#c9a76a",
          anim=[{"prop": "x", "path": f"inbound.cartons.{i}.p", "from": -7.0, "to": 2.8, "snap": True}, {"prop": "visible", "path": f"inbound.cartons.{i}.on"}]))

# ---------------------------------------------------------------- 자재 랙: 선택형 파렛트 랙 (업라이트 + 빔), 파렛트 위 자재 높이 = 재고
RAW = (("steel", 4.6, "#9aa7b5"), ("bolt", 7.0, "#c9a76a"), ("paint", 9.4, "#2f6fd6"))
for i, x in enumerate((3.45, 5.75, 8.05, 10.35)):
    for zz in (IN_Z - 0.6, IN_Z + 0.6):
        add(B(f"rack_post{i}{zz:+.1f}", [0.1, 2.7, 0.1], [x, 1.35, zz], "#e07a2f"))
for k, (key, x, color) in enumerate(RAW):
    for zz in (IN_Z - 0.55, IN_Z + 0.55):
        add(B(f"rack_beam_{key}{zz:+.2f}", [2.3, 0.12, 0.08], [x, 1.5, zz], "#2f6fd6"))
    add(B(f"raw_pallet_{key}", [1.1, 0.15, 1.1], [x, 0.075, IN_Z], "#4a5666"))
    add(B(f"raw_load_{key}", [1.0, 1.0, 1.0], [x, 0.65, IN_Z], color, anim=[{"prop": "fill", "path": f"stock.{key}.pct", "base_y": 0.15, "size_y": 1.0}]))
    add(S(f"raw_lamp_{key}", 0.15, [x, 2.45, IN_Z - 0.6], "#222222", anim=[{"prop": "lamp", "path": f"stock.{key}.level", "map": {"ok": "#33c27f", "low": "#ef4b4b"}}]))

# ---------------------------------------------------------------- 완제품 창고(바닥 적재), 출하 도크 대기 칸, AGV 안내선
for i, sl in enumerate(LAYOUT["rack"]):
    add(B(f"fg_slot{i}", [1.35, 0.012, 1.35], [sl[0], 0.007, sl[2]], "#4a4220"))
for i, (x, z) in enumerate(((0.9, -1.7), (8.1, -1.7), (0.9, -5.6), (8.1, -5.6))):          # 노란 안전 기둥
    add(C(f"fg_bollard{i}", 0.1, 1.0, [x, 0.5, z], "#d8a020"))
for i, sl in enumerate(LAYOUT["dock"]):
    add(B(f"dock_slot{i}", [1.35, 0.012, 1.35], [sl[0], 0.007, sl[2]], "#2f4a36"))
add(B("agv_tape", [12.0, 0.012, 0.14], [10.1, 0.007, 0.0], "#d8a020"))

# ---------------------------------------------------------------- AGV: 파렛트 잭형 (포크가 파렛트 아래로 들어가 0.1m 들어 올린다)
agv = G("agv", [LAYOUT["agv_x"][0], 0.0, 0.0], [
    B("agv_fork_l", [1.15, 0.07, 0.17], [0.0, 0.07, -0.3], "#8a94a3", anim=[{"prop": "y", "path": "agv.lift", "from": 0.07, "to": 0.17}]),
    B("agv_fork_r", [1.15, 0.07, 0.17], [0.0, 0.07, 0.3], "#8a94a3", anim=[{"prop": "y", "path": "agv.lift", "from": 0.07, "to": 0.17}]),
    B("agv_body", [0.8, 0.3, 0.72], [-0.95, 0.2, 0.0], "#d8a020"),
    B("agv_cover", [0.78, 0.04, 0.7], [-0.95, 0.37, 0.0], "#2d3541"),
    C("agv_lidar", 0.1, 0.1, [-0.62, 0.44, 0.0], "#111418"),                                     # 안전 라이다 스캐너
    C("agv_mast", 0.03, 0.5, [-1.2, 0.65, 0.0], "#3a414b"),
    S("agv_beacon", 0.1, [-1.2, 0.95, 0.0], "#222222", anim=[{"prop": "lamp", "path": "agv.moving", "blink_path": "agv.moving", "map": {"1": "#ffb020", "0": "#3a3020"}}]),   # 움직이면 깜박이는 경고 비콘
    C("agv_estop", 0.05, 0.05, [-1.32, 0.4, 0.2], "#ef4b4b"),                                      # 비상정지 버튼
    B("agv_led_l", [0.78, 0.04, 0.02], [-0.95, 0.24, -0.37], "#7a8696", anim=[{"prop": "lamp", "path": "agv.state", "map": {"idle": "#7a8696", "loading": "#f2c230", "moving": "#33c27f", "unloading": "#f2c230", "returning": "#2f9bff"}}]),
    B("agv_led_r", [0.78, 0.04, 0.02], [-0.95, 0.24, 0.37], "#7a8696", anim=[{"prop": "lamp", "path": "agv.state", "map": {"idle": "#7a8696", "loading": "#f2c230", "moving": "#33c27f", "unloading": "#f2c230", "returning": "#2f9bff"}}]),
], anim=[{"prop": "x", "path": "agv.pos", "from": LAYOUT["agv_x"][0], "to": LAYOUT["agv_x"][1]}])
add(agv)

# ---------------------------------------------------------------- 이름표
for key, x, y, z, w in (("inbound_dock", WX_IN + 0.8, 4.5, IN_Z, 2.4), ("telescopic", WX_IN + 1.0, 1.7, IN_Z + 1.4, 2.7), ("raw_rack", 7.0, 3.2, IN_Z, 2.4),
                        ("fg_rack", 4.6, 2.0, -3.6, 2.4), ("agv", 10.1, 1.6, 0.0, 2.6), ("outbound_dock", WX_OUT - 0.8, 4.5, 0.0, 2.4),
                        ("dock_leveler", WX_OUT - 1.2, 1.1, 1.9, 2.4)):
    add(dict(shape="label", key=key, pos=[x, y, z], w=w))

# ---------------------------------------------------------------- 파렛트 (T-11 1.1 x 1.1m 플라스틱 파렛트 + 박스, 수량(qty)만큼 박스가 보인다)
pallet_model = [{"size": [1.1, 0.05, 1.1], "pos": [0, -0.175, 0], "color": "#3a4a5c"}]
pallet_model += [{"size": [1.1, 0.1, 0.14], "pos": [0, -0.25, zz], "color": "#33414f"} for zz in (-0.48, 0.0, 0.48)]
pallet_model += [{"size": [0.52, 0.3, 0.52], "pos": [x, 0.0, z], "rule": True, "min_qty": i + 1} for i, (x, z) in enumerate(((-0.27, -0.27), (0.27, -0.27), (-0.27, 0.27), (0.27, 0.27)))]
pallet_model += [{"size": [0.52, 0.3, 0.52], "pos": [0, 0.3, 0], "rule": True, "min_qty": 5}]

scene = {
    "title": "물류 · 출하 구역", "background": "#111418",
    "camera": {"position": [10, 18, 22], "target": [9, 0.6, 0]},
    "views": {"diag": {"position": [10, 18, 22], "target": [9, 0.6, 0]}, "top": {"position": [10, 34, 1], "target": [10, 0, 0]},
              "inbound": {"position": [-8, 8, 16], "target": [-5, 0.5, 5]}, "outbound": {"position": [28, 8, 14], "target": [20, 0.5, 0]}},
    "objects": O,
    "parts": {"model": pallet_model, "colors": {"normal": "#c9a76a", "wait": "#8a6f3a"}, "rules": [{"if": {"stage": ["wait"]}, "color": "wait"}], "default": "normal", "segments": {}},
    "summary": {
        "title": "물류 · 출하 구역",
        "status": {"path": "agv.state", "map": {"idle": "AGV 대기", "loading": "AGV 적재", "moving": "AGV 운반", "unloading": "AGV 하역", "returning": "AGV 복귀"}},
        "metrics": [{"key": "steel_stock", "path": "stock.steel.qty", "suffix": " kg"}, {"key": "bolt_stock", "path": "stock.bolt.qty", "suffix": " 개"},
                    {"key": "paint_stock", "path": "stock.paint.qty", "suffix": " L"}, {"label": "완제품 창고", "path": "counts.rack", "suffix": " 파렛트"},
                    {"label": "출하 완료", "path": "counts.shipped_pcs", "suffix": " 개"}, {"label": "입고 횟수", "path": "counts.received"}],
        "actions": [{"label": "입고 요청", "post": "/api/logistics/request_inbound", "body": {}}],
    },
}


def fix_paths(o):                              # 그룹 안의 바퀴 spin 경로 자리표시를 실제 경로로 (truck() 에서 이미 채움)
    for c in o.get("children", []):
        fix_paths(c)


for o in O:
    fix_paths(o)
(ROOT / "src" / "scenes" / "logistics.json").write_text(json.dumps(scene, ensure_ascii=False, indent=1), encoding="utf-8")
print("src/scenes/logistics.json:", len(O), "개 최상위 오브젝트")
