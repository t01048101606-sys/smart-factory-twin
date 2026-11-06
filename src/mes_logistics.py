"""물류 · 출하 구역의 이벤트를 Auto Parts MES(SQLite)에 넣는다 (mes_adapter.MesAdapter 가 사용).

  lot.received          -> MES 원자재 입고 (RECEIPT LOT). 이벤트의 lot_no, 품목, 수량, 공급업체 그대로.
  shipment.dispatched   -> MES 출하 등록. 파렛트에 담긴 작업물 번호(시리얼)로 완제품 LOT 를 찾고, LOT 별 수량으로 출하한다.
                           고객사는 현대파츠. FAIL(불합격) LOT 는 MES 의 출하 검증이 막는다.
  pallet.stored         -> machine_event 에만 보관

출하 시점에 아직 MES 가 그 작업물들의 완제품 LOT 를 만들지 못했으면(같은 묶음의 마지막 작업물이 아직 라인 끝에 도착하지 않음),
출하를 보류해 두었다가 완제품 LOT 가 만들어질 때 다시 시도한다 (state 의 pending_shipments, 재시작해도 이어짐).
"""
MAX_ATTEMPTS = 400    # 그 이상 못 찾으면(예: MES 데이터를 지운 뒤) 버린다


class LogisticsMes:
    def __init__(self, adapter):
        self.a = adapter

    @property
    def pending(self):
        return self.a.state.setdefault("pending_shipments", [])

    def handle(self, ev):
        self.a.press.ensure()     # 품목, 거래처 같은 기준정보 (프레스 라인과 같은 구성)
        typ, p = ev["type"], ev["payload"]
        if typ == "lot.received":
            self._receive(p)
        elif typ == "shipment.dispatched":
            self.pending.append({"payload": p, "attempts": 0})
            self.retry()

    def _receive(self, p):
        a, s = self.a, self.a.svc
        item = a._one("SELECT item_id FROM item WHERE item_code=?", (p["item_code"],))
        supplier = a._one("SELECT partner_id FROM partner WHERE partner_name=?", (p["supplier"],))
        if item is None:
            a.log(f"[MES 거절] (물류) 알 수 없는 품목 {p['item_code']}")
            return
        try:
            s.register_receipt(s.ReceiptRegistration(item, p["lot_no"], a.today(), p["qty"], supplier))
            a.log(f"[MES] (물류) 입고 {p['lot_no']} {p['item_code']} {p['qty']:g}{p['unit']} ({p['supplier']})")
        except ValueError as e:     # 이미 등록된 LOT 번호 등
            a.log(f"[MES 거절] (물류) 입고 {p['lot_no']}: {str(e).splitlines()[0]}")

    def retry(self):
        """보류 중인 출하를 다시 시도한다. 완제품 LOT 가 아직 없으면 계속 보류."""
        keep = []
        for item in self.pending:
            item["attempts"] += 1
            done = self._ship(item["payload"])
            if not done and item["attempts"] < MAX_ATTEMPTS:
                keep.append(item)
            elif not done:
                self.a.log(f"[MES] (물류) 출하 {item['payload']['shipment_no']}: 완제품 LOT 를 찾지 못해 버립니다")
        self.a.state["pending_shipments"] = keep

    def _ship(self, p):
        """출하를 등록하면 True(성공 또는 MES 가 거절해서 더 시도할 필요 없음), 완제품 LOT 를 아직 못 찾으면 False."""
        a, s = self.a, self.a.svc
        pieces = [pc for pal in p["pallets"] for pc in pal["pieces"]]
        c = a._conn()
        try:
            found = dict(c.execute("SELECT serial_no, lot_id FROM unit_serial WHERE serial_no IN (%s)" % ",".join("?" * len(pieces)), pieces).fetchall())
        finally:
            c.close()
        if len(found) < len(pieces):
            return False
        per_lot = {}
        for pc in pieces:
            per_lot[found[pc]] = per_lot.get(found[pc], 0) + 1
        customer = a._one("SELECT partner_id FROM partner WHERE partner_name=?", (p["customer"],))
        try:
            s.register_shipment(s.ShipmentRegistration(p["shipment_no"], customer, a.today(),
                                                       [{"lot_id": lot, "qty": float(q)} for lot, q in sorted(per_lot.items())]))
            a.log(f"[MES] (물류) 출하 {p['shipment_no']} -> {p['customer']} | LOT {len(per_lot)}개, 작업물 {len(pieces)}개")
        except ValueError as e:     # 예: 불합격(FAIL) LOT 는 출하할 수 없다
            a.log(f"[MES 거절] (물류) 출하 {p['shipment_no']}: {str(e).splitlines()[0]}")
        return True
