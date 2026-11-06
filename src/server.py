"""PLC(시뮬레이터 또는 OpenPLC)를 돌리고 상태를 웹으로 내보내는 Flask 서버.

실행 (프로젝트 폴더에서):
    python src/server.py plc/1102          # 파이썬 시뮬레이터가 PLC 로직을 실행
    python src/server.py modbus            # OpenPLC(127.0.0.1:502)가 PLC 로직을 실행
    python src/server.py modbus 192.168.0.109   # 다른 PLC 주소
접속: http://localhost:5001
"""
import json
import sys
import threading
import time
from pathlib import Path

from flask import Flask, jsonify, request, send_from_directory

from plc_sim import PlcSim
from workpiece import Tracker
from events import EventEmitter
from anomaly import CycleAnomalyDetector
from plc_sim import FAULTS
from line_sim import LineSim, FAULTS as LINE_FAULTS
from line_events import LineEventBridge
from machining_view import MachiningView
from logistics_sim import LogisticsSim
from cobot_sim import CobotSim
from cobot_events import CobotEventBridge
from logistics_events import LogisticsEventBridge

BASE = Path(__file__).resolve().parent
ARG = sys.argv[1] if len(sys.argv) > 1 else str(BASE.parent / "plc" / "1102")

app = Flask(__name__, static_folder=str(BASE / "static"))
if ARG == "modbus":
    from modbus_plc import ModbusPlc
    sim = ModbusPlc(sys.argv[2] if len(sys.argv) > 2 else "127.0.0.1")
else:
    sim = PlcSim(ARG)
tracker = Tracker()
view = MachiningView()      # 3D 화면용 실린더 위치 값
events = EventEmitter(log_path=BASE.parent / "logs" / "events.jsonl", detector=CycleAnomalyDetector())
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
            view.update(sim.dev)
            events.observe(sim.dev)
        time.sleep(0.05)


@app.get("/")
def index():
    return send_from_directory(app.static_folder, "index.html")


THREE_VERSION = "0.170.0"


def _page_3d(name):
    """3D 화면 HTML. static/vendor 에 three.js 가 내려받아져 있으면 그것을 쓰고(오프라인 가능), 없으면 CDN에서 불러온다."""
    vendor = Path(app.static_folder) / "vendor"
    if (vendor / "three.module.js").exists() and (vendor / "addons" / "controls" / "OrbitControls.js").exists():
        imports = {"three": "/static/vendor/three.module.js", "three/addons/": "/static/vendor/addons/"}
    else:
        cdn = f"https://cdn.jsdelivr.net/npm/three@{THREE_VERSION}"
        imports = {"three": f"{cdn}/build/three.module.js", "three/addons/": f"{cdn}/examples/jsm/"}
    html = (Path(app.static_folder) / name).read_text(encoding="utf-8")
    return html.replace("__IMPORTMAP__", json.dumps({"imports": imports}))


@app.get("/3d")
def twin_3d():
    return _page_3d("twin3d.html")


# ---- 프레스 -> 용접 -> 도장 라인 (PLC 없이 파이썬 시뮬레이터, 장면은 JSON 으로 정의)
line = LineSim()
line.hook = LineEventBridge(events)   # 라인의 변화를 공통 이벤트로 내보낸다 (MES 연동, OEE)
line_lock = threading.Lock()
SCENE_FILE = BASE / "scenes" / "press_weld_paint.json"


def line_loop():
    last = time.time()
    while True:
        time.sleep(0.05)
        now = time.time()
        with line_lock:
            line.advance(now - last)
        last = now


# ---- 물류 · 출하 구역: 프레스 라인의 이벤트로 재고가 줄고 파렛트가 만들어진다 (logistics_events.py)
logi = LogisticsSim()
logi_lock = threading.RLock()
logi_bridge = LogisticsEventBridge(events, logi, logi_lock, from_cobot=True)   # 파렛트는 협동로봇이 쌓은 것

# ---- 협동로봇 팔레타이징 셀: 프레스 라인 끝 -> 비전 검사 -> 양품은 파렛트, 불량은 NG 수납함 (cobot_events.py)
cobot = CobotSim()
cobot_lock = threading.RLock()
cobot_bridge = CobotEventBridge(events, cobot, cobot_lock)


def cobot_loop():
    last = time.time()
    while True:
        time.sleep(0.05)
        now = time.time()
        with cobot_lock:
            cobot.speed = line.speed         # 프레스 라인과 같은 배속
            cobot.advance(now - last)
        last = now


@app.get("/api/cobot/state")
def cobot_state():
    with cobot_lock:
        return jsonify(cobot.state())


@app.post("/api/cobot/control")
def cobot_control():
    action = (request.get_json(silent=True) or {}).get("action")
    if action != "flush":
        return jsonify(error="flush(모자란 파렛트 마감)만 가능합니다"), 400
    with cobot_lock:
        cobot.request_flush()
    return jsonify(ok=True)


