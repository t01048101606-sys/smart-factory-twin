"""드릴 하강 출력(Y22)이 켜져 있던 시간을 재서 D10 설정과 맞는지 확인한다.
사용: python src/measure_drill.py   (server.py modbus 실행 중, 트윈에서 연속 시작 후)
"""
import json, time, urllib.request

def state():
    return json.load(urllib.request.urlopen("http://127.0.0.1:5001/api/state", timeout=2))

print("드릴 하강 출력(Y22)이 켜져 있던 시간을 5회 잽니다. 트윈에서 '연속'을 눌러 두세요. (Ctrl+C로 중단)")
on_at, n = None, 0
while n < 5:
    s = state()
    if s["Y22"] and on_at is None:
        on_at = time.time()
    elif not s["Y22"] and on_at is not None:
        n += 1
        print(f"{n}회: 드릴 하강 {time.time() - on_at:.2f}초  (D10={s['D10']} -> 가공시간 {s['D10'] / 10:.1f}초)")
        on_at = None
    time.sleep(0.02)
