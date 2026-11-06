"""프레스·용접·도장 라인의 이벤트가 MES(작업지시, 공정 실행, LOT, 시리얼, 검사, LOT 추적)에 맞게 들어가는지 확인합니다.

가공 라인(PLC 시뮬레이터)과 프레스 라인을 같은 이벤트 스트림, 같은 MES DB에서 동시에 돌려서 서로 섞이지 않는지도 봅니다.
MES 폴더는 임시 폴더로 복사해서 쓰므로 원본은 바뀌지 않습니다.
실행 (프로젝트 폴더에서):  python tests/test_mes_press_line.py [MES 폴더 경로]
"""
import shutil
import sqlite3
import sys
import tempfile
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
from plc_sim import PlcSim                         # noqa: E402
from line_sim import LineSim                       # noqa: E402
from line_events import LineEventBridge, LINE_ID   # noqa: E402
from events import EventEmitter                    # noqa: E402
from mes_adapter import MesAdapter                 # noqa: E402

MES_SRC = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT.parent / "AutoParts-MES-Arduino"
T0 = 1793923800.0

# ---- 이벤트: 가공 라인과 프레스 라인을 같은 시계, 같은 이벤트 발행기로 함께 돌린다
clock = [T0]
em = EventEmitter(now=lambda: clock[0], keep=10 ** 7)
plc = PlcSim(str(ROOT / "plc" / "1102"))
line = LineSim()
line.hook = LineEventBridge(em)
plan_line = {0.0: "start", 150.0: "weld_slow", 210.0: "none", 330.0: "stop", 345.0: "start", 420.0: "reset", 421.0: "start", 500.0: "stop"}
total = 600.0
for i in range(int(total / 0.05)):
    t = i * 0.05
    clock[0] = T0 + t
    for at, act in plan_line.items():
        if abs(t - at) < 1e-9:
            if act in ("start", "stop", "reset"):
                getattr(line, act)()
            else:
                line.set_fault(act)
    line.advance(0.05)
    if i == 20:
        em.command("M101", "web")
    plc.scan(["M101"] if i == 20 else [])
    em.observe(plc.dev)
ev = em.since(-1, 10 ** 8)
lines = {e["line_id"] for e in ev}
print(f"이벤트 {len(ev)}개, 라인: {sorted(lines)}")
assert lines == {"LINE-MACHINING-01", LINE_ID}

# ---- MES
tmp = Path(tempfile.mkdtemp(prefix="mes_press_"))
mes = tmp / "mes"
shutil.copytree(MES_SRC, mes, ignore=shutil.ignore_patterns(".git", "__pycache__", "*.docx", "*.pdf", "*.db", "*.db-*"))
logs = []
ad = MesAdapter(mes, batch=4, today=lambda: date(2026, 11, 6), log=logs.append, press_batch=5)
ad.init_db(); ad.seed_master(); ad.press.ensure()
for e in ev:
    ad.handle(e)
db = mes / "sql" / "auto_parts.db"


def rows(sql, params=()):
    c = sqlite3.connect(db); c.row_factory = sqlite3.Row
    try:
        return [dict(r) for r in c.execute(sql, params).fetchall()]
    finally:
        c.close()


# 1) 기준정보: MES 샘플 데이터와 같은 코드
assert {r["process_code"] for r in rows("SELECT process_code FROM process_master")} >= {"PRESS", "WELD", "PAINT", "DRILL", "SORT"}
steps = rows("SELECT rs.step_no, rs.process_code, i.item_code FROM routing_step rs JOIN routing r USING (routing_id) JOIN item p ON p.item_id=r.product_item_id "
             "JOIN item i ON i.item_id=rs.output_item_id WHERE p.item_code='FG-BRKA' ORDER BY step_no")
assert [(r["process_code"], r["item_code"]) for r in steps] == [("PRESS", "SP-BRKA-PRS"), ("WELD", "SP-BRKA-WLD"), ("PAINT", "FG-BRKA")], steps
bom = rows("SELECT rs.step_no, i.item_code, b.qty_per_unit q FROM bom b JOIN routing_step rs USING (routing_step_id) JOIN item i ON i.item_id=b.material_item_id "
           "JOIN routing r USING (routing_id) JOIN item p ON p.item_id=r.product_item_id WHERE p.item_code='FG-BRKA' ORDER BY rs.step_no, b.bom_id")
assert [(r["step_no"], r["item_code"], r["q"]) for r in bom] == [
    (1, "RM-STEEL", 0.5), (2, "RM-BOLT", 4), (2, "SP-BRKA-PRS", 1), (3, "RM-PAINT", 0.05), (3, "SP-BRKA-WLD", 1)], bom
print("기준정보 확인: 라우팅 PRESS -> WELD -> PAINT, BOM(자재와 반제품)")

