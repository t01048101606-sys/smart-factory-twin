"""프레스 -> 용접 -> 도장 라인의 설비 이벤트로 OEE와 공정별 가동 상태를 계산한다 (DB 없이 DataFrame만으로 동작).

시간은 이벤트의 sim_t(시뮬레이터가 흐른 시간)로 계산한다. 배속(x1~x8)과 상관없이 공정 시간이 맞는다.

OEE = 가용률 x 성능률 x 품질률
  - 가용률 = (가동 시간 - 정지 시간) / 가동 시간
             가동 시간: machine.state 가 running_* 인 구간 (정지를 눌러도 라인이 비워질 때까지는 가동)
             정지 시간: 가동 중에 어느 한 공정이라도 '정지(down)' 상태였던 시간의 합집합 (프레스 정지, 도장 정지 결함)
  - 성능률 = 병목 공정의 공칭 사이클 x 완성 수량 / (가동 시간 - 정지 시간)   (최대 100%)
             공칭 사이클 = 결함이 없을 때의 사이클 중 가장 긴 것 (병목). 용접이 느려지면 처리량이 줄어 성능률이 떨어진다.
  - 품질률 = 양품 / (양품 + 불량)   (용접 불량 = 라인 끝에서 scrap)
공정 상태 시간: 작업 중(working) / 막힘(blocked: 일은 끝났는데 다음 칸이 차 있음) / 대기(starved: 일감 없음) / 정지(down)
"""
from __future__ import annotations

import pandas as pd

STATIONS = ("press", "weld", "paint")
NAMES = {"press": "프레스", "weld": "용접", "paint": "도장"}
STATE_KO = {"working": "작업 중", "blocked": "막힘", "starved": "대기", "down": "정지"}
FAULT_KO = {"none": "해제 (정상)", "weld_slow": "용접 속도 저하 (2.2배)", "press_down": "프레스 정지", "paint_down": "도장 정지"}


def line_events(events: pd.DataFrame) -> pd.DataFrame:
    """sim_t 가 있는 이벤트만 발생 순서(seq)대로. 서버를 다시 켜면 sim_t 가 0부터 다시 시작하므로
    sim_t 가 줄어드는 지점을 새 실행 세션으로 보고(session 열), 세션을 이어 붙인 연속 시간(gt 열)을 만든다.
    (sim_t 로 정렬하면 서로 다른 세션의 이벤트가 뒤섞여서 가동 시간이 틀어진다.)"""
    if events is None or events.empty or "sim_t" not in events:
        return pd.DataFrame()
    ev = events[events["sim_t"].notna()].sort_values("seq").reset_index(drop=True)
    sess, gt, base, end, prev, cur = [], [], 0.0, 0.0, None, 0
    for t in ev["sim_t"].astype(float):
        if prev is not None and t < prev - 1e-9:      # 시간이 거꾸로 감 = 서버를 다시 켠 것
            cur, base, end = cur + 1, base + end, 0.0
        end = max(end, t)
        sess.append(cur); gt.append(base + t); prev = t
    ev["session"], ev["gt"] = sess, gt
    return ev


def compute_line_oee(events: pd.DataFrame) -> dict | None:
    ev = line_events(events)
    if ev.empty:
        return None
    running, down = False, set()
    st = {s: "starved" for s in STATIONS}
    acc = {s: {k: 0.0 for k in STATE_KO} for s in STATIONS}
    run = downtime = 0.0
    cycles = {s: [] for s in STATIONS}
    nominal = {}
    good = scrap = 0
    exit_t = []
    t_prev, session = float(ev["gt"].iloc[0]), ev["session"].iloc[0]
    for _, r in ev.iterrows():
        t = float(r["gt"])
        if r["session"] != session:        # 서버를 다시 켠 지점: 이전 세션의 가동 상태와 공정 상태는 이어가지 않는다
            session, running, down = r["session"], False, set()
            st = {s: "starved" for s in STATIONS}
            t_prev = t
        dt = max(0.0, t - t_prev)
        if running:
            run += dt
            if down:
                downtime += dt
            for s in STATIONS:
                acc[s][st[s]] += dt
        t_prev = t
        typ, p = r["event_type"], r["payload"]
        if typ == "machine.state":
            running = str(p.get("state", "")).startswith("running")
            if p.get("reason") == "reset":
                st, down = {s: "starved" for s in STATIONS}, set()
        elif typ == "station.state":
            st[p["station"]] = p["to"]
            (down.add if p["to"] == "down" else down.discard)(p["station"])
        elif typ == "station.completed":
            cycles[p["station"]].append(float(p["duration_s"]))
            nominal[p["station"]] = float(p["nominal_s"])
        elif typ == "piece.exited":
            good, scrap = (good + 1, scrap) if p["result"] == "good" else (good, scrap + 1)
            exit_t.append(t)
    done = good + scrap
    work = run - downtime
    ideal = max(nominal.values()) if nominal else None
    availability = work / run if run > 0 else 0.0
    performance = min(1.0, ideal * done / work) if (ideal and work > 0) else 0.0
    quality = good / done if done else 0.0
    util = {s: {k: (v / run if run > 0 else 0.0) for k, v in acc[s].items()} for s in STATIONS}
    bott = max(STATIONS, key=lambda s: util[s]["working"] + util[s]["down"]) if run >= 60 else None
    return {
        "oee": availability * performance * quality, "availability": availability, "performance": performance, "quality": quality,
        "run_s": run, "down_s": downtime, "work_s": work, "good": good, "scrap": scrap, "done": done, "ideal_cycle_s": ideal,
        "throughput_per_min": (done / work * 60) if work > 0 else 0.0, "util": util, "bottleneck": bott,
        "cycles": cycles, "nominal": nominal, "exit_t": exit_t, "t0": float(ev["gt"].iloc[0]), "t1": float(ev["gt"].iloc[-1]),
        "sessions": int(ev["session"].iloc[-1]) + 1,
    }


