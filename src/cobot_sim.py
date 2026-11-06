"""협동로봇 팔레타이징 셀 시뮬레이터 (라인 끝 -> 비전 검사 -> 로봇이 집기 -> 양품은 파렛트 적재, 불량은 NG 수납함).

흐름
  프레스 라인 끝의 작업물(양품, 불량) -> 인피드 컨베이어 -> 정지 블록에서 멈춤 -> 비전 카메라 검사(1초)
  -> 로봇이 집어서 양품은 파렛트 칸(5칸)에, 불량은 NG 수납함에 놓음 -> 파렛트가 차면 물류 구역으로 넘김 (pallet_closed)
  라인이 멈춘 뒤 셀이 다 비면 모자란 파렛트도 마감한다 (flush).

로봇팔: 어깨 관절(위치 고정)에서 yaw(좌우), shoulder, elbow, wrist(위아래) 4관절 + 그리퍼. 집는 위치, 파렛트 칸, NG 상자 위치는
역기구학(ik)으로 관절 각도를 구하고, 3D 장면은 state()의 arm 각도를 그대로 쓴다. 장면 JSON(tools/make_cobot_scene.py)의 치수와 같다.
시뮬레이터가 알려 주는 장면 좌표는 모두 셀 기준 좌표(factory.json 의 offset 으로 공장에 놓임)다.
"""
import math
import zlib

