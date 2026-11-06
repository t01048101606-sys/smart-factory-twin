"""물류 · 출하 구역이 MES(원자재 입고, 출하 관리, LOT 추적)에 맞게 들어가는지 확인합니다.

프레스 라인과 물류 구역을 같은 이벤트 스트림에서 돌리고, 입고는 원자재 입고로, 출하는 출하 관리로 등록되는지,
불합격(FAIL) LOT 의 출하를 MES 가 막는지, 완제품 LOT 가 아직 없을 때 출하를 보류했다가 다시 시도하는지 봅니다.
MES 폴더는 임시 폴더로 복사해서 쓰므로 원본은 바뀌지 않습니다.
실행 (프로젝트 폴더에서):  python tests/test_mes_logistics.py [MES 폴더 경로]
"""
import json
import shutil
import sqlite3
import sys
import tempfile
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
from line_sim import LineSim                         # noqa: E402
from line_events import LineEventBridge              # noqa: E402
from logistics_sim import LogisticsSim               # noqa: E402
from logistics_events import LogisticsEventBridge, LINE_ID   # noqa: E402
from events import EventEmitter                      # noqa: E402
from mes_adapter import MesAdapter                   # noqa: E402

try:
    import jsonschema
    V = jsonschema.Draft7Validator(json.loads((ROOT / "docs" / "event_schema.json").read_text(encoding="utf-8")))
except ImportError:
    V = None

MES_SRC = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT.parent / "AutoParts-MES-Arduino"
T0 = 1793923800.0

# ---- 이벤트: 프레스 라인 + 물류 구역. 처음 5개 작업물은 용접 불량(100%)으로 만들어 첫 LOT 가 FAIL 이 되게 한다
clock = [T0]
em = EventEmitter(now=lambda: clock[0], keep=10 ** 7)
line = LineSim(defect_rate=1.0); line.hook = LineEventBridge(em)
logi = LogisticsSim(); bridge = LogisticsEventBridge(em, logi)
welds = [0]


def flip(e):
    if e["type"] == "station.completed" and e["payload"]["station"] == "weld":
        welds[0] += 1
        if welds[0] == 5:
            line.defect_rate = 0.08


em.subscribe(flip)
line.start()
for i in range(int(1500 / 0.5)):
    clock[0] = T0 + i * 0.5
    if i == int(600 / 0.5):
        line.stop()
    line.advance(0.5); logi.advance(0.5)
ev = em.since(-1, 10 ** 8)
by = {}
for e in ev:
    by.setdefault((e["line_id"], e["type"]), 0)
    by[(e["line_id"], e["type"])] += 1
rec_ev = [e for e in ev if e["type"] == "lot.received"]
dis_ev = [e for e in ev if e["type"] == "shipment.dispatched"]
pal_ev = [e for e in ev if e["type"] == "pallet.stored"]
print(f"이벤트 {len(ev)}개: 입고 {len(rec_ev)}건, 파렛트 {len(pal_ev)}개, 출하 {len(dis_ev)}건")
assert rec_ev and pal_ev and dis_ev and {e["line_id"] for e in rec_ev + dis_ev} == {LINE_ID}
if V:
    bad = [e for e in ev if not V.is_valid(e)]
    assert not bad, bad[0]
    print("스키마 검증 통과 (lot.received, pallet.stored, shipment.dispatched 포함)")

# ---- MES
tmp = Path(tempfile.mkdtemp(prefix="mes_logi_"))
mes = tmp / "mes"
shutil.copytree(MES_SRC, mes, ignore=shutil.ignore_patterns(".git", "__pycache__", "*.docx", "*.pdf", "*.db", "*.db-*"))
logs = []
ad = MesAdapter(mes, today=lambda: date(2026, 11, 6), log=logs.append, press_batch=5)
ad.init_db(); ad.seed_master(); ad.press.ensure()
for e in ev:
    ad.handle(e)
db = mes / "sql" / "auto_parts.db"
rows = lambda sql, p=(): [dict(r) for r in (lambda c: (setattr(c, "row_factory", sqlite3.Row), c.execute(sql, p).fetchall())[1])(sqlite3.connect(db))]

# 1) 입고 -> 원자재 입고 (RECEIPT LOT)
for e in rec_ev:
    p = e["payload"]
    lot = rows("SELECT l.*, i.item_code, pa.partner_name FROM lot l JOIN item i USING (item_id) LEFT JOIN partner pa USING (partner_id) WHERE lot_no=?", (p["lot_no"],))
    assert len(lot) == 1 and lot[0]["lot_type"] == "RECEIPT" and lot[0]["item_code"] == p["item_code"], (p, lot)
    assert lot[0]["qty"] == p["qty"] and lot[0]["partner_name"] == p["supplier"]
