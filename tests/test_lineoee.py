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
def in_time_order(rs):                      # 실제 이벤트는 발생 순서대로 순번(seq)이 붙는다
    rs = sorted(rs, key=lambda r: r["sim_t"])
    for i, r in enumerate(rs):
        r["seq"] = i
    return rs
r = lo.compute_line_oee(pd.DataFrame(in_time_order(rows)))
# 가용률 (100-20)/100 = 0.8, 성능률 8초 x 8개 / 80초 = 0.8, 품질률 6/8 = 0.75, OEE = 0.48
assert abs(r["availability"] - 0.8) < 1e-9 and abs(r["performance"] - 0.8) < 1e-9 and abs(r["quality"] - 0.75) < 1e-9, r
assert abs(r["oee"] - 0.48) < 1e-9 and r["good"] == 6 and r["scrap"] == 2 and r["down_s"] == 20
assert abs(r["util"]["press"]["down"] - 0.2) < 1e-9
print("손계산 일치: 가용률 80.0% x 성능률 80.0% x 품질률 75.0% = OEE 48.0%")
assert lo.compute_line_oee(pd.DataFrame()) is None and lo.compute_line_oee(None) is None

# 정지(가동 아님) 구간은 가동 시간에 들어가지 않는다
rows2 = [ev(0, "machine.state", {"state": "running_continuous"}), ev(50, "machine.state", {"state": "stopped"}),
         ev(150, "machine.state", {"state": "running_continuous"}), ev(200, "machine.state", {"state": "stopped"})]
assert abs(lo.compute_line_oee(pd.DataFrame(in_time_order(rows2)))["run_s"] - 100) < 1e-9
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

# ---- 3) 서버를 다시 켠 경우 (sim_t 가 0부터 다시 시작). 세션 1은 정지 이벤트 없이 끊기고, 세션 2가 이어진다
clock2 = [1793923800.0]
em2 = EventEmitter(now=lambda: clock2[0], keep=10 ** 6)


def session(seconds, stop=False):
    sm = LineSim(); sm.hook = LineEventBridge(em2)       # 새 서버 = 새 시뮬레이터, 새 브리지(sim_t 가 0부터)
    sm.start()
    for _ in range(int(seconds / 0.5)):
        sm.advance(0.5); clock2[0] += 0.5
    if stop:
        sm.stop()
        for _ in range(int(60 / 0.5)):
            sm.advance(0.5); clock2[0] += 0.5
    return sm


s1 = session(400)                                          # 정지하지 못하고 끊김 (서버를 끔)
s2 = session(400, stop=True)                               # 다시 켬: sim_t 0 부터, 정상 정지
s3 = session(300)                                          # 또 다시 켬
df3 = pd.DataFrame([{"seq": e["seq"], "ts": pd.Timestamp(e["ts"]), "event_type": e["type"], "piece_id": e["piece_id"],
                     "payload": e["payload"], "sim_t": e.get("sim_t")} for e in em2.since(-1, 10 ** 7)])
assert (df3["sim_t"] < df3["sim_t"].shift()).sum() == 2    # 서버를 다시 켠 지점 2곳
r3 = lo.compute_line_oee(df3)
exits3 = int((df3["event_type"] == "piece.exited").sum())
total_run = 400 + (s2.time) + 300                           # 세 세션의 가동 시간 (세션 1과 3은 끊긴 시점까지)
assert r3["sessions"] == 3 and r3["done"] == exits3
assert abs(r3["run_s"] - total_run) < 3, (r3["run_s"], total_run)                    # 세션을 이어 붙여도 가동 시간이 맞는다
assert 6.5 < r3["throughput_per_min"] <= 7.6, r3["throughput_per_min"]               # 이론 한계 7.5개/분을 넘지 않는다
assert r3["performance"] <= 1.0 and r3["availability"] == 1.0
# sim_t 로 정렬하던 예전 방식이면 어떻게 되는지: 세션이 뒤섞여 가동 시간이 틀어진다 (이 시험이 잡으려는 문제)
old = df3.sort_values(["sim_t", "seq"]).reset_index(drop=True); old["session"] = 0; old["gt"] = old["sim_t"]
run_old, running_old, tp = 0.0, False, float(old["gt"].iloc[0])
for _, row in old.iterrows():
    if running_old:
        run_old += max(0.0, row["gt"] - tp)
    tp = row["gt"]
    if row["event_type"] == "machine.state":
        running_old = str(row["payload"].get("state", "")).startswith("running")
assert abs(run_old - total_run) > 100, "예전 방식에서는 틀어져야 이 시험이 의미가 있다"
print(f"서버 재시작 3세션: 가동 {r3['run_s']:.0f}초 (기대 {total_run:.0f}), 처리량 {r3['throughput_per_min']:.2f}개/분, "
      f"[sim_t 로 정렬하던 예전 방식은 가동 {run_old:.0f}초로 틀림]")

fr = lo.fault_report(df, r)
print(fr.to_string(index=False))
assert list(fr["조작"]) == ["용접 속도 저하 (2.2배)", "해제 (정상)", "프레스 정지", "해제 (정상)"]
slow, press = float(fr.iloc[0]["처리량(개/분)"]), float(fr.iloc[2]["처리량(개/분)"])
assert 3.8 < slow < 5.2                                          # 용접 저하 시 약 4.5개/분
assert press < 0.5 * float(fr.iloc[3]["처리량(개/분)"])            # 프레스 정지 중에는 라인에 남은 부품 몇 개만 나온다
assert int(fr.iloc[0]["평상시 대비"].rstrip("%")) < 75 and int(fr.iloc[2]["평상시 대비"].rstrip("%")) < 50
print("\n테스트 통과")
