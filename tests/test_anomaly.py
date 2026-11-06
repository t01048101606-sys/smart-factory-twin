"""사이클 시간 이상 감지기를 시험합니다.

1) 합성 데이터로 감지기 규칙을 확인하고  2) 시뮬레이터에 결함을 주입해 실제로 잡는지 측정합니다.
실행 (프로젝트 폴더에서):  python tests/test_anomaly.py
"""
import json
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
from anomaly import CycleAnomalyDetector   # noqa: E402
from plc_sim import PlcSim                 # noqa: E402
from events import EventEmitter            # noqa: E402

try:
    import jsonschema
    SCHEMA = jsonschema.Draft7Validator(json.loads((ROOT / "docs" / "event_schema.json").read_text(encoding="utf-8")))
except ImportError:
    SCHEMA = None


def run(det, series, ds=30):
    """사이클 시간 목록을 감지기에 넣고 (판정, 경보 이벤트)를 모은다."""
    judg, alarms = [], []
    for i, ct in enumerate(series):
        for typ, p in det.on_cycle(ct, ds):
            (judg if typ == "ai.judgement" else alarms).append((i, typ, p))
    return judg, alarms


# ---- 1) 합성 데이터 --------------------------------------------------------------
rnd = random.Random(1)
healthy = [6.4 + rnd.choice([0, 0, 0, 0.05]) for _ in range(120)]
j, a = run(CycleAnomalyDetector(), healthy)
assert not a, a                      # 정상 120회에서 경보가 없어야 한다
assert [x[2]["phase"] for x in j[:8]] == ["learning"] * 8 and j[8][2]["phase"] == "monitoring"
print("정상 120회: 경보 0건, 처음 8회는 학습, 이후 감시")

# 갑작스러운 변화: 40번째부터 +3.6초
step = healthy[:40] + [ct + 3.6 for ct in healthy[40:70]] + healthy[70:]
j, a = run(CycleAnomalyDetector(), step)
raised = [x for x in a if x[1] == "alarm.raised"]; cleared = [x for x in a if x[1] == "alarm.cleared"]
assert len(raised) == 1 and raised[0][0] == 41, raised          # 두 번째 이상 사이클에서 경보 (연속 2회 규칙)
assert raised[0][2]["severity"] == "critical"
assert len(cleared) == 1 and 70 <= cleared[0][0] <= 72, cleared  # 정상으로 돌아오고 3회 뒤 해제
print(f"갑작스러운 변화(+3.6초): 40번째 사이클부터 -> {raised[0][0]}번째에 경보, {cleared[0][0]}번째에 해제")

# 서서히 나빠짐: 40번째부터 사이클마다 +0.04초
drift = healthy[:40] + [healthy[i] + 0.04 * (i - 39) for i in range(40, 90)]
j, a = run(CycleAnomalyDetector(), drift)
raised = [x for x in a if x[1] == "alarm.raised"]
assert raised and raised[0][0] < 60, raised
shift = 0.04 * (raised[0][0] - 39)
print(f"서서히 나빠짐(+0.04초/사이클): {raised[0][0]}번째에 경보 (그때까지 늘어난 시간 약 +{shift:.2f}초)")

# 가공 시간(D10)을 바꿔도 이상이 아니다: 30 -> 20 으로 바꾸면 사이클 시간이 1초 줄어든다
det = CycleAnomalyDetector()
j, a = run(det, healthy[:30])
j2, a2 = [], []
for ct in healthy[30:60]:
    for typ, p in det.on_cycle(ct - 1.0, 20):
        (j2 if typ == "ai.judgement" else a2).append(p)
assert not a2 and all(p["result"] == "ok" for p in j2)
print("가공 시간 설정을 3.0 -> 2.0초로 바꿔도 오탐 없음")

# 기준값 다시 학습
det.reset(); assert det.status()["phase"] == "learning"
print("기준값 재학습(reset) 확인")

# 실측 데이터(학원 PC에서 결함 없이 돌린 146사이클): 컴퓨터 부하로 사이클 시간이 조금씩 이동한다.
# 예전 설정(산포 최솟값 0.05초, 양쪽 같은 임계값)에서는 이 데이터에서 오탐 경보가 났다.
real = json.loads((ROOT / "tests" / "data" / "real_healthy_cycles.json").read_text(encoding="utf-8"))
series = [v + real["drill_time_set_ds"] / 10 for v in real["values"]]
_, old_alarms = run(CycleAnomalyDetector(rel_floor=0.0, neg_factor=1.0), series)
assert any(x[1] == "alarm.raised" for x in old_alarms), "실측 데이터가 예전 오탐을 재현하지 못합니다"
_, new_alarms = run(CycleAnomalyDetector(), series)
assert not new_alarms, new_alarms
print(f"실측 정상 데이터 {len(series)}사이클: 예전 설정 경보 {sum(x[1] == 'alarm.raised' for x in old_alarms)}건 -> 현재 설정 0건")
# 크게 빨라지는 경우(단계 누락 의심)는 여전히 이상으로 본다
fast = healthy[:40] + [ct - 2.0 for ct in healthy[40:60]] + healthy[60:]
_, a = run(CycleAnomalyDetector(), fast)
assert any(x[1] == "alarm.raised" for x in a)
print("크게 빨라지는 경우(-2.0초)는 여전히 경보")

