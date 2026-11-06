import streamlit as st

from src.ui import require_role, setup_page

setup_page("공정 3D")
require_role("ADMIN", "OPERATOR", "INSPECTOR")
st.title("공정 3D 보기")
st.caption("트윈 서버가 보내는 공정 상태를 3D로 보여 줍니다. 공정을 골라서 같은 화면에서 비교해 보세요.")

c1, c2, c3 = st.columns([2, 3, 1])
with c1:
    line = st.selectbox("공정", ["가공 라인 (PLC)", "프레스 · 용접 · 도장 라인"])
with c2:
    twin_url = st.text_input("트윈 서버 주소", value="http://localhost:5001",
                             help="MES를 다른 컴퓨터에서 열었다면 localhost 대신 트윈 서버가 있는 컴퓨터의 주소를 넣으세요.")
with c3:
    height = st.number_input("높이", min_value=300, max_value=1300, value=820, step=20)
view_only = st.checkbox("조작 패널 숨기기 (보기 전용)", value=False)

path = "/3d" if line.startswith("가공") else "/3d/line"
src = f"{twin_url.rstrip('/')}{path}?embed={'view' if view_only else '1'}"
try:
    import streamlit.components.v1 as components
    components.iframe(src, height=int(height), scrolling=True)
except Exception:
    st.info("3D 화면을 이 페이지 안에 표시하지 못했습니다. 아래 링크로 새 탭에서 여세요.")
st.markdown(f"[새 탭에서 열기]({src})")

with st.expander("공정 설명"):
    st.markdown(
        """
- **가공 라인 (PLC)**: 매거진 → 드릴 가공 → 컨베이어 → 금속/비금속 분류. PLC 프로그램의 센서와 출력이 그대로 반영됩니다. MES의 작업지시, LOT 추적, OEE와 이어집니다.
- **프레스 · 용접 · 도장 라인**: 파이썬 시뮬레이터로 돌리는 자동차 부품 라인(MES의 PRESS, WELD, PAINT 공정과 같은 구성)입니다.
  결함 주입(용접 속도 저하, 프레스 정지, 도장 정지)을 하면 병목이 옮겨가고 앞뒤 공정이 막히거나 노는 모습을 볼 수 있습니다.
  공정 색: 초록 = 작업 중, 노랑 = 막힘(다음 칸이 차 있음), 회색 = 대기(일감 없음), 빨강 = 정지.
"""
    )
