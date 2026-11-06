"""MES 공장 전체 대시보드의 계산 (생산, 재고, 출하, 품질, 경보, 라인별 OEE).

모든 함수는 fetch(sql, params) -> DataFrame 을 받는다 (MES 에서는 src.db.fetch_dataframe). 화면 코드와 분리해서 숫자를 시험으로 검증한다.
숫자는 모두 MES 테이블(LOT, 시리얼, 검사, 출하, 공정 실행)과 설비 이벤트(machine_event)에서 나온다.

  생산     : 시리얼(작업물 번호) 상태. COMPLETED = 양품, SCRAPPED = 불량. 제품별로 센다.
  재고     : 입고한 자재 LOT 수량 - 공정 실행이 소비한 수량. BOM 단위당 수량으로 나누면 "남은 재고로 만들 수 있는 완제품 수"
  출하     : 출하 등록(shipment, shipment_item). 출하 가능 수량 = 양품 시리얼 수 - 이미 출하한 수량. 검사 FAIL LOT 는 MES 가 출하를 막는다.
  품질     : 완제품 LOT 검사 결과(PASS, PARTIAL, FAIL)와 불량 사유 합계
  라인별 OEE: 가공 라인은 oee.compute_oee, 프레스 라인은 lineoee.compute_line_oee (정의가 다르다)
"""
from __future__ import annotations

import pandas as pd

try:
    from src import lineoee, oee           # MES 에 설치된 상태
except ImportError:                        # 트윈 저장소에서 바로 시험할 때
    import importlib.util as _u
    from pathlib import Path as _P

    def _load(name):
        spec = _u.spec_from_file_location(name, _P(__file__).with_name(name + ".py"))
        m = _u.module_from_spec(spec)
        spec.loader.exec_module(m)
        return m

    oee, lineoee = _load("oee"), _load("lineoee")

MACHINING, PRESS, LOGISTICS, COBOT = "LINE-MACHINING-01", "LINE-PRESS-WELD-PAINT-01", "LINE-LOGISTICS-01", "LINE-COBOT-01"
LOGISTICS_PRODUCT = "FG-BRKA"      # 물류 · 출하 구역이 출하하는 제품 (브라켓 A)
STALE_S = 90                         # 이 시간 넘게 이벤트가 없으면 라인이 멈췄거나 연결이 끊긴 것으로 본다


def production(fetch):
    """제품별 시리얼 수 (양품, 불량)와 작업지시 상태별 건수."""
    serial = fetch(
        """
        SELECT i.item_code, i.item_name,
               COUNT(*) AS total,
               SUM(CASE WHEN u.status = 'COMPLETED' THEN 1 ELSE 0 END) AS good,
               SUM(CASE WHEN u.status = 'SCRAPPED' THEN 1 ELSE 0 END) AS scrap
        FROM unit_serial AS u JOIN lot AS l ON l.lot_id = u.lot_id JOIN item AS i ON i.item_id = l.item_id
        GROUP BY i.item_id ORDER BY i.item_code
        """
    ).fillna(0)
    wo = fetch(
        """
        SELECT p.item_code, w.status, COUNT(*) AS n
        FROM work_order AS w JOIN item AS p ON p.item_id = w.product_item_id
        GROUP BY p.item_code, w.status ORDER BY p.item_code, w.status
        """
    )
    return serial, wo


AUTO_RECEIPT = ("RM-BLANK",)    # 어댑터가 모자라면 자동으로 입고하는 자재 (시연용). 물류 구역의 발주 대상이 아니라서 "부족"으로 보지 않는다


