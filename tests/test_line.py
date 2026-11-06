"""프레스-용접-도장 라인 시뮬레이터를 확인합니다. (병목, 처리량, 결함 주입의 영향)

실행 (프로젝트 폴더에서):  python tests/test_line.py
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
from line_sim import LineSim, CYCLE  # noqa: E402


def run(fault="none", seconds=600, ramp=None):
    sim = LineSim()
    sim.start()
    sim.set_fault(fault)
    sim.advance(seconds)
    return sim


# 1) 기본: 병목은 사이클이 가장 긴 도장(8초) -> 처리량 7.5개/분
s = run()
k = s.state()["kpi"]
print(f"기본: 처리량 {k['throughput_per_min']}개/분 (이론 {60 / CYCLE['paint']:.1f}), 병목 {k['bottleneck_name']}, 양품률 {k['good_rate']}")
assert k["bottleneck"] == "paint" and abs(k["throughput_per_min"] - 7.5) < 0.5
u = s.state()["util"]
assert u["press"]["blocked"] > 0.3 and u["paint"]["working"] > 0.9 and u["paint"]["starved"] < 0.05   # 프레스는 막혀 쉬고, 도장은 쉬지 않는다
assert 0.85 < k["good_rate"] < 0.97                                                                  # 불량률 8% 안팎
assert s.counts["in"] >= s.counts["good"] + s.counts["scrap"]
print(f"  가동률(일하는 시간): 프레스 {u['press']['working']:.0%} (막힘 {u['press']['blocked']:.0%}), "
      f"용접 {u['weld']['working']:.0%} (막힘 {u['weld']['blocked']:.0%}), 도장 {u['paint']['working']:.0%}")

# 2) 용접이 2.2배 느려지면 병목이 용접(13.2초)으로 옮겨가고 처리량이 줄어든다
s = run("weld_slow")
k = s.state()["kpi"]
print(f"용접 속도 저하: 처리량 {k['throughput_per_min']}개/분 (이론 {60 / 13.2:.1f}), 병목 {k['bottleneck_name']}")
assert k["bottleneck"] == "weld" and abs(k["throughput_per_min"] - 60 / 13.2) < 0.5
assert s.state()["util"]["paint"]["starved"] > 0.2                                                   # 하류인 도장은 일감이 없어 논다

# 3) 프레스가 멈추면 하류가 차례로 비고 처리량이 0으로 간다. 도장이 멈추면 상류가 막힌다
s = LineSim(); s.start(); s.advance(120); before = s.counts["good"] + s.counts["scrap"]
s.set_fault("press_down"); s.advance(120)
after = s.counts["good"] + s.counts["scrap"]
st = s.state()["stations"]
print(f"프레스 정지 2분: 추가 완성 {after - before}개, 용접 {st['weld']['state']}, 도장 {st['paint']['state']}")
assert st["press"]["state"] == "down" and st["weld"]["state"] == "starved" and st["paint"]["state"] == "starved"
assert after - before <= 5          # 프레스 뒤 칸(컨베이어1, 용접, 컨베이어2, 도장, 컨베이어3)에 남아 있던 부품 5개까지만 나온다
s = LineSim(); s.start(); s.set_fault("paint_down"); s.advance(120)
st = s.state()["stations"]
print(f"도장 정지 2분: 프레스 {st['press']['state']}, 용접 {st['weld']['state']}, 도장 {st['paint']['state']}")
assert st["paint"]["state"] == "down" and st["weld"]["state"] == "blocked" and st["press"]["state"] == "blocked"
assert s.counts["good"] + s.counts["scrap"] == 0

# 4) 정지/배속/리셋, 부품 상태 표시
# 처리량은 라인이 채워지는 초기 구간에 영향받지 않고, 병목은 60초 이후부터 표시한다
s = LineSim(); s.start(); s.advance(50); k = s.state()["kpi"]
assert k["bottleneck"] is None and 6.5 < k["throughput_per_min"] < 8.5, k
s.advance(20); assert s.state()["kpi"]["bottleneck"] == "paint"
s = LineSim(); s.advance(10); assert s.time == 0 and not s.state()["parts"]     # 시작 전에는 진행하지 않는다
s.start(); s.set_speed(4); s.advance(10)
assert abs(s.time - 40) < 0.2                                                    # 4배속
st = s.state()
assert all(0 <= p["t"] <= 1 for p in st["parts"]) and len(st["parts"]) >= 2
stages = {p["stage"] for p in st["parts"]}
s.reset(); assert s.state()["counts"] == {"in": 0, "good": 0, "scrap": 0} and not s.running
try:
    s.set_fault("xx"); raise AssertionError
except ValueError:
    pass
print("정지/배속/리셋/잘못된 결함 확인")

# 정지는 투입을 멈추고 라인에 남은 부품을 모두 내보낸 뒤에 멈춘다 (작업이 중간에 얼어붙지 않게)
s = LineSim(); s.start(); s.advance(70)
n_in = s.counts["in"]; assert len(s.state()["parts"]) >= 4
s.stop(); assert s.running and s.state()["draining"]
s.advance(5); assert s.counts["in"] == n_in and s.running                   # 새 투입은 없고 아직 가동 중
s.advance(60); st = s.state()
assert not s.running and not st["draining"] and not st["parts"] and s.counts["good"] + s.counts["scrap"] == n_in
print(f"정지: 투입 중단 후 라인 비움 ({n_in}개 모두 나온 뒤 정지)")
s = LineSim(); s.start(); s.advance(40); s.stop(); s.advance(3); s.start()   # 비우는 중에 다시 시작
assert s.running and not s.state()["draining"]
s.advance(20); assert s.counts["in"] > 6
s = LineSim(); s.start(); s.stop(); assert not s.running                      # 비어 있으면 바로 정지

# 5) 같은 시드면 같은 결과 (재현 가능)
a, b = run(), run()
assert a.counts == b.counts and a.state()["util"] == b.state()["util"]
print("재현성 확인")
print("\n테스트 통과")

# 재공품(WIP): 칸마다 empty / working / waiting / down, kpi.wip = 비어 있지 않은 칸 수, 일을 마치고 기다리는 부품은 waiting 으로 표시
from line_sim import ELEMENTS  # noqa: E402
sim = LineSim(); sim.start()
st0 = sim.state()
assert set(st0["occ"]) == set(ELEMENTS) and st0["kpi"]["wip"] == 0 and st0["kpi"]["waiting"] == 0 and set(st0["occ"].values()) == {"empty"}
seen, max_wip = set(), 0
for _ in range(1200):
    sim.advance(0.5)
    st = sim.state()
    assert set(st["occ"].values()) <= {"empty", "working", "waiting", "down"}
    assert st["kpi"]["wip"] == sum(v != "empty" for v in st["occ"].values()) == len(st["parts"])           # 재공품 수 = 라인 안의 부품 수
    assert st["kpi"]["waiting"] == sum(v == "waiting" for v in st["occ"].values()) == sum(p["waiting"] for p in st["parts"])
    seen |= set(st["occ"].values()); max_wip = max(max_wip, st["kpi"]["wip"])
assert {"empty", "working", "waiting"} <= seen and 3 <= max_wip <= len(ELEMENTS), (seen, max_wip)         # 병목(도장) 앞에서 용접 부품이 기다린다
sim.set_fault("press_down"); sim.advance(5)
assert sim.state()["occ"]["press"] in ("empty", "down")
sim = LineSim(); sim.start(); sim.set_fault("paint_down"); sim.advance(300)
st = sim.state()
assert st["occ"]["paint"] == "down" and st["kpi"]["waiting"] >= 1 and st["kpi"]["wip"] >= 3, st["occ"]        # 도장이 서면 뒤가 막혀 부품이 쌓이고 기다린다
print(f"재공품: 최대 {max_wip}개, 상태 {sorted(seen)}, 도장 정지 시 {st['kpi']['wip']}개가 라인에 머물고 {st['kpi']['waiting']}개가 기다림")
print("\n테스트 통과")
