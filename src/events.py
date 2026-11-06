"""PLC 상태 변화를 공통 이벤트(docs/event_schema.json)로 바꾸는 발행기.

server.py의 스캔 루프가 스캔마다 observe(sim.dev)를 부르면, 센서/출력/카운트 변화에서
이벤트를 만들어 메모리(최근 2000개)와 JSONL 파일(logs/events.jsonl)에 쌓습니다.

- tag 이름은 docs/tagmap.csv의 tag_id와 같습니다.
- 사이클 단계(cycle.step)와 piece_id는 PLC가 알려 주는 값이 아니라 센서/출력의 변화로 추정합니다.
- 비금속 작업물의 컨베이어 끝 도착(end_nonmetal)은 컨베이어 가동 시간(약 3초)으로 추정합니다.
"""
import json
import re
import threading
import time
import uuid
from collections import deque
from datetime import datetime, timezone
from pathlib import Path

from workpiece import BELT_SEC_TO_SORT, SORT_T

BELT_TOTAL_S = BELT_SEC_TO_SORT / SORT_T  # 컨베이어 시작 -> 끝 도착 (약 3초)

SENSORS = {
    "X0": "SUP_BWD_LS", "X1": "SUP_FWD_LS", "X2": "DRILL_DN_LS", "X3": "DRILL_UP_LS",
    "X4": "OUT_BWD_LS", "X5": "OUT_FWD_LS", "X6": "EJECT_BWD_LS", "X7": "EJECT_FWD_LS",
    "X8": "MAGAZINE_LOADED", "X9": "SENS_METAL", "X0A": "SENS_NONMETAL",
}
OUTPUTS = {
    "Y20": "SUP_FWD_SOL", "Y21": "SUP_BWD_SOL", "Y22": "DRILL_DN_SOL", "Y23": "OUT_FWD_SOL",
    "Y24": "OUT_BWD_SOL", "Y25": "EJECT_FWD_SOL", "Y26": "EJECT_BWD_SOL", "Y27": "CONVEYOR",
    "Y28": "DRILL_MOTOR", "Y29": "LAMP_RED", "Y2A": "LAMP_YELLOW", "Y2B": "LAMP_GREEN",
}
IO_TAGS = {**SENSORS, **OUTPUTS}
COMMANDS = {  # 장치 -> (command, tag_id)
    "M100": ("start_single", "HMI_START_SINGLE"),
    "M101": ("start_continuous", "HMI_START_CONT"),
    "M102": ("stop", "HMI_STOP"),
    "M103": ("count_reset", "HMI_COUNT_RESET"),
    "X0E": ("reset", "PB_RESET"),
}
WATCH = list(IO_TAGS) + ["D0", "D2", "D4", "D10"]


