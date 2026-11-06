"""협동로봇 팔레타이징 셀(cobot_sim.CobotSim)과 공통 이벤트를 이어 준다.

  프레스 라인의 이벤트 -> 셀: 라인 끝 작업물(piece.exited)이 인피드에 올라온다, 라인이 정지하면 모자란 파렛트를 마감하게 한다
  셀 -> 공통 이벤트: vision.inspected(비전 검사), cobot.placed(파렛트 또는 NG 수납함에 놓음), cobot.pallet_closed(파렛트 완성)
물류 구역은 cobot.pallet_closed 로 파렛트를 만든다 (logistics_events.LogisticsEventBridge(from_cobot=True)).
"""
import threading

from line_events import LINE_ID as PRESS_LINE_ID

LINE_ID = "LINE-COBOT-01"


class CobotEventBridge:
    def __init__(self, emitter, sim, lock=None):
        self.em, self.sim = emitter, sim
        self.lock = lock or threading.RLock()
        self.offset = 0.0
        sim.hook = self
        emitter.subscribe(self.on_event)

    def _emit(self, typ, payload, d, piece_id=None):
        self.em.emit(typ, payload, piece_id=piece_id, source="gateway", line_id=LINE_ID, sim_t=self.offset + d["sim_t"])

    # 프레스 라인의 이벤트 -> 셀
    def on_event(self, e):
        if e.get("line_id") != PRESS_LINE_ID:
            return
        typ, p = e["type"], e["payload"]
        with self.lock:
            if typ == "piece.exited":
                self.sim.add_part(e["piece_id"], p["result"])
            elif typ == "machine.state" and p.get("state") == "stopped":
                self.sim.request_flush()

    # 셀 -> 공통 이벤트 (시뮬레이터가 hook 으로 부른다)
    def __call__(self, kind, d):
        if kind == "inspected":
            self._emit("vision.inspected", {"result": d["result"], "confidence": d["conf"]}, d, d["id"])
        elif kind == "placed":
            self._emit("cobot.placed", {"target": d["target"], "slot": d["slot"], "cycle_s": d["cycle_s"]}, d, d["id"])
        elif kind == "pallet_closed":
            self._emit("cobot.pallet_closed", {"pieces": d["pieces"], "partial": d["partial"]}, d)
        elif kind == "reset":
            self.offset += d["sim_t"]
