"""설비 이벤트(machine_event)로 가동 상태와 OEE를 계산한다.

OEE = 가용률 x 성능률 x 품질률
  - 가용률  = 가동 시간 / 계획 시간
              가동 시간: machine.state 가 running_* 인 구간의 합 (녹색 램프 = 운전 중)
              계획 시간: 선택한 기간의 첫 이벤트 ~ 마지막 이벤트
  - 성능률  = 이상 사이클 시간의 합 / 가동 시간 (최대 100%)
              이상 사이클 시간 = 고정 소요 시간 + 그 사이클의 가공 시간(D10 설정)
              고정 소요 시간 = 관측된 사이클 중 (사이클 시간 - 가공 시간)의 최솟값 (가장 빠르게 돈 경우)
  - 품질률  = 금속(정상) 작업물 수 / 분류된 작업물 수  (비금속 = 이종 재질 혼입 불량)

compute_oee()는 DataFrame만 받는 순수 함수라서 DB 없이 시험할 수 있다.
"""
from __future__ import annotations

import json

import pandas as pd

try:
    from src import terms          # MES 에 설치된 상태
except ImportError:                # 트윈 저장소에서 바로 시험할 때
    import importlib.util as _u
    from pathlib import Path as _P
    _spec = _u.spec_from_file_location("terms", _P(__file__).with_name("terms.py"))
    terms = _u.module_from_spec(_spec)
    _spec.loader.exec_module(terms)

STATE_KO = {"running_continuous": "연속 운전", "running_single": "단속 운전", "idle": "대기",
            "stopped": "정지", "alarm": "경보"}
COMMAND_KO = {"start_single": "단속 시작", "start_continuous": "연속 시작", "stop": "정지",
              "reset": "리셋(PB4)", "count_reset": "카운트 초기화"}
TYPE_KO = {"command.issued": "조작", "machine.state": "운전 상태", "cycle.started": "사이클 시작",
           "cycle.step": "단계", "cycle.completed": "사이클 완료", "piece.classified": "분류",
           "count.updated": "카운트", "param.changed": "설정 변경", "io.changed": "입출력",
           "ai.judgement": "AI 판정", "alarm.raised": "경보", "alarm.cleared": "경보 해제",
           "station.completed": "공정 완료", "station.state": "공정 상태", "piece.exited": "라인 끝", "sim.fault": "결함 주입",
           "lot.received": "자재 입고", "pallet.stored": "파렛트 보관", "shipment.dispatched": "출하", "vision.inspected": "비전 검사",
           "cobot.placed": "로봇 적재", "cobot.pallet_closed": "파렛트 완성"}
STATION_KO = {"press": "프레스", "weld": "용접", "paint": "도장"}
FAULT_KO = {"none": "해제", "cyl_slow": "실린더 속도 저하", "cyl_degrade": "실린더 점진 열화", "sensor_flaky": "센서 응답 지연",
            "weld_slow": "용접 속도 저하", "press_down": "프레스 정지", "paint_down": "도장 정지"}


def load_events(since: pd.Timestamp | None = None, line_id: str | None = None) -> pd.DataFrame:
    """machine_event 테이블을 읽는다. line_id 를 주면 그 라인의 이벤트만 (가공 라인 = LINE-MACHINING-01).
    테이블이 아직 없으면 빈 표를 돌려준다."""
    from src.db import get_connection  # MES 쪽 모듈 (DB 경로가 여기에 정해져 있다)

    conn = get_connection()
    where, params = ("WHERE line_id = ? ", (line_id,)) if line_id else ("", ())
    try:
        try:
            df = pd.read_sql_query("SELECT event_id, seq, ts, source, line_id, event_type, piece_id, work_order_id, payload, sim_t "
                                   f"FROM machine_event {where}ORDER BY seq", conn, params=params)
        except Exception:   # sim_t 열이 없는 예전 DB
            df = pd.read_sql_query("SELECT event_id, seq, ts, source, line_id, event_type, piece_id, work_order_id, payload "
                                   f"FROM machine_event {where}ORDER BY seq", conn, params=params)
    except Exception:
        return pd.DataFrame()
    finally:
        conn.close()
    if df.empty:
        return df
    df["ts"] = pd.to_datetime(df["ts"], utc=True)
    df["payload"] = df["payload"].apply(json.loads)
    if since is not None:
        df = df[df["ts"] >= since]
    return df.reset_index(drop=True)


