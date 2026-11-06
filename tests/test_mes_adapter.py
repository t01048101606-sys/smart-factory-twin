"""시뮬레이터 이벤트를 어댑터에 흘려 보내고, Auto Parts MES의 DB가 맞게 채워지는지 확인합니다.

MES 폴더는 임시 폴더로 복사해서 쓰므로 원본 MES는 바뀌지 않습니다.
실행 (프로젝트 폴더에서):  python tests/test_mes_adapter.py [MES 폴더 경로]
(MES의 db.py가 pandas를 쓰므로 pandas가 필요합니다)
"""
import shutil
import sqlite3
import sys
import tempfile
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
from plc_sim import PlcSim          # noqa: E402
from events import EventEmitter     # noqa: E402
from mes_adapter import MesAdapter  # noqa: E402

MES_SRC = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT.parent / "AutoParts-MES-Arduino"
T0 = 1793923800.0


def simulate(mode, scans, script):
    """시뮬레이터를 돌려 이벤트 목록을 만든다. script: {스캔번호: 장치}"""
    clock = [T0]
    sim = PlcSim(str(ROOT / "plc" / "1102"))
    sim.piece_mode = mode
    em = EventEmitter(now=lambda: clock[0])
    for s in range(scans):
        clock[0] = T0 + s * 0.05
        dev = script.get(s)
        if dev:
            em.command(dev, "web")
        sim.scan([dev] if dev else [])
        em.observe(sim.dev)
    return em.since(-1, 100000)


def new_mes():
    tmp = Path(tempfile.mkdtemp(prefix="mes_test_"))
    dst = tmp / "mes"
    shutil.copytree(MES_SRC, dst, ignore=shutil.ignore_patterns(".git", "__pycache__", "*.docx", "*.pdf", "*.db", "*.db-*"))
    return dst


def rows(db, sql, params=()):
    c = sqlite3.connect(db); c.row_factory = sqlite3.Row
    try:
        return [dict(r) for r in c.execute(sql, params).fetchall()]
    finally:
        c.close()


# ===================================================================== 1) 번갈아(금속/비금속) + 중간 리셋
mes = new_mes()
ad = MesAdapter(mes, batch=4, today=lambda: date(2026, 11, 6), log=lambda m: print("  ", m))
ad.init_db(); ad.seed_master()
ev = simulate("alternate", 2300, {20: "M101", 900: "X0E", 940: "M101", 2100: "M102"})
print(f"시뮬레이션 이벤트 {len(ev)}개 -> 어댑터")
for e in ev:
    ad.handle(e)
db = mes / "sql" / "auto_parts.db"

wos = rows(db, "SELECT * FROM work_order ORDER BY work_order_id")
print("\n작업지시:", [(w["work_order_no"], w["status"]) for w in wos])
done = [w for w in wos if w["status"] == "COMPLETED"]
canceled = [w for w in wos if w["status"] == "CANCELED"]
assert done, "완료된 작업지시가 없습니다"
assert canceled, "리셋으로 취소된 작업지시가 없습니다"
full, partial = [], []
for w in done:
    ops = rows(db, "SELECT o.*, rs.step_no FROM operation o JOIN routing_step rs USING (routing_step_id) WHERE work_order_id=? ORDER BY step_no", (w["work_order_id"],))
    assert [o["step_no"] for o in ops] == [1, 2] and ops[0]["qty"] == ops[1]["qty"], ops
    qty = int(ops[0]["qty"])
    lot = rows(db, "SELECT * FROM lot WHERE lot_id=?", (ops[1]["output_lot_id"],))[0]
    assert lot["lot_type"] == "FINISHED" and lot["qty"] == qty
    ser = {r["status"]: r["n"] for r in rows(db, "SELECT status, COUNT(*) n FROM unit_serial WHERE lot_id=? GROUP BY status", (lot["lot_id"],))}
    assert sum(ser.values()) == qty, ser
    ins = rows(db, "SELECT * FROM inspection WHERE lot_id=?", (lot["lot_id"],))[0]
    bad = ser.get("SCRAPPED", 0)
    exp = "PASS" if bad == 0 else ("FAIL" if bad == qty else "PARTIAL")
    assert (ins["result"], ins["checked_qty"], ins["defect_qty"]) == (exp, qty, bad), (ins, ser)
    assert (ins["reason_code"] == "MAT_MIX") == (bad > 0)
    if qty == 4:
        assert ser == {"COMPLETED": 2, "SCRAPPED": 2} and ins["result"] == "PARTIAL"
        full.append(w)
    else:
        partial.append((w["work_order_no"], qty, exp))
    s = ad.svc  # MES 자체 검증: FAIL이 아니면 출하 가능
    errs = s.validate_shipment(s.ShipmentRegistration("SHP-TEST-%d" % w["work_order_id"], None, date(2026, 11, 6),
                                                       [{"lot_id": lot["lot_id"], "qty": qty}]))
    assert (errs == []) == (exp != "FAIL"), (exp, errs)
