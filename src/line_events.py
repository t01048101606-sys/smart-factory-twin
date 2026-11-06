"""프레스·용접·도장 라인 시뮬레이터(line_sim.LineSim)의 변화를 공통 이벤트로 내보낸다.

LineSim.hook 에 이 객체를 걸면, 부품 투입, 공정 완료, 공정 상태 변화, 라인 완료(양품/불량), 시작/정지/리셋, 결함 주입이
공통 이벤트(docs/event_schema.json)로 바뀌어 가공 라인과 같은 순번과 파일(logs/events.jsonl)에 쌓인다.
어댑터가 이 이벤트로 MES의 작업지시, 공정 실행, LOT, 시리얼, 검사를 만들고, MES 화면이 OEE를 계산한다.

이벤트의 sim_t 는 시뮬레이터가 흐른 시간(초)이다. 배속(x1~x8)을 올려도 공정 시간 계산이 맞도록 ts(실제 시각) 대신 이것을 쓴다.
"""
LINE_ID = "LINE-PRESS-WELD-PAINT-01"


class LineEventBridge:
    def __init__(self, emitter, line_id=LINE_ID):
        self.em, self.line_id = emitter, line_id
        self.pid = {}          # 시뮬레이터 부품 번호 -> 작업물 번호 (B-20261106-0001)
        self.offset = 0.0      # 리셋해도 sim_t 가 계속 늘어나게 하는 보정값

    def _emit(self, typ, payload, d, piece_id=None, source="gateway"):
        self.em.emit(typ, payload, piece_id=piece_id, source=source, line_id=self.line_id, sim_t=self.offset + d["sim_t"])

    def __call__(self, kind, d):
        if kind == "spawn":
            self.pid[d["id"]] = self.em.alloc_id("B")
            self._emit("cycle.started", {"mode": "continuous"}, d, self.pid[d["id"]])
        elif kind == "completed" and d["id"] in self.pid:
            payload = {"station": d["station"], "duration_s": d["duration_s"], "nominal_s": d["nominal_s"]}
            if "defect" in d:
                payload["defect"] = d["defect"]
            self._emit("station.completed", payload, d, self.pid[d["id"]])
        elif kind == "exit" and d["id"] in self.pid:
            self._emit("piece.exited", {"result": d["result"]}, d, self.pid.pop(d["id"]))
        elif kind == "state":
            self._emit("station.state", {"station": d["station"], "from": d["frm"], "to": d["to"]}, d)
        elif kind == "running":
            self._emit("machine.state", {"state": "running_continuous" if d["on"] else "stopped",
                                         "reason": "line start" if d["on"] else "line stop"}, d)
        elif kind == "drain":   # 정지 요청: 새 투입은 멈췄지만 라인에 남은 부품이 다 나올 때까지는 계속 가동 중이다
            self._emit("machine.state", {"state": "running_continuous", "reason": "drain"}, d)
        elif kind == "fault":
            self._emit("sim.fault", {"mode": d["mode"], "origin": "web"}, d, source="web")
        elif kind == "reset":
            self._emit("machine.state", {"state": "idle", "reason": "reset"}, d)
            self.pid.clear()
            self.offset += d["sim_t"]
