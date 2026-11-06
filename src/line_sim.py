"""프레스 -> 용접 -> 도장 라인 시뮬레이터 (PLC 없이 파이썬만으로).

  [투입] -> 프레스 -> 컨베이어1 -> 용접 -> 컨베이어2 -> 도장 -> 컨베이어3 -> [양품 / 불량]

- 각 공정에는 한 번에 부품 1개가 들어가고, 정해진 사이클 시간 동안 작업한다.
- 사이클이 끝났는데 다음 칸이 차 있으면 "막힘(blocked)", 칸이 비어 일감을 기다리면 "대기(starved)"가 된다.
- 병목(가장 오래 일하는 공정)이 라인 전체 처리량을 결정하는 것을 볼 수 있다.
- 정지: 새 블랭크 투입을 멈추고, 라인에 남은 부품이 모두 나온 뒤에 멈춘다 (run-out). 그래서 작업지시가 중간에 얼어붙지 않는다.
- 결함 주입: weld_slow(용접이 2.2배 느려짐), press_down(프레스 정지), paint_down(도장 정지)
- 용접이 끝난 부품은 일정 확률로 불량(defect)이 되고, 라인 끝에서 불량으로 집계된다.

state()가 돌려주는 값은 3D 화면(src/scenes/*.json 의 path)이 그대로 읽는다.
"""
import math

from paint_cell import STATION_X as PAINT_X, dip as paint_dip, part_y as paint_part_y
from weld_cell import pose as weld_pose
import random

ELEMENTS = ["press", "c1", "weld", "c2", "paint", "c3"]
STATIONS = ("press", "weld", "paint")
NAMES = {"press": "프레스", "weld": "용접", "paint": "도장", "c1": "컨베이어1", "c2": "컨베이어2", "c3": "컨베이어3"}
FAULTS = {"none": "정상", "weld_slow": "용접 속도 저하 (2.2배)", "press_down": "프레스 정지", "paint_down": "도장 정지"}
CYCLE = {"press": 4.0, "weld": 6.0, "paint": 8.0, "c1": 2.0, "c2": 2.0, "c3": 2.5}  # 초


