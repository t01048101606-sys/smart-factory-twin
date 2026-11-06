"""시뮬레이터를 서버 없이 돌려서 이벤트가 스키마와 PLC 결과에 맞는지 확인합니다.

실행 (프로젝트 폴더에서):  python tests/test_events.py
(스키마 검증은 jsonschema가 있을 때만: pip install jsonschema)
"""
import collections
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
from plc_sim import PlcSim          # noqa: E402
from events import EventEmitter     # noqa: E402

T0 = 1793923800.0  # 2026-11-06 00:10:00 UTC
clock = [T0]
sim = PlcSim(str(ROOT / "plc" / "1102"))
em = EventEmitter(now=lambda: clock[0])


def press(dev):
    em.command(dev, "web")
    return [dev]


script = {20: "M101", 250: "D10", 440: "M102", 700: "M101", 900: "X0E"}
for s in range(1100):
    clock[0] = T0 + s * 0.05
    pressed = []
    act = script.get(s)
    if act == "D10":
        em.note_param_origin("web")
        sim.dev["D10"] = 20
    elif act:
        pressed = press(act)
    sim.scan(pressed)
    em.observe(sim.dev)

ev = em.since(-1, 10000)
by = collections.Counter(e["type"] for e in ev)
print("이벤트", len(ev), "개:", dict(by))

# ---- 1) 스키마 검증 ----
try:
    import jsonschema
    schema = json.loads((ROOT / "docs" / "event_schema.json").read_text(encoding="utf-8"))
    v = jsonschema.Draft7Validator(schema)
    bad = [e for e in ev if not v.is_valid(e)]
    assert not bad, f"스키마 위반 {len(bad)}개: {bad[0]}"
    print("스키마 검증 통과")
except ImportError:
    print("jsonschema 없음 -> 스키마 검증 건너뜀")

# ---- 2) PLC 결과와 대조 ----
cls = collections.Counter(e["payload"]["kind"] for e in ev if e["type"] == "piece.classified")
last_cnt = [e for e in ev if e["type"] == "count.updated"][-1]["payload"]
print("분류 금속/비금속:", dict(cls), "| 마지막 카운트:", last_cnt, "| PLC D0,D2,D4:", sim.dev["D0"], sim.dev["D2"], sim.dev["D4"])
assert last_cnt == {"metal": sim.dev["D0"], "nonmetal": sim.dev["D2"], "total": sim.dev["D4"], "reason": last_cnt["reason"]}
for e in ev:
    if e["type"] == "count.updated":
        c = e["payload"]; assert c["total"] == c["metal"] + c["nonmetal"], c
started = by["cycle.started"]; done = by["cycle.completed"]
assert started - done in (0, 1), (started, done)
assert abs(cls["metal"] - cls["nonmetal"]) <= 1, cls          # 번갈아 투입
# 같은 piece_id의 단계가 순서대로 나오는지
order = ["feed", "supply_back", "drill_motor", "drill_down", "drilling", "drill_up", "out_forward", "out_back", "belt"]
steps = collections.defaultdict(list)
for e in ev:
    if e["type"] == "cycle.step":
        steps[e["piece_id"]].append(e["payload"]["step"])
for pid, s in steps.items():
    head = [x for x in s if x in order]
    assert head == [x for x in order if x in head], (pid, s)
    tail = [x for x in s if x not in order]  # 컨베이어 이후: 금속 eject -> bin_metal, 비금속 end_nonmetal
    assert tail in ([], ["eject"], ["eject", "bin_metal"], ["end_nonmetal"]), (pid, s)
print("사이클 시작/완료:", started, "/", done, "| 단계 순서 확인 통과 (작업물", len(steps), "개)")
ct = [e["payload"]["cycle_time_s"] for e in ev if e["type"] == "cycle.completed"]
print("사이클 시간(초):", ct[:3], "... (D10 변경 후:", ct[-1], ")")
pc = [e for e in ev if e["type"] == "param.changed"]
print("param.changed:", [(e["payload"]["from"], e["payload"]["to"], e["payload"]["origin"]) for e in pc])
print("command.issued:", [e["payload"]["command"] for e in ev if e["type"] == "command.issued"])
print("machine.state:", [(e["ts"][11:19], e["payload"]["state"]) for e in ev if e["type"] == "machine.state"])

print("\n--- 첫 사이클 타임라인 ---")
first = next(e["piece_id"] for e in ev if e["type"] == "cycle.started")
for e in ev:
    if e["piece_id"] == first and e["type"] != "io.changed":
        p = e["payload"]
        print(e["ts"][11:23], e["type"], p.get("step") or p.get("kind") or p.get("mode") or p.get("reason") or p.get("cycle_time_s") or "")
print("\n테스트 통과")
