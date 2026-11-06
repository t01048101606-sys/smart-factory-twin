"""MES 페이지의 라인 조작 막대(twin_api.control_bar)를 시험합니다. 가짜 트윈 서버가 받은 요청으로 확인합니다.

 - 버튼을 누르면 정확한 API(시작, 정지, 리셋, 추가 버튼)가 불린다
 - 배속을 바꾸면 한 번만 적용되고, 화면을 다시 그려도 반복해서 보내지 않는다
 - 눌리지 않은 버튼(흉내 낸 화면의 MagicMock)은 아무것도 보내지 않는다
 - 서버가 꺼져 있어도 예외 없이 경고와 오류 메시지를 보여 준다

실행 (프로젝트 폴더에서):  python tests/test_twin_api.py
"""
import importlib.util
import sys
from pathlib import Path
from unittest.mock import MagicMock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tests"))
import fake_twin_server  # noqa: E402

spec = importlib.util.spec_from_file_location("twin_api", ROOT / "mes" / "addons" / "src" / "twin_api.py")
ta = importlib.util.module_from_spec(spec); spec.loader.exec_module(ta)


class FakeSt:
    """누를 버튼 이름과 고를 배속을 정할 수 있는 흉내 화면."""
    def __init__(self, click=(), speed=1):
        self.click, self.speed = set(click), speed
        self.session_state, self.out = {}, {"success": [], "error": [], "warning": [], "caption": []}

    def markdown(self, *a, **k): pass
    def columns(self, n): return [_Col(self) for _ in range(n)]
    def success(self, m): self.out["success"].append(m)
    def error(self, m): self.out["error"].append(m)
    def warning(self, m): self.out["warning"].append(m)
    def caption(self, m): self.out["caption"].append(m)


class _Col:
    def __init__(self, st): self.st = st
    def button(self, label, key=None): return True if label in self.st.click else MagicMock()   # 안 누른 버튼은 MagicMock (True 가 아님)
    def selectbox(self, label, options, index=0, key=None): return self.st.speed


srv, url, log, state = fake_twin_server.start()
posts = lambda: [(p, b) for m, p, b in log if m == "POST"]
EXTRA = [("입고 요청", "/api/logistics/request_inbound", {}), ("파렛트 마감", "/api/cobot/control", {"action": "flush"})]

# 1) 누른 버튼만 정확한 API 로 간다
st = FakeSt(click=["▶ 라인 시작", "입고 요청"])
ta.control_bar(st, url, extra=EXTRA, key="t1")
assert posts() == [("/api/line/control", {"action": "start"}), ("/api/logistics/request_inbound", {})], posts()
assert st.out["success"] and "입고 요청: 완료" in st.out["success"][-1] and not st.out["error"]
assert any("프레스 · 용접 · 도장 라인" in c and "투입 12" in c and "양품 9" in c for c in st.out["caption"]), st.out["caption"]   # 상태 줄
print("버튼: '라인 시작'과 '입고 요청'만 눌렀더니 해당 API 두 개만 호출됨, 상태 줄(투입 12, 양품 9) 표시")

# 2) 정지, 리셋, 파렛트 마감
log.clear()
for label, want in (("■ 정지 (남은 부품을 내보낸 뒤)", ("/api/line/control", {"action": "stop"})), ("↺ 리셋", ("/api/line/control", {"action": "reset"})),
                    ("파렛트 마감", ("/api/cobot/control", {"action": "flush"}))):
    log.clear()
    ta.control_bar(FakeSt(click=[label]), url, extra=EXTRA, key="t2")
    assert posts() == [want], (label, posts())
print("정지, 리셋, 파렛트 마감 API 확인")

# 3) 배속: 서버가 x1 일 때 x4 를 고르면 한 번만 보내고, 다시 그려도 반복하지 않는다
log.clear()
st = FakeSt(speed=4)
ta.control_bar(st, url, key="t3")
ta.control_bar(st, url, key="t3")           # 같은 세션 상태로 다시 그림
assert posts() == [("/api/line/speed", {"value": 4})], posts()
log.clear()
ta.control_bar(FakeSt(speed=1), url, key="t4")      # 서버 배속과 같으면 보내지 않는다 (페이지를 열기만 해서는 아무것도 바꾸지 않는다)
assert posts() == [], posts()
print("배속: x4 선택은 한 번만 적용, 같은 값이나 페이지를 열기만 할 때는 보내지 않음")

# 4) 아무 버튼도 안 눌렀다 (MagicMock 버튼) -> 아무것도 안 보낸다
log.clear()
ta.control_bar(FakeSt(), url, extra=EXTRA, key="t5")
assert posts() == []

# 5) 서버가 거절하면 (HTTP 400) 오류 메시지, 꺼져 있으면 경고 + 오류. 예외는 없다
ok, msg = ta.post(url, "/api/nope", {})
assert not ok and "400" in msg
srv.shutdown(); srv.server_close()
st = FakeSt(click=["▶ 라인 시작"])
ta.control_bar(st, url, key="t6")
assert st.out["error"] and "연결하지 못했습니다" in st.out["error"][-1] and st.out["warning"], st.out
assert ta.get_json(url, "/api/line/state") is None
print("서버가 꺼져 있어도 예외 없이 경고와 오류 메시지 ('트윈 서버에 연결하지 못했습니다')")
print("\n테스트 통과")
