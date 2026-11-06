"""트윈의 공통 이벤트를 Auto Parts MES(SQLite)에 넣는 어댑터.

흐름:  server.py의 /api/events (또는 logs/events.jsonl)  ->  이 어댑터  ->  MES의 services.py 함수  ->  sql/auto_parts.db

대응 규칙 (docs/mes_integration.md 참고)
  - 작업지시(WO)  : 작업물 N개(기본 5개)를 한 묶음으로 보고 WO 1건을 만든다.
  - 공정 실행     : N개가 모두 가공을 마치면 1단계(DRILL), 모두 분류를 마치면 2단계(SORT)를 각각 1건씩 등록한다.
                    (MES는 WO당 단계별 공정 실행을 1번만 허용하기 때문)
  - 시리얼        : piece_id를 시리얼 번호로 쓴다. 금속=COMPLETED, 비금속=SCRAPPED.
  - 검사          : 완제품 LOT에 FINISHED 검사 1건. 비금속 수 = 불량 수(사유 MAT_MIX, 이종 재질 혼입).
                    불량 0 -> PASS, 일부 -> PARTIAL, 전부 -> FAIL(MES가 출하를 자동 차단).
  - 모든 이벤트   : machine_event 테이블에 보관 (io.changed는 기본적으로 제외, --store-io로 포함).

MES 코드는 수정하지 않고, MES의 services.py 함수를 그대로 불러 씁니다(검증 규칙이 그대로 적용됨).
"""
import argparse
import importlib
import json
import os
import shutil
import sqlite3
import sys
import time
import urllib.request
from datetime import date
from pathlib import Path

HERE = Path(__file__).resolve().parent
TWIN_ROOT = HERE.parent
DEFAULT_MES = Path(os.environ.get("MES_ROOT", TWIN_ROOT.parent / "AutoParts-MES-Arduino"))

PROCESSES = [("DRILL", "드릴 가공"), ("SORT", "분류/배출")]
EQUIPMENT = [("EQ-FEED-01", "공급 실린더", "DRILL"), ("EQ-DRILL-01", "드릴", "DRILL"),
             ("EQ-CONV-01", "컨베이어·배출 실린더", "SORT")]
ITEMS = [("RM-BLANK", "가공용 블랭크", "MATERIAL", "EA"),
         ("SP-DRILLED", "드릴 가공품", "SEMI_PRODUCT", "EA"),
         ("FG-DRILLPART", "가공 부품", "PRODUCT", "EA")]
REASON = ("MAT_MIX", "이종 재질 혼입(비금속)")
FINAL_STEPS = {"bin_metal", "end_nonmetal"}


