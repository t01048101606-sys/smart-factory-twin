"""협동로봇 팔레타이징 셀 시험: 역기구학, 집기와 놓기 위치, 사이클 시간, 파렛트 마감, 이벤트, 물류 연동.

실행 (프로젝트 폴더에서):  python tests/test_cobot.py
"""
import json
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
import cobot_sim as C                                           # noqa: E402
from cobot_sim import CobotSim                                  # noqa: E402
from cobot_events import CobotEventBridge, LINE_ID               # noqa: E402
from line_events import LINE_ID as PRESS_LINE_ID                 # noqa: E402
from logistics_sim import LogisticsSim                           # noqa: E402
from logistics_events import LogisticsEventBridge                # noqa: E402
from events import EventEmitter                                  # noqa: E402

try:
    import jsonschema
    V = jsonschema.Draft7Validator(json.loads((ROOT / "docs" / "event_schema.json").read_text(encoding="utf-8")))
except ImportError:
    V = None

dist = lambda a, b: math.dist(a, b)

# ---- 1) 역기구학: 집기, 파렛트 5칸, NG 상자, 각 위 1.3 높이, 홈 모두 닿고 FK 로 되돌려 보면 같다
pts = {"pick": C.PICK, "ng": C.NG_DROP, "home": C.HOME_TIP}
pts.update({f"slot{i}": s for i, s in enumerate(C.SLOTS)})
pts.update({k + "_hover": C.hover(v) for k, v in list(pts.items()) if k != "home"})
worst = max(dist(C.fk(C.ik(t)), t) for t in pts.values())
assert worst < 1e-9, worst
for t in pts.values():                          # 그리퍼는 항상 아래를 향한다 (shoulder + elbow + wrist = -90도)
    j = C.ik(t)
    assert abs(j["shoulder"] + j["elbow"] + j["wrist"] + math.pi / 2) < 1e-9 and j["elbow"] < 0 and 0 < j["shoulder"] < math.pi / 2 + 0.6
try:
    C.ik((20.0, 1.0, 0.0)); raise AssertionError("닿지 않는 위치인데 오류가 나지 않았습니다")
except ValueError:
    pass
print(f"역기구학: {len(pts)}개 지점 모두 닿음 (FK 오차 {worst:.1e}), 그리퍼는 항상 아래를 향함, 닿지 않는 위치는 거부")

# ---- 2) 시뮬레이션: 8초마다 작업물이 나오고 5번째마다 불량. 집을 때와 놓을 때 그리퍼 끝 위치를 확인한다
log = []
sim = CobotSim()
sim.hook = lambda kind, d: log.append((kind, d))
results = ["scrap" if i % 5 == 4 else "good" for i in range(33)]       # 양품 27, 불량 6 -> 파렛트 5개 + 2개 남음
yaw_prev, max_dyaw, max_queue, carried_err = None, 0.0, 0, 0.0
t = 0.0
nxt = 0
while t < 8 * len(results) + 40:
    if nxt < len(results) and t >= nxt * 8.0:
        sim.add_part(f"B-{nxt:04d}", results[nxt]); nxt += 1
    sim.step(0.05); t += 0.05
    st = sim.state()
    max_queue = max(max_queue, st["queue"])
    if yaw_prev is not None:
        max_dyaw = max(max_dyaw, abs(st["arm"]["yaw"] - yaw_prev))
    yaw_prev = st["arm"]["yaw"]
    for p in st["parts"]:
        if p["stage"] == "carried":
            carried_err = max(carried_err, dist(p["pos"], C.fk(sim.joints)))
    assert all(math.isfinite(v) for v in st["arm"].values())
picked = [d for k, d in log if k == "picked"]; placed = [d for k, d in log if k == "placed"]
assert len(picked) == len(placed) == len(results), (len(picked), len(placed))
assert max(dist(d["tip"], C.PICK) for d in picked) < 1e-6                    # 집을 때 그리퍼 끝이 집는 위치에 있다
for d, r in zip(placed, results):                                           # 놓을 때는 파렛트 칸 또는 NG 상자 위
    want = C.SLOTS[d["slot"]] if d["target"] == "pallet" else C.NG_DROP
    assert dist(d["tip"], want) < 1e-6 and (d["target"] == "pallet") == (r == "good"), (d, r)
assert [d["id"] for d in placed] == [f"B-{i:04d}" for i in range(len(results))]   # 들어온 순서대로 처리
cycles = [d["cycle_s"] for d in placed]
assert 4.5 < min(cycles) and max(cycles) < 6.0, (min(cycles), max(cycles))      # 라인 사이클(8초)보다 빠르다
assert max_queue <= 2, max_queue                                            # 작업물이 쌓이지 않는다
assert max_dyaw < 0.3, max_dyaw                                             # 관절 각도가 +-pi 로 뒤집히면 한 스텝에 6rad 가까이 튄다. 연속이면 190도를 1.4초에 도는 정도(0.2rad)
assert carried_err < 2e-3, carried_err                                      # 들고 있는 워크는 그리퍼 끝을 따라간다
print(f"집기/놓기: {len(picked)}개 모두 집는 위치와 놓는 위치(칸별)에 정확히 닿음, 사이클 {min(cycles):.2f}~{max(cycles):.2f}초, 대기열 최대 {max_queue}개, 관절 연속(1스텝 최대 {max_dyaw:.3f}rad)")