def inventory(fetch, low_units: int = 20) -> pd.DataFrame:
    """자재별 입고, 소비, 재고와 '남은 재고로 만들 수 있는 완제품 수'. low_units 보다 적으면 부족 (자동 입고 자재는 제외)."""
    mat = fetch(
        """
        SELECT i.item_id, i.item_code, i.item_name, i.unit,
               COALESCE((SELECT SUM(l.qty) FROM lot AS l WHERE l.item_id = i.item_id AND l.lot_type = 'RECEIPT'), 0) AS received,
               COALESCE((SELECT SUM(om.qty) FROM operation_material AS om WHERE om.material_item_id = i.item_id), 0) AS consumed
        FROM item AS i WHERE i.item_type = 'MATERIAL' ORDER BY i.item_code
        """
    )
    per = fetch("SELECT material_item_id AS item_id, SUM(qty_per_unit) AS per_unit FROM bom GROUP BY material_item_id")
    df = mat.merge(per, on="item_id", how="left")
    df["balance"] = df["received"] - df["consumed"]
    df["makeable"] = df.apply(lambda r: (r["balance"] / r["per_unit"]) if r["per_unit"] and r["per_unit"] > 0 else None, axis=1)
    df["auto"] = df["item_code"].isin(AUTO_RECEIPT)
    df["low"] = [(m is not None and m < low_units and not a) for m, a in zip(df["makeable"], df["auto"])]
    return df.drop(columns=["item_id"])


def shipments(fetch, product_code: str = LOGISTICS_PRODUCT) -> dict:
    """출하 건수와 수량, 최근 출하, 출하 대기(출하 가능 수량 > 0), 검사 FAIL 로 막힌 LOT.
    출하 가능 수량 = 양품(COMPLETED) 시리얼 수 - 이미 출하한 수량 (불량 시리얼은 LOT 안에 남아 있지만 출하 대상이 아니다)."""
    summ = fetch(
        "SELECT COUNT(DISTINCT s.shipment_id) AS n, COALESCE(SUM(si.qty), 0) AS qty "
        "FROM shipment AS s LEFT JOIN shipment_item AS si ON si.shipment_id = s.shipment_id"
    ).iloc[0]
    recent = fetch(
        """
        SELECT s.shipment_no AS 출하번호, s.shipment_date AS 출하일, COALESCE(p.partner_name, '-') AS 고객사,
               SUM(si.qty) AS 수량, COUNT(DISTINCT si.lot_id) AS LOT수
        FROM shipment AS s JOIN shipment_item AS si ON si.shipment_id = s.shipment_id LEFT JOIN partner AS p ON p.partner_id = s.partner_id
        GROUP BY s.shipment_id ORDER BY s.shipment_id DESC LIMIT 10
        """
    )
    lots = fetch(
        """
        SELECT l.lot_no, i.item_name, l.qty AS lot_qty, ins.result,
               (SELECT COUNT(*) FROM unit_serial AS u WHERE u.lot_id = l.lot_id AND u.status = 'COMPLETED') AS good,
               (SELECT COUNT(*) FROM unit_serial AS u WHERE u.lot_id = l.lot_id AND u.status = 'SCRAPPED') AS scrap,
               COALESCE((SELECT SUM(si.qty) FROM shipment_item AS si WHERE si.lot_id = l.lot_id), 0) AS shipped
        FROM lot AS l JOIN item AS i ON i.item_id = l.item_id LEFT JOIN inspection AS ins ON ins.lot_id = l.lot_id
        WHERE l.lot_type = 'FINISHED' AND i.item_code = ? ORDER BY l.lot_id DESC
        """,
        (product_code,),
    )
    lots["shippable"] = (lots["good"] - lots["shipped"]).clip(lower=0)
    waiting = lots[(lots["shippable"] > 0) & (lots["result"] != "FAIL")]
    blocked = lots[lots["result"] == "FAIL"]
    other = fetch(
        "SELECT COUNT(*) AS n FROM lot AS l JOIN item AS i ON i.item_id = l.item_id "
        "WHERE l.lot_type = 'FINISHED' AND i.item_code <> ?", (product_code,)).iloc[0]["n"]
    return {"count": int(summ["n"]), "qty": float(summ["qty"]), "recent": recent, "waiting": waiting, "blocked": blocked, "other_lots": int(other)}


def quality(fetch):
    """완제품 LOT 검사 결과 분포와 불량 사유별 수량."""
    dist = fetch(
        "SELECT result, COUNT(*) AS lots, COALESCE(SUM(checked_qty), 0) AS checked, COALESCE(SUM(defect_qty), 0) AS defect "
        "FROM inspection WHERE inspection_type = 'FINISHED' GROUP BY result"
    )
    reasons = fetch(
        "SELECT r.reason_name AS reason, SUM(ins.defect_qty) AS qty FROM inspection AS ins "
        "JOIN defect_reason_code AS r ON r.reason_code = ins.reason_code WHERE ins.defect_qty > 0 "
        "GROUP BY r.reason_code ORDER BY qty DESC"
    )
    return dist, reasons