# ---- 2) 시뮬레이터에 결함 주입 ----------------------------------------------------------
T0 = 1793923800.0


def simulate(plan, seconds):
    """plan: {시각(초): 결함 모드}. 이벤트 목록과 주입 시각을 돌려준다."""
    clock = [T0]
    sim = PlcSim(str(ROOT / "plc" / "1102"))
    em = EventEmitter(now=lambda: clock[0], detector=CycleAnomalyDetector())
    injected = []
    for s in range(int(seconds / 0.05)):
        t = s * 0.05
        clock[0] = T0 + t
        for at, mode in plan.items():
            if abs(t - at) < 1e-9:
                sim.set_fault(mode); em.sim_fault(mode); injected.append((at, mode))
        cmd = "M101" if s == 20 else None
        if cmd:
            em.command(cmd, "web")
        sim.scan([cmd] if cmd else [])
        em.observe(sim.dev)
    return em.since(-1, 10 ** 6), injected


def analyse(ev, fault_at, clear_at=None):
    ts = lambda e: float(__import__("datetime").datetime.fromisoformat(e["ts"].replace("Z", "+00:00")).timestamp()) - T0
    cyc = [(ts(e), e["payload"]["cycle_time_s"]) for e in ev if e["type"] == "cycle.completed"]
    ai = [e for e in ev if e["type"] == "ai.judgement"]
    raised = [ts(e) for e in ev if e["type"] == "alarm.raised"]
    cleared = [ts(e) for e in ev if e["type"] == "alarm.cleared"]
    return cyc, ai, raised, cleared, ts


# 2-1) 정상만 5분: 오탐이 없어야 한다
ev, _ = simulate({}, 300)
assert not [e for e in ev if e["type"] == "alarm.raised"], "정상 운전에서 오탐 경보가 났습니다"
n_cycles = sum(1 for e in ev if e["type"] == "cycle.completed")
print(f"\n시뮬레이터 정상 운전 5분: 사이클 {n_cycles}회, 오탐 경보 0건")

# 2-2) 실린더 속도 저하: 120초에 주입, 240초에 해제
ev, inj = simulate({120.0: "cyl_slow", 240.0: "none"}, 330)
cyc, ai, raised, cleared, ts = analyse(ev, 120)
assert raised and 120 <= raised[0] < 160, raised
assert cleared and cleared[0] > 240 and cleared[0] < 290, cleared
base = [ct for t, ct in cyc if 40 < t < 120]; slow = [ct for t, ct in cyc if 150 < t < 240]
print(f"실린더 속도 저하: 사이클 {sum(base)/len(base):.2f}초 -> {sum(slow)/len(slow):.2f}초, "
      f"주입 {raised[0] - 120:.1f}초 뒤 경보, 해제 후 {cleared[0] - 240:.1f}초 뒤 경보 해제")

# 2-3) 점진 열화: 120초에 주입
ev, _ = simulate({120.0: "cyl_degrade"}, 420)
cyc, ai, raised, cleared, ts = analyse(ev, 120)
assert raised and raised[0] > 120, raised
at = raised[0]
before = [ct for t, ct in cyc if 40 < t < 120]; atcyc = [ct for t, ct in cyc if t <= at][-1]
print(f"점진 열화: 주입 {at - 120:.0f}초 뒤 경보 (경보 시점 사이클 {atcyc:.2f}초, 정상 {sum(before)/len(before):.2f}초 -> 약 +{atcyc - sum(before)/len(before):.2f}초)")
assert atcyc - sum(before) / len(before) < 2.0   # 사이클이 2초 넘게 늘어나기 전에 잡아야 한다

# 2-4) 센서 응답 지연(간헐)
ev, _ = simulate({120.0: "sensor_flaky"}, 420)
cyc, ai, raised, cleared, ts = analyse(ev, 120)
assert raised and raised[0] > 120, "센서 지연을 잡지 못했습니다"
print(f"센서 응답 지연(간헐): 주입 {raised[0] - 120:.0f}초 뒤 경보, 경보 {len(raised)}회")

# 이벤트가 스키마를 통과하는지
if SCHEMA:
    bad = [e for e in ev if not SCHEMA.is_valid(e)]
    assert not bad, bad[0]
    print(f"스키마 검증 통과 (이벤트 {len(ev)}개, ai.judgement/alarm/sim.fault 포함)")
else:
    print("jsonschema 없음 -> 스키마 검증 건너뜀")
print("\n테스트 통과")