# 파렛트: 양품 5개마다 마감, 칸 순서대로
closed = [d for k, d in log if k == "pallet_closed"]
good_ids = [f"B-{i:04d}" for i, r in enumerate(results) if r == "good"]
assert len(closed) == 5 and all(not c["partial"] and len(c["pieces"]) == 5 for c in closed)
assert [x for c in closed for x in c["pieces"]] == good_ids[:25]
slots = [d["slot"] for d in placed if d["target"] == "pallet"]
assert slots[:10] == [0, 1, 2, 3, 4, 0, 1, 2, 3, 4]
assert sim.state()["counts"] == {"inspected": 33, "good": 27, "ng": 6, "pallets": 5, "picks": 33}
st = sim.state()
assert st["pallet"]["count"] == 2 and st["pallet"]["slots"] == [1, 1, 0, 0, 0] and len(sim.ng) == 6
print("파렛트: 양품 5개마다 마감(5개), 칸 0~4 순서, 남은 양품 2개는 파렛트에 적재 중, NG 수납함 6개")

# 라인이 멈추면 셀이 다 빈 뒤 모자란 파렛트를 마감 (flush)
sim.request_flush()
for _ in range(100):
    sim.step(0.05)
partial = [d for k, d in log if k == "pallet_closed"][-1]
assert partial["partial"] and partial["pieces"] == good_ids[25:] and sim.counts["pallets"] == 6
sim.request_flush()                      # 비어 있으면 아무 일도 없다
for _ in range(100):
    sim.step(0.05)
assert sim.counts["pallets"] == 6 and not sim.flush_req
# 일하는 중에 flush 를 요청하면 일이 끝난 뒤에 마감한다
s2 = CobotSim(); got = []
s2.hook = lambda k, d: got.append((k, d))
for i in range(3):
    s2.add_part(f"X-{i}", "good")
s2.request_flush()
for _ in range(800):
    s2.step(0.05)
pc = [d for k, d in got if k == "pallet_closed"]
assert len(pc) == 1 and pc[0]["partial"] and pc[0]["pieces"] == ["X-0", "X-1", "X-2"]
print("flush: 라인이 멈추면 셀이 다 빈 뒤 모자란 파렛트를 마감 (일하는 중에 요청해도 일이 끝난 뒤)")

# 배속이 달라도 같은 결과
a, b = CobotSim(), CobotSim(); b.set_speed(4)
for s in (a, b):
    for i in range(6):
        s.add_part(f"S-{i}", "good" if i != 2 else "scrap")
a.advance(60); b.advance(15)
assert a.state()["counts"] == b.state()["counts"] and a.state()["pallet"] == b.state()["pallet"]
print("배속 x4 에서도 같은 결과")

# ---- 3) 이벤트: 프레스 라인의 piece.exited 로 셀이 움직이고, 스키마와 순서가 맞다
em = EventEmitter(now=lambda: 1793923800.0 + clock[0], keep=10 ** 6)
clock = [0.0]
cs = CobotSim(); cb = CobotEventBridge(em, cs)
lg = LogisticsSim(); lb = LogisticsEventBridge(em, lg, from_cobot=True)           # 파렛트는 로봇이 쌓은 것
for i in range(12):
    em.emit("piece.exited", {"result": "scrap" if i == 3 else "good"}, piece_id=f"B-20261106-{i:04d}", line_id=PRESS_LINE_ID, sim_t=i * 8.0)
    for _ in range(160):
        cs.step(0.05); clock[0] += 0.05
em.emit("machine.state", {"state": "stopped", "reason": "line stop"}, line_id=PRESS_LINE_ID, sim_t=100.0)
for _ in range(200):
    cs.step(0.05); clock[0] += 0.05
ev = em.since(-1, 10 ** 6)
by = {}
for e in ev:
    by.setdefault(e["type"], []).append(e)
if V:
    bad = [e for e in ev if not V.is_valid(e)]
    assert not bad, bad[0]
assert len(by["vision.inspected"]) == 12 and len(by["cobot.placed"]) == 12
assert sum(e["payload"]["result"] == "scrap" for e in by["vision.inspected"]) == 1 and all(0.94 <= e["payload"]["confidence"] <= 1 for e in by["vision.inspected"])
assert [e["payload"]["target"] for e in by["cobot.placed"]].count("ng_bin") == 1
pc = [e for e in by["cobot.pallet_closed"]]
assert [len(e["payload"]["pieces"]) for e in pc] == [5, 5, 1], [len(e["payload"]["pieces"]) for e in pc]      # 양품 11개 = 5 + 5 + 모자란 1
assert [e["payload"]["partial"] for e in pc] == [False, False, True]
sims = [e["sim_t"] for e in ev if e["line_id"] == LINE_ID]
assert all(b2 >= a2 for a2, b2 in zip(sims, sims[1:]))
# 물류: 로봇이 마감한 파렛트로만 파렛트가 만들어진다 (piece.exited 로는 만들어지지 않는다)
assert lg.counts["pallets"] == 3 and sum(len(p["pieces"]) for p in lg.pallets) == 11
lg2 = LogisticsSim(); em2 = EventEmitter(now=lambda: 1793923800.0, keep=100)
LogisticsEventBridge(em2, lg2, from_cobot=True)
for i in range(6):
    em2.emit("piece.exited", {"result": "good"}, piece_id=f"Q-{i}", line_id=PRESS_LINE_ID, sim_t=i)
assert lg2.counts["pallets"] == 0
print(f"이벤트: 비전 검사 12건(불량 1건), 놓기 12건(NG 1건), 파렛트 3개(5개, 5개, 모자란 1개 마감), 스키마 통과, 물류는 로봇이 마감한 파렛트로만 생성")
print("\n테스트 통과")