def compute_oee(events: pd.DataFrame, ideal_overhead_s: float | None = None) -> dict | None:
    """OEE와 근거 수치를 계산한다. 이벤트가 없으면 None."""
    if events is None or events.empty:
        return None
    ev = events.sort_values(["ts", "seq"]).reset_index(drop=True)
    t0, t1 = ev["ts"].iloc[0], ev["ts"].iloc[-1]
    planned = (t1 - t0).total_seconds()

    # ---- 가동 시간 ----
    states = ev[ev["event_type"] == "machine.state"]
    run, start = 0.0, None
    is_run = lambda p: str(p.get("state", "")).startswith("running")
    if not states.empty and not is_run(states.iloc[0]["payload"]):
        run += (states.iloc[0]["ts"] - t0).total_seconds()  # 기간이 시작되기 전부터 운전 중이던 경우
    for _, r in states.iterrows():
        if is_run(r["payload"]):
            if start is None:
                start = r["ts"]
        elif start is not None:
            run += (r["ts"] - start).total_seconds()
            start = None
    if start is not None:
        run += (t1 - start).total_seconds()  # 아직 운전 중이면 마지막 이벤트까지
    availability = min(1.0, run / planned) if planned > 0 else 0.0

    # ---- 성능률 ----
    cyc = ev[ev["event_type"] == "cycle.completed"]
    cdf = pd.DataFrame({
        "ts": list(cyc["ts"]),
        "cycle_time_s": [float(p["cycle_time_s"]) for p in cyc["payload"]],
        "drill_s": [p["drill_time_set_ds"] / 10 for p in cyc["payload"]],
    })
    overhead = ideal_overhead_s
    if overhead is None and len(cdf):
        overhead = float((cdf["cycle_time_s"] - cdf["drill_s"]).min())
    cdf["ideal_s"] = (overhead or 0.0) + cdf["drill_s"]
    ideal_total = float(cdf["ideal_s"].sum()) if len(cdf) else 0.0
    performance = min(1.0, ideal_total / run) if run > 0 else 0.0

    # ---- 품질률 ----
    kinds = [p["kind"] for p in ev[ev["event_type"] == "piece.classified"]["payload"]]
    total = len(kinds)
    good = sum(1 for k in kinds if k == "metal")
    quality = good / total if total else 0.0

    return {
        "oee": availability * performance * quality,
        "availability": availability, "performance": performance, "quality": quality,
        "planned_s": planned, "run_s": run, "cycles": len(cdf), "ideal_overhead_s": overhead,
        "ideal_total_s": ideal_total, "total": total, "good": good, "defect": total - good,
        "cycle_df": cdf, "t0": t0, "t1": t1,
    }


def describe(row, mode: str = "field") -> str:
    p, t = row["payload"], row["event_type"]
    if t == "command.issued":
        return f"{COMMAND_KO.get(p['command'], p['command'])} ({p['origin']})"
    if t == "machine.state":
        return STATE_KO.get(p["state"], p["state"])
    if t == "cycle.started":
        return "연속" if p.get("mode") == "continuous" else "단속"
    if t == "cycle.step":
        return terms.t("step." + p["step"], mode)
    if t == "cycle.completed":
        return f"{p['cycle_time_s']}초 (가공 {p['drill_time_set_ds'] / 10:g}초 설정)"
    if t == "piece.classified":
        return terms.t("ok_label", mode) if p["kind"] == "metal" else terms.t("ng_long", mode)
    if t == "count.updated":
        return f"{terms.t('ok_part', mode)} {p['metal']} / {terms.t('ng_part', mode)} {p['nonmetal']} / {terms.t('total', mode)} {p['total']}"
    if t == "station.completed":
        extra = " (용접 불량)" if p.get("defect") else ""
        return f"{STATION_KO.get(p['station'], p['station'])} {p['duration_s']}초 (공칭 {p['nominal_s']}초){extra}"
    if t == "station.state":
        return f"{STATION_KO.get(p['station'], p['station'])}: {p['from']} -> {p['to']}"
    if t == "piece.exited":
        return "양품" if p["result"] == "good" else "불량 (용접 불량)"
    if t == "lot.received":
        return f"{p['item_code']} {p['qty']:g}{p['unit']} 입고 ({p['supplier']})"
    if t == "pallet.stored":
        return f"파렛트 {p['pallet_id']} 보관 ({p['qty']}개)"
    if t == "shipment.dispatched":
        return f"{p['shipment_no']} 출하 ({p['customer']}), 파렛트 {len(p['pallets'])}개 {sum(len(x['pieces']) for x in p['pallets'])}개"
    if t == "vision.inspected":
        return f"{'양품' if p['result'] == 'good' else '불량'} (신뢰도 {p['confidence'] * 100:.1f}%)"
    if t == "cobot.placed":
        return ("파렛트 %d번 칸" % (p["slot"] + 1) if p["target"] == "pallet" else "NG 수납함") + f" ({p['cycle_s']}초)"
    if t == "cobot.pallet_closed":
        return f"파렛트 {len(p['pieces'])}개 마감" + (" (라인 정지, 모자란 채)" if p["partial"] else "")
    if t == "sim.fault":
        return FAULT_KO.get(p["mode"], p["mode"])
    if t == "param.changed":
        return f"가공 시간 {p['from'] / 10:g}초 -> {p['to'] / 10:g}초 ({p.get('origin', '')})"
    return json.dumps(p, ensure_ascii=False)


def recent_events(events: pd.DataFrame, n: int = 40, mode: str = "field") -> pd.DataFrame:
    """최근 이벤트를 사람이 읽기 쉬운 표로 만든다 (io.changed 제외)."""
    cols = ["시각", "유형", "작업물", "내용"]
    if events is None or events.empty:
        return pd.DataFrame(columns=cols)
    ev = events[~events["event_type"].isin(["io.changed", "station.state"])].tail(n).iloc[::-1]
    return pd.DataFrame({
        "시각": ev["ts"].dt.tz_convert("Asia/Seoul").dt.strftime("%H:%M:%S"),
        "유형": ev["event_type"].map(lambda x: TYPE_KO.get(x, x)),
        "작업물": ev["piece_id"].fillna(""),
        "내용": ev.apply(lambda r: describe(r, mode), axis=1),
    })
