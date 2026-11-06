"""OEE 계산을 손으로 계산한 값과 비교하고, 시뮬레이터 이벤트로도 확인합니다.

실행 (프로젝트 폴더에서):  python tests/test_oee.py
(pandas 필요. MES 폴더는 필요 없습니다)
"""
import importlib.util
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("oee", ROOT / "mes" / "addons" / "src" / "oee.py")
oee = importlib.util.module_from_spec(spec); spec.loader.exec_module(oee)

T0 = pd.Timestamp("2026-11-06T00:00:00Z")


def ev(sec, typ, payload, seq=[0]):
    seq[0] += 1
    return {"event_id": str(seq[0]), "seq": seq[0], "ts": T0 + pd.Timedelta(seconds=sec), "source": "gateway",
            "event_type": typ, "piece_id": None, "work_order_id": None, "payload": payload}


# ---- 1) 손계산: 0~100초 운전, 200초에 마지막 이벤트 / 사이클 10개(각 6.0초, 가공 3초) / 분류 10개 중 금속 8개
rows = [ev(0, "machine.state", {"state": "running_continuous"})]
rows += [ev(10 + i, "cycle.completed", {"cycle_time_s": 6.0, "drill_time_set_ds": 30}) for i in range(10)]
rows += [ev(10 + i, "piece.classified", {"kind": "metal" if i < 8 else "nonmetal", "sensor": "x"}) for i in range(10)]
rows += [ev(100, "machine.state", {"state": "idle"}), ev(200, "count.updated", {"metal": 8, "nonmetal": 2, "total": 10})]
r = oee.compute_oee(pd.DataFrame(rows))
# 가용률 100/200 = 0.5, 이상 사이클 = (6-3)+3 = 6.0초 x 10 = 60초 -> 성능률 60/100 = 0.6, 품질률 8/10 = 0.8
assert abs(r["availability"] - 0.5) < 1e-9, r["availability"]
assert abs(r["performance"] - 0.6) < 1e-9, r["performance"]
assert abs(r["quality"] - 0.8) < 1e-9, r["quality"]
assert abs(r["oee"] - 0.24) < 1e-9, r["oee"]
assert r["ideal_overhead_s"] == 3.0 and r["cycles"] == 10 and r["defect"] == 2
print("손계산 일치: 가용률 50.0% x 성능률 60.0% x 품질률 80.0% = OEE 24.0%")

# ---- 2) 가공 시간을 바꾼 경우: 이상 사이클이 설정에 따라 달라지는지 (고정 3초 + 가공 3초 / 가공 2초)
rows = [ev(0, "machine.state", {"state": "running_single"})]
rows += [ev(10, "cycle.completed", {"cycle_time_s": 6.0, "drill_time_set_ds": 30}),
         ev(20, "cycle.completed", {"cycle_time_s": 5.0, "drill_time_set_ds": 20}),
         ev(30, "piece.classified", {"kind": "metal", "sensor": "x"}), ev(30, "machine.state", {"state": "idle"})]
r = oee.compute_oee(pd.DataFrame(rows))
assert list(r["cycle_df"]["ideal_s"]) == [6.0, 5.0] and abs(r["performance"] - 11.0 / 30) < 1e-9
print("가공 시간 변경 반영 확인: 이상 사이클 [6.0, 5.0]초")

# ---- 3) 기간 앞부분이 잘려 첫 상태 이벤트가 idle인 경우: 기간 시작부터 그 시각까지는 운전 중으로 본다
rows = [ev(0, "count.updated", {"metal": 1, "nonmetal": 0, "total": 1}), ev(40, "machine.state", {"state": "idle"}),
        ev(100, "count.updated", {"metal": 1, "nonmetal": 0, "total": 1})]
r = oee.compute_oee(pd.DataFrame(rows))
assert abs(r["run_s"] - 40) < 1e-9 and abs(r["availability"] - 0.4) < 1e-9
print("기간이 운전 중에 시작되는 경우 처리 확인")

# ---- 4) 빈 입력, 이벤트 표 변환
assert oee.compute_oee(pd.DataFrame()) is None and oee.compute_oee(None) is None
t = oee.recent_events(pd.DataFrame(rows))
assert list(t.columns) == ["시각", "유형", "작업물", "내용"] and len(t) == 3, t
print("빈 입력과 이벤트 표 변환 확인")

# ---- 5) 시뮬레이터 이벤트 (연속 운전 중 가공 시간 변경과 정지)
sys.path.insert(0, str(ROOT / "src"))
from plc_sim import PlcSim          # noqa: E402
from events import EventEmitter     # noqa: E402

clock = [1793923800.0]
sim = PlcSim(str(ROOT / "plc" / "1102"))
em = EventEmitter(now=lambda: clock[0])
script = {20: "M101", 700: "D10", 1800: "M102"}
for s in range(2100):
    clock[0] = 1793923800.0 + s * 0.05
    a = script.get(s)
    if a == "D10":
        em.note_param_origin("web"); sim.dev["D10"] = 20
    elif a:
        em.command(a, "web")
    sim.scan([a] if a and a != "D10" else [])
    em.observe(sim.dev)
df = pd.DataFrame([{**e, "ts": pd.Timestamp(e["ts"]), "event_type": e["type"]} for e in em.since(-1, 100000)])
df = df.drop(columns=["type"])
r = oee.compute_oee(df)
print(f"시뮬레이션: 계획 {r['planned_s']:.0f}초, 가동 {r['run_s']:.0f}초, 사이클 {r['cycles']}회, "
      f"고정 소요 {r['ideal_overhead_s']:.2f}초")
print(f"  가용률 {r['availability']:.1%} x 성능률 {r['performance']:.1%} x 품질률 {r['quality']:.1%} = OEE {r['oee']:.1%}")
assert 0.8 < r["availability"] <= 1 and 0.5 < r["performance"] <= 1 and abs(r["quality"] - 0.5) < 0.1
assert abs(r["oee"] - r["availability"] * r["performance"] * r["quality"]) < 1e-12
print(oee.recent_events(df, 6).to_string(index=False))
print("\n테스트 통과")
