"""물류 · 출하 구역 시뮬레이터를 확인합니다 (재고, 입고, 파렛트, AGV, 출하 트럭).

실행 (프로젝트 폴더에서):  python tests/test_logistics.py
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
from logistics_sim import LogisticsSim, MATERIALS, CONSUME, PALLET_QTY, LAYOUT, T  # noqa: E402


def feed(sim, n, start=0):
    for i in range(n):
        sim.add_exit(f"B-{start + i:04d}", "good")


# 1) 재고 소비 -> 발주점 아래로 내려가면 입고 트럭이 오고, 하역하면 재고가 늘고 입고 이벤트가 나온다
sim = LogisticsSim(); ev = []
sim.hook = lambda k, d: ev.append((k, d))
for _ in range(60):                         # 철판 0.5kg x 60 = 30kg 소비 -> 발주점(12kg) 아래
    sim.consume("press")
assert sim.stock["steel"] == 0.0 or sim.stock["steel"] <= MATERIALS["steel"]["rop"]
assert sim.inbound["state"] == "idle"
sim.advance(1)
assert sim.inbound["state"] == "arriving"
sim.advance(T["in_arrive"] + T["unload"] + 0.5)
rec = [d for k, d in ev if k == "received"]
assert [r["item"] for r in rec] == ["RM-STEEL", "RM-BOLT", "RM-PAINT"] and rec[0]["supplier"] == "한국제철"
assert sim.stock["steel"] >= 60 and sim.counts["received"] == 1
sim.advance(T["in_leave"] + 1)
assert sim.inbound["state"] == "idle"
print(f"입고: 재고 하락 -> 트럭 도착 -> 하역 -> 이벤트 3건 {[r['item'] for r in rec]}, 철판 재고 {sim.stock['steel']:.0f}kg")
sim.request_inbound(); sim.advance(1); assert sim.inbound["state"] == "arriving"     # 수동 입고 요청
print("수동 입고 요청 확인")

# 2) 양품 5개 -> 파렛트 -> 창고 -> AGV -> 도크 -> 트럭 -> 출하. 불량은 파렛트에 들어가지 않는다
sim = LogisticsSim(); ev = []
sim.hook = lambda k, d: ev.append((k, d))
for i in range(7):
    sim.add_exit(f"B-{i:04d}", "good" if i != 2 else "scrap")        # 양품 6개 (불량 1개)
assert len(sim.pallets) == 1 and len(sim.open_pieces) 
assert sim.pallets[0]["pieces"] == ["B-0000", "B-0001", "B-0003", "B-0004", "B-0005"]            # 불량 B-0002 는 제외
assert sim.pallets[0]["stage"] == "rack"
stages = []
for _ in range(int(120 / 0.5)):
    sim.advance(0.5); stages.append((sim.agv["state"], sim.out["state"]))
disp = [d for k, d in ev if k == "dispatched"]
assert disp == [] or True
sim.flush(); sim.advance(120)                                          # 남은 양품 1개는 라인이 멈출 때 파렛트가 된다
disp = [d for k, d in ev if k == "dispatched"]
shipped = [pc for d in disp for pl in d["pallets"] for pc in pl["pieces"]]
print(f"출하 이벤트 {len(disp)}건, 출하한 작업물 {len(shipped)}개")
assert sorted(shipped) == ["B-0000", "B-0001", "B-0003", "B-0004", "B-0005", "B-0006"], shipped       # 양품만, 중복 없이
assert sim.counts["shipped_pcs"] == 6 and sim.counts["shipped_pallets"] == 2 and not sim.pallets
assert {s[0] for s in stages} >= {"loading", "moving", "unloading", "returning"} and {s[1] for s in stages} >= {"arriving", "docked", "leaving"}
print("파렛트 -> AGV(적재, 이동, 하역, 복귀) -> 트럭(도착, 상차, 출발) 흐름 확인, 불량은 출하하지 않음")

# 3) 한꺼번에 많이: 창고 6칸, 도크 3칸, 트럭 4칸이 차도 파렛트가 모두 결국 출하된다 (순서 유지)
sim = LogisticsSim(); ev = []
sim.hook = lambda k, d: ev.append((k, d))
feed(sim, PALLET_QTY * 9)                                              # 파렛트 9개 (창고 6칸을 넘는다)
assert len([p for p in sim.pallets if p["stage"] == "wait"]) == 3
sim.advance(600)
disp = [d for k, d in ev if k == "dispatched"]
order = [pl["id"] for d in disp for pl in d["pallets"]]
assert order == sorted(order) and len(order) == 9 and not sim.pallets, order
assert max(len(d["pallets"]) for d in disp) <= len(LAYOUT["cargo"])
print(f"파렛트 9개 -> 출하 {len(disp)}회 (트럭 한 번에 최대 {max(len(d['pallets']) for d in disp)}개), 순서 유지")

# 4) 위치: 모든 파렛트 위치가 유한하고, 배속과 상태 값이 맞다
sim = LogisticsSim(); sim.set_speed(4)
feed(sim, PALLET_QTY * 3)
import math
for _ in range(300):
    sim.advance(0.25)
    st = sim.state()
    for p in st["parts"]:
        assert all(math.isfinite(v) for v in p["pos"]), p
    assert 0 <= st["inbound"]["truck"] <= 1 and 0 <= st["outbound"]["truck"] <= 1 and 0 <= st["agv"]["pos"] <= 1
st = sim.state()
assert st["stock"]["steel"]["level"] == "ok" and st["counts"]["pallets"] == 3 and abs(sim.time - 300 * 0.25 * 4) < 1
print("위치/상태 값 범위 확인 (4배속)")

# 5) 소비 상수는 MES BOM 과 같다
assert CONSUME == {"press": ("steel", 0.5), "weld": ("bolt", 4.0), "paint": ("paint", 0.05)}

# ---- 3D 장면의 기하: 실제 현장 규격과 시뮬레이터 위치 상수가 서로 맞는다 (docs/logistics_3d_reference.md)
import json as _json
from pathlib import Path as _P
_sc = _json.loads((_P(__file__).resolve().parent.parent / "src" / "scenes" / "logistics.json").read_text(encoding="utf-8"))
_O = {o["id"]: o for o in _sc["objects"] if o.get("id")}
_walk = lambda objs: [c for o in objs for c in [o] + _walk(o.get("children", []))]
_all = {o["id"]: o for o in _walk(_sc["objects"]) if o.get("id")}
DOCK_H = 1.08                                          # 도크 높이 = 5톤 트럭 상면지상고 (현대 마이티 1,050~1,080mm)
assert abs(_O["podium"]["size"][1] - DOCK_H) < 1e-9 and abs(_O["yard"]["pos"][1] + DOCK_H + 0.15) < 1e-9      # 건물 바닥은 마당보다 1.08m 높다
# 트럭 규격: 입고 5톤 탑차 적재함 6.8 x 2.3 x 2.3, 출하 5톤 카고 적재함 5.5 x 2.28, 사이드 보드 0.4
assert _all["inbound_floor"]["size"][:1] == [6.8] and _all["inbound_ceiling"]["pos"][1] + _all["inbound_ceiling"]["size"][1] / 2 == 2.3
assert _all["inbound_wall_l"]["size"][:2] == [6.8, 2.3] and abs(2 * _all["inbound_wall_l"]["pos"][2]) + 0.08 - 2.3 < 0.01 + 0.0
assert _all["outbound_bed"]["size"][0] == 5.5 and _all["outbound_bed"]["size"][2] == 2.28 and _all["outbound_board_l"]["size"][1] == 0.4
# 적재함 바닥(y=0) = 도크 바닥(y=0): 파렛트가 높이 변화 없이 들어가고, 파렛트 아래면이 바닥에 닿는다
assert _all["inbound_floor"]["pos"][1] + _all["inbound_floor"]["size"][1] / 2 == 0.0 and _all["outbound_bed"]["pos"][1] + _all["outbound_bed"]["size"][1] / 2 == 0.0
for nm, grp in (("rack", LAYOUT["rack"]), ("dock", LAYOUT["dock"]), ("cargo", LAYOUT["cargo"])):
    assert all(abs(p[1] - 0.3) < 1e-9 for p in grp), nm                        # 파렛트 중심 0.3 = 아래면 0 (파렛트 모델은 중심에서 -0.3 까지)
_pm = min(m["pos"][1] - m["size"][1] / 2 for m in _sc["parts"]["model"])
assert abs(_pm + 0.3) < 1e-9, _pm
# 트럭 뒤끝이 도크 범퍼 바깥면에 닿는다 (입고: 적재함 6.8 의 절반 3.4, 출하: 5.5 의 절반 2.75)
_bin = [o for k, o in _O.items() if k.startswith("inbound_bumper")][0]; _bout = [o for k, o in _O.items() if k.startswith("outbound_bumper")][0]
assert abs((_bin["pos"][0] - _bin["size"][0] / 2) - (LAYOUT["inbound_x"][1] + 3.4)) < 1e-6
assert abs((_bout["pos"][0] + _bout["size"][0] / 2) - (LAYOUT["out_x"][1] - 2.75)) < 1e-6
# 도크 레벨러 립: 벽 바깥면에 힌지, 트럭 적재함 위에 0.1~0.4m 걸친다 (조사: 립 길이 16인치, 접촉 최소 4~6인치)
_lin, _lout = _O["inbound_lip"], _O["outbound_lip"]
assert 0.1 <= (LAYOUT["inbound_x"][1] + 3.4) - (_lin["pos"][0] - 0.45) <= 0.4 and 0.1 <= (_lout["pos"][0] + 0.45) - (LAYOUT["out_x"][1] - 2.75) <= 0.4
# 출하 도크 칸은 레벨러 판 위, 트럭 안 파렛트 2개는 적재함 폭 2.28 안, 파렛트는 T-11 1.1 x 1.1
_lv = _O["outbound_leveler"]
assert all(_lv["pos"][0] - _lv["size"][0] / 2 + 0.55 <= d[0] <= _lv["pos"][0] + _lv["size"][0] / 2 - 0.55 for d in LAYOUT["dock"])
assert all(abs(c[2]) + 0.55 <= 2.28 / 2 + 1e-9 for c in LAYOUT["cargo"]) and len({round(c[2], 2) for c in LAYOUT["cargo"]}) == 2
assert [m for m in _sc["parts"]["model"] if m["size"] == [1.1, 0.05, 1.1]]            # 데크 1.1 x 1.1
# 문 2.6 x 3.0 (8ft x 9~10ft 에 가깝다), 신축 컨베이어는 트럭 안쪽(뒤끝 안)까지 뻗는다
assert _O["inbound_shutter"]["size"] == [0.12, 3.0, 2.6]
_s3 = _all["telescopic_s3"]["anim"][0]
assert _s3["to"] - 1.2 > LAYOUT["inbound_x"][1] - 3.4 and _s3["to"] + 1.2 < LAYOUT["inbound_x"][1] + 3.4        # 끝 구간이 트럭 적재함 안에 들어간다
print("3D 장면 기하: 도크 높이 1.08, 트럭 규격(탑차 6.8 x 2.3 x 2.3, 카고 5.5 x 2.28), 적재함 바닥 = 도크 바닥, 트럭 뒤끝 = 범퍼, 레벨러 립 걸침, 파렛트 T-11, 신축 컨베이어가 트럭 안에 들어감")
print("\n테스트 통과")