class MesAdapter:
    def __init__(self, mes_root=DEFAULT_MES, batch=5, auto_next=True, auto_receipt=True,
                 store_io=False, state_path=None, today=date.today, log=print):
        self.root = Path(mes_root).resolve()
        self.db = self.root / "sql" / "auto_parts.db"
        self.batch, self.auto_next, self.auto_receipt = batch, auto_next, auto_receipt
        self.store_io, self.state_path, self.today, self.log = store_io, state_path, today, log
        self.ids = {}
        self.state = {"last_seq": -1, "batches": []}
        self._import_mes()
        self._load_state()

    # ------------------------------------------------------------ MES 불러오기 / DB 준비
    def _import_mes(self):
        if not (self.root / "src" / "services.py").exists():
            raise FileNotFoundError(f"Auto Parts MES 폴더가 아닙니다: {self.root}")
        # MES의 'src' 패키지가 먼저 잡히도록, 트윈 프로젝트 루트는 경로에서 뺀다
        sys.path[:] = [p for p in sys.path if os.path.abspath(p or ".") != str(TWIN_ROOT)]
        if str(self.root) in sys.path:
            sys.path.remove(str(self.root))
        sys.path.insert(0, str(self.root))  # 이미 있어도 맨 앞으로: 다른 MES 폴더의 모듈이 먼저 잡히지 않게
        for name in [m for m in sys.modules if m == "src" or m.startswith("src.")]:
            del sys.modules[name]  # 다른 MES 폴더의 모듈이 남아 있으면 그 폴더의 DB를 쓰게 되므로 새로 불러온다
        self.svc = importlib.import_module("src.services")
        self.q = importlib.import_module("src.queries")

    def _conn(self):
        c = sqlite3.connect(self.db, timeout=10)
        c.row_factory = sqlite3.Row
        c.execute("PRAGMA foreign_keys = ON")
        return c

    def _one(self, sql, params=()):
        c = self._conn()
        try:
            r = c.execute(sql, params).fetchone()
            return r[0] if r else None
        finally:
            c.close()

    def init_db(self, with_sample=False):
        """DB 파일이 없으면 MES의 schema.sql로 만들고, machine_event 테이블을 추가한다."""
        if not self.db.exists():
            c = sqlite3.connect(self.db)
            c.executescript((self.root / "sql" / "schema.sql").read_text(encoding="utf-8"))
            if with_sample:
                c.executescript((self.root / "sql" / "sample_data.sql").read_text(encoding="utf-8"))
            c.commit()
            c.close()
            self.log(f"[MES] DB 생성: {self.db}")
        c = sqlite3.connect(self.db)
        c.executescript((TWIN_ROOT / "mes" / "machine_event.sql").read_text(encoding="utf-8"))
        c.commit()
        c.close()

    def install_addons(self):
        """mes/addons 의 추가 파일(OEE 계산, 설비 현황 페이지)을 MES 폴더로 복사한다. 같은 이름은 덮어쓴다."""
        base = TWIN_ROOT / "mes" / "addons"
        for f in sorted(base.rglob("*")):
            if f.is_file() and "__pycache__" not in f.parts:
                dst = self.root / f.relative_to(base)
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(f, dst)
                self.log(f"[MES] 설치: {dst.relative_to(self.root)}")

    def reset_demo(self, latest_seq):
        """시연 데이터(작업지시, 공정 실행, LOT, 시리얼, 검사, 출하, 설비 이벤트)를 지운다.
        기준정보(품목, 공정, 설비, 라우팅, BOM, 거래처, 불량 사유)와 사용자 계정은 그대로 둔다.
        어댑터는 지금까지의 이벤트를 다시 처리하지 않도록 latest_seq 이후부터 읽는다."""
        c = self._conn()
        try:
            c.execute("BEGIN IMMEDIATE")
            for t in ("machine_event", "shipment_item", "shipment", "inspection", "unit_serial", "operation_material",
                      "operation", "lot", "work_order", "handling_event"):
                try:
                    c.execute(f"DELETE FROM {t}")
                except sqlite3.OperationalError:
                    pass  # 테이블이 없으면 건너뛴다
            c.commit()
        finally:
            c.close()
        self.state = {"last_seq": latest_seq, "batches": []}
        self.save_state()

    def seed_master(self):
        """우리 라인의 기준정보(공정, 설비, 품목, 라우팅, BOM, 불량 사유)를 등록한다. 여러 번 해도 안전."""
        s = self.svc
        for code, name in PROCESSES:
            if not self._one("SELECT 1 FROM process_master WHERE process_code=?", (code,)):
                s.register_process(s.ProcessRegistration(code, name))
        for code, name, proc in EQUIPMENT:
            if not self._one("SELECT 1 FROM equipment WHERE equipment_code=?", (code,)):
                s.register_equipment(s.EquipmentRegistration(code, name, proc))
        for code, name, typ, unit in ITEMS:
            if not self._one("SELECT 1 FROM item WHERE item_code=?", (code,)):
                s.register_item(s.ItemRegistration(code, name, typ, unit))
        for name, typ in (("블랭크 공급사(시연)", "SUPPLIER"), ("고객사(시연)", "CUSTOMER")):
            if not self._one("SELECT 1 FROM partner WHERE partner_name=?", (name,)):
                s.register_partner(s.PartnerRegistration(name, typ))
        if not self._one("SELECT 1 FROM defect_reason_code WHERE reason_code=?", (REASON[0],)):
            s.register_defect_reason_code(s.DefectReasonCodeRegistration(*REASON))

        item = lambda code: self._one("SELECT item_id FROM item WHERE item_code=?", (code,))
        rm, sp, fg = item("RM-BLANK"), item("SP-DRILLED"), item("FG-DRILLPART")
        s.get_or_create_routing(fg, "가공 부품 표준공정")
        rid = self._one("SELECT routing_id FROM routing WHERE product_item_id=?", (fg,))
        if not self._one("SELECT 1 FROM routing_step WHERE routing_id=?", (rid,)):
            s.add_routing_step(s.RoutingStepRegistration(rid, "DRILL", sp))
            s.add_routing_step(s.RoutingStepRegistration(rid, "SORT", fg))
        step = lambda n: self._one("SELECT routing_step_id FROM routing_step WHERE routing_id=? AND step_no=?", (rid, n))
        for sid, mat in ((step(1), rm), (step(2), sp)):
            if not self._one("SELECT 1 FROM bom WHERE routing_step_id=? AND material_item_id=?", (sid, mat)):
                s.add_bom_line(s.BomLineRegistration(sid, mat, 1))
        eq = lambda code: self._one("SELECT equipment_id FROM equipment WHERE equipment_code=?", (code,))
        self.ids = {
            "rm": rm, "sp": sp, "fg": fg, "routing": rid, "step1": step(1), "step2": step(2),
            "eq_drill": eq("EQ-DRILL-01"), "eq_conv": eq("EQ-CONV-01"),
            "supplier": self._one("SELECT partner_id FROM partner WHERE partner_name=?", ("블랭크 공급사(시연)",)),
        }

    # ------------------------------------------------------------ 상태 저장
    def _load_state(self):
        if self.state_path and Path(self.state_path).exists():
            self.state = json.loads(Path(self.state_path).read_text(encoding="utf-8"))

    def save_state(self):
        if self.state_path:
            p = Path(self.state_path)
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(json.dumps(self.state, ensure_ascii=False), encoding="utf-8")

    # ------------------------------------------------------------ 이벤트 처리
    def handle(self, ev):
        if ev["seq"] <= self.state["last_seq"]:
            return
        try:
            self._handle(ev)
        except ValueError as e:  # MES가 검증에서 거절한 경우: 기록만 남기고 계속
            self.log(f"[MES 거절] seq {ev['seq']} {ev['type']}: {str(e).splitlines()[0]}")
        self.state["last_seq"] = ev["seq"]

    def _batch_of(self, pid):
        for b in self.state["batches"]:
            if pid in b["pieces"]:
                return b
        return None

    def _handle(self, ev):
        typ, pid, pl = ev["type"], ev.get("piece_id"), ev["payload"]
        if typ == "command.issued" and pl["command"] == "reset":
            self._abort_open_batches()
        elif typ == "cycle.started" and pid:
            b = self._open_batch()
            if b is not None:
                b["pieces"][pid] = {"kind": None, "done": False, "final": False}
        elif typ == "piece.classified" and pid and self._batch_of(pid):
            self._batch_of(pid)["pieces"][pid]["kind"] = pl["kind"]
        elif typ == "cycle.completed" and pid and self._batch_of(pid):
            b = self._batch_of(pid)
            b["pieces"][pid]["done"] = True
            self._progress(b)
        elif typ == "cycle.step" and pl["step"] in FINAL_STEPS and pid and self._batch_of(pid):
            b = self._batch_of(pid)
            b["pieces"][pid]["final"] = True
            self._progress(b)
        elif typ == "machine.state" and pl["state"] in ("idle", "stopped", "alarm"):
            self._flush_partial()
        self._store(ev)

    def _store(self, ev):
        if ev["type"] == "io.changed" and not self.store_io:
            return
        b = self._batch_of(ev.get("piece_id")) if ev.get("piece_id") else None
        c = self._conn()
        try:
            c.execute(
                "INSERT OR IGNORE INTO machine_event (event_id, seq, ts, source, line_id, event_type, piece_id, work_order_id, payload)"
                " VALUES (?,?,?,?,?,?,?,?,?)",
                (ev["event_id"], ev["seq"], ev["ts"], ev["source"], ev["line_id"], ev["type"], ev.get("piece_id"),
                 b["wo_id"] if b else None, json.dumps(ev["payload"], ensure_ascii=False)))
            c.commit()
        finally:
            c.close()

    # ------------------------------------------------------------ 작업지시 묶음
    @staticmethod
    def _qty(b):
        """이 묶음의 실제 수량. 정지로 부분 마감된 묶음은 계획보다 적을 수 있다."""
        return b.get("qty", b["planned"])

    def _progress(self, b):
        if len(b["pieces"]) != self._qty(b):
            return
        ps = list(b["pieces"].values())
        if all(p["done"] for p in ps):
            self._run_step1(b)
        if all(p["final"] for p in ps):
            self._finalize(b)

    def _flush_partial(self):
        """정지(대기 상태 전환) 시 계획 수량에 못 미친 묶음은 지금까지 만든 수량으로 마감한다."""
        for b in list(self.state["batches"]):
            if not b["closed"] and "qty" not in b and 0 < len(b["pieces"]) < b["planned"]:
                b["qty"] = len(b["pieces"])
                self.log(f"[MES] 정지: {b['wo_no']}를 실적 수량 {b['qty']}개로 마감합니다 (계획 {b['planned']}개)")
                self._progress(b)

    def _open_batch(self):
        """새 작업물을 담을 묶음. 아직 자리가 있는 묶음이 있으면 그것, 없으면 새 작업지시를 만든다."""
        for b in self.state["batches"]:
            if not b["closed"] and len(b["pieces"]) < self._qty(b):
                return b
        if self.state["batches"] and not self.auto_next:
            return None
        s, d = self.svc, self.today()
        n = (self._one("SELECT COUNT(*) FROM work_order WHERE work_order_no LIKE ?", (f"WO-{d:%Y%m%d}-%",)) or 0) + 1
        no = f"WO-{d:%Y%m%d}-{n:03d}"
        r = s.register_work_order(s.WorkOrderRegistration(no, self.ids["fg"], self.ids["routing"], self.batch, d))
        b = {"wo_id": r["work_order_id"], "wo_no": no, "planned": self.batch, "pieces": {},
             "step1_done": False, "closed": False}
        self.state["batches"].append(b)
        self.log(f"[MES] 작업지시 {no} 생성 (계획 {self.batch}개)")
        return b

    def _abort_open_batches(self):
        """PB4 리셋: 공정 실행이 아직 없는 작업지시는 취소하고, 나머지는 그대로 둔다."""
        for b in self.state["batches"]:
            if b["closed"]:
                continue
            if not b["step1_done"]:
                try:
                    self.svc.cancel_work_order(b["wo_id"])
                    self.log(f"[MES] 리셋: 작업지시 {b['wo_no']} 취소")
                except ValueError as e:
                    self.log(f"[MES] 리셋: {b['wo_no']} 취소 불가 - {e}")
            else:
                self.log(f"[MES] 리셋: {b['wo_no']}는 공정 실행 이력이 있어 취소하지 못하고 중단 처리만 합니다")
            b["closed"] = True
        self.state["batches"] = [b for b in self.state["batches"] if not b["closed"]][-20:]

    # ------------------------------------------------------------ 공정 실행 / 완료
    def _material_rows(self, item_id, lot_type, qty):
        s = self.svc
        need, rows = float(qty), []
        for r in sorted(self.q.lots_with_balance_for_item(item_id, lot_type), key=lambda r: r["lot_id"]):
            take = min(float(r["remaining_qty"]), need)
            if take > 0:
                rows.append({"material_item_id": item_id, "material_lot_id": r["lot_id"], "qty": take})
                need -= take
            if need <= 0:
                return rows
        if lot_type == "RECEIPT" and self.auto_receipt:
            d = self.today()
            n = (self._one("SELECT COUNT(*) FROM lot WHERE lot_no LIKE ?", (f"RM-AUTO-{d:%Y%m%d}-%",)) or 0) + 1
            s.register_receipt(s.ReceiptRegistration(item_id, f"RM-AUTO-{d:%Y%m%d}-{n:03d}", d,
                                                     max(need, 5 * self.batch), self.ids["supplier"]))
            self.log(f"[MES] 블랭크 재고 부족 -> 자동 입고 (시연용)")
            return self._material_rows(item_id, lot_type, qty)
        raise ValueError(f"투입할 LOT 재고가 부족합니다 (부족 {need:g})")

    def _run_step1(self, b):
        if b["step1_done"]:
            return
        s, d = self.svc, self.today()
        qty = self._qty(b)
        rows = self._material_rows(self.ids["rm"], "RECEIPT", qty)
        r = s.register_operation(s.OperationRegistration(b["wo_id"], self.ids["step1"], self.ids["eq_drill"],
                                                         d, qty, rows))
        b["step1_done"], b["wip_lot"] = True, r["output_lot_id"]
        self.log(f"[MES] {b['wo_no']} 1단계(드릴 가공) 완료 -> {r['output_lot_no']}")

    def _finalize(self, b):
        self._run_step1(b)
        s, d = self.svc, self.today()
        qty = self._qty(b)
        rows = self._material_rows(self.ids["sp"], "WIP", qty)
        r = s.register_operation(s.OperationRegistration(b["wo_id"], self.ids["step2"], self.ids["eq_conv"],
                                                         d, qty, rows))
        lot_id = r["output_lot_id"]
        metal = [p for p, v in b["pieces"].items() if v["kind"] == "metal"]
        nonmetal = [p for p, v in b["pieces"].items() if v["kind"] != "metal"]
        c = self._conn()
        try:  # 시리얼: 작업물마다 piece_id를 시리얼 번호로 등록
            c.execute("BEGIN IMMEDIATE")
            for pid, v in b["pieces"].items():
                c.execute("INSERT OR IGNORE INTO unit_serial (lot_id, serial_no, status, created_date) VALUES (?,?,?,?)",
                          (lot_id, pid, "COMPLETED" if v["kind"] == "metal" else "SCRAPPED", str(d)))
            c.execute("UPDATE machine_event SET work_order_id=? WHERE piece_id IN (%s)" % ",".join("?" * len(b["pieces"])),
                      (b["wo_id"], *b["pieces"]))
            c.commit()
        finally:
            c.close()
        n, bad = len(b["pieces"]), len(nonmetal)
        result = "PASS" if bad == 0 else ("FAIL" if bad == n else "PARTIAL")
        s.register_inspection(s.InspectionRegistration(
            lot_id, "FINISHED", d, n, bad, result, REASON[0] if bad else None,
            f"비금속 {bad}개 (X0A 감지)" if bad else None))
        b["closed"] = True
        self.log(f"[MES] {b['wo_no']} 완료 -> {r['output_lot_no']} | 금속 {len(metal)} / 비금속 {bad} | 검사 {result}")
        self.state["batches"] = [x for x in self.state["batches"] if not x["closed"]]


