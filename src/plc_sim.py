"""가공 공정(11/2 HMI연동) 명령어 목록 CSV를 읽어 PLC 스캔을 흉내 내는 시뮬레이터.

사용법 (프로젝트 폴더에서):
    python src/plc_sim.py plc/1102

- CSV는 GX Works2에서 내보낸 명령어 목록(UTF-16, 탭 구분)이어야 합니다.
- 실린더와 센서는 단순한 지연 모델로 흉내 냅니다(실제 장비의 시간과 다름).
- POFF가 대기 프로그램의 출력을 끈다는 가정이 들어 있으며, 실제 PLC에서 확인이 필요합니다.
"""
import collections
import csv
import io
import random
import sys
from pathlib import Path

PROGRAMS = ["READY", "MAIN", "TEST1", "HMI"]
TICKS = 2  # 스캔 1회 = 50 ms, 타이머 단위 100 ms = 2 스캔
NAMES = {
    "Y20": "공급전진", "Y21": "공급후진", "Y22": "드릴하강", "Y23": "송출전진",
    "Y24": "송출후진", "Y25": "배출전진", "Y26": "배출후진", "Y27": "컨베이어",
    "Y28": "드릴모터", "Y29": "적색", "Y2A": "황색", "Y2B": "녹색",
}
# 실린더 출력 -> (도착 센서, 출발 센서)
CYLINDERS = {
    "Y20": ("X1", "X0"), "Y21": ("X0", "X1"), "Y23": ("X5", "X4"),
    "Y24": ("X4", "X5"), "Y25": ("X7", "X6"), "Y26": ("X6", "X7"),
}


def load_program(path):
    text = Path(path).read_bytes().decode("utf-16")
    rows = list(csv.reader(io.StringIO(text), delimiter="\t"))
    out = []
    for r in rows[3:]:
        if len(r) < 4 or not any(r):
            continue
        if r[2] == "" and out:  # 두 번째 줄 이후의 피연산자
            out[-1].append(r[3])
            continue
        out.append([r[2], r[3]])
    return out


FAULTS = {
    "none": "정상",
    "cyl_slow": "실린더 속도 저하 (이동 시간 3배)",
    "cyl_degrade": "실린더 점진 열화 (사이클마다 느려짐)",
    "sensor_flaky": "센서 응답 지연 (간헐)",
}