def _last_state(ev: pd.DataFrame):
    m = ev[ev["event_type"] == "machine.state"]
    return None if m.empty else m.iloc[-1]["payload"].get("state")


def line_overview(ev_m: pd.DataFrame, ev_p: pd.DataFrame, ev_l: pd.DataFrame, now: pd.Timestamp | None = None, ev_c: pd.DataFrame | None = None):
    """라인별 상태, OEE, 처리량. 반환: (표 DataFrame, 라인별 계산 결과 dict)"""
    now = now or pd.Timestamp.now(tz="UTC")
    pct = lambda x: f"{x * 100:.1f}%"
    rows, res = [], {}
    age = lambda ev: None if ev.empty else (now - ev["ts"].max()).total_seconds()
    status = lambda ev, running: ("연결 없음" if ev.empty else (f"무응답 ({age(ev) / 60:.0f}분 전)" if age(ev) > STALE_S else ("가동" if running else "정지")))

    m = None if ev_m.empty else oee.compute_oee(ev_m)
    res["machining"] = m
    st_m = _last_state(ev_m) or ""
    rows.append({"라인": "가공 라인 (PLC)", "상태": status(ev_m, st_m.startswith("running")),
                 "OEE": pct(m["oee"]) if m else "-", "가용률": pct(m["availability"]) if m else "-",
                 "성능률": pct(m["performance"]) if m else "-", "품질률": pct(m["quality"]) if m else "-",
                 "처리": (f"{m['total']}개 판별 ({m['total'] / (m['run_s'] / 60):.1f}개/분)" if m and m["run_s"] > 0 else "-"),
                 "비고": "AI 이상 감지 경보" if (not ev_m.empty and (ev_m["event_type"] == "alarm.raised").sum() > (ev_m["event_type"] == "alarm.cleared").sum()) else ""})
    p = None if ev_p.empty else lineoee.compute_line_oee(ev_p)
    res["press"] = p
    st_p = _last_state(ev_p) or ""
    rows.append({"라인": "프레스 · 용접 · 도장 라인", "상태": status(ev_p, st_p.startswith("running")),
                 "OEE": pct(p["oee"]) if p else "-", "가용률": pct(p["availability"]) if p else "-",
                 "성능률": pct(p["performance"]) if p else "-", "품질률": pct(p["quality"]) if p else "-",
                 "처리": (f"{p['done']}개 완성 ({p['throughput_per_min']:.2f}개/분)" if p else "-"),
                 "비고": (f"병목: {lineoee.NAMES[p['bottleneck']]}" if p and p["bottleneck"] else "")})
    rec = (ev_l["event_type"] == "lot.received").sum() if not ev_l.empty else 0
    shp = (ev_l["event_type"] == "shipment.dispatched").sum() if not ev_l.empty else 0
    pal = (ev_l["event_type"] == "pallet.stored").sum() if not ev_l.empty else 0
    res["logistics"] = {"received": int(rec), "shipments": int(shp), "pallets": int(pal)}
    rows.append({"라인": "물류 · 출하 구역", "상태": "연결 없음" if ev_l.empty else ("가동" if age(ev_l) <= 300 else f"대기 ({age(ev_l) / 60:.0f}분 전 활동)"),
                 "OEE": "-", "가용률": "-", "성능률": "-", "품질률": "-",
                 "처리": f"입고 {rec}회 · 파렛트 {pal}개 · 출하 {shp}회", "비고": "OEE 대신 입고와 출하 건수로 봅니다"})
    if ev_c is not None:        # 협동로봇 팔레타이징 셀 (이벤트가 없으면 연결 없음)
        insp = ev_c[ev_c["event_type"] == "vision.inspected"] if not ev_c.empty else ev_c
        ng = int(insp["payload"].apply(lambda p: p.get("result") == "scrap").sum()) if len(insp) else 0
        pal = int((ev_c["event_type"] == "cobot.pallet_closed").sum()) if not ev_c.empty else 0
        cyc = ev_c[ev_c["event_type"] == "cobot.placed"]["payload"].apply(lambda p: p["cycle_s"]) if not ev_c.empty else []
        avg = float(sum(cyc) / len(cyc)) if len(cyc) else 0.0
        res["cobot"] = {"inspected": len(insp), "ng": ng, "pallets": pal, "avg_cycle_s": avg}
        rows.append({"라인": "협동로봇 팔레타이징 셀", "상태": "연결 없음" if ev_c.empty else ("가동" if age(ev_c) <= 300 else f"대기 ({age(ev_c) / 60:.0f}분 전 활동)"),
                     "OEE": "-", "가용률": "-", "성능률": "-", "품질률": "-",
                     "처리": f"비전 검사 {len(insp)}개 · 불량 검출 {ng}개 · 파렛트 {pal}개" + (f" · 사이클 {avg:.1f}초" if avg else ""),
                     "비고": "OEE 대신 검사, 적재 건수로 봅니다"})
    return pd.DataFrame(rows), res


