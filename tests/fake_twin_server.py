"""시험용 가짜 트윈 서버: 조작 API 요청을 기록하고, 라인 상태를 돌려준다 (MES 페이지의 조작 버튼 시험에 쓴다)."""
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


def start(state=None):
    state = state or {"running": False, "draining": False, "speed": 1, "counts": {"in": 12, "good": 9, "scrap": 1}}
    log = []

    class H(BaseHTTPRequestHandler):
        def log_message(self, *a): pass

        def _send(self, code, body):
            data = json.dumps(body).encode("utf-8")
            self.send_response(code); self.send_header("Content-Type", "application/json"); self.send_header("Content-Length", str(len(data))); self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            log.append(("GET", self.path, None))
            self._send(200, state) if self.path == "/api/line/state" else self._send(404, {"error": "no"})

        def do_POST(self):
            n = int(self.headers.get("Content-Length", 0) or 0)
            body = json.loads(self.rfile.read(n) or b"{}")
            log.append(("POST", self.path, body))
            if self.path == "/api/line/control" and body.get("action") == "start":
                state["running"] = True
            self._send(200, {"ok": True}) if self.path != "/api/nope" else self._send(400, {"error": "bad"})

    srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, f"http://127.0.0.1:{srv.server_address[1]}", log, state
