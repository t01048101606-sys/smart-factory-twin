"""작업물(워크) 위치 추적기.

PLC는 작업물 위치를 직접 알려 주지 않으므로, 실린더·센서·컨베이어 신호의 변화로
작업물이 어느 단계에 있는지 추정한다. (실제 PLC/OpenPLC에서도 같은 디바이스를 읽어 쓸 수 있음)

단계: feed(공급 중) -> drill(가공 위치) -> out(송출 중) -> belt(컨베이어)
      -> eject(금속 배출 중) -> binm(금속 박스) / end(비금속, 컨베이어 끝)
"""
DT = 0.05            # 스캔 1회 = 50 ms
SORT_T = 0.5         # 컨베이어에서 분류(배출) 위치 (0~1)
BELT_SEC_TO_SORT = 1.5  # 컨베이어 시작 -> 분류 위치 도달 시간
LINGER = 40          # 박스/끝에 도착한 뒤 화면에 남아 있는 스캔 수 (약 2초)


class Tracker:
    def __init__(self):
        self.pieces = []
        self.prev = {}

    def _rise(self, d, k):
        return bool(d[k]) and not self.prev.get(k, 0)

    def update(self, d):
        if self._rise(d, "X0E"):  # PB4 리셋: 작업물을 치운 것으로 본다
            self.pieces.clear()
        if self._rise(d, "Y20"):
            self.pieces.append({"stage": "feed", "t": 0.0, "metal": False, "age": 0})
        for p in list(self.pieces):
            st = p["stage"]
            if st == "feed":
                if d["Y20"]:
                    p["t"] = min(1.0, p["t"] + DT / 0.3)
                if d["X1"]:
                    p["stage"], p["t"] = "drill", 0.0
            elif st == "drill":
                if d["Y23"]:
                    p["stage"], p["t"] = "out", 0.0
            elif st == "out":
                if d["Y23"]:
                    p["t"] = min(1.0, p["t"] + DT / 0.3)
                if d["X5"]:
                    p["stage"], p["t"], p["metal"] = "belt", 0.0, bool(d["X9"])
            elif st == "belt":
                if d["Y27"]:
                    p["t"] += DT * SORT_T / BELT_SEC_TO_SORT
                if p["metal"] and p["t"] >= SORT_T:
                    p["t"] = SORT_T
                    if d["Y25"]:
                        p["stage"], p["t"] = "eject", 0.0
                elif p["t"] >= 1.0:
                    p["stage"], p["t"], p["age"] = "end", 1.0, 0
            elif st == "eject":
                if d["Y25"]:
                    p["t"] = min(1.0, p["t"] + DT / 0.3)
                if d["X7"] or p["t"] >= 1.0:
                    p["stage"], p["t"], p["age"] = "binm", 1.0, 0
            elif st in ("binm", "end"):
                p["age"] += 1
                if p["age"] > LINGER:
                    self.pieces.remove(p)
        self.prev = {k: int(d[k]) for k in ("Y20", "X0E")}

    def snapshot(self):
        return [{"stage": p["stage"], "t": round(p["t"], 3), "metal": p["metal"]} for p in self.pieces]