def _kst(ts):
    return ts.tz_convert("Asia/Seoul").strftime("%m-%d %H:%M:%S")


def alerts(ev_all: pd.DataFrame, inv: pd.DataFrame, ship: dict, overview: pd.DataFrame, n: int = 12) -> pd.DataFrame:
    """지금 주의가 필요한 일만: FAIL LOT 출하 차단, 재고 부족, 라인 무응답, 지금 경보 중인 AI 이상 감지, 지금 주입되어 있는 결함.
    지나간 경보와 결함은 history() 에 있다."""
    rows = []
    for _, r in ship["blocked"].iterrows():
        rows.append(("품질", f"{r['lot_no']} 검사 불합격(FAIL): 출하 차단 (불량 {int(r['scrap'])}개)", ""))
    for _, r in inv[inv["low"]].iterrows():
        rows.append(("재고", f"{r['item_name']} 재고 {r['balance']:,.1f} {r['unit']}: 완제품 {r['makeable']:,.0f}개 분량만 남음", ""))
    for _, r in overview.iterrows():
        if str(r["상태"]).startswith("무응답"):
            rows.append(("설비", f"{r['라인']}: {r['상태']}", ""))
    if not ev_all.empty:
        for line_id, g in ev_all.groupby("line_id"):
            ai = g[g["event_type"].isin(["alarm.raised", "alarm.cleared"])]
            if len(ai) and ai.iloc[-1]["event_type"] == "alarm.raised":          # 마지막 경보 이벤트가 '발생'이면 지금 경보 중
                p = ai.iloc[-1]["payload"]
                rows.append(("AI", f"이상 감지 경보 중 ({p.get('metric', p.get('code', ''))})".replace(" ()", ""), _kst(ai.iloc[-1]["ts"])))
            fl = g[g["event_type"] == "sim.fault"]
            if len(fl) and fl.iloc[-1]["payload"].get("mode") != "none":          # 마지막 결함 이벤트가 '해제'가 아니면 지금 주입 중
                rows.append(("결함", f"결함 주입 중: {oee.FAULT_KO.get(fl.iloc[-1]['payload']['mode'], fl.iloc[-1]['payload']['mode'])}", _kst(fl.iloc[-1]["ts"])))
    return pd.DataFrame(rows, columns=["구분", "내용", "발생"]).head(n)


def history(ev_all: pd.DataFrame, n: int = 15) -> pd.DataFrame:
    """지나간 경보와 결함 주입 이력 (최근 것이 위)."""
    cols = ["시각", "구분", "내용"]
    if ev_all.empty:
        return pd.DataFrame(columns=cols)
    ev = ev_all[ev_all["event_type"].isin(["alarm.raised", "alarm.cleared", "sim.fault"])].tail(n).iloc[::-1]
    rows = []
    for _, r in ev.iterrows():
        t, p = r["event_type"], r["payload"]
        what = {"alarm.raised": "AI 이상 감지 경보 발생", "alarm.cleared": "AI 이상 감지 경보 해제"}.get(t) or f"결함 주입: {oee.FAULT_KO.get(p.get('mode'), p.get('mode'))}"
        rows.append((_kst(r["ts"]), "AI" if t.startswith("alarm") else "결함", what))
    return pd.DataFrame(rows, columns=cols)


