"""OpenPLC(Modbus TCP)에 연결하는 게이트웨이.

PLC 로직은 OpenPLC(machining.st)가 실행하고, 이 파일은 장비(센서) 모델만 돌립니다.
  - 장비 모델이 계산한 센서값  -> SIM_* 코일(24~38)에 씀
  - PLC 출력(Y20~Y2B)          <- 코일 0~11에서 읽음
  - 카운트 D0/D2/D4, 가공시간 D10 <- 홀딩 레지스터 1024~1027
  - HMI 버튼(M100~M103), PB4 리셋 -> 코일 16~19, 38에 150 ms 동안 씀
PlcSim과 같은 인터페이스(dev, scan, piece_mode)를 제공하므로 server.py가 그대로 씁니다.
"""
import collections
import threading

from plc_sim import PlcSim

OUT_COILS = list(range(0x20, 0x2C))  # Y20..Y2B -> 코일 0..11
HMI_COIL = {"M100": 16, "M101": 17, "M102": 18, "M103": 19}
SIM_BASE = 24                         # %QX3.0
SIM_ORDER = ["X0", "X1", "X2", "X3", "X4", "X5", "X6", "X7",
             "X8", "X9", "X0A", "X0B", "X0C", "X0D", "X0E"]
PB_RESET_COIL = SIM_BASE + SIM_ORDER.index("X0E")  # 38
HOLD_TICKS = 3                        # 버튼을 눌러 두는 스캔 수 (50 ms x 3)
D_BASE = 1024                         # %MW0 -> D0, %MW1 -> D2, %MW2 -> D4, %MW3 -> D10


def _call(fn, *args, **kw):
    # pymodbus 버전마다 slave / device_id 인자 이름이 달라 차례로 시도
    for extra in ({"device_id": 1}, {"slave": 1}, {}):
        try:
            return fn(*args, **kw, **extra)
        except TypeError:
            continue
    raise RuntimeError("pymodbus 호출 형식을 찾지 못했습니다")


class ModbusPlc(PlcSim):
    def __init__(self, host="127.0.0.1", port=502, client=None):
        # PlcSim.__init__은 CSV를 읽으므로 호출하지 않고 필요한 값만 직접 만든다
        self.dev = collections.defaultdict(int)
        self.moving = {}
        self.scan_no = 0
        self.piece_mode = "alternate"
        self._next_metal = True
        self._kind_metal = True
        self._x5_prev = 0
        for x in ("X0", "X3", "X4", "X6", "X8"):
            self.dev[x] = 1
        self.connected = False
        self.error = ""
        self._hold = {}                # 코일 번호 -> 남은 스캔 수
        self._lock = threading.Lock()
        if client is None:
            from pymodbus.client import ModbusTcpClient
            client = ModbusTcpClient(host, port=port, timeout=1)
        self.c = client

    def set_d10(self, value):
        with self._lock:
            try:
                _call(self.c.write_register, D_BASE + 3, int(value))
            except Exception as e:  # 연결이 끊긴 경우
                self.error = str(e)

    def scan(self, pressed=()):
        for d in pressed:
            if d in HMI_COIL:
                self._hold[HMI_COIL[d]] = HOLD_TICKS
            elif d == "X0E":
                self._hold[PB_RESET_COIL] = HOLD_TICKS
        try:
            if not self.connected:
                self.connected = bool(self.c.connect())
                if not self.connected:
                    self.error = "OpenPLC의 502 포트에 연결하지 못했습니다"
                    return
            self._plant()                                   # 1) 장비 모델
            sim = [int(bool(self.dev[k])) for k in SIM_ORDER]
            for coil in list(self._hold):                   # 눌려 있는 버튼 반영
                if coil >= SIM_BASE:
                    sim[coil - SIM_BASE] = 1
            _call(self.c.write_coils, SIM_BASE, [bool(v) for v in sim])
            hmi = [self._hold.get(HMI_COIL[d], 0) > 0 for d in ("M100", "M101", "M102", "M103")]
            _call(self.c.write_coils, HMI_COIL["M100"], hmi)
            for coil in list(self._hold):
                self._hold[coil] -= 1
                if self._hold[coil] <= 0:
                    del self._hold[coil]
            r = _call(self.c.read_coils, 0, count=12)       # 2) PLC 출력
            if r.isError():
                raise RuntimeError(str(r))
            for i, y in enumerate(OUT_COILS):
                self.dev[f"Y{y:X}"] = int(r.bits[i])
            r = _call(self.c.read_holding_registers, D_BASE, count=4)   # 3) 카운트, D10
            if r.isError():
                raise RuntimeError(str(r))
            self.dev["D0"], self.dev["D2"], self.dev["D4"], self.dev["D10"] = r.registers
            self.error = ""
        except Exception as e:
            self.connected = False
            self.error = str(e)
            try:
                self.c.close()
            except Exception:
                pass
        self.scan_no += 1