def station_table(res: dict) -> pd.DataFrame:
    """공정별 시간 구성(가동 시간 대비 %)과 사이클 시간."""
    rows = []
    for s in STATIONS:
        c = res["cycles"][s]
        rows.append({"공정": NAMES[s], **{STATE_KO[k]: round(res["util"][s][k] * 100, 1) for k in STATE_KO},
                     "평균 사이클(초)": round(sum(c) / len(c), 2) if c else None,
                     "공칭 사이클(초)": res["nominal"].get(s), "완료 수": len(c)})
    return pd.DataFrame(rows)


def _running_intervals(ev: pd.DataFrame) -> list[tuple[float, float]]:
    out, start, last_t, cur = [], None, None, None
    for _, r in ev.iterrows():
        if r["session"] != cur:                       # 세션이 바뀌면 열려 있던 가동 구간을 그 세션의 마지막 시각에서 닫는다
            if start is not None:
                out.append((start, last_t))
            start, cur = None, r["session"]
        last_t = float(r["gt"])
        if r["event_type"] == "machine.state":
            on = str(r["payload"].get("state", "")).startswith("running")
            if on and start is None:
                start = last_t
            elif not on and start is not None:
                out.append((start, last_t)); start = None
    if start is not None:
        out.append((start, last_t))
    return out


def fault_report(events: pd.DataFrame, res: dict | None = None) -> pd.DataFrame:
    """결함을 주입한 구간별 처리량이 평상시(결함이 없던 구간)에 비해 얼마나 줄었는지."""
    cols = ["조작", "시작(초)", "지속(초)", "처리량(개/분)", "평상시 대비"]
    ev = line_events(events)
    if ev.empty:
        return pd.DataFrame(columns=cols)
    faults = [(float(r["gt"]), r["payload"]["mode"]) for _, r in ev[ev["event_type"] == "sim.fault"].iterrows()]
    if not faults:
        return pd.DataFrame(columns=cols)
    res = res or compute_line_oee(events)
    end = float(ev["gt"].iloc[-1])
    runs = _running_intervals(ev)
    exits = res["exit_t"]
    overlap = lambda a, b: sum(max(0.0, min(b, e) - max(a, s)) for s, e in runs)
    windows = [(faults[i][0], faults[i + 1][0] if i + 1 < len(faults) else end, faults[i][1]) for i in range(len(faults))]
    bad = [(a, b) for a, b, m in windows if m != "none"]
    normal_run = overlap(0, end) - sum(overlap(a, b) for a, b in bad)   # 결함이 없던 가동 시간
    normal_exits = sum(1 for t in exits if not any(a <= t < b for a, b in bad))
    base = normal_exits / normal_run * 60 if normal_run > 0 else None
    rows = []
    for a, b, m in windows:
        run_s = overlap(a, b)
        n = sum(1 for t in exits if a <= t < b)
        rate = n / run_s * 60 if run_s > 0 else None
        rows.append({"조작": FAULT_KO.get(m, m), "시작(초)": round(a), "지속(초)": round(b - a),
                     "처리량(개/분)": None if rate is None else round(rate, 2),
                     "평상시 대비": None if (rate is None or not base) else f"{rate / base * 100:.0f}%"})
    return pd.DataFrame(rows, columns=cols)
