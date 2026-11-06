"""물류 · 출하 구역 시뮬레이터(logistics_sim.LogisticsSim)와 공통 이벤트를 이어 준다.

  프레스 라인의 이벤트 -> 물류 시뮬레이터: 공정 완료(자재 소비), 라인 끝 양품(파렛트에 담기), 라인 정지(모자란 파렛트 마감)
  물류 시뮬레이터 -> 공통 이벤트: lot.received(입고), pallet.stored(완제품 창고에 보관), shipment.dispatched(트럭 출발)
어댑터가 입고는 MES 원자재 입고로, 출하는 MES 출하 관리로 등록한다.
"""
import threading

from line_events import LINE_ID as PRESS_LINE_ID

LINE_ID = "LINE-LOGISTICS-01"
CUSTOMER = "현대파츠"


class LogisticsEventBridge:
    def __init__(self, emitter, sim, lock=None):
        self.em, self.sim = emitter, sim
        self.lock = lock or threading.RLock()
        self.pal = {}            # 시뮬레이터 파렛트 번호 -> 파렛트 번호표 (PL-20261106-0001)
        self.offset = 0.0
        sim.hook = self
        emitter.subscribe(self.on_event)

    def _emit(self, typ, payload, d):
        self.em.emit(typ, payload, source="gateway", line_id=LINE_ID, sim_t=self.offset + d["sim_t"])

    # 프레스 라인의 이벤트 -> 물류
    def on_event(self, e):
        if e.get("line_id") != PRESS_LINE_ID:
            return
        typ, p = e["type"], e["payload"]
        with self.lock:
            if typ == "station.completed":
                self.sim.consume(p["station"])
            elif typ == "piece.exited":
                self.sim.add_exit(e["piece_id"], p["result"])
            elif typ == "machine.state" and p.get("state") == "stopped":
                self.sim.flush()

    # 물류 -> 공통 이벤트 (시뮬레이터가 hook 으로 부른다)
    def __call__(self, kind, d):
        if kind == "received":
            self._emit("lot.received", {"lot_no": self.em.alloc_id("RM"), "item_code": d["item"], "qty": d["qty"], "unit": d["unit"],
                                         "supplier": d["supplier"], "material": d["material"]}, d)
        elif kind == "pallet":
            self.pal[d["id"]] = self.em.alloc_id("PL")
            self._emit("pallet.stored", {"pallet_id": self.pal[d["id"]], "qty": len(d["pieces"]), "pieces": d["pieces"]}, d)
        elif kind == "dispatched":
            self._emit("shipment.dispatched", {
                "shipment_no": self.em.alloc_id("SHP"), "customer": CUSTOMER,
                "pallets": [{"pallet_id": self.pal.pop(p["id"], str(p["id"])), "pieces": p["pieces"]} for p in d["pallets"]]}, d)
        elif kind == "reset":
            self.offset += d["sim_t"]
            self.pal.clear()