class LineSim:
    def __init__(self, seed=3, defect_rate=0.08):
        self.seed, self.defect_rate = seed, defect_rate
        self.fault = "none"
        self.speed = 1.0
        self.hook = None   # hook(kind, data): 이벤트 발행 등. kind = spawn, completed, exit, state, running, fault, reset
        self.reset()

    def _h(self, kind, **data):
        if self.hook:
            self.hook(kind, {"sim_t": self.time, **data})

    def reset(self):
        self._h("reset")   # 지우기 전의 시뮬레이터 시간을 알려 준다 (이벤트 시간이 리셋해도 이어지도록)
        self.rng = random.Random(self.seed)
        self.time = 0.0
        self.running = False
        self.feeding = True          # False 이면 새 블랭크를 넣지 않는다 (정지를 눌러 라인을 비우는 중)
        self.occ = {e: None for e in ELEMENTS}
        self.counts = {"in": 0, "good": 0, "scrap": 0}
        self.acc = {s: {"working": 0.0, "blocked": 0.0, "starved": 0.0, "down": 0.0} for s in STATIONS}
        self._next_id = 1
        self._prev_state = {s: "starved" for s in STATIONS}
        self.first_exit = self.last_exit = None   # 첫 완성, 마지막 완성 시각 (처리량 계산용)

    def start(self):
        if not self.running:
            self.running, self.feeding = True, True
            self._h("running", on=True)
        elif not self.feeding:           # 비우는 중에 다시 시작
            self.feeding = True
            self._h("running", on=True)

    def stop(self):
        """투입을 멈추고 라인에 남은 부품을 모두 내보낸 뒤 정지한다 (이미 비어 있으면 바로 정지)."""
        if not self.running:
            return
        if all(o is None for o in self.occ.values()):
            self.running = False
            self._h("running", on=False)
        elif self.feeding:
            self.feeding = False
            self._h("drain")

    def set_fault(self, mode):
        if mode not in FAULTS:
            raise ValueError(f"알 수 없는 결함: {mode}")
        if mode != self.fault:
            self.fault = mode
            self._h("fault", mode=mode)
            self._track_states()   # 정지 결함은 시간이 흐르기 전에도 공정 상태를 바꾼다
        self.fault = mode

    def _track_states(self):
        """공정 상태(작업 중, 막힘, 대기, 정지)가 바뀌었으면 알린다."""
        for st in STATIONS:
            now = self._station_state(st)
            if now != self._prev_state[st]:
                self._h("state", station=st, frm=self._prev_state[st], to=now)
                self._prev_state[st] = now

    def set_speed(self, value):
        self.speed = max(0.5, min(8.0, float(value)))

    # ---- 내부 ----
    def _down(self, name):
        return (self.fault == "press_down" and name == "press") or (self.fault == "paint_down" and name == "paint")

    def duration(self, name):
        d = CYCLE[name]
        return d * 2.2 if (self.fault == "weld_slow" and name == "weld") else d

    def _station_state(self, name):
        if self._down(name):
            return "down"
        o = self.occ[name]
        if o is None:
            return "starved"
        return "blocked" if o["t_el"] >= self.duration(name) else "working"

    def _move(self, name, nxt):
        part = self.occ[name]
        if name == "press":
            part["pressed"] = True
        elif name == "weld":
            part["welded"] = True
            part["defect"] = self.rng.random() < self.defect_rate  # 용접 불량은 용접이 끝나는 시점에 정해진다
        elif name == "paint":
            part["painted"] = True
        if name in STATIONS:
            extra = {"defect": bool(part["defect"])} if name == "weld" else {}
            worked = min(part["t_el"], self.duration(name))   # 작업한 시간 (다음 칸이 차서 기다린 시간은 제외)
            self._h("completed", id=part["id"], station=name, duration_s=round(worked, 2),
                    nominal_s=CYCLE[name], **extra)
        part["t_el"] = 0.0
        self.occ[nxt] = part
        self.occ[name] = None

    def step(self, dt):
        """dt초만큼 진행한다 (stopped 이면 아무것도 하지 않는다)."""
        if not self.running:
            return
        self.time += dt
        for name in reversed(ELEMENTS):          # 하류부터 처리해야 같은 순간에 빈 칸으로 밀려난다
            o = self.occ[name]
            if o is None or self._down(name):
                continue
            o["t_el"] += dt
            if o["t_el"] >= self.duration(name):
                if name == "c3":                  # 라인 끝: 양품 / 불량 집계
                    self.counts["scrap" if o["defect"] else "good"] += 1
                    self.occ[name] = None
                    self._h("exit", id=o["id"], result="scrap" if o["defect"] else "good")
                    if self.first_exit is None:
                        self.first_exit = self.time
                    self.last_exit = self.time
                else:
                    nxt = ELEMENTS[ELEMENTS.index(name) + 1]
                    if self.occ[nxt] is None:
                        self._move(name, nxt)
        if self.feeding and self.occ["press"] is None and not self._down("press"):   # 투입 (프레스 칸이 비면 새 블랭크)
            self.occ["press"] = {"id": self._next_id, "t_el": 0.0, "pressed": False, "welded": False,
                                 "painted": False, "defect": False}
            self._h("spawn", id=self._next_id)
            self._next_id += 1
            self.counts["in"] += 1
        for s in STATIONS:                          # 가동률 집계
            self.acc[s][self._station_state(s)] += dt
        self._track_states()
        if not self.feeding and all(o is None for o in self.occ.values()):   # 다 비었으면 정지
            self.running = False
            self._h("running", on=False)

    def advance(self, seconds, dt=0.05):
        """실제 경과 시간 seconds 를 배속에 맞춰 진행한다."""
        t = seconds * self.speed
        while t > 1e-9:
            d = min(dt, t)
            self.step(d)
            t -= d

    def _throughput(self, done):
        """첫 완성 이후의 완성 간격으로 계산한다 (라인이 채워지는 초기 구간 때문에 낮게 나오지 않게)."""
        if done < 3 or self.last_exit is None or self.last_exit <= self.first_exit:
            return 0.0
        return round((done - 1) / ((self.last_exit - self.first_exit) / 60), 2)

    # ---- 3D 화면과 API가 읽는 값 ----
    def state(self):
        st, parts = {}, []
        for name in STATIONS:
            o = self.occ[name]
            state = self._station_state(name)
            p = 0.0 if o is None else min(1.0, o["t_el"] / self.duration(name))
            working = state == "working"
            st[name] = {
                "state": state, "progress": round(p, 3), "cycle": round(self.duration(name), 2),
                "working": working,
                "ram": round(math.sin(math.pi * p), 3) if working and name == "press" else 0.0,   # 프레스 램 (0 = 위, 1 = 아래)
                "arm": round(math.sin(math.pi * p), 3) if working and name == "weld" else 0.0,    # 용접 토치 (0 = 위, 1 = 아래)
                "spark": bool(working and name == "weld" and 0.25 < p < 0.75),
                "spray": bool(working and name == "paint" and 0.15 < p < 0.85),
            }
            if name == "weld":      # 6축 스폿 용접 로봇의 관절, 건 닫힘, 불꽃, 지그 클램프 (weld_cell.py: 용접 점 세 곳을 차례로)
                rp = weld_pose(p, working)
                st[name].update(robot={k: rp[k] for k in ("yaw", "shoulder", "elbow", "wrist")}, gun=rp["gun"], clamp=rp["clamp"], spark=rp["spark"])
            if name == "paint":     # 행거가 부품을 전착조 액 속으로 내렸다 올린다 (paint_cell.py)
                d = paint_dip(p, working)
                st[name].update(dip=round(d, 3), voltage=bool(d > 0.9))
        conv = {c: {"moving": bool(self.occ[c] is not None and self.occ[c]["t_el"] < self.duration(c))} for c in ("c1", "c2", "c3")}
        for e in ELEMENTS:
            o = self.occ[e]
            if o is not None:
                item = {"id": o["id"], "stage": e, "t": round(min(1.0, o["t_el"] / self.duration(e)), 3),
                        "pressed": o["pressed"], "welded": o["welded"], "painted": o["painted"], "defect": o["defect"]}
                if e == "paint":    # 도장 공정에서는 부품이 행거에 매달려 액 속으로 내려간다: 높이는 침지 깊이를 따른다
                    item["pos"] = [PAINT_X, paint_part_y(st["paint"]["dip"]), 0.0]
                parts.append(item)
        total = max(self.time, 1e-9)
        util = {s: {k: round(v / total, 3) for k, v in self.acc[s].items()} for s in STATIONS}
        done = self.counts["good"] + self.counts["scrap"]
        bott = None
        if self.time >= 60:
            bott = max(STATIONS, key=lambda s: util[s]["working"] + util[s]["down"])
        return {
            "time": round(self.time, 1), "running": self.running, "draining": self.running and not self.feeding, "fault": self.fault, "speed": self.speed,
            "stations": st, "conveyors": conv, "parts": parts, "counts": dict(self.counts), "oven": {"heat": 1 if self.running else 0},
            "util": util, "kpi": {"throughput_per_min": self._throughput(done),
                                   "good_rate": round(self.counts["good"] / done, 3) if done else None,
                                   "bottleneck": bott, "bottleneck_name": NAMES.get(bott)},
        }