def logistics_loop():
    last = time.time()
    while True:
        time.sleep(0.05)
        now = time.time()
        with logi_lock:
            logi.speed = line.speed          # 프레스 라인과 같은 배속
            logi.advance(now - last)         # advance 가 배속을 곱한다
        last = now


@app.get("/api/logistics/state")
def logistics_state():
    with logi_lock:
        return jsonify(logi.state())


@app.post("/api/logistics/request_inbound")
def logistics_request_inbound():
    with logi_lock:
        logi.request_inbound()
    return jsonify(ok=True)


@app.get("/3d/line")
def line_3d():
    return _page_3d("linescene.html")


# ---- 스마트 팩토리 통합 화면: 라인별 장면(JSON)을 위치만 달리해서 한 장면에 배치한다
SCENES = {"machining": "machining.json", "press_weld_paint": "press_weld_paint.json", "logistics": "logistics.json", "cobot": "cobot.json"}


@app.get("/3d/factory")
def factory_3d():
    return _page_3d("factory.html")


@app.get("/api/factory/layout")
def factory_layout():
    return jsonify(json.loads((BASE / "scenes" / "factory.json").read_text(encoding="utf-8")))


@app.get("/api/scene/<name>")
def scene_by_name(name):
    if name not in SCENES:
        return jsonify(error=f"{', '.join(SCENES)} 중 하나"), 404
    return jsonify(json.loads((BASE / "scenes" / SCENES[name]).read_text(encoding="utf-8")))


@app.get("/api/factory/state")
def factory_state():
    with lock:
        m = machining_state()
    with line_lock:
        p = line.state()
    with logi_lock:
        lg = logi.state()
    with cobot_lock:
        cb = cobot.state()
    return jsonify({"machining": m, "press": p, "logistics": lg, "cobot": cb})


@app.get("/api/line/scene")
def line_scene():
    return jsonify(json.loads(SCENE_FILE.read_text(encoding="utf-8")))


@app.get("/api/line/state")
def line_state():
    with line_lock:
        return jsonify(line.state())


@app.post("/api/line/control")
def line_control():
    action = (request.get_json(silent=True) or {}).get("action")
    if action not in ("start", "stop", "reset"):
        return jsonify(error="start, stop, reset 중 하나"), 400
    with line_lock:
        getattr(line, action)()
    return jsonify(ok=True)


@app.post("/api/line/fault")
def line_fault():
    mode = (request.get_json(silent=True) or {}).get("mode")
    if mode not in LINE_FAULTS:
        return jsonify(error=f"{', '.join(LINE_FAULTS)} 중 하나"), 400
    with line_lock:
        line.set_fault(mode)
    return jsonify(ok=True)


@app.post("/api/line/speed")
def line_speed():
    value = (request.get_json(silent=True) or {}).get("value")
    if not isinstance(value, (int, float)) or not 0.5 <= value <= 8:
        return jsonify(error="0.5~8 사이의 숫자"), 400
    with line_lock:
        line.set_speed(value)
    return jsonify(ok=True)


def machining_state():
    """가공 라인의 화면용 상태 (lock 을 잡은 상태에서 부른다)."""
    out = {k: int(sim.dev[k]) for k in STATE_KEYS}
    out["pieces"] = tracker.snapshot()
    out["mode"] = sim.piece_mode
    out["fault"] = getattr(sim, "fault_mode", "none")
    out["ai"] = events.detector.status()
    out["connected"] = getattr(sim, "connected", True)
    out["error"] = getattr(sim, "error", "")
    out["derived"] = view.snapshot()
    return out


@app.get("/api/terms")
def terms():
    """화면에 보이는 이름 사전 (현장 용어 / 장비 원명칭). src/terms.json"""
    return jsonify(json.loads((BASE / "terms.json").read_text(encoding="utf-8")))


@app.get("/api/state")
def state():
    with lock:
        return jsonify(machining_state())


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


@app.post("/api/fault")
def set_fault():
    """시뮬레이터에 결함을 주입하거나 해제한다 (이상 감지가 잡는지 확인하는 용도)."""
    mode = (request.get_json(silent=True) or {}).get("mode")
    if mode not in FAULTS:
        return jsonify(error=f"{', '.join(FAULTS)} 중 하나"), 400
    with lock:
        sim.set_fault(mode)
        events.sim_fault(mode, "web")
    return jsonify(ok=True)


@app.post("/api/ai/relearn")
def relearn():
    """이상 감지의 기준값을 버리고 처음부터 다시 학습한다."""
    with lock:
        events.detector.reset()
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
    threading.Thread(target=line_loop, daemon=True).start()
    threading.Thread(target=logistics_loop, daemon=True).start()
    threading.Thread(target=cobot_loop, daemon=True).start()
    app.run(host="127.0.0.1", port=5001, debug=False)