print(f"입고 {len(rec_ev)}건 -> MES 원자재 입고(RECEIPT LOT): 품목, 수량, 공급업체 일치 (예: {rec_ev[0]['payload']['lot_no']} {rec_ev[0]['payload']['item_code']} {rec_ev[0]['payload']['qty']:g}{rec_ev[0]['payload']['unit']} {rec_ev[0]['payload']['supplier']})")

# 2) 출하 -> 출하 관리
sh = rows("SELECT s.*, p.partner_name FROM shipment s JOIN partner p USING (partner_id) ORDER BY shipment_id")
assert [s["shipment_no"] for s in sh] == [e["payload"]["shipment_no"] for e in dis_ev] and all(s["partner_name"] == "현대파츠" for s in sh), sh
items = rows("SELECT si.*, l.lot_type, l.qty lot_qty, l.lot_no FROM shipment_item si JOIN lot l USING (lot_id)")
shipped_pcs = sum(len(pc) for e in dis_ev for pal in e["payload"]["pallets"] for pc in [pal["pieces"]])
assert sum(i["qty"] for i in items) == shipped_pcs and all(i["lot_type"] == "FINISHED" for i in items)
for lot_id in {i["lot_id"] for i in items}:      # LOT 별 출하량이 LOT 수량을 넘지 않는다
    assert sum(i["qty"] for i in items if i["lot_id"] == lot_id) <= [i["lot_qty"] for i in items if i["lot_id"] == lot_id][0]
print(f"출하 {len(sh)}건 -> MES 출하 관리: 고객사 현대파츠, 완제품 LOT {len({i['lot_id'] for i in items})}개, 출하 작업물 {shipped_pcs}개 (LOT 수량을 넘지 않음)")
assert logi.counts["shipped_pcs"] == shipped_pcs

# 3) 불합격(FAIL) LOT 는 출하되지 않는다 (불량은 파렛트에 담기지 않았고, 억지로 출하해도 MES 가 막는다)
fail = rows("SELECT i.lot_id, l.lot_no FROM inspection i JOIN lot l USING (lot_id) WHERE i.result='FAIL'")
assert len(fail) == 1, fail
assert not [i for i in items if i["lot_id"] == fail[0]["lot_id"]], "FAIL LOT 가 출하되었습니다"
bad_serials = [r["serial_no"] for r in rows("SELECT serial_no FROM unit_serial WHERE lot_id=?", (fail[0]["lot_id"],))]
n_ship = len(sh)
forged = {"event_id": "forged-1", "seq": 10 ** 9, "ts": "2026-11-06T00:00:00.000Z", "source": "gateway", "line_id": LINE_ID, "type": "shipment.dispatched",
          "piece_id": None, "payload": {"shipment_no": "SHP-FORGED-0001", "customer": "현대파츠", "pallets": [{"pallet_id": "PL-X", "pieces": bad_serials[:2]}]}}
ad.handle(forged)
assert len(rows("SELECT 1 FROM shipment")) == n_ship
assert any("불합격" in l for l in logs[-3:]), logs[-3:]
print(f"FAIL LOT {fail[0]['lot_no']}: 정상 흐름에서는 출하되지 않았고, 억지로 출하를 시도해도 MES 가 '불합격 LOT' 라며 거절함")

# 4) 완제품 LOT 가 아직 없는 작업물의 출하는 보류했다가 다시 시도한다
ghost = dict(forged, event_id="forged-2", seq=10 ** 9 + 1, payload={"shipment_no": "SHP-GHOST-0001", "customer": "현대파츠", "pallets": [{"pallet_id": "PL-Y", "pieces": ["B-99991231-0001"]}]})
ad.handle(ghost)
assert [p["payload"]["shipment_no"] for p in ad.state["pending_shipments"]] == ["SHP-GHOST-0001"]
ad.logi.retry(); assert len(ad.state["pending_shipments"]) == 1 and ad.state["pending_shipments"][0]["attempts"] == 2
print("완제품 LOT 를 아직 못 찾는 출하는 보류됨 (다시 시도 횟수 증가), 정상 흐름에서는 보류가 남지 않음")
real_pending = [p for p in ad.state["pending_shipments"] if p["payload"]["shipment_no"] != "SHP-GHOST-0001"]
assert not real_pending, real_pending

