"""OpenPLC(machining.st) Modbus 주소 점검. 사용: python src/modbus_probe.py"""
import sys, time
from pymodbus.client import ModbusTcpClient

HOST = sys.argv[1] if len(sys.argv) > 1 else "127.0.0.1"
c = ModbusTcpClient(HOST, port=502)
if not c.connect():
    sys.exit("502 포트에 연결하지 못했습니다. OpenPLC가 실행 중인지, docker run에 -p 502:502가 있는지 확인하세요.")

def call(fn, *a, **kw):
    # pymodbus 버전마다 slave / device_id 인자 이름이 다르므로 차례로 시도
    for extra in ({"device_id": 1}, {"slave": 1}, {}):
        try:
            return fn(*a, **kw, **extra)
        except TypeError:
            continue
    raise RuntimeError("pymodbus 호출 형식을 찾지 못했습니다")

def coils(addr, n):
    r = call(c.read_coils, addr, count=n)
    if r.isError(): sys.exit(f"coil 읽기 실패: {r}")
    return [int(b) for b in r.bits[:n]]

def hregs(addr, n):
    r = call(c.read_holding_registers, addr, count=n)
    if r.isError(): sys.exit(f"holding register 읽기 실패: {r}")
    return list(r.registers)

def setc(addr, v): call(c.write_coil, addr, bool(v))

Y = {n: 0+i for i, n in enumerate(["Y20","Y21","Y22","Y23","Y24","Y25","Y26","Y27"])}
print("1) 출력 코일 0~11 (Y20~Y2B):", coils(0, 12))
print("2) 가공시간 D10 (holding 1024+3) / 카운트 D0,D2,D4:",
      "D10 =", hregs(1027, 1)[0], "| D0,D2,D4 =", hregs(1024, 3))
print("   -> D10이 30이면 초기값 설정이 동작한 것입니다.")

print("3) 센서 시뮬레이션 쓰기 후 단속 시작 (M100)")
for a in (24, 27, 28, 32):      # X0 공급후진, X3 드릴상승, X4 송출후진, X8 매거진
    setc(a, 1)
setc(16, 1); time.sleep(0.3); setc(16, 0)   # HMI_START_SINGLE 펄스
time.sleep(0.3)
out = coils(0, 12)
print("   출력:", out)
print("   -> 앞에서 첫 번째(Y20 공급전진)가 1이면 입력/시작/로직 경로가 모두 맞는 것입니다." if out[0] else
      "   -> Y20이 0입니다. 주소 배치나 로직을 확인해야 합니다.")

# 원상복구
for a in (24, 27, 28, 32): setc(a, 0)
setc(18, 1); time.sleep(0.3); setc(18, 0)    # HMI 정지
c.close()