# 2) 작업지시: 프레스 라인 작업지시만 따로 본다 (제품 FG-BRKA)
wos = rows("SELECT w.* FROM work_order w JOIN item i ON i.item_id=w.product_item_id WHERE i.item_code='FG-BRKA' ORDER BY work_order_id")
other = rows("SELECT COUNT(*) n FROM work_order w JOIN item i ON i.item_id=w.product_item_id WHERE i.item_code='FG-DRILLPART'")[0]["n"]
done = [w for w in wos if w["status"] == "COMPLETED"]
print(f"프레스 라인 작업지시: {[(w['work_order_no'], w['status']) for w in wos]} | 가공 라인 작업지시 {other}건 (섞이지 않음)")
assert len(done) >= 3 and other >= 3
import re
aborted = set(re.findall(r"리셋: (WO-\d+-\d+)는 공정 실행 이력이 있어", " ".join(logs)))   # 리셋 때 이미 공정 실행이 있어 MES 규칙상 취소하지 못한 작업지시
still_open = {w["work_order_no"] for w in wos if w["status"] in ("PLANNED", "IN_PROGRESS")}
assert still_open == aborted, (still_open, aborted)       # 열려 있는 것은 리셋으로 중단된 작업지시뿐이다
print(f"리셋으로 중단된 작업지시(이미 공정 실행이 있어 취소 불가): {sorted(aborted)}")
canceled = [w for w in wos if w["status"] == "CANCELED"]
assert canceled, "리셋으로 취소된 작업지시가 없습니다"

consumed = {"RM-STEEL": 0.0, "RM-BOLT": 0.0, "RM-PAINT": 0.0}
full = partial = 0
for w in done:
    ops = rows("SELECT o.*, rs.step_no, e.equipment_code FROM operation o JOIN routing_step rs USING (routing_step_id) "
               "JOIN equipment e ON e.equipment_id=o.equipment_id WHERE work_order_id=? ORDER BY step_no", (w["work_order_id"],))
    assert [o["step_no"] for o in ops] == [1, 2, 3] and len({o["qty"] for o in ops}) == 1, ops
    assert [o["equipment_code"] for o in ops] == ["EQ-PRESS-01", "EQ-WELD-01", "EQ-PAINT-01"]
    qty = int(ops[0]["qty"])
    full, partial = (full + 1, partial) if qty == 5 else (full, partial + 1)
    lots = [rows("SELECT * FROM lot WHERE lot_id=?", (o["output_lot_id"],))[0] for o in ops]
    assert [l["lot_type"] for l in lots] == ["WIP", "WIP", "FINISHED"] and all(l["qty"] == qty for l in lots)
    # 시리얼: 작업물 번호, 용접 불량은 SCRAPPED
    ser = rows("SELECT serial_no, status FROM unit_serial WHERE lot_id=?", (lots[2]["lot_id"],))
    assert len(ser) == qty and all(s["serial_no"].startswith("B-20") for s in ser)
    bad = sum(s["status"] == "SCRAPPED" for s in ser)
    ins = rows("SELECT * FROM inspection WHERE lot_id=?", (lots[2]["lot_id"],))[0]
    exp = "PASS" if bad == 0 else ("FAIL" if bad == qty else "PARTIAL")
    assert (ins["result"], ins["checked_qty"], ins["defect_qty"]) == (exp, qty, bad), (ins, bad)
    assert (ins["reason_code"] == "WELD_CRACK") == (bad > 0)
    # 자재 소비량 = BOM x 수량
    for code, per in (("RM-STEEL", 0.5), ("RM-BOLT", 4), ("RM-PAINT", 0.05)):
        consumed[code] += per * qty
print(f"완료 {len(done)}건 (계획 수량 5개를 채운 것 {full}건, 정지로 마감 {partial}건): 공정 실행 3단계(설비 연결), LOT WIP -> WIP -> FINISHED, 시리얼, 검사")
ops_all = rows("SELECT rs.step_no, o.qty FROM operation o JOIN routing_step rs USING (routing_step_id) JOIN work_order w USING (work_order_id) "
               "JOIN item i ON i.item_id=w.product_item_id WHERE i.item_code='FG-BRKA'")
want_all = {"RM-STEEL": sum(0.5 * o["qty"] for o in ops_all if o["step_no"] == 1),
            "RM-BOLT": sum(4 * o["qty"] for o in ops_all if o["step_no"] == 2),
            "RM-PAINT": sum(0.05 * o["qty"] for o in ops_all if o["step_no"] == 3)}
for code, want in want_all.items():       # 리셋으로 중단된 작업지시가 이미 소비한 자재도 소비된 것으로 기록되어 있어야 한다
    got = rows("SELECT COALESCE(SUM(om.qty),0) q FROM operation_material om JOIN item i ON i.item_id=om.material_item_id WHERE i.item_code=?", (code,))[0]["q"]
    assert abs(got - want) < 1e-6, (code, got, want)
    assert got >= consumed[code] - 1e-6
print("자재 소비량 확인 (BOM 단위당 수량 x 공정 실행 수량):", {k: round(v, 2) for k, v in want_all.items()})

