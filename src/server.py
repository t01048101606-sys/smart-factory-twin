"""PLC 시뮬레이터를 돌리고 상태를 웹으로 내보내는 Flask 서버.

실행 (프로젝트 폴더에서):
    python src/server.py plc/1102
접속: http://localhost:5001
"""
import sys
import threading
import time
from pathlib import Path

from flask import Flask, jsonify, request, send_from_directory

from plc_sim import PlcSim
from workpiece import Tracker

BASE = Path(__file__).resolve().parent
CSV_DIR = sys.argv[1] if len(sys.argv) > 1 else str(BASE.parent / "plc" / "1102")

app = Flask(__name__, static_folder=str(BASE / "static"))
sim = PlcSim(CSV_DIR)
tracker = Tracker()
lock = threading.Lock()
pending = set()  # 다음 스캔에서 한 번만 켜질 입력

# 웹에서 조작을 허용하는 디바이스
PRESS_ALLOWED = {"M100", "M101", "M102", "M103", "X0E"}
STATE_KEYS = (
    [f"X{i}" if i < 10 else f"X0{i:X}" for i in range(0, 11)]
    + [f"Y{i:X}" for i in range(0x20, 0x2C)]
    + ["M0", "M1", "D0", "D2", "D4", "D10"]
)


def scan_loop():
    while True:
        with lock:
            sim.scan(list(pending))
            pending.clear()
            tracker.update(sim.dev)
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
        return jsonify(out)


@app.post("/api/press")
def press():
    dev = (request.get_json(silent=True) or {}).get("dev")
    if dev not in PRESS_ALLOWED:
        return jsonify(error="허용되지 않은 디바이스"), 400
    with lock:
        pending.add(dev)
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
        sim.dev["D10"] = value  # 5~100 범위 제한은 PLC 프로그램이 처리
    return jsonify(ok=True)


if __name__ == "__main__":
    threading.Thread(target=scan_loop, daemon=True).start()
    app.run(host="127.0.0.1", port=5001, debug=False)
