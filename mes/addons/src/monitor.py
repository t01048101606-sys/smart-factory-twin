"""현장 모니터링: AI 이상 감지 이벤트(ai.judgement, alarm.*, sim.fault)를 화면용 표로 바꾼다.

입력은 oee.load_events() 가 돌려주는 machine_event DataFrame (ts, seq, event_type, piece_id, payload).
DB 없이 DataFrame만으로 동작하는 순수 함수라서 시험하기 쉽다.
"""
from __future__ import annotations

import pandas as pd

FAULT_KO = {"none": "해제 (정상)", "cyl_slow": "실린더 속도 저하", "cyl_degrade": "실린더 점진 열화",
            "sensor_flaky": "센서 응답 지연(간헐)"}
SEVERITY_KO = {"info": "정보", "warning": "주의", "critical": "위험"}


def _kst(ts):
    return ts.tz_convert("Asia/Seoul").tz_localize(None)


def judgements(events: pd.DataFrame) -> pd.DataFrame:
    """ai.judgement 이벤트를 사이클 단위 표로 만든다."""
    cols = ["ts", "piece_id", "phase", "result", "value", "baseline", "sigma", "score", "ewma_score", "confidence"]
    if events is None or events.empty:
        return pd.DataFrame(columns=cols)
    ev = events[events["event_type"] == "ai.judgement"]
    rows = [{"ts": r["ts"], "piece_id": r["piece_id"], **{k: r["payload"].get(k) for k in cols[2:]}}
            for _, r in ev.iterrows()]
    return pd.DataFrame(rows, columns=cols)


def faults(events: pd.DataFrame) -> pd.DataFrame:
    """시뮬레이터에 결함을 주입하거나 해제한 기록."""
    if events is None or events.empty:
        return pd.DataFrame(columns=["ts", "mode"])
    ev = events[events["event_type"] == "sim.fault"]
    return pd.DataFrame({"ts": list(ev["ts"]), "mode": [p["mode"] for p in ev["payload"]]}, columns=["ts", "mode"])


def alarms(events: pd.DataFrame) -> pd.DataFrame:
    """경보 이력: 발생과 해제를 짝지어 한 줄로 만든다."""
    cols = ["발생", "해제", "지속(초)", "등급", "내용"]
    if events is None or events.empty:
        return pd.DataFrame(columns=cols)
    out, open_ = [], None
    for _, r in events[events["event_type"].isin(["alarm.raised", "alarm.cleared"])].iterrows():
        if r["event_type"] == "alarm.raised":
            if open_ is not None:
                out.append(open_)
            open_ = {"발생": r["ts"], "해제": None, "등급": r["payload"].get("severity"), "내용": r["payload"].get("message", "")}
        elif open_ is not None:
            open_["해제"] = r["ts"]
            out.append(open_)
            open_ = None
    if open_ is not None:
        out.append(open_)
    df = pd.DataFrame(out, columns=["발생", "해제", "등급", "내용"])
    if df.empty:
        return pd.DataFrame(columns=cols)
    end = events["ts"].max()
    df["지속(초)"] = [round(((h if pd.notna(h) else end) - b).total_seconds(), 1) for b, h in zip(df["발생"], df["해제"])]
    df["등급"] = df["등급"].map(lambda x: SEVERITY_KO.get(x, x))
    df = df.iloc[::-1].reset_index(drop=True)
    df["발생"] = df["발생"].map(lambda t: _kst(t).strftime("%H:%M:%S"))
    df["해제"] = df["해제"].map(lambda t: _kst(t).strftime("%H:%M:%S") if pd.notna(t) else "진행 중")
    return df[cols]


def detection_report(events: pd.DataFrame) -> pd.DataFrame:
    """결함을 주입한 뒤 경보가 얼마나 빨리 났는지, 해제 뒤 경보가 얼마나 빨리 풀렸는지 정리한다."""
    cols = ["시각", "조작", "경보 발생/해제까지(초)", "사이클 수", "결과"]
    f = faults(events)
    if f.empty:
        return pd.DataFrame(columns=cols)
    ev = events.sort_values(["ts", "seq"])
    rows = []
    for i, r in f.iterrows():
        nxt = f.iloc[i + 1]["ts"] if i + 1 < len(f) else ev["ts"].max() + pd.Timedelta(seconds=1)
        win = ev[(ev["ts"] >= r["ts"]) & (ev["ts"] <= nxt)]
        want = "alarm.cleared" if r["mode"] == "none" else "alarm.raised"
        hit = win[win["event_type"] == want]
        if hit.empty:
            result = "해제 없음" if r["mode"] == "none" else "감지 못 함"
            sec, cyc = None, None
            if r["mode"] == "none":  # 해제 시점에 경보가 없었으면 해제할 것이 없다
                before = ev[(ev["ts"] < r["ts"]) & ev["event_type"].isin(["alarm.raised", "alarm.cleared"])]
                if before.empty or before.iloc[-1]["event_type"] == "alarm.cleared":
                    result = "해당 없음 (경보 없었음)"
        else:
            t_hit = hit.iloc[0]["ts"]
            sec = round((t_hit - r["ts"]).total_seconds(), 1)
            cyc = int((win[(win["event_type"] == "cycle.completed") & (win["ts"] <= t_hit)]).shape[0])
            result = "해제됨" if r["mode"] == "none" else "감지"
        rows.append({"시각": _kst(r["ts"]).strftime("%H:%M:%S"), "조작": FAULT_KO.get(r["mode"], r["mode"]),
                     "경보 발생/해제까지(초)": sec, "사이클 수": cyc, "결과": result})
    return pd.DataFrame(rows, columns=cols)


def current_status(events: pd.DataFrame) -> dict:
    """화면 맨 위 카드용 현재 상태."""
    j = judgements(events)
    a = events[events["event_type"].isin(["alarm.raised", "alarm.cleared"])] if events is not None and not events.empty else None
    alarm = bool(a is not None and not a.empty and a.iloc[-1]["event_type"] == "alarm.raised")
    st = {"phase": "none", "alarm": alarm, "last_result": None, "last_value": None, "baseline": None,
          "learned": 0, "ng_count": 0, "total": 0}
    if j.empty:
        return st
    last = j.iloc[-1]
    mon = j[j["phase"] == "monitoring"]
    st.update({"phase": last["phase"], "last_result": last["result"], "last_value": last["value"],
               "baseline": mon.iloc[-1]["baseline"] if not mon.empty else None,
               "learned": int((j["phase"] == "learning").sum()),
               "ng_count": int((mon["result"] == "ng").sum()), "total": len(mon)})
    return st