# 5) LOT 추적: 자재 LOT 에서 시작해 완제품 LOT 와 출하까지
steel = rows("SELECT lot_id, lot_no FROM lot l JOIN item i USING (item_id) WHERE i.item_code='RM-STEEL' ORDER BY lot_id")
traced = [ad.q.forward_trace_shipments(s["lot_id"]) for s in steel]
assert any(len(t) for t in traced), "정방향 추적에 출하가 나오지 않습니다"
first = next(t for t in traced if len(t))
print("LOT 추적(정방향): 냉연강판 LOT ->", list(first.columns)[:4], f"... 출하 {len(first)}건")

# 6) 가공 라인 페이지/기준정보 등 다른 데이터와 섞이지 않는다: 물류 이벤트의 machine_event
me = rows("SELECT line_id, COUNT(*) n, SUM(sim_t IS NOT NULL) s FROM machine_event GROUP BY line_id")
d = {r["line_id"]: r for r in me}
assert d[LINE_ID]["n"] == len([e for e in ev if e["line_id"] == LINE_ID]) + 2 and d[LINE_ID]["s"] == d[LINE_ID]["n"] - 2   # + 위조 이벤트 2건은 sim_t 없음

# 7) MES 출하 관리 페이지(원본 pages/10_출하관리.py)가 열린다 (원본 스키마에 없던 handling_event 테이블이 있어야 한다)
import types
from unittest.mock import MagicMock
assert rows("SELECT COUNT(*) n FROM sqlite_master WHERE name='handling_event'")[0]["n"] == 1
seen = {"options": None, "error": None, "tables": 0}


class FakeSt(types.ModuleType):
    def __init__(self):
        super().__init__("streamlit")
        self.session_state = {"logged_in": True, "user_role": "ADMIN"}
    def tabs(self, labels): return [MagicMock() for _ in labels]
    def columns(self, spec, **k): return [MagicMock() for _ in range(spec if isinstance(spec, int) else len(spec))]
    def selectbox(self, label, options, **k): return options[0]
    def multiselect(self, label, options, **k): seen["options"] = list(options); return []
    def button(self, *a, **k): return False
    def dataframe(self, *a, **k): seen["tables"] += 1
    def error(self, msg, *a, **k): seen["error"] = msg
    def __getattr__(self, name): return MagicMock()


sys.modules.update({"streamlit": FakeSt(), "plotly": MagicMock(), "plotly.graph_objects": MagicMock()})
for name in [m for m in sys.modules if m == "src" or m.startswith("src.")]:
    del sys.modules[name]
if str(mes) in sys.path:
    sys.path.remove(str(mes))
sys.path.insert(0, str(mes))
import runpy
runpy.run_path(str(mes / "pages" / "10_출하관리.py"), run_name="__main__")      # 예외 없이 끝까지 실행되어야 한다
opts = seen["options"]
assert opts is not None, "출하할 LOT 선택 목록까지 도달하지 못했습니다"
fail_lots = [r["lot_no"] for r in rows("SELECT l.lot_no FROM lot l JOIN inspection i USING (lot_id) WHERE i.result='FAIL'")]
assert fail_lots and all(any(lot in o and "불합격" in o for o in opts) for lot in fail_lots if rows("SELECT 1 FROM lot WHERE lot_no=?", (lot,))), (fail_lots, opts[:3])
print(f"MES 출하 관리 페이지 실행 확인: 출하 가능한 LOT {len(opts)}개 중 FAIL LOT 는 '불합격(출하불가)' 배지, 오류 없음")

# 8) MES 공장 현황 대시보드(13_공장현황.py): 화면의 숫자를 MES 데이터에서 따로 계산한 값과 비교한다
ad.log = lambda m: None
ad.install_addons()
for f in ("pages/13_공장현황.py", "pages/17_물류출하.py", "pages/16_협동로봇셀.py", "src/factory_dash.py", "src/lineoee.py"):
    assert (mes / f).exists(), f


sys.path.insert(0, str(ROOT / "tests"))
import fake_cols            # noqa: E402
import fake_twin_server     # noqa: E402
twin_srv, TWIN, twin_log, _ = fake_twin_server.start()