# ---------------------------------------------------------------- 이벤트 가져오기
def fetch_http(base, after, limit=500):
    with urllib.request.urlopen(f"{base}/api/events?after={after}&limit={limit}", timeout=5) as r:
        return json.loads(r.read().decode("utf-8"))


def fetch_file(path, after, limit=500):
    out = []
    p = Path(path)
    if p.exists():
        for line in p.read_text(encoding="utf-8").splitlines():
            e = json.loads(line)
            if e["seq"] > after:
                out.append(e)
                if len(out) >= limit:
                    break
    return out


def latest_seq(fetch):
    """이벤트 출처에서 가장 큰 seq를 찾는다 (없으면 -1)."""
    after = -1
    while True:
        evs = fetch(after)
        if not evs:
            return after
        after = evs[-1]["seq"]


def main():
    ap = argparse.ArgumentParser(description="트윈 이벤트 -> Auto Parts MES 어댑터")
    ap.add_argument("--mes", default=str(DEFAULT_MES), help="Auto Parts MES 폴더 (기본: 형제 폴더 AutoParts-MES-Arduino)")
    ap.add_argument("--url", default="http://127.0.0.1:5001", help="트윈 서버 주소")
    ap.add_argument("--file", help="서버 대신 logs/events.jsonl 파일에서 읽기")
    ap.add_argument("--batch", type=int, default=5, help="작업지시 1건당 작업물 수")
    ap.add_argument("--no-auto-next", action="store_true", help="첫 작업지시만 처리하고 다음 작업지시는 만들지 않음")
    ap.add_argument("--no-auto-receipt", action="store_true", help="블랭크 재고가 모자라도 자동 입고하지 않음")
    ap.add_argument("--store-io", action="store_true", help="io.changed(센서/출력 변화)도 machine_event에 저장")
    ap.add_argument("--with-sample", action="store_true", help="DB를 새로 만들 때 MES 샘플 데이터도 넣기")
    ap.add_argument("--install-addons", action="store_true", help="설비 현황/OEE 페이지를 MES 폴더에 복사하고 종료")
    ap.add_argument("--reset-demo", action="store_true",
                    help="시연 데이터(작업지시, LOT, 시리얼, 검사, 설비 이벤트)를 지우고 지금부터 새로 시작")
    ap.add_argument("--init-only", action="store_true", help="DB와 기준정보만 준비하고 종료")
    ap.add_argument("--once", action="store_true", help="한 번만 가져와서 처리하고 종료")
    ap.add_argument("--reset-state", action="store_true", help="저장된 처리 위치를 지우고 처음부터")
    ap.add_argument("--state", default=str(TWIN_ROOT / "logs" / "mes_adapter_state.json"), help="처리 위치 저장 파일")
    ap.add_argument("--interval", type=float, default=1.0)
    a = ap.parse_args()

    state_path = Path(a.state)
    if a.reset_state and state_path.exists():
        state_path.write_text('{"last_seq": -1, "batches": []}', encoding="utf-8")
    ad = MesAdapter(a.mes, a.batch, not a.no_auto_next, not a.no_auto_receipt, a.store_io, state_path)
    if a.install_addons:
        ad.install_addons()
        return
    ad.init_db(a.with_sample)
    ad.seed_master()
    if a.reset_demo:
        src0 = (lambda after: fetch_file(a.file, after, 100000)) if a.file else (lambda after: fetch_http(a.url, after, 1000))
        if input("MES의 작업지시, 공정 실행, LOT, 시리얼, 검사, 출하, 설비 이벤트를 모두 지웁니다. 계속할까요? (y/N) ").strip().lower() != "y":
            print("취소했습니다.")
            return
        try:
            last = latest_seq(src0)
        except Exception as e:
            print(f"[트윈 서버에 연결하지 못했습니다] {e}\n서버를 켠 뒤 다시 실행하세요 (이미 처리한 이벤트를 다시 읽지 않기 위해 필요합니다).")
            return
        ad.reset_demo(last)
        print(f"[MES] 시연 데이터를 지웠습니다. 이벤트 {last}번 이후부터 새로 처리합니다.")
        return
    print(f"[MES] 준비 완료: {ad.db}")
    if a.init_only:
        return
    src = (lambda after: fetch_file(a.file, after)) if a.file else (lambda after: fetch_http(a.url, after))
    print("[MES] 이벤트를 기다리는 중... (Ctrl+C로 종료)")
    while True:
        try:
            evs = src(ad.state["last_seq"])
        except Exception as e:
            print(f"[이벤트 읽기 실패] {e}")
            evs = []
        for e in evs:
            ad.handle(e)
        if evs:
            ad.save_state()
        if a.once:
            break
        time.sleep(a.interval)


if __name__ == "__main__":
    main()
