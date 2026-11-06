"""프레스 -> 용접 -> 도장 라인의 이벤트를 Auto Parts MES(SQLite)에 넣는다 (mes_adapter.MesAdapter 가 사용).

MES 샘플 데이터와 같은 구성: 제품 FG-BRKA(브라켓 A), 라우팅 PRESS -> WELD -> PAINT, 냉연강판/볼트/도료 BOM.
작업물 N개(기본 5개)를 작업지시 1건으로 묶고, 그 N개가 한 공정을 모두 마칠 때마다 그 단계의 공정 실행을 1건씩 등록한다.
  - 1단계 PRESS  : 냉연강판(RM-STEEL)을 소비 -> 반제품 LOT SP-BRKA-PRS
  - 2단계 WELD   : 볼트(RM-BOLT)와 반제품 SP-BRKA-PRS 를 소비 -> 반제품 LOT SP-BRKA-WLD
  - 3단계 PAINT  : 도료(RM-PAINT)와 반제품 SP-BRKA-WLD 를 소비 -> 완제품 LOT FG-BRKA
  - 라인 끝: 시리얼(작업물 번호) 부여, 용접 불량은 SCRAPPED, 완제품 LOT 검사 (불량 사유 WELD_CRACK)
소비하는 자재는 MES의 BOM(단계별 자재와 단위당 수량)에서 읽는다. 반제품 줄이 BOM에 없으면 처음에 추가해서 LOT 추적이 끊기지 않게 한다.
"""
from line_events import LINE_ID

STEPS = (("press", "PRESS"), ("weld", "WELD"), ("paint", "PAINT"))   # (이벤트의 공정 이름, MES 공정 코드)
PROCESSES = [("PRESS", "프레스"), ("WELD", "용접"), ("PAINT", "도장")]
EQUIPMENT = [("EQ-PRESS-01", "프레스기 1호", "PRESS"), ("EQ-WELD-01", "용접기 1호", "WELD"), ("EQ-PAINT-01", "도장기 1호", "PAINT")]
ITEMS = [("RM-STEEL", "냉연강판 1.2T", "MATERIAL", "KG"), ("RM-BOLT", "육각볼트 M8", "MATERIAL", "EA"),
         ("RM-PAINT", "전착도료", "MATERIAL", "L"), ("SP-BRKA-PRS", "브라켓A-프레스품", "SEMI_PRODUCT", "EA"),
         ("SP-BRKA-WLD", "브라켓A-용접품", "SEMI_PRODUCT", "EA"), ("FG-BRKA", "브라켓 A", "PRODUCT", "EA")]
PARTNERS = [("한국제철", "SUPPLIER"), ("대한볼트산업", "SUPPLIER"), ("삼성도료", "SUPPLIER"), ("현대파츠", "CUSTOMER")]
ROUTING = [("PRESS", "SP-BRKA-PRS"), ("WELD", "SP-BRKA-WLD"), ("PAINT", "FG-BRKA")]                 # (공정, 출력 품목)
BOM = {1: [("RM-STEEL", 0.5)], 2: [("RM-BOLT", 4), ("SP-BRKA-PRS", 1)], 3: [("RM-PAINT", 0.05), ("SP-BRKA-WLD", 1)]}
REASON = ("WELD_CRACK", "용접 균열")