class FakeSt2(FakeSt):
    def columns(self, spec, **k): return [fake_cols.Col() for _ in range(spec if isinstance(spec, int) else len(spec))]
    def checkbox(self, *a, **k): return False
    def text_input(self, label, value="", **k): return TWIN if "트윈 서버 주소" in label else value
    def number_input(self, label, value=0, **k): return value
    def stop(self): raise AssertionError("대시보드가 st.stop() 으로 멈췄습니다 (MES 테이블을 읽지 못함)")


seen8 = {"kpi": None, "plots": 0, "tables": 0}
sys.modules.update({"streamlit": FakeSt2(), "plotly": MagicMock(), "plotly.graph_objects": MagicMock()})
for name in [m for m in sys.modules if m == "src" or m.startswith("src.")]:
    del sys.modules[name]
import src.ui as ui   # noqa: E402
ui.kpi_row = lambda items, columns=3: seen8.__setitem__("kpi", {a: b for a, b, _ in items})
orig_df = ui.show_dataframe
ui.show_dataframe = lambda df, msg="": (seen8.__setitem__("tables", seen8["tables"] + 1), None)[1]
import streamlit as _st
_st.plotly_chart = lambda *a, **k: seen8.__setitem__("plots", seen8["plots"] + 1)
fake_cols.Col.clicks = {"▶ 라인 시작", "가공 라인 연속동작"}
runpy.run_path(str(mes / "pages" / "13_공장현황.py"), run_name="__main__")
reqs13 = [(p, b) for m, p, b in twin_log if m == "POST"]
assert reqs13 == [("/api/line/control", {"action": "start"}), ("/api/press", {"dev": "M101"})], reqs13      # 공장현황: 프레스 라인 시작 + 가공 라인 연속동작
print("공장현황 페이지 버튼: 프레스 라인 시작과 가공 라인 연속동작이 트윈 서버로 전달됨")
twin_log.clear()
k = seen8["kpi"]
print("대시보드 KPI:", k)
assert k and list(k) == ["양품 생산", "불량", "출하 수량", "출하 대기", "출하 차단 LOT", "재고 부족 자재"], k
assert seen8["plots"] >= 3 and seen8["tables"] >= 4, seen8              # 재고와 출하 상세는 물류 · 출하 페이지로 옮겨졌다

import pandas as pd
from src import factory_dash as fd, oee, lineoee
from src.db import fetch_dataframe as F
# 생산: 시리얼 수를 직접 센 값과 같다
good_direct = rows("SELECT COUNT(*) n FROM unit_serial WHERE status='COMPLETED'")[0]["n"]
scrap_direct = rows("SELECT COUNT(*) n FROM unit_serial WHERE status='SCRAPPED'")[0]["n"]
serial, wo = fd.production(F)
assert int(serial["good"].sum()) == good_direct and int(serial["scrap"].sum()) == scrap_direct and good_direct > 0 and scrap_direct >= 5
assert k["양품 생산"] == f"{good_direct:,} 개", k["양품 생산"]
# 재고: 냉연강판 소비량 = 프레스 1단계 공정 실행 수량 x 0.5
inv = fd.inventory(F)
steel = inv[inv["item_code"] == "RM-STEEL"].iloc[0]
op1 = rows("SELECT COALESCE(SUM(o.qty),0) q FROM operation o JOIN routing_step rs USING (routing_step_id) JOIN work_order w USING (work_order_id) "
           "JOIN item i ON i.item_id=w.product_item_id WHERE i.item_code='FG-BRKA' AND rs.step_no=1")[0]["q"]