# 3) LOT 추적: 냉연강판 LOT 에서 시작해 반제품 두 단계를 거쳐 완제품 LOT 까지 이어진다
steel = rows("SELECT lot_id, lot_no FROM lot l JOIN item i USING (item_id) WHERE i.item_code='RM-STEEL' ORDER BY lot_id LIMIT 1")[0]
ad.press  # (조회는 MES 쪽 함수를 그대로 쓴다)
nodes = ad.q.forward_trace_nodes(steel["lot_id"])
chain = {int(d): set(g["item_code"]) for d, g in nodes.groupby("depth")}
assert chain[0] == {"RM-STEEL"} and chain[1] == {"SP-BRKA-PRS"} and chain[2] == {"SP-BRKA-WLD"} and chain[3] == {"FG-BRKA"}, chain
edges = ad.q.forward_trace_edges(steel["lot_id"])
assert list(edges["process_name"].drop_duplicates()) == ["프레스", "용접", "도장"], edges["process_name"].tolist()
print(f"LOT 추적: {steel['lot_no']} -> 프레스품 -> 용접품 -> 완제품 (정방향 {len(nodes)}개 LOT, 단계 {sorted(chain)})")

# 4) 설비 이벤트 저장: sim_t, 작업지시 연결, 가공 라인과 구분
me = rows("SELECT line_id, COUNT(*) n, SUM(sim_t IS NOT NULL) s, SUM(work_order_id IS NOT NULL) w FROM machine_event GROUP BY line_id")
by = {r["line_id"]: r for r in me}
assert by[LINE_ID]["s"] == by[LINE_ID]["n"] and by[LINE_ID]["w"] > 0 and by["LINE-MACHINING-01"]["s"] == 0
print("machine_event:", {k: (v["n"], f"sim_t {v['s']}", f"작업지시 연결 {v['w']}") for k, v in by.items()})

# 5) 같은 이벤트를 다시 넣어도, 껐다 켜도 중복이 없다
n0 = rows("SELECT COUNT(*) n FROM machine_event")[0]["n"]
for e in ev:
    ad.handle(e)
assert rows("SELECT COUNT(*) n FROM machine_event")[0]["n"] == n0
print("재처리해도 중복 없음")

# 6) MES 페이지(15_프레스라인.py)를 실제 DB 데이터로 끝까지 실행
import runpy
import types
from unittest.mock import MagicMock
ad.log = lambda m: None
ad.install_addons()
for f in ("sections/press.py", "src/lineoee.py", "src/oee.py"):
    assert (mes / f).exists(), f
calls = {"kpi": None, "plots": 0, "dataframes": 0, "iframe": None}


class FakeSt(types.ModuleType):
    def __init__(self):
        super().__init__("streamlit")
        self.session_state = {"logged_in": True, "user_role": "ADMIN"}
    def columns(self, spec, **k): return [MagicMock() for _ in range(spec if isinstance(spec, int) else len(spec))]
    def selectbox(self, label, options, **k): return options[0]
    def text_input(self, label, value="", **k): return value
    def checkbox(self, label, value=False, **k): return value
    def number_input(self, label, value=0, **k): return value
    def dataframe(self, df, **k): calls["dataframes"] += 1
    def plotly_chart(self, fig, **k): calls["plots"] += 1
    def rerun(self): pass
    def tabs(self, labels): return [MagicMock() for _ in labels]
    def radio(self, label, options, **k): return options[0]
    def __getattr__(self, name): return MagicMock()


fake = FakeSt()
comp = types.ModuleType("streamlit.components.v1")
comp.iframe = lambda src, **k: calls.__setitem__("iframe", src)
fake.components = types.SimpleNamespace(v1=comp)
sys.modules.update({"streamlit": fake, "streamlit.components": fake.components, "streamlit.components.v1": comp,
                    "plotly": MagicMock(), "plotly.graph_objects": MagicMock()})
for name in [m for m in sys.modules if m == "src" or m.startswith("src.")]:
    del sys.modules[name]
if str(mes) in sys.path:
    sys.path.remove(str(mes))
sys.path.insert(0, str(mes))
import src.ui as ui  # noqa: E402
calls["kpi"] = {}
ui.kpi_row = lambda items, columns=3: calls["kpi"].update({a: b for a, b, _ in items})
import runpy as _r
_r.run_path(str(mes / "sections" / "press.py"), run_name="__main__")
k = calls["kpi"]
print("페이지 KPI:", k)
assert k and all(x in k for x in ("OEE", "가용률", "성능률", "품질률", "처리량", "양품 / 불량"))
assert calls["plots"] == 1 and calls["dataframes"] >= 4 and calls["iframe"] == "http://localhost:5001/3d/line?embed=1"
pc = lambda x: float(x.rstrip("%"))
assert abs(pc(k["가용률"]) * pc(k["성능률"]) * pc(k["품질률"]) / 10000 - pc(k["OEE"])) < 0.2
# 가공 라인 페이지가 프레스 라인 이벤트에 영향받지 않는다 (라인 구분)
calls["kpi"] = {}
_r.run_path(str(mes / "sections" / "machining.py"), run_name="__main__")
k2 = calls["kpi"]
assert "판별한 워크" in k2, k2          # 기본은 현장 용어
print("가공 라인 페이지도 정상 (라인별로 이벤트를 구분해서 읽음):", {x: k2[x] for x in ("OEE", "판별한 워크")})
print("\n테스트 통과")