class EventEmitter:
    def __init__(self, line_id="LINE-MACHINING-01", log_path=None, now=time.time, keep=2000, detector=None):
        self.line_id = line_id
        self.detector = detector  # 사이클 이상 감지기 (anomaly.CycleAnomalyDetector), 없으면 판정하지 않는다
        self.now = now
        self.log_path = Path(log_path) if log_path else None
        self.events = deque(maxlen=keep)
        self._lock = threading.Lock()
        self.seq = 0
        self._piece_no = {}        # 'P-20261106' 같은 접두어와 날짜 -> 마지막 일련번호 (라인마다 접두어가 다르다)
        self._load_tail()
        self.prev = None
        self._last_t = None
        self.continuous = False    # 마지막 시작 명령이 연속인지
        self.cycle = None          # 사이클 진행 중인 작업물 (Y20 상승 ~ X4 복귀)
        self.belt = []             # X5 이후 컨베이어에 있는 작업물
        self.last_nonmetal = None
        self._d10_origin = ("hmi", -10.0)

    # ---- 파일에서 이어 받기 (재시작해도 seq와 일련번호가 이어지게) ----
    def _load_tail(self):
        if not self.log_path or not self.log_path.exists():
            return
        try:
            for line in self.log_path.read_text(encoding="utf-8").splitlines():
                e = json.loads(line)
                self.seq = max(self.seq, e["seq"] + 1)
                m = re.match(r"^([A-Z]+-\d{8})-(\d+)$", e.get("piece_id") or "")
                if m:
                    self._piece_no[m.group(1)] = max(self._piece_no.get(m.group(1), 0), int(m.group(2)))
        except Exception:
            pass

    def alloc_id(self, prefix, t=None):
        """작업물 번호 'P-20261106-0001' 형태를 새로 받는다. 서버를 다시 켜도 이어서 센다."""
        day = time.strftime("%Y%m%d", time.localtime(self.now() if t is None else t))
        key = f"{prefix}-{day}"
        with self._lock:
            self._piece_no[key] = self._piece_no.get(key, 0) + 1
            return f"{key}-{self._piece_no[key]:04d}"

    def _new_piece_id(self, t):
        return {"id": self.alloc_id("P", t), "kind": None,
                "belt_t": 0.0, "ejecting": False, "t0": t, "drill_ds": 0}

    # ---- 이벤트 만들기 ----
    def emit(self, typ, payload, piece_id=None, source="gateway", line_id=None, sim_t=None):
        """다른 라인(프레스·용접·도장 등)이 같은 순번과 파일을 쓰며 이벤트를 내보낼 때 쓴다."""
        return self._emit(typ, payload, self.now(), piece_id, source, line_id, sim_t)

    def _emit(self, typ, payload, t, piece_id=None, source="gateway", line_id=None, sim_t=None):
        iso = datetime.fromtimestamp(t, timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.") + f"{int(t % 1 * 1000):03d}Z"
        with self._lock:   # 서로 다른 스레드(PLC 스캔, 라인 시뮬레이터)가 함께 부르므로 순번 배정부터 잠근다
            e = {"event_id": str(uuid.uuid4()), "ts": iso, "seq": self.seq, "source": source,
                 "line_id": line_id or self.line_id, "type": typ, "piece_id": piece_id, "payload": payload}
            if sim_t is not None:
                e["sim_t"] = round(float(sim_t), 2)   # 시뮬레이터가 흐른 시간(초). 배속과 무관하게 공정 시간을 계산할 때 쓴다
            self.seq += 1
            self.events.append(e)
            if self.log_path:
                try:
                    self.log_path.parent.mkdir(parents=True, exist_ok=True)
                    with self.log_path.open("a", encoding="utf-8") as f:
                        f.write(json.dumps(e, ensure_ascii=False) + "\n")
                except OSError:
                    pass
        return e

    def since(self, after=-1, limit=200):
        with self._lock:
            return [e for e in self.events if e["seq"] > after][:limit]

    # ---- 조작 (server.py가 웹 조작을 받을 때 부른다) ----
    def command(self, dev, origin="web"):
        if dev not in COMMANDS:
            return
        t = self.now()
        cmd, tag = COMMANDS[dev]
        self._emit("command.issued", {"command": cmd, "origin": origin, "tag": tag}, t, source=origin)
        if cmd == "start_continuous":
            self.continuous = True
        elif cmd in ("start_single", "stop", "reset"):
            self.continuous = False
        if cmd == "reset":  # PB4 리셋: 화면의 작업물을 치운 것으로 본다
            self.cycle, self.belt = None, []

    def sim_fault(self, mode, origin="web"):
        """시뮬레이터에 결함을 주입하거나 해제했다는 기록 (이상 감지가 맞는지 확인하는 기준이 된다)."""
        self._emit("sim.fault", {"mode": mode, "origin": origin}, self.now(), source=origin)

    def note_param_origin(self, origin):
        self._d10_origin = (origin, self.now())

    # ---- 스캔마다 호출 ----
    def observe(self, dev):
        t = self.now()
        cur = {k: int(dev[k]) for k in WATCH}
        if self.prev is None:  # 첫 스캔은 기준값으로만 쓴다
            self.prev, self._last_t = cur, t
            return
        prev = self.prev
        dt = min(0.2, max(0.0, t - self._last_t))
        self._last_t, self.prev = t, cur
        rise = lambda k: cur[k] and not prev[k]
        fall = lambda k: prev[k] and not cur[k]
        pid = lambda: self.cycle["id"] if self.cycle else None
        step = lambda s, ev, p=None: self._emit(
            "cycle.step", {"step": s, "evidence": ev}, t, (p or self.cycle or {}).get("id"))

        # 1) 센서/출력의 원본 변화
        for k, tag in IO_TAGS.items():
            if cur[k] != prev[k]:
                self._emit("io.changed", {"tag": tag, "from": prev[k], "to": cur[k]}, t, pid())

        # 2) 사이클 시작과 단계
        if rise("Y20"):
            self.cycle = self._new_piece_id(t)
            self.cycle["drill_ds"] = cur["D10"]
            self.cycle["stage"] = "feed"
            self._emit("cycle.started", {"mode": "continuous" if self.continuous else "single"}, t, pid())
        if self.cycle:
            if rise("Y21"): step("supply_back", "SUP_BWD_SOL")
            if rise("Y28"): step("drill_motor", "DRILL_MOTOR")
            if rise("Y22"): step("drill_down", "DRILL_DN_SOL")
            if rise("X2"): step("drilling", "DRILL_DN_LS")
            if fall("Y22"): step("drill_up", "DRILL_DN_SOL")
            if rise("Y23"): step("out_forward", "OUT_FWD_SOL")
            if rise("Y24"):
                step("out_back", "OUT_BWD_SOL")
                self.cycle["stage"] = "out_back"

        # 3) 분류(센서)와 컨베이어 진입
        for sensor, kind, tag in (("X9", "metal", "SENS_METAL"), ("X0A", "nonmetal", "SENS_NONMETAL")):
            if rise(sensor) and self.cycle and self.cycle["kind"] is None:
                self.cycle["kind"] = kind
                self._emit("piece.classified", {"kind": kind, "sensor": tag}, t, pid())
                if kind == "nonmetal":
                    self.last_nonmetal = self.cycle
        if rise("X5") and self.cycle:
            self.belt.append(self.cycle)
            step("belt", "OUT_FWD_LS")

        # 4) 사이클 종료 (송출 후진 완료)
        if rise("X4") and self.cycle and self.cycle.get("stage") == "out_back":
            self._emit("cycle.completed",
                       {"cycle_time_s": round(t - self.cycle["t0"], 2), "drill_time_set_ds": self.cycle["drill_ds"]},
                       t, pid())
            if self.detector is not None:
                for typ, payload in self.detector.on_cycle(round(t - self.cycle["t0"], 2), self.cycle["drill_ds"]):
                    self._emit(typ, payload, t, pid(), source="ai")
            self.cycle = None

        # 5) 컨베이어 이동 추정, 금속 배출, 비금속 끝 도착
        if cur["Y27"]:
            for p in list(self.belt):
                p["belt_t"] += dt
                if p["kind"] == "nonmetal" and p["belt_t"] >= BELT_TOTAL_S:
                    step("end_nonmetal", "CONVEYOR(추정)", p)
                    self.belt.remove(p)
        if rise("Y25"):
            head = next((p for p in self.belt if p["kind"] == "metal" and not p["ejecting"]), None)
            if head:
                head["ejecting"] = True
                step("eject", "EJECT_FWD_SOL", head)
        if rise("X7"):
            head = next((p for p in self.belt if p["ejecting"]), None)
            if head:
                step("bin_metal", "EJECT_FWD_LS", head)
                self.belt.remove(head)

        # 6) 카운트 변화
        if any(cur[k] != prev[k] for k in ("D0", "D2", "D4")):
            if cur["D0"] == 0 and cur["D2"] == 0 and (prev["D0"] or prev["D2"]):
                reason, who = "count_reset", None
            elif cur["D0"] > prev["D0"]:
                reason = "metal_ejected"
                who = next((p for p in self.belt if p["kind"] == "metal"), None)
            else:
                reason, who = "nonmetal_sensed", self.last_nonmetal
            self._emit("count.updated",
                       {"metal": cur["D0"], "nonmetal": cur["D2"], "total": cur["D4"], "reason": reason},
                       t, who["id"] if who else None)

        # 7) 가공 시간 설정 변경 (D10이 0일 때는 초기화 구간이라 제외)
        if cur["D10"] != prev["D10"] and prev["D10"] != 0:
            origin, ot = self._d10_origin
            if t - ot > 1.0:
                origin = "hmi"
            self._emit("param.changed",
                       {"tag": "DRILL_TIME_SET", "from": prev["D10"], "to": cur["D10"], "unit": "0.1s", "origin": origin},
                       t, source="web" if origin == "web" else "gateway")

        # 8) 운전 상태 (녹색 램프 = 운전 중 M17)
        if rise("Y2B"):
            self._emit("machine.state",
                       {"state": "running_continuous" if self.continuous else "running_single", "reason": "LAMP_GREEN on"}, t)
        elif fall("Y2B"):
            self._emit("machine.state", {"state": "idle", "reason": "LAMP_GREEN off"}, t)
