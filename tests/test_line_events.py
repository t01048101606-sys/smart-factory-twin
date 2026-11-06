"""프레스·용접·도장 라인이 내보내는 공통 이벤트를 확인합니다 (스키마, 순서, 시간, 불량 표시).

실행 (프로젝트 폴더에서):  python tests/test_line_events.py
"""
import collections
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
from line_sim import LineSim                       # noqa: E402
from line_events import LineEventBridge, LINE_ID   # noqa: E402
from events import EventEmitter                    # noqa: E402

try:
    import jsonschema
    V = jsonschema.Draft7Validator(json.loads((ROOT / "docs" / "event_schema.json").read_text(encoding="utf-8")))
except ImportError:
    V = None

T0 = 1793923800.0
sim = LineSim()
clock = [T0]
em = EventEmitter(now=lambda: clock[0], keep=10 ** 6)
sim.hook = LineEventBridge(em)


def run(seconds, step=0.5):
    n = int(seconds / step)
    for _ in range(n):
        sim.advance(step)
        clock[0] = T0 + sim.time


sim.start(); run(120)
sim.set_fault("weld_slow"); run(120)
sim.set_fault("none"); run(120)
sim.stop(); run(40)            # 라인에 남은 부품이 모두 나오고 정지한다
sim.start(); run(60)
sim.reset(); sim.start(); run(60)            # 리셋 뒤에도 sim_t 가 이어져야 한다
ev = em.since(-1, 10 ** 7)
by = collections.Counter(e["type"] for e in ev)
print("이벤트", len(ev), "개:", dict(by))
assert {e["line_id"] for e in ev} == {LINE_ID}

# 스키마
if V:
    bad = [e for e in ev if not V.is_valid(e)]
    assert not bad, bad[0]
    print("스키마 검증 통과")

# 시간: sim_t 는 이벤트 순서대로 줄지 않고, 리셋 뒤에도 이어진다
ts = [e["sim_t"] for e in ev]
assert all(b >= a for a, b in zip(ts, ts[1:])), "sim_t 가 거꾸로 갑니다"
assert 480 < ts[-1] < 560, ts[-1]
print(f"sim_t 단조 증가 확인 (마지막 {ts[-1]:.0f}초, 리셋 포함)")

# 작업물 번호 형식과 중복
pids = [e["piece_id"] for e in ev if e["type"] == "cycle.started"]
assert all(re.fullmatch(r"B-\d{8}-\d{4}", p) for p in pids) and len(set(pids)) == len(pids)
assert len(pids) == by["cycle.started"]

# 부품마다 공정 완료가 press -> weld -> paint 순서로, 끝나면 piece.exited
steps = collections.defaultdict(list)
for e in ev:
    if e["type"] == "station.completed":
        steps[e["piece_id"]].append(e["payload"]["station"])
for pid, s in steps.items():
    assert s in (["press"], ["press", "weld"], ["press", "weld", "paint"]), (pid, s)
exited = {e["piece_id"]: e["payload"]["result"] for e in ev if e["type"] == "piece.exited"}
assert all(steps[p] == ["press", "weld", "paint"] for p in exited)
print(f"부품 {len(pids)}개: 공정 완료는 press -> weld -> paint 순서, 라인 끝까지 간 {len(exited)}개")

# 용접 불량이 piece.exited 의 결과와 일치
weld = {e["piece_id"]: e["payload"]["defect"] for e in ev if e["type"] == "station.completed" and e["payload"]["station"] == "weld"}
assert all((exited[p] == "scrap") == weld[p] for p in exited)
print(f"용접 불량 표시와 라인 끝 결과 일치 (불량 {sum(r == 'scrap' for r in exited.values())}개 / 완성 {len(exited)}개)")

# 결함 주입이 사이클 시간에 반영된다 (용접 6.0초 -> 13.2초), 공칭값(nominal_s)은 그대로
w = [(e["sim_t"], e["payload"]["duration_s"], e["payload"]["nominal_s"]) for e in ev if e["type"] == "station.completed" and e["payload"]["station"] == "weld"]
normal = [d for t, d, n in w if t < 120 or 255 < t < 270]
slow = [d for t, d, n in w if 140 < t < 240]
assert normal and all(abs(d - 6.0) < 0.1 for d in normal), normal
assert slow and all(abs(d - 13.2) < 0.1 for d in slow), slow
assert all(n == 6.0 for _, _, n in w)
print(f"용접 사이클: 정상 {sum(normal) / len(normal):.1f}초, 속도 저하 중 {sum(slow) / len(slow):.1f}초 (공칭 6.0초)")

# 공정 상태 변화, 가동 상태, 결함
assert by["station.state"] > 20 and by["sim.fault"] == 2
ms = [(e["payload"]["state"], e["payload"]["reason"]) for e in ev if e["type"] == "machine.state"]
assert ms[0] == ("running_continuous", "line start") and ("stopped", "line stop") in ms and ("idle", "reset") in ms, ms
assert ("running_continuous", "drain") in ms          # 정지 요청(투입 중단) 시점
assert ms.index(("running_continuous", "drain")) < ms.index(("stopped", "line stop"))
print("가동 상태(시작, 정지, 리셋)와 결함 주입 이벤트 확인")
print("\n테스트 통과")
