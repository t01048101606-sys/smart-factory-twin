"""한 사이클 동안 센서(X)/출력(Y)의 변화를 시각과 함께 기록한다.
사용: python src/trace.py 20   (server.py modbus 실행 중. 20초 동안 기록. 시작 직후 트윈에서 '연속동작'을 누르세요)
결과는 화면에 출력되고 trace.txt 에도 저장된다.
"""
import json, sys, time, urllib.request

SEC = float(sys.argv[1]) if len(sys.argv) > 1 else 20
NAMES = {"X0":"공급후진센서","X1":"공급전진센서","X2":"드릴하강센서","X3":"드릴상승센서","X4":"송출후진센서","X5":"송출전진센서",
         "X6":"배출후진센서","X7":"배출전진센서","X8":"매거진","X9":"금속","X0A":"비금속",
         "Y20":"공급전진","Y21":"공급후진","Y22":"드릴하강","Y23":"송출전진","Y24":"송출후진","Y25":"배출전진","Y26":"배출후진",
         "Y27":"컨베이어","Y28":"드릴모터","Y29":"적색","Y2A":"황색","Y2B":"녹색"}

def state():
    return json.load(urllib.request.urlopen("http://127.0.0.1:5001/api/state", timeout=2))

lines = []
def out(s):
    print(s); lines.append(s)

prev = state(); t0 = time.time()
out(f"시작 상태: " + ", ".join(k for k in NAMES if prev[k]))
out(f"D0,D2,D4={prev['D0']},{prev['D2']},{prev['D4']}  D10={prev['D10']}")
while time.time() - t0 < SEC:
    s = state()
    for k in NAMES:
        if s[k] != prev[k]:
            out(f"{time.time()-t0:6.2f}s  {NAMES[k]}({k}) {'ON' if s[k] else 'off'}")
    prev = s
    time.sleep(0.02)
open("trace.txt", "w", encoding="utf-8").write("\n".join(lines))
print("\ntrace.txt 에 저장했습니다.")