def receipts(fetch, limit: int = 12) -> pd.DataFrame:
    """최근 자재 입고 (MES 입고 LOT). 물류 구역의 입고 이벤트가 만든 것과 자동 입고(시연용)가 함께 나온다."""
    return fetch(
        """
        SELECT l.lot_no AS LOT, i.item_name AS 자재, l.qty AS 수량, i.unit AS 단위, COALESCE(p.partner_name, '-') AS 공급업체, l.received_date AS 입고일
        FROM lot AS l JOIN item AS i ON i.item_id = l.item_id LEFT JOIN partner AS p ON p.partner_id = l.partner_id
        WHERE l.lot_type = 'RECEIPT' ORDER BY l.lot_id DESC LIMIT ?
        """,
        (limit,),
    )


def cobot_summary(ev_c: pd.DataFrame | None) -> dict | None:
    """협동로봇 셀 이벤트 요약: 검사, 불량 검출, 적재, 파렛트, 사이클, 신뢰도, 최근 검사 표, 파렛트 마감 표, 사이클 추이.
    사이클 = 집기 시작부터 놓기까지 걸린 시간 (cobot.placed 의 cycle_s)."""
    if ev_c is None or ev_c.empty:
        return None
    kst = lambda ts: ts.tz_convert("Asia/Seoul").strftime("%H:%M:%S")
    insp = ev_c[ev_c["event_type"] == "vision.inspected"]
    placed = ev_c[ev_c["event_type"] == "cobot.placed"]
    closed = ev_c[ev_c["event_type"] == "cobot.pallet_closed"]
    ins = pd.DataFrame({"piece": insp["piece_id"], "ts": insp["ts"], "result": insp["payload"].apply(lambda p: p["result"]),
                        "conf": insp["payload"].apply(lambda p: p["confidence"])}).reset_index(drop=True)
    pl = pd.DataFrame({"piece": placed["piece_id"], "ts": placed["ts"], "target": placed["payload"].apply(lambda p: p["target"]),
                       "slot": placed["payload"].apply(lambda p: p["slot"]), "cycle_s": placed["payload"].apply(lambda p: p["cycle_s"])}).reset_index(drop=True)
    merged = ins.merge(pl[["piece", "target", "slot", "cycle_s"]], on="piece", how="left")
    recent = pd.DataFrame({
        "시각": merged["ts"].apply(kst), "작업물": merged["piece"], "판정": merged["result"].map({"good": "양품", "scrap": "불량"}),
        "신뢰도": (merged["conf"] * 100).round(1).astype(str) + "%",
        "놓은 곳": merged.apply(lambda r: "대기 중" if pd.isna(r["target"]) else (f"파렛트 {int(r['slot']) + 1}번 칸" if r["target"] == "pallet" else "NG 수납함"), axis=1),
        "사이클(초)": merged["cycle_s"]}).tail(20).iloc[::-1]
    pallets = pd.DataFrame({
        "시각": closed["ts"].apply(kst), "수량": closed["payload"].apply(lambda p: len(p["pieces"])),
        "마감": closed["payload"].apply(lambda p: "라인 정지로 모자란 채 마감" if p["partial"] else "5개 가득 참")}).tail(10).iloc[::-1]
    n_ng = int((ins["result"] == "scrap").sum())
    return {"inspected": len(ins), "ng": n_ng, "good": len(ins) - n_ng, "pallets": len(closed), "partial": int(closed["payload"].apply(lambda p: p["partial"]).sum()),
            "avg_cycle_s": float(pl["cycle_s"].mean()) if len(pl) else 0.0, "min_cycle_s": float(pl["cycle_s"].min()) if len(pl) else 0.0,
            "max_cycle_s": float(pl["cycle_s"].max()) if len(pl) else 0.0, "avg_conf": float(ins["conf"].mean()) if len(ins) else 0.0,
            "recent": recent, "pallet_table": pallets, "cycles": pl[["ts", "cycle_s"]]}