class PlcSim:
    fault_mode = "none"  # 시뮬레이터에 주입하는 결함 (ModbusPlc도 이 값을 그대로 쓴다)

    def __init__(self, csv_dir):
        d = Path(csv_dir)
        self.progs = {n: load_program(d / f"{n}.csv") for n in PROGRAMS}
        self.dev = collections.defaultdict(int)
        self.prev_edge = {}
        self.timers = {}
        self.active = {"READY": 1, "MAIN": 1, "TEST1": 0, "HMI": 0}
        self.moving = {}
        self.scan_no = 0
        self.piece_mode = "alternate"  # alternate(번갈아) | metal | nonmetal
        self._next_metal = True        # alternate 모드에서 다음 작업물이 금속인지
        self._kind_metal = True        # 현재 센서 위치의 작업물이 금속인지
        self._x5_prev = 0
        for x in ("X0", "X3", "X4", "X6", "X8"):  # 초기 센서 상태
            self.dev[x] = 1

    # ---- 명령어 실행 ----
    def _val(self, o, first):
        if o.startswith("K"):
            return int(o[1:])
        if o == "SM400":
            return 1
        if o == "SM402":
            return 1 if first else 0
        if o == "SM412":
            return (self.scan_no // (5 * TICKS)) % 2
        return self.dev[o]

    def _run(self, name, first):
        st = []
        g = lambda o: self._val(o, first)
        for idx, (ins, *ops) in enumerate(self.progs[name]):
            if ins in ("LD", "LDI", "LDP"):
                v = g(ops[0])
                if ins == "LDP":
                    e = int(bool(v) and not self.prev_edge.get((name, idx), 0))
                    self.prev_edge[(name, idx)] = int(bool(v))
                    st.append(e)
                else:
                    st.append(v if ins == "LD" else 1 - v)
            elif ins == "AND": st[-1] &= g(ops[0])
            elif ins == "ANI": st[-1] &= 1 - g(ops[0])
            elif ins == "OR": st[-1] |= g(ops[0])
            elif ins == "ANB":
                b = st.pop(); st[-1] &= b
            elif ins == "AND=": st[-1] &= int(g(ops[0]) == g(ops[1]))
            elif ins == "LD>": st.append(int(g(ops[0]) > g(ops[1])))
            elif ins == "LD<": st.append(int(g(ops[0]) < g(ops[1])))
            elif ins == "OUT":
                o = ops[0]
                if o.startswith("T"):
                    self.timers[o] = self.timers.get(o, 0) + 1 if st[-1] else 0
                    self.dev[o] = int(self.timers[o] >= g(ops[1]) * TICKS)
                else:
                    self.dev[o] = st[-1]
            elif ins == "MOV":
                if st[-1]: self.dev[ops[1]] = g(ops[0])
            elif ins == "INC":
                if st[-1]: self.dev[ops[0]] += 1
            elif ins == "+":
                if st[-1]: self.dev[ops[2]] = g(ops[0]) + g(ops[1])
            elif ins == "PSCAN":
                if st[-1]: self.active[ops[0].strip('"')] = 1
            elif ins == "POFF":
                if st[-1]:
                    tg = ops[0].strip('"')
                    self.active[tg] = 0
                    for i2, *o2 in self.progs[tg]:  # 가정: 끄면 그 프로그램의 출력도 0
                        if i2 == "OUT":
                            self.dev[o2[0]] = 0
                            self.timers.pop(o2[0], None)

    # ---- 결함 주입 ----
    def _fs(self):
        fs = self.__dict__.get("_fault_state")
        if fs is None:
            fs = {"deg": 0.0, "y20": 0, "delay": {}, "rng": random.Random(7)}
            self.__dict__["_fault_state"] = fs
        return fs

    def set_fault(self, mode):
        if mode not in FAULTS:
            raise ValueError(f"알 수 없는 결함: {mode}")
        self.fault_mode = mode
        self.__dict__.pop("_fault_state", None)  # 열화 정도와 난수를 처음 상태로

    def _fault_factor(self, fs):
        if self.fault_mode == "cyl_slow":
            return 3.0
        if self.fault_mode == "cyl_degrade":
            return 1.0 + fs["deg"]
        return 1.0

    # ---- 장비(센서) 모델 ----
    def _plant(self):
        dev, mv = self.dev, self.moving
        fs = self._fs()
        if dev["Y20"] and not fs["y20"] and self.fault_mode == "cyl_degrade":
            fs["deg"] = min(fs["deg"] + 0.12, 3.0)  # 사이클이 시작될 때마다 이동 시간이 조금씩 늘어난다
        fs["y20"] = int(bool(dev["Y20"]))
        arrive = max(6, int(round(6 * self._fault_factor(fs))))  # 한 번 이동하는 데 걸리는 스캔 수 (정상 6 = 0.3초)
        for y, (to, frm) in CYLINDERS.items():
            if dev[y]:
                mv[y] = mv.get(y, 0) + 1
                if mv[y] == 1 and self.fault_mode == "sensor_flaky":  # 30% 확률로 도착 센서가 0.7~1.5초 늦게 켜진다
                    fs["delay"][y] = fs["rng"].randint(14, 30) if fs["rng"].random() < 0.3 else 0
                if mv[y] >= arrive + fs["delay"].get(y, 0): dev[to] = 1; dev[frm] = 0
                elif mv[y] >= 2: dev[frm] = 0
            else:
                mv[y] = 0
        if dev["Y22"]:  # 드릴 하강
            mv["dd"] = mv.get("dd", 0) + 1
            if mv["dd"] >= arrive: dev["X2"] = 1; dev["X3"] = 0
            elif mv["dd"] >= 2: dev["X3"] = 0
        elif dev["X2"]:  # 상승 중
            mv["du"] = mv.get("du", 0) + 1
            if mv["du"] >= arrive: dev["X2"] = 0; dev["X3"] = 1
        else:
            mv["du"] = 0
        # 송출 전진이 끝나는 순간 작업물 종류를 정하고, 그 종류에 맞는 센서(X9 금속 / X0A 비금속)를 켠다
        if dev["X5"] and not self._x5_prev:
            if self.piece_mode == "metal":
                self._kind_metal = True
            elif self.piece_mode == "nonmetal":
                self._kind_metal = False
            else:
                self._kind_metal = self._next_metal
                self._next_metal = not self._next_metal
        self._x5_prev = dev["X5"]
        dev["X9"] = 1 if dev["X5"] and self._kind_metal else 0
        dev["X0A"] = 1 if dev["X5"] and not self._kind_metal else 0

    def scan(self, pressed=()):
        """스캔 1회. pressed: 이번 스캔에만 켜질 입력 (예: 'M101', 'X0E')."""
        for d in ("X0B", "X0C", "X0D", "X0E", "M100", "M101", "M102", "M103"):
            self.dev[d] = 0
        for d in pressed:
            self.dev[d] = 1
        self._plant()
        for n in PROGRAMS:
            if self.active[n]:
                self._run(n, self.scan_no == 0)
        self.scan_no += 1

    def outputs(self):
        return {NAMES[k]: self.dev[k] for k in NAMES}


def demo(csv_dir, events, nscan, label):
    sim = PlcSim(csv_dir)
    last = {}
    print(f"== {label}")
    for s in range(nscan):
        sim.scan([d for t, d in events if t == s])
        for k in NAMES:
            if sim.dev[k] != last.get(k, 0):
                print(f"{s * 0.05:6.2f}s {NAMES[k]} {'ON' if sim.dev[k] else 'off'}")
                last[k] = sim.dev[k]
    print(f"   D10={sim.dev['D10']}  금속 D0={sim.dev['D0']}  비금속 D2={sim.dev['D2']}  합계 D4={sim.dev['D4']}")


if __name__ == "__main__":
    folder = sys.argv[1] if len(sys.argv) > 1 else "plc/1102"
    demo(folder, [(20, "M101"), (200, "M102")], 900, "HMI 연속 시작, 10초에 HMI 정지")
    demo(folder, [(20, "M101"), (200, "X0E")], 700, "연속 중 10초에 PB4 리셋")
