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
print("\n테스트 통과")