recv = rows("SELECT COALESCE(SUM(l.qty),0) q FROM lot l JOIN item i USING (item_id) WHERE i.item_code='RM-STEEL' AND l.lot_type='RECEIPT'")[0]["q"]
assert abs(steel["consumed"] - 0.5 * op1) < 1e-6 and abs(steel["received"] - recv) < 1e-6
assert abs(steel["balance"] - (recv - 0.5 * op1)) < 1e-6 and abs(steel["makeable"] - steel["balance"] / 0.5) < 1e-6
assert (inv["balance"] >= -1e-9).all()
# 출하: 건수와 수량은 shipment 테이블과 같고, 출하 가능 수량은 양품 - 출하
ship = fd.shipments(F)
assert ship["count"] == rows("SELECT COUNT(*) n FROM shipment")[0]["n"] and abs(ship["qty"] - rows("SELECT COALESCE(SUM(qty),0) q FROM shipment_item")[0]["q"]) < 1e-9
assert k["출하 수량"] == f"{ship['qty']:,.0f} 개 ({ship['count']}건)"
brka_good = rows("SELECT COUNT(*) n FROM unit_serial u JOIN lot l USING (lot_id) JOIN item i ON i.item_id=l.item_id WHERE i.item_code='FG-BRKA' AND u.status='COMPLETED'")[0]["n"]
assert ship["qty"] <= brka_good, (ship["qty"], brka_good)                                 # 양품보다 많이 출하하지 않았다
assert int(ship["waiting"]["shippable"].sum()) == brka_good - int(ship["qty"])               # 출하 대기 = 양품 - 출하 (FAIL LOT 는 양품이 0개)
assert len(ship["blocked"]) >= 1 and all(r == "FAIL" for r in ship["blocked"]["result"]) and set(ship["blocked"]["lot_no"]) >= set(fail_lots)
assert k["출하 차단 LOT"] == f"{len(ship['blocked'])} 개"
# 품질: 검사 결과 분포의 LOT 합 = 완제품 검사 건수, 용접 균열 불량 수량 = 검사의 불량 합
dist, reasons = fd.quality(F)
assert int(dist["lots"].sum()) == rows("SELECT COUNT(*) n FROM inspection WHERE inspection_type='FINISHED'")[0]["n"]
weld_direct = rows("SELECT COALESCE(SUM(defect_qty),0) q FROM inspection WHERE reason_code='WELD_CRACK'")[0]["q"]
assert float(reasons[reasons["reason"] == "용접 균열"]["qty"].iloc[0]) == weld_direct and weld_direct >= 5
# 라인 현황: 프레스 라인 OEE 는 lineoee 와 같고, 물류 건수는 이벤트 수와 같다
ev_m, ev_p, ev_l = (oee.load_events(None, line_id=x) for x in (fd.MACHINING, fd.PRESS, fd.LOGISTICS))
ov, res = fd.line_overview(ev_m, ev_p, ev_l, now=ev_p["ts"].max())
assert ov.iloc[0]["상태"] == "연결 없음"                                                  # 이 시험에는 가공 라인 이벤트가 없다
assert ov.iloc[1]["OEE"] == f"{lineoee.compute_line_oee(ev_p)['oee'] * 100:.1f}%"
assert res["logistics"] == {"received": int((ev_l["event_type"] == "lot.received").sum()), "shipments": int((ev_l["event_type"] == "shipment.dispatched").sum()),
                            "pallets": int((ev_l["event_type"] == "pallet.stored").sum())}
al = fd.alerts(oee.load_events(None), inv, ship, ov)
assert any("출하 차단" in t for t in al["내용"]), al
assert not any(g == "설비" for g in al["구분"]), "이벤트가 없는 라인(연결 없음)은 경보가 아닙니다"
ov_old, _ = fd.line_overview(ev_m, ev_p, ev_l, now=ev_p["ts"].max() + pd.Timedelta(minutes=10))    # 10분 동안 이벤트가 없으면 무응답
al2 = fd.alerts(oee.load_events(None), inv, ship, ov_old)
assert ov_old.iloc[1]["상태"].startswith("무응답") and any(g == "설비" and "무응답" in t for g, t in zip(al2["구분"], al2["내용"])), al2
# 자동 입고 자재(가공용 블랭크)는 부족으로 보지 않는다. 물류 구역이 발주하는 자재만 부족 판정
assert bool(inv.loc[inv["item_code"] == "RM-BLANK", "auto"].iloc[0]) and not bool(inv.loc[inv["item_code"] == "RM-BLANK", "low"].iloc[0])
low_df = fd.inventory(F, low_units=10 ** 9)                                                   # 기준을 아주 크게 하면 물류 자재는 모두 부족
assert set(low_df[low_df["low"]]["item_code"]) == {"RM-STEEL", "RM-BOLT", "RM-PAINT"}, low_df[["item_code", "low"]]
# 경보와 이력: 지금 진행 중인 것만 '주의', 지나간 것은 이력에만
T = pd.Timestamp("2026-11-06T01:00:00Z")
mk = lambda i, line, typ, payload: {"seq": i, "ts": T + pd.Timedelta(seconds=i), "line_id": line, "event_type": typ, "payload": payload, "piece_id": None, "sim_t": None}
empty_ship = {"blocked": ship["blocked"].iloc[0:0]}
no_ov = pd.DataFrame(columns=["라인", "상태"])
inv_ok = inv.assign(low=False)
done_ev = pd.DataFrame([mk(1, fd.MACHINING, "alarm.raised", {"metric": "CYCLE_TIME_ANOMALY"}), mk(2, fd.MACHINING, "alarm.cleared", {}),
                        mk(3, fd.PRESS, "sim.fault", {"mode": "weld_slow"}), mk(4, fd.PRESS, "sim.fault", {"mode": "none"})])
