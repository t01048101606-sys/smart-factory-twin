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
print("\n테스트 통과")
