"""MES 페이지에서 트윈 서버(Flask, 기본 http://localhost:5001)의 조작 API 를 부르는 도구.

3D 화면 안의 카드를 켜지 않아도 MES 페이지 자체의 버튼으로 라인을 시작, 정지, 리셋하고 배속을 바꿀 수 있다.
MES(Streamlit)가 서버 쪽에서 직접 호출하므로 트윈 서버와 같은 컴퓨터에서 MES 를 열어야 하고, 다른 컴퓨터면 '트윈 서버 주소'에 그 컴퓨터 주소를 넣는다.
"""
from __future__ import annotations

import json
import urllib.error
import urllib.request

SPEEDS = (1, 2, 4, 8)


def _url(base: str, path: str) -> str:
    return base.rstrip("/") + path


def post(base: str, path: str, body: dict | None = None, timeout: float = 3.0) -> tuple[bool, str]:
    req = urllib.request.Request(_url(base, path), data=json.dumps(body or {}).encode("utf-8"),
                                 headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return True, r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return False, f"서버가 요청을 거절했습니다 (HTTP {e.code})"
    except Exception as e:  # 서버가 꺼져 있거나 주소가 틀린 경우
        return False, f"트윈 서버에 연결하지 못했습니다 ({_url(base, path)}): {e}"


def get_json(base: str, path: str, timeout: float = 2.0):
    try:
        with urllib.request.urlopen(_url(base, path), timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8"))
    except Exception:
        return None


def control_bar(st, base: str, extra=(), key: str = "ctl", note: str = ""):
    """프레스 · 용접 · 도장 라인 조작(시작, 정지, 리셋, 배속)과 이 페이지만의 추가 버튼을 보여 준다.
    extra: [(버튼 이름, API 경로, 본문 dict), ...]"""
    st.markdown("##### 라인 조작")
    actions = [("▶ 라인 시작", "/api/line/control", {"action": "start"}),
               ("■ 정지 (남은 부품을 내보낸 뒤)", "/api/line/control", {"action": "stop"}),
               ("↺ 리셋", "/api/line/control", {"action": "reset"})] + list(extra)
    state = get_json(base, "/api/line/state")
    cols = st.columns(len(actions) + 1)
    for i, (label, path, body) in enumerate(actions):
        if cols[i].button(label, key=f"{key}_btn{i}") is True:          # 흉내 낸 화면에서는 눌린 것으로 치지 않는다
            ok, msg = post(base, path, body)
            st.session_state[f"{key}_msg"] = (ok, f"{label}: 완료" if ok else f"{label}: {msg}")
    cur = int(state.get("speed", 1)) if state and state.get("speed") in SPEEDS else 1
    speed = cols[len(actions)].selectbox("배속", list(SPEEDS), index=list(SPEEDS).index(cur), key=f"{key}_speed")
    applied = st.session_state.get(f"{key}_speed_applied", cur)
    if speed != applied and speed in SPEEDS:
        ok, msg = post(base, "/api/line/speed", {"value": speed})
        st.session_state[f"{key}_msg"] = (ok, f"배속 x{speed}: 완료" if ok else f"배속: {msg}")
    st.session_state[f"{key}_speed_applied"] = speed if speed in SPEEDS else applied
    last = st.session_state.get(f"{key}_msg")
    if last:
        (st.success if last[0] else st.error)(last[1])
    if state is None:
        st.warning("트윈 서버에 연결하지 못했습니다. 트윈 서버(`python src\\server.py plc\\1102`)가 켜져 있는지, 아래 '트윈 서버 주소'가 맞는지 확인하세요.")
    else:
        c = state.get("counts", {})
        run = "정지 중 (남은 부품 배출)" if state.get("draining") else ("가동 중" if state.get("running") else "정지")
        st.caption(f"프레스 · 용접 · 도장 라인: **{run}** · 투입 {c.get('in', 0)} · 양품 {c.get('good', 0)} · 불량 {c.get('scrap', 0)} · 배속 x{state.get('speed', 1):g}")
    if note:
        st.caption(note)