assert fd.alerts(done_ev, inv_ok, empty_ship, no_ov).empty, "해제된 경보와 결함이 주의 목록에 남아 있습니다"
h = fd.history(done_ev)
assert list(h["내용"]) == ["결함 주입: 해제", "결함 주입: 용접 속도 저하", "AI 이상 감지 경보 해제", "AI 이상 감지 경보 발생"], list(h["내용"])   # 최근 것이 위
live_ev = pd.DataFrame([mk(1, fd.MACHINING, "alarm.raised", {"metric": "CYCLE_TIME_ANOMALY"}), mk(2, fd.PRESS, "sim.fault", {"mode": "paint_down"})])
live = fd.alerts(live_ev, inv_ok, empty_ship, no_ov)
assert list(live["구분"]) == ["AI", "결함"] and "경보 중" in live.iloc[0]["내용"] and "도장 정지" in live.iloc[1]["내용"], live
print("경보 목록: 지금 진행 중인 AI 경보와 결함만 나오고, 해제된 것은 이력(최근 것이 위)에만 남음")
print(f"대시보드 숫자 검증: 양품 {good_direct} / 불량 {scrap_direct}, 냉연강판 소비 {steel['consumed']:.1f}kg (공정 실행 x 0.5), 출하 {ship['count']}건 {ship['qty']:.0f}개 "
      f"(양품 {brka_good}개 이하), FAIL 차단 LOT {len(ship['blocked'])}개, 용접 균열 {weld_direct:.0f}개, 프레스 OEE {ov.iloc[1]['OEE']}")

# 9) 물류 · 출하 페이지(17_물류출하.py): 재고, 출하, 입고 이력. 화면 숫자를 MES 데이터와 이벤트에서 따로 센 값과 비교한다
seen8.update(kpi=None, plots=0, tables=0)
fake_cols.Col.clicks = {"▶ 라인 시작", "입고 요청 (트럭 부르기)"}
runpy.run_path(str(mes / "pages" / "17_물류출하.py"), run_name="__main__")
reqs17 = [(p, b) for m, p, b in twin_log if m == "POST"]
assert reqs17 == [("/api/line/control", {"action": "start"}), ("/api/logistics/request_inbound", {})], reqs17      # 물류출하: 라인 시작 + 입고 요청
print("물류출하 페이지 버튼: 라인 시작과 입고 요청이 트윈 서버로 전달됨")
kl = seen8["kpi"]
print("물류 페이지 KPI:", kl)
assert list(kl) == ["입고 횟수", "파렛트 보관", "출하", "출하 대기", "출하 차단 LOT", "재고 부족 자재"], kl
n_recv_direct = sum(1 for e in ev if e["line_id"] == LINE_ID and e["type"] == "lot.received")
n_pal_direct = sum(1 for e in ev if e["line_id"] == LINE_ID and e["type"] == "pallet.stored")
assert kl["입고 횟수"] == f"{n_recv_direct} 회" and kl["파렛트 보관"] == f"{n_pal_direct} 개", (kl, n_recv_direct, n_pal_direct)
assert kl["출하"] == f"{ship['qty']:,.0f} 개 ({ship['count']}건)" and kl["출하 차단 LOT"] == f"{len(ship['blocked'])} 개"
assert seen8["plots"] >= 1 and seen8["tables"] >= 5, seen8          # 재고 그래프, 재고 표, 최근 출하, 출하 대기, 입고 이력, 물류 이벤트
rec = fd.receipts(F)
assert len(rec) >= 1 and set(rec.columns) >= {"LOT", "자재", "수량", "공급업체"} and rec["공급업체"].isin(["한국제철", "대한볼트산업", "삼성도료", "블랭크 공급사(시연)"]).all(), rec
assert (oee.recent_events(oee.load_events(None, line_id=fd.LOGISTICS), 25)["내용"].str.contains("입고|보관|출하")).any()
print(f"물류 페이지: 입고 {n_recv_direct}회, 파렛트 {n_pal_direct}개, 출하 {ship['count']}건과 일치, 입고 이력 {len(rec)}건(공급업체 확인), 물류 이벤트 설명 확인")
print("\n테스트 통과")