class PressLineMes:
    def __init__(self, adapter, batch=5):
        self.a, self.batch, self.ids, self.ready = adapter, batch, {}, False

    # ------------------------------------------------------------ 기준정보 (MES 샘플 데이터와 같은 구성, 여러 번 해도 안전)
    def ensure(self):
        if self.ready:
            return
        a, s = self.a, self.a.svc
        for code, name in PROCESSES:
            if not a._one("SELECT 1 FROM process_master WHERE process_code=?", (code,)):
                s.register_process(s.ProcessRegistration(code, name))
        for code, name, proc in EQUIPMENT:
            if not a._one("SELECT 1 FROM equipment WHERE equipment_code=?", (code,)):
                s.register_equipment(s.EquipmentRegistration(code, name, proc))
        for code, name, typ, unit in ITEMS:
            if not a._one("SELECT 1 FROM item WHERE item_code=?", (code,)):
                extra = {"drawing_no": "DWG-BRKA-001", "drawing_rev": "Rev.C", "material_spec": "SPCC 1.2T",
                         "tolerance_note": "±0.1mm"} if code == "FG-BRKA" else {}
                s.register_item(s.ItemRegistration(code, name, typ, unit, **extra))
        for name, typ in PARTNERS:
            if not a._one("SELECT 1 FROM partner WHERE partner_name=?", (name,)):
                s.register_partner(s.PartnerRegistration(name, typ))
        if not a._one("SELECT 1 FROM defect_reason_code WHERE reason_code=?", (REASON[0],)):
            s.register_defect_reason_code(s.DefectReasonCodeRegistration(*REASON))
        item = lambda code: a._one("SELECT item_id FROM item WHERE item_code=?", (code,))
        fg = item("FG-BRKA")
        s.get_or_create_routing(fg, "브라켓A 표준공정")
        rid = a._one("SELECT routing_id FROM routing WHERE product_item_id=?", (fg,))
        if not a._one("SELECT 1 FROM routing_step WHERE routing_id=?", (rid,)):
            for proc, out in ROUTING:
                s.add_routing_step(s.RoutingStepRegistration(rid, proc, item(out)))
        step = lambda n: a._one("SELECT routing_step_id FROM routing_step WHERE routing_id=? AND step_no=?", (rid, n))
        for n, lines in BOM.items():
            for code, qty in lines:
                if not a._one("SELECT 1 FROM bom WHERE routing_step_id=? AND material_item_id=?", (step(n), item(code))):
                    s.add_bom_line(s.BomLineRegistration(step(n), item(code), qty))
        self.ids = {"fg": fg, "routing": rid, "step": {k: step(k) for k in (1, 2, 3)},
                    "equipment": {proc: a._one("SELECT equipment_id FROM equipment WHERE equipment_code=?", (code,))
                                  for code, _, proc in EQUIPMENT}}
        self.ready = True

    # ------------------------------------------------------------ 상태 (어댑터의 state JSON 에 저장되어 재시작해도 이어진다)
    @property
    def batches(self):
        return self.a.state.setdefault("press_batches", [])

    def batch_of(self, pid):
        return next((b for b in self.batches if pid in b["pieces"]), None)

    @staticmethod
    def _qty(b):
        return b.get("qty", b["planned"])

    def drop_stale(self):
        """MES 에서 작업지시가 지워졌으면(--reset-demo 등) 그 작업지시에 묶인 진행 상태를 버린다."""
        if not self.batches:
            return
        c = self.a._conn()
        try:
            ids = [b["wo_id"] for b in self.batches]
            alive = {r[0] for r in c.execute("SELECT work_order_id FROM work_order WHERE work_order_id IN (%s)" % ",".join("?" * len(ids)), ids)}
        finally:
            c.close()
        kept = [b for b in self.batches if b["wo_id"] in alive]
        if len(kept) < len(self.batches):
            self.a.log(f"[MES] (프레스 라인) 작업지시 {len(self.batches) - len(kept)}건이 DB에서 사라져 진행 상태를 버립니다")
            self.a.state["press_batches"] = kept

    # ------------------------------------------------------------ 이벤트 처리
    def handle(self, ev):
        self.ensure()
        self.drop_stale()
        typ, pid, pl = ev["type"], ev.get("piece_id"), ev["payload"]
        if typ == "cycle.started" and pid:
            b = self._open_batch()
            b["pieces"][pid] = {"done": [], "result": None, "defect": False}
        elif typ == "station.completed" and pid and self.batch_of(pid):
            b = self.batch_of(pid)
            b["pieces"][pid]["done"].append(pl["station"])
            if pl["station"] == "weld":
                b["pieces"][pid]["defect"] = bool(pl.get("defect"))
            self._progress(b)
        elif typ == "piece.exited" and pid and self.batch_of(pid):
            b = self.batch_of(pid)
            b["pieces"][pid]["result"] = pl["result"]
            self._progress(b)
        elif typ == "machine.state":
            if pl.get("reason") == "reset":
                self._abort()
            elif pl.get("reason") == "drain" or pl["state"] == "stopped":   # 투입이 끝났으니 계획 수량에 못 미친 묶음은 지금 수량으로 마감
                self._flush_partial()

    def _open_batch(self):
        for b in self.batches:
            if not b["closed"] and len(b["pieces"]) < self._qty(b):
                return b
        a, s, d = self.a, self.a.svc, self.a.today()
        n = (a._one("SELECT COUNT(*) FROM work_order WHERE work_order_no LIKE ?", (f"WO-{d:%Y%m%d}-%",)) or 0) + 1
        no = f"WO-{d:%Y%m%d}-{n:03d}"
        r = s.register_work_order(s.WorkOrderRegistration(no, self.ids["fg"], self.ids["routing"], self.batch, d))
        b = {"wo_id": r["work_order_id"], "wo_no": no, "planned": self.batch, "pieces": {}, "ops": [], "closed": False}
        self.batches.append(b)
        a.log(f"[MES] (프레스 라인) 작업지시 {no} 생성 (계획 {self.batch}개)")
        return b

    def _flush_partial(self):
        for b in list(self.batches):
            if not b["closed"] and "qty" not in b and 0 < len(b["pieces"]) < b["planned"]:
                b["qty"] = len(b["pieces"])
                self.a.log(f"[MES] (프레스 라인) 정지: {b['wo_no']}를 실적 수량 {b['qty']}개로 마감합니다 (계획 {b['planned']}개)")
                self._progress(b)

    def _abort(self):
        for b in self.batches:
            if b["closed"]:
                continue
            if not b["ops"]:
                try:
                    self.a.svc.cancel_work_order(b["wo_id"])
                    self.a.log(f"[MES] (프레스 라인) 리셋: 작업지시 {b['wo_no']} 취소")
                except ValueError as e:
                    self.a.log(f"[MES] (프레스 라인) 리셋: {b['wo_no']} 취소 불가 - {e}")
            else:
                self.a.log(f"[MES] (프레스 라인) 리셋: {b['wo_no']}는 공정 실행 이력이 있어 중단 처리만 합니다")
            b["closed"] = True
        self.a.state["press_batches"] = [b for b in self.batches if not b["closed"]]

    # ------------------------------------------------------------ 공정 실행과 완료
    def _progress(self, b):
        if len(b["pieces"]) != self._qty(b):
            return
        ps = list(b["pieces"].values())
        for n, (station, _) in enumerate(STEPS, start=1):
            if n not in b["ops"] and all(station in p["done"] for p in ps):
                self._run_op(b, n)
        if len(b["ops"]) == 3 and all(p["result"] for p in ps):
            self._finalize(b)

    def _run_op(self, b, n):
        a, s = self.a, self.a.svc
        qty, step_id = self._qty(b), self.ids["step"][n]
        c = a._conn()
        try:   # 소비할 자재는 MES의 BOM(단계별 자재, 단위당 수량)에서 읽는다
            bom = c.execute("SELECT b.material_item_id, b.qty_per_unit, i.item_type FROM bom b JOIN item i ON i.item_id = b.material_item_id "
                            "WHERE b.routing_step_id = ? ORDER BY b.bom_id", (step_id,)).fetchall()
        finally:
            c.close()
        rows = []
        for r in bom:
            rows += a._material_rows(r["material_item_id"], "WIP" if r["item_type"] == "SEMI_PRODUCT" else "RECEIPT", r["qty_per_unit"] * qty)
        proc = STEPS[n - 1][1]
        res = s.register_operation(s.OperationRegistration(b["wo_id"], step_id, self.ids["equipment"][proc], a.today(), qty, rows))
        b["ops"].append(n)
        b["last_lot"] = res["output_lot_id"]
        b["last_lot_no"] = res["output_lot_no"]
        a.log(f"[MES] (프레스 라인) {b['wo_no']} {n}단계({proc}) 완료 -> {res['output_lot_no']}")

    def _finalize(self, b):
        a, s, d = self.a, self.a.svc, self.a.today()
        lot_id, qty = b["last_lot"], self._qty(b)
        bad = [p for p, v in b["pieces"].items() if v["result"] == "scrap"]
        c = a._conn()
        try:
            c.execute("BEGIN IMMEDIATE")
            for pid, v in b["pieces"].items():
                c.execute("INSERT OR IGNORE INTO unit_serial (lot_id, serial_no, status, created_date) VALUES (?,?,?,?)",
                          (lot_id, pid, "SCRAPPED" if v["result"] == "scrap" else "COMPLETED", str(d)))
            c.execute("UPDATE machine_event SET work_order_id=? WHERE piece_id IN (%s)" % ",".join("?" * len(b["pieces"])),
                      (b["wo_id"], *b["pieces"]))
            c.commit()
        finally:
            c.close()
        result = "PASS" if not bad else ("FAIL" if len(bad) == qty else "PARTIAL")
        s.register_inspection(s.InspectionRegistration(lot_id, "FINISHED", d, qty, len(bad), result,
                                                       REASON[0] if bad else None, f"용접 불량 {len(bad)}개" if bad else None))
        b["closed"] = True
        a.log(f"[MES] (프레스 라인) {b['wo_no']} 완료 -> {b['last_lot_no']} | 양품 {qty - len(bad)} / 불량 {len(bad)} | 검사 {result}")
        a.state["press_batches"] = [x for x in self.batches if not x["closed"]]
        a.logi.retry()      # 이 묶음의 완제품 LOT 가 생겼으니, 기다리던 출하가 있으면 다시 시도