assert full, "계획 수량(4개)을 모두 채운 작업지시가 없습니다"
assert partial, "정지로 부분 마감된 작업지시가 없습니다"
assert not [w for w in wos if w["status"] in ("PLANNED", "IN_PROGRESS")], "마감되지 않은 작업지시가 남았습니다"
print(f"완료 {len(done)}건 확인 (계획 수량 채움 {len(full)}건, 정지로 부분 마감 {[(n, q) for n, q, _ in partial]}): "
      "공정 실행 2단계, 완제품 LOT, 시리얼 COMPLETED/SCRAPPED, 검사(불량 수 = 비금속 수), 출하 검증 통과")
for w in canceled:
    assert rows(db, "SELECT COUNT(*) n FROM operation WHERE work_order_id=?", (w["work_order_id"],))[0]["n"] == 0
print(f"리셋으로 취소된 작업지시 {len(canceled)}건: 공정 실행 이력 없음 확인")

# machine_event: io.changed 제외 전부 들어갔는지, 중복이 없는지
exp = [e for e in ev if e["type"] != "io.changed"]
got = rows(db, "SELECT COUNT(*) n, COUNT(DISTINCT event_id) d FROM machine_event")[0]
assert got["n"] == got["d"] == len(exp), (got, len(exp))
linked = rows(db, "SELECT COUNT(*) n FROM machine_event WHERE work_order_id IS NOT NULL")[0]["n"]
print(f"machine_event {got['n']}건 저장 (io.changed 제외), 작업지시와 연결된 이벤트 {linked}건")
for e in ev:      # 같은 이벤트를 다시 넣어도 늘어나지 않는다
    ad.handle(e)
assert rows(db, "SELECT COUNT(*) n FROM machine_event")[0]["n"] == len(exp)
print("같은 이벤트를 다시 넣어도 중복 없음 확인")

# 재고: 블랭크 소비량 = 완료 건수 x 4
rm = rows(db, "SELECT COALESCE(SUM(om.qty),0) q FROM operation_material om JOIN item i ON i.item_id=om.material_item_id WHERE i.item_code='RM-BLANK'")[0]["q"]
exp_rm = sum(rows(db, "SELECT qty FROM operation WHERE work_order_id=? AND routing_step_id=?", (w["work_order_id"], ad.ids["step1"]))[0]["qty"] for w in done)
assert rm == exp_rm, (rm, exp_rm)
print(f"블랭크 소비량 {rm:g}개 = 완료한 작업지시들의 실적 수량 합")