ARM = {"base": (0.0, 1.6, 0.0), "L1": 3.2, "L2": 3.0, "L3": 1.3}      # 어깨 위치, 윗팔, 아랫팔, 손목에서 그리퍼 끝까지
PICK = (-3.55, 0.93, 0.0)                                               # 집는 위치 (워크 중심, 인피드 끝 정지 블록 앞)
SLOTS = [(2.2, 0.46, -0.65), (3.4, 0.46, -0.65), (4.6, 0.46, -0.65), (2.8, 0.46, 0.65), (4.0, 0.46, 0.65)]   # 파렛트 5칸
NG_DROP = (0.0, 0.76, -4.2)                                             # NG 수납함 위에서 놓는 위치
NG_SLOTS = [(-0.6 + 0.6 * (i % 3), 0.46, -4.2 - 0.45 + 0.9 * (i // 3)) for i in range(6)]
HOME_TIP = (2.0, 3.4, 0.0)
HOVER = 1.3                                                             # 집기, 놓기 전에 위에서 멈추는 높이
PALLET_QTY = 5
INFEED_X0, GAP, INFEED_SPEED = -9.3, 1.25, 2.4
T = {"vision": 1.0, "approach": 1.2, "down": 0.5, "grip": 0.4, "up": 0.5, "transfer": 1.4, "release": 0.4, "home": 1.0, "pallet_out": 1.5}


def ik(tip, arm=ARM):
    """그리퍼 끝(tip, 아래를 향함)이 닿는 관절 각도(라디안). 팔꿈치는 위로 꺾인다. 닿지 않으면 ValueError."""
    bx, by, bz = arm["base"]
    L1, L2, L3 = arm["L1"], arm["L2"], arm["L3"]
    dx, dz = tip[0] - bx, tip[2] - bz
    r = math.hypot(dx, dz)
    wy = tip[1] + L3 - by                    # 손목(그리퍼 위 끝)의 어깨 기준 높이
    d = math.hypot(r, wy)
    if d > L1 + L2 - 1e-6 or d < abs(L1 - L2) + 1e-6:
        raise ValueError(f"로봇이 닿지 않는 위치입니다: {tip}")
    psi = math.acos(max(-1.0, min(1.0, (L1 * L1 + L2 * L2 - d * d) / (2 * L1 * L2))))
    elbow = -(math.pi - psi)
    shoulder = math.atan2(wy, r) + math.acos(max(-1.0, min(1.0, (L1 * L1 + d * d - L2 * L2) / (2 * L1 * d))))
    yaw = 0.0 if r < 1e-9 else math.atan2(-dz, dx)
    if yaw <= -math.pi + 1e-9:
        yaw += 2 * math.pi                   # 집는 위치는 항상 +pi 쪽으로 (표현이 +-pi 로 뒤집혀 관절이 반대로 돌지 않게)
    wrist = -math.pi / 2 - (shoulder + elbow)
    return {"yaw": yaw, "shoulder": shoulder, "elbow": elbow, "wrist": wrist}


def fk(j, arm=ARM):
    """관절 각도 -> 그리퍼 끝 위치."""
    bx, by, bz = arm["base"]
    a = j["shoulder"]; b = a + j["elbow"]; c = b + j["wrist"]
    rr = arm["L1"] * math.cos(a) + arm["L2"] * math.cos(b) + arm["L3"] * math.cos(c)
    hh = arm["L1"] * math.sin(a) + arm["L2"] * math.sin(b) + arm["L3"] * math.sin(c)
    return (bx + rr * math.cos(j["yaw"]), by + hh, bz - rr * math.sin(j["yaw"]))


def hover(p):
    return (p[0], p[1] + HOVER, p[2])


def confidence(piece_id):
    """비전 검사 신뢰도 (표시용, 작업물 번호에서 정해지는 값)."""
    return round(0.94 + (zlib.crc32(str(piece_id).encode()) % 55) / 1000, 3)


class CobotSim:
    def __init__(self):
        self.speed = 1.0
        self.hook = None      # hook(kind, data): inspected, picked, placed, pallet_closed, reset
        self.reset()

    def _h(self, kind, **data):
        if self.hook:
            self.hook(kind, {"sim_t": self.time, **data})

    def reset(self):
        self._h("reset")
        self.time = 0.0
        self.parts = []                       # 인피드에 있거나 로봇이 들고 있는 작업물: {"id", "result", "x", "stage", "inspected", "conf"}
        self.pallet = []                      # 파렛트에 놓인 것: {"id", "slot"}
        self.ng = []                          # NG 수납함에 놓인 것 (최근 6개만 보인다)
        self.joints = ik(HOME_TIP)
        self.grip = 0.0
        self.seg, self.carry = None, None
        self.counts = {"inspected": 0, "good": 0, "ng": 0, "pallets": 0, "picks": 0}
        self.cycle_s, self.cycles = 0.0, []
        self.cycle_t0 = None
        self.flush_req, self.leaving, self.leave_t = False, False, 0.0
        self.vision = {"active": False, "t": 0.0, "result": None, "conf": None, "head": None}
        self.flash = {"red": 0.0, "yellow": 0.0}
        self.infeed_running = False

    def set_speed(self, v):
        self.speed = max(0.5, min(8.0, float(v)))

    # ---- 외부에서 들어오는 일 ----
    def add_part(self, piece_id, result):
        """프레스 라인 끝에서 나온 작업물 (result: good 또는 scrap)."""
        self.parts.append({"id": piece_id, "result": result, "x": INFEED_X0, "stage": "infeed", "inspected": False, "conf": None})

    def request_flush(self):
        """라인이 멈췄다: 셀이 다 비면 모자란 파렛트를 마감한다."""
        self.flush_req = True

    # ---- 시간 진행 ----
    def advance(self, seconds, dt=0.05):
        t = seconds * self.speed
        while t > 1e-9:
            d = min(dt, t)
            self.step(d)
            t -= d

    def step(self, dt):
        self.time += dt
        for k in self.flash:
            self.flash[k] = max(0.0, self.flash[k] - dt)
        self._infeed(dt)
        self._vision(dt)
        self._robot(dt)
        self._pallet(dt)

    def _queue(self):
        return [p for p in self.parts if p["stage"] in ("infeed", "wait")]

    def _infeed(self, dt):
        moving = False
        for i, p in enumerate(self._queue()):
            target = PICK[0] - GAP * i
            if p["x"] < target - 1e-9:
                p["x"] = min(target, p["x"] + INFEED_SPEED * dt)
                moving = True
            p["stage"] = "wait" if abs(p["x"] - target) < 1e-9 and i == 0 else "infeed"
        self.infeed_running = moving

    def _vision(self, dt):
        q = self._queue()
        head = q[0] if q else None
        v = self.vision
        if head is None or head["stage"] != "wait" or head["inspected"]:
            v["active"], v["t"] = False, 0.0
            return
        if v["head"] != head["id"]:
            v.update(head=head["id"], t=0.0)
        v["active"], v["t"] = True, v["t"] + dt
        if v["t"] >= T["vision"]:
            head["inspected"], head["conf"] = True, confidence(head["id"])
            v.update(active=False, result=head["result"], conf=head["conf"], t=0.0)
            self.counts["inspected"] += 1
            self.counts["good" if head["result"] == "good" else "ng"] += 1
            if head["result"] != "good":
                self.flash["red"] = 1.5
            self._h("inspected", id=head["id"], result=head["result"], conf=head["conf"])

    # ---- 로봇 ----
    def _plan(self, tag, tip, grip, dur, end=None):
        return {"tag": tag, "to": ik(tip), "grip": grip, "dur": dur, "end": end, "t": 0.0, "from": None, "g0": None}

    def _ready_part(self):
        q = self._queue()
        if not q or q[0]["stage"] != "wait" or not q[0]["inspected"]:
            return None
        if q[0]["result"] == "good" and (self.leaving or len(self.pallet) >= PALLET_QTY):
            return None                        # 파렛트가 나가는 중이면 양품은 잠깐 기다린다
        return q[0]

    def _start_cycle(self, part):
        tgt = SLOTS[len(self.pallet)] if part["result"] == "good" else NG_DROP
        self.plan = [
            self._plan("approach", hover(PICK), 0.0, T["approach"]), self._plan("down", PICK, 0.0, T["down"]),
            self._plan("grip", PICK, 1.0, T["grip"], "picked"), self._plan("up", hover(PICK), 1.0, T["up"]),
            self._plan("transfer", hover(tgt), 1.0, T["transfer"]), self._plan("lower", tgt, 1.0, T["down"]),
            self._plan("release", tgt, 0.0, T["release"], "released"), self._plan("clear", hover(tgt), 0.0, T["up"])]
        self.cycle_t0, self.cycle_part, self.cycle_target = self.time, part, tgt
        self.seg = None

    def _robot(self, dt):
        if self.seg is None:
            if getattr(self, "plan", None):
                self.seg = self.plan.pop(0)
            else:
                part = self._ready_part()
                if part is not None:
                    self._start_cycle(part)
                    self.seg = self.plan.pop(0)
                elif any(abs(self.joints[k] - v) > 1e-6 for k, v in ik(HOME_TIP).items()):
                    self.seg = self._plan("home", HOME_TIP, 0.0, T["home"])
        elif self.seg["tag"] == "home" and self._ready_part() is not None:       # 홈으로 가는 중에 일감이 오면 바로 다음 일로
            self.seg = None
            self.plan = []
            return
        s = self.seg
        if s is None:
            return
        if s["from"] is None:
            s["from"], s["g0"] = dict(self.joints), self.grip
        s["t"] += dt
        p = min(1.0, s["t"] / s["dur"])
        k = 0.5 - 0.5 * math.cos(math.pi * p)           # 부드럽게 출발하고 멈춘다
        self.joints = {a: s["from"][a] + (s["to"][a] - s["from"][a]) * k for a in s["from"]}
        self.grip = s["g0"] + (s["grip"] - s["g0"]) * k
        if p >= 1.0:
            end, self.seg = s["end"], None
            if end == "picked":
                part = self.cycle_part
                part["stage"] = "carried"
                self.counts["picks"] += 1
                self._h("picked", id=part["id"], tip=fk(self.joints))
            elif end == "released":
                self._released()

    def _released(self):
        part, tgt = self.cycle_part, self.cycle_target
        self.parts.remove(part)
        self.cycle_s = round(self.time - self.cycle_t0, 2)
        self.cycles.append(self.cycle_s)
        if part["result"] == "good":
            slot = len(self.pallet)
            self.pallet.append({"id": part["id"], "slot": slot})
            self._h("placed", id=part["id"], target="pallet", slot=slot, cycle_s=self.cycle_s, tip=fk(self.joints))
            if len(self.pallet) >= PALLET_QTY:
                self._close(partial=False)
        else:
            self.ng.append(part["id"])
            self.ng = self.ng[-6:]
            self._h("placed", id=part["id"], target="ng_bin", slot=len(self.ng) - 1, cycle_s=self.cycle_s, tip=fk(self.joints))

    def _close(self, partial):
        pieces = [x["id"] for x in self.pallet]
        self.counts["pallets"] += 1
        self.leaving, self.leave_t = True, 0.0
        self.flash["yellow"] = T["pallet_out"]
        self._h("pallet_closed", pieces=pieces, partial=partial)

    def _pallet(self, dt):
        if self.leaving:
            self.leave_t += dt
            if self.leave_t >= T["pallet_out"]:
                self.pallet, self.leaving = [], False
        elif self.flush_req and not self.parts and self.seg is None and not getattr(self, "plan", None):
            if self.pallet:
                self._close(partial=True)
            self.flush_req = False

    # ---- 화면용 상태 ----
    def _part_pos(self, p):
        if p["stage"] == "carried":
            return list(fk(self.joints))
        return [p["x"], PICK[1], 0.0]

    def state(self):
        parts = [{"id": p["id"], "pos": [round(v, 3) for v in self._part_pos(p)], "stage": p["stage"],
                  "result": p["result"] if p["inspected"] else None} for p in self.parts]
        parts += [{"id": x["id"], "pos": list(SLOTS[x["slot"]]), "stage": "placed", "result": "good"} for x in self.pallet]
        parts += [{"id": pid, "pos": list(NG_SLOTS[i]), "stage": "ng", "result": "scrap"} for i, pid in enumerate(self.ng)]
        busy = bool(self.parts or self.seg or self.pallet)
        v = self.vision
        return {
            "time": round(self.time, 1), "speed": self.speed, "status_code": 1 if busy else 0,
            "arm": {**{k: round(x, 4) for k, x in self.joints.items()}, "grip": round(self.grip, 3)},
            "parts": parts, "queue": len(self._queue()),
            "vision": {"active": 1 if v["active"] else 0, "result": v["result"], "conf": v["conf"]},
            "infeed": {"running": bool(self.infeed_running)},
            "pallet": {"count": len(self.pallet), "slots": [1 if any(x["slot"] == i for x in self.pallet) else 0 for i in range(PALLET_QTY)], "leaving": self.leaving},
            "lamp": {"red": 1 if self.flash["red"] > 0 else 0, "yellow": 1 if (self.flash["yellow"] > 0 or (self.pallet and len(self.pallet) >= PALLET_QTY)) else 0,
                     "green": 1},
            "counts": dict(self.counts), "cycle_s": self.cycle_s,
            "avg_cycle_s": round(sum(self.cycles) / len(self.cycles), 2) if self.cycles else 0.0,
        }
