"""PLC(시뮬레이터 또는 OpenPLC)를 돌리고 상태를 웹으로 내보내는 Flask 서버.

실행 (프로젝트 폴더에서):
    python src/server.py plc/1102          # 파이썬 시뮬레이터가 PLC 로직을 실행
    python src/server.py modbus            # OpenPLC(127.0.0.1:502)가 PLC 로직을 실행
    python src/server.py modbus 192.168.0.109   # 다른 PLC 주소
접속: http://localhost:5001
"""
import sys
import threading
import time
from pathlib import Path

from flask import Flask, jsonify, request, send_from_directory

from plc_sim import PlcSim
from workpiece import Tracker
from events import EventEmitter

BASE = Path(__file__).resolve().parent
ARG = sys.argv[1] if len(sys.argv) > 1 else str(BASE.parent / "plc" / "1102")

app = Flask(__name__, static_folder=str(BASE / "static"))
if ARG == "modbus":
    from modbus_plc import ModbusPlc
    sim = ModbusPlc(sys.argv[2] if len(sys.argv) > 2 else "127.0.0.1")
else:
    sim = PlcSim(ARG)
tracker = Tracker()
events = EventEmitter(log_path=BASE.parent / "logs" / "events.jsonl")
lock = threading.Lock()
pending = set()  # 다음 스캔에서 한 번만 켜질 입력

# 웹에서 조작을 허용하는 디바이스
PRESS_ALLOWED = {"M100", "M101", "M102", "M103", "X0E"}
STATE_KEYS = (
    [f"X{i}" if i < 10 else f"X0{i:X}" for i in range(0, 11)]
    + [f"Y{i:X}" for i in range(0x20, 0x2C)]
    + ["D0", "D2", "D4", "D10"]
)


def scan_loop():
    while True:
        with lock:
            sim.scan(list(pending))
            pending.clear()
            tracker.update(sim.dev)
            events.observe(sim.dev)
        time.sleep(0.05)


@app.get("/")
def index():
    return send_from_directory(app.static_folder, "index.html")


@app.get("/api/state")
def state():
    with lock:
        out = {k: int(sim.dev[k]) for k in STATE_KEYS}
        out["pieces"] = tracker.snapshot()
        out["mode"] = sim.piece_mode
        out["connected"] = getattr(sim, "connected", True)
        out["error"] = getattr(sim, "error", "")
        return jsonify(out)


@app.post("/api/press")
def press():
    dev = (request.get_json(silent=True) or {}).get("dev")
    if dev not in PRESS_ALLOWED:
        return jsonify(error="허용되지 않은 디바이스"), 400
    with lock:
        pending.add(dev)
        events.command(dev, "web")
    return jsonify(ok=True)


@app.post("/api/mode")
def set_mode():
    mode = (request.get_json(silent=True) or {}).get("mode")
    if mode not in ("alternate", "metal", "nonmetal"):
        return jsonify(error="alternate, metal, nonmetal 중 하나"), 400
    with lock:
        sim.piece_mode = mode
    return jsonify(ok=True)


@app.post("/api/d10")
def set_d10():
    value = (request.get_json(silent=True) or {}).get("value")
    if not isinstance(value, int) or not 0 <= value <= 999:
        return jsonify(error="0~999 정수만 가능"), 400
    with lock:
        events.note_param_origin("web")
        if hasattr(sim, "set_d10"):
            sim.set_d10(value)  # OpenPLC의 D10 레지스터에 쓴다
        else:
            sim.dev["D10"] = value  # 5~100 범위 제한은 PLC 프로그램이 처리
    return jsonify(ok=True)


@app.get("/api/events")
def get_events():
    """공통 이벤트 조회. ?after=<seq>(그 번호 이후만) &limit=<개수, 기본 200>"""
    after = request.args.get("after", -1, type=int)
    limit = min(request.args.get("limit", 200, type=int), 1000)
    return jsonify(events.since(after, limit))


if __name__ == "__main__":
    threading.Thread(target=scan_loop, daemon=True).start()
    app.run(host="127.0.0.1", port=5001, debug=False)