# ---- 시연 데이터 초기화: 거래 데이터는 지우고 기준정보는 남긴다. 이미 처리한 이벤트는 다시 읽지 않는다
last = max(e["seq"] for e in ev)
ad.reset_demo(last)
assert rows(db, "SELECT COUNT(*) n FROM work_order")[0]["n"] == 0 and rows(db, "SELECT COUNT(*) n FROM machine_event")[0]["n"] == 0
assert rows(db, "SELECT COUNT(*) n FROM lot")[0]["n"] == 0 and rows(db, "SELECT COUNT(*) n FROM item")[0]["n"] == 3
assert rows(db, "SELECT COUNT(*) n FROM routing_step")[0]["n"] == 2 and rows(db, "SELECT COUNT(*) n FROM defect_reason_code")[0]["n"] == 1
for e in ev:
    ad.handle(e)  # 지운 뒤 같은 이벤트가 다시 들어와도 아무것도 만들어지면 안 된다
assert rows(db, "SELECT COUNT(*) n FROM work_order")[0]["n"] == 0
print("초기화 확인: 거래 데이터 삭제, 기준정보 유지, 이미 처리한 이벤트는 다시 처리하지 않음")

# ===================================================================== 2) 비금속만 -> FAIL, 출하 자동 차단
mes2 = new_mes()
ad2 = MesAdapter(mes2, batch=3, today=lambda: date(2026, 11, 6), log=lambda m: None)
ad2.init_db(); ad2.seed_master()
for e in simulate("nonmetal", 1500, {20: "M101", 1300: "M102"}):
    ad2.handle(e)
db2 = mes2 / "sql" / "auto_parts.db"
ins = rows(db2, "SELECT i.*, l.lot_no FROM inspection i JOIN lot l USING (lot_id) ORDER BY inspection_id")
assert ins and all(i["result"] == "FAIL" and i["defect_qty"] == i["checked_qty"] for i in ins), ins  # 비금속만이므로 전부 불량
assert sum(1 for i in ins if i["checked_qty"] == 3) >= 2   # 계획 수량(3개)을 채운 묶음 (마지막 묶음은 정지로 부분 마감될 수 있음)
s = ad2.svc
errs = s.validate_shipment(s.ShipmentRegistration("SHP-X", None, date(2026, 11, 6), [{"lot_id": ins[0]["lot_id"], "qty": 3}]))
print("\n비금속만 투입: 검사", [i["result"] for i in ins], "| 출하 검증:", errs[0] if errs else "통과(문제)")
assert errs and "불합격" in errs[0]

# ===================================================================== 3) 어댑터가 켜진 채로 다른 쪽에서 --reset-demo 를 실행한 경우
mes3 = new_mes()
logs3 = []
ad3 = MesAdapter(mes3, batch=3, today=lambda: date(2026, 11, 6), log=logs3.append)
ad3.init_db(); ad3.seed_master()
ev3 = simulate("alternate", 1400, {20: "M101", 1300: "M102"})
half = len(ev3) // 2
for e in ev3[:half]:
    ad3.handle(e)
other = MesAdapter(mes3, batch=3, today=lambda: date(2026, 11, 6), log=lambda m: None)  # 별도 프로세스에서 초기화한 것에 해당
other.reset_demo(ev3[half - 1]["seq"])
for e in ev3[half:]:
    ad3.handle(e)                                  # 여기서 예외가 나면 어댑터가 죽는다
db3 = mes3 / "sql" / "auto_parts.db"
done3 = rows(db3, "SELECT COUNT(*) n FROM work_order WHERE status='COMPLETED'")[0]["n"]
min_seq = rows(db3, "SELECT MIN(seq) m FROM machine_event")[0]["m"]
assert done3 >= 1, "초기화 뒤에도 새 작업지시가 만들어져야 합니다"
assert min_seq > ev3[half - 1]["seq"] - 1, "초기화 이전 이벤트가 다시 들어왔습니다"
assert any("사라져" in l or "불일치" in l for l in logs3), logs3[-3:]
print(f"\n켜진 어댑터 초기화 복구: 예외 없이 이어서 처리, 초기화 이후 작업지시 {done3}건 완료")

print("\n테스트 통과")
