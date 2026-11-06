"""프레스 라인 OEE 계산을 손계산과 시뮬레이터 결과로 확인합니다 (DB 없이).

실행 (프로젝트 폴더에서):  python tests/test_lineoee.py   (pandas 필요)
"""
import importlib.util
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
spec = importlib.util.spec_from_file_location("lineoee", ROOT / "mes" / "addons" / "src" / "lineoee.py")
lo = importlib.util.module_from_spec(spec); spec.loader.exec_module(lo)
from line_sim import LineSim                      # noqa: E402
from line_events import LineEventBridge          # noqa: E402
from events import EventEmitter                  # noqa: E402

T0 = pd.Timestamp("2026-11-06T00:00:00Z")
_seq = [0]


def ev(sim_t, typ, payload):
    _seq[0] += 1
    return {"seq": _seq[0], "ts": T0 + pd.Timedelta(seconds=sim_t), "event_type": typ, "piece_id": None, "payload": payload, "sim_t": sim_t}


# ---- 1) 손계산: 0~100초 가동, 프레스 정지 40~60초(20초), 완성 8개(양품 6, 불량 2), 공칭 사이클 8초
rows = [ev(0, "machine.state", {"state": "running_continuous"}),
        ev(10, "station.completed", {"station": "paint", "duration_s": 8.0, "nominal_s": 8.0}),
        ev(40, "station.state", {"station": "press", "from": "working", "to": "down"}),
        ev(60, "station.state", {"station": "press", "from": "down", "to": "working"})]
rows += [ev(20 + 10 * i, "piece.exited", {"result": "scrap" if i in (2, 5) else "good"}) for i in range(8)]
rows.append(ev(100, "machine.state", {"state": "stopped"}))
r = lo.compute_line_oee(pd.DataFrame(rows))
# 가용률 (100-20)/100 = 0.8, 성능률 8초 x 8개 / 80초 = 0.8, 품질률 6/8 = 0.75, OEE = 0.48
assert abs(r["availability"] - 0.8) < 1e-9 and abs(r["performance"] - 0.8) < 1e-9 and abs(r["quality"] - 0.75) < 1e-9, r
assert abs(r["oee"] - 0.48) < 1e-9 and r["good"] == 6 and r["scrap"] == 2 and r["down_s"] == 20
assert abs(r["util"]["press"]["down"] - 0.2) < 1e-9
print("손계산 일치: 가용률 80.0% x 성능률 80.0% x 품질률 75.0% = OEE 48.0%")
assert lo.compute_line_oee(pd.DataFrame()) is None and lo.compute_line_oee(None) is None

# 정지(가동 아님) 구간은 가동 시간에 들어가지 않는다
rows2 = [ev(0, "machine.state", {"state": "running_continuous"}), ev(50, "machine.state", {"state": "stopped"}),
         ev(150, "machine.state", {"state": "running_continuous"}), ev(200, "machine.state", {"state": "stopped"})]
assert abs(lo.compute_line_oee(pd.DataFrame(rows2))["run_s"] - 100) < 1e-9
print("정지 구간 제외 확인 (가동 50초 + 50초)")

# ---- 2) 시뮬레이터: 정상 -> 용접 속도 저하 -> 정상 -> 프레스 정지 -> 정상, 마지막에 정지(라인 비움)
clock = [1793923800.0]
em = EventEmitter(now=lambda: clock[0], keep=10 ** 6)
sim = LineSim(); sim.hook = LineEventBridge(em)


def run(sec):
    for _ in range(int(sec / 0.5)):
        sim.advance(0.5); clock[0] = 1793923800.0 + sim.time


sim.start(); run(300)
sim.set_fault("weld_slow"); run(240)
sim.set_fault("none"); run(180)
sim.set_fault("press_down"); run(90)
sim.set_fault("none"); run(240)
sim.stop(); run(60)
assert not sim.running
df = pd.DataFrame([{"seq": e["seq"], "ts": pd.Timestamp(e["ts"]), "event_type": e["type"], "piece_id": e["piece_id"],
                    "payload": e["payload"], "sim_t": e.get("sim_t")} for e in em.since(-1, 10 ** 7)])
r = lo.compute_line_oee(df)
st = sim.state()
print(f"시뮬레이션 {r['run_s']:.0f}초 가동: 정지 {r['down_s']:.0f}초, 완성 {r['done']}개 (양품 {r['good']} / 불량 {r['scrap']})")
print(f"  가용률 {r['availability']:.1%} x 성능률 {r['performance']:.1%} x 품질률 {r['quality']:.1%} = OEE {r['oee']:.1%}")
assert r["done"] == st["counts"]["good"] + st["counts"]["scrap"] and r["good"] == st["counts"]["good"]   # 시뮬레이터의 집계와 일치
assert abs(r["down_s"] - 90) < 1.5                              # 프레스 정지 90초
assert abs(r["ideal_cycle_s"] - 8.0) < 1e-9
assert 0.9 < r["availability"] < 0.95 and 0.85 < r["performance"] < 0.95 and 0.85 < r["quality"] < 0.97   # 용접 저하 240초의 손실이 전체 성능률 약 10%
assert abs(r["oee"] - r["availability"] * r["performance"] * r["quality"]) < 1e-12

tbl = lo.station_table(r)
w = tbl[tbl["공정"] == "용접"].iloc[0]
assert 6.5 < w["평균 사이클(초)"] < 9.5 and w["공칭 사이클(초)"] == 6.0   # 정상 6.0초와 저하 13.2초의 평균
assert abs(tbl[tbl["공정"] == "프레스"].iloc[0]["정지"] - 90 / r["run_s"] * 100) < 1
print(tbl.to_string(index=False))

fr = lo.fault_report(df, r)
print(fr.to_string(index=False))
assert list(fr["조작"]) == ["용접 속도 저하 (2.2배)", "해제 (정상)", "프레스 정지", "해제 (정상)"]
slow, press = float(fr.iloc[0]["처리량(개/분)"]), float(fr.iloc[2]["처리량(개/분)"])
assert 3.8 < slow < 5.2                                          # 용접 저하 시 약 4.5개/분
assert press < 0.5 * float(fr.iloc[3]["처리량(개/분)"])            # 프레스 정지 중에는 라인에 남은 부품 몇 개만 나온다
assert int(fr.iloc[0]["평상시 대비"].rstrip("%")) < 75 and int(fr.iloc[2]["평상시 대비"].rstrip("%")) < 50
print("\n테스트 통과")
