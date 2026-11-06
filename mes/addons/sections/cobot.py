import time
from datetime import timedelta

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from src import factory_dash as fd
from src import oee, twin_api
from src.ui import alert_badge, kpi_row, require_role, setup_page, show_dataframe

setup_page("협동로봇 셀")
require_role("ADMIN", "OPERATOR", "INSPECTOR")
st.header("협동로봇 팔레타이징 셀")
st.caption("프레스 · 용접 · 도장 라인 끝에서 협동로봇이 워크를 비전으로 검사하고, 양품은 파렛트에 5개씩 쌓고, 불량은 NG 수납함에 넣습니다. "
           "파렛트가 차면 물류 · 출하 구역으로 넘어갑니다.")

c1, c2 = st.columns([3, 1])
with c1:
    period = st.selectbox("집계 기간 (실제 시각 기준)", ["전체", "최근 10분", "최근 30분", "최근 1시간"])
with c2:
    st.write("")
    auto_refresh = st.checkbox("자동 새로고침 (3초)", value=False)
minutes = {"최근 10분": 10, "최근 30분": 30, "최근 1시간": 60}.get(period)
since = pd.Timestamp.now(tz="UTC") - timedelta(minutes=minutes) if minutes else None

twin_url = st.text_input("트윈 서버 주소", value="http://localhost:5001",
                                 help="MES를 다른 컴퓨터에서 열었다면 localhost 대신 트윈 서버가 있는 컴퓨터의 주소를 넣으세요.")
twin_api.control_bar(st, twin_url, extra=[("파렛트 마감 (모자란 파렛트도 지금 마감)", "/api/cobot/control", {"action": "flush"})], key="cobot",
                     note='이 셀은 프레스 · 용접 · 도장 라인 끝에서 워크를 받아 일합니다. 그래서 "라인 시작"이 프레스 라인 시작이고, 라인 끝에서 워크가 나오기 시작하면(약 25초 뒤) 로봇이 움직입니다.')

with st.expander("3D 협동로봇 셀", expanded=True):
    t2, t3 = st.columns([3, 1])
    with t2:
        show_cards = st.checkbox("조작 카드 포함", value=False, help="'파렛트 마감' 버튼과 다른 라인의 카드를 3D 화면 위에 함께 표시합니다.")
    with t3:
        height = st.number_input("높이", min_value=300, max_value=1300, value=620, step=20)
    src = f"{twin_url.rstrip('/')}/3d/factory?embed={'1' if show_cards else 'scene'}&focus=cobot"
    try:
        import streamlit.components.v1 as components
        components.iframe(src, height=int(height), scrolling=False)
    except Exception:
        st.info("3D 화면을 이 페이지 안에 표시하지 못했습니다. 아래 링크로 새 탭에서 여세요.")
    st.markdown(f"[새 탭에서 열기]({src})")
    st.caption("사용법: 프레스 · 용접 · 도장 라인을 시작하면(공장 화면의 프레스 라인 카드) 라인 끝의 워크가 이 셀의 인피드 컨베이어로 들어옵니다. "
               "라인이 멈춘 뒤 셀이 비면 모자란 파렛트도 자동으로 마감하고, '파렛트 마감' 버튼으로 바로 마감할 수도 있습니다.")

st.markdown("---")

ev_c = oee.load_events(since, line_id=fd.COBOT)
cs = fd.cobot_summary(ev_c)
if cs is None:
    st.info("아직 협동로봇 셀 이벤트가 없습니다. 트윈 서버와 어댑터가 켜져 있는지 확인하고, 프레스 · 용접 · 도장 라인을 시작하세요. 기간을 '전체'로 바꿔 보는 것도 방법입니다.")
else:
    age = (pd.Timestamp.now(tz="UTC") - ev_c["ts"].max()).total_seconds()
    st.caption(f"마지막 이벤트: {ev_c['ts'].max().tz_convert('Asia/Seoul'):%H:%M:%S} ({age:.0f}초 전)")
    if age > 120:
        alert_badge("협동로봇 셀의 마지막 이벤트가 2분 넘게 전입니다. 프레스 라인이 멈춰 있거나 어댑터가 꺼졌을 수 있습니다.", "warning")
    st.subheader("한눈에 보기")
    kpi_row(
        [
            ("비전 검사", f"{cs['inspected']:,} 개", "kpi-blue"),
            ("불량 검출", f"{cs['ng']:,} 개 ({(cs['ng'] / cs['inspected'] * 100) if cs['inspected'] else 0:.1f}%)", "kpi-red"),
            ("양품 적재", f"{cs['good']:,} 개", "kpi-green"),
            ("완성 파렛트", f"{cs['pallets']:,} 개 (모자란 것 {cs['partial']})", "kpi-gold"),
            ("집기 사이클 평균", f"{cs['avg_cycle_s']:.2f} 초", "kpi-purple"),
            ("비전 신뢰도 평균", f"{cs['avg_conf'] * 100:.1f}%", "kpi-teal"),
        ],
        columns=3,
    )
    if cs["avg_cycle_s"] and cs["avg_cycle_s"] > 8.0:
        alert_badge("로봇 사이클이 프레스 라인 사이클(8초)보다 깁니다. 인피드 컨베이어에 워크가 쌓일 수 있습니다.", "warning")

    l1, l2 = st.columns(2)
    with l1:
        st.subheader("집기 사이클 시간")
        cy = cs["cycles"]
        if cy.empty:
            st.info("완료된 사이클이 없습니다.")
        else:
            fig = go.Figure()
            fig.add_trace(go.Scatter(x=list(range(1, len(cy) + 1)), y=cy["cycle_s"], mode="lines+markers", name="사이클"))
            fig.add_hline(y=8.0, line_dash="dash", line_color="#ef4b4b", annotation_text="프레스 라인 사이클(8초)")
            fig.update_layout(xaxis_title="사이클 번호", yaxis_title="초", margin=dict(l=10, r=10, t=10, b=10), height=280, legend=dict(orientation="h"))
            st.plotly_chart(fig, use_container_width=True)
    with l2:
        st.subheader("비전 검사 결과")
        fig2 = go.Figure(go.Bar(x=["양품", "불량"], y=[cs["good"], cs["ng"]], marker_color=["#33c27f", "#ef4b4b"]))
        fig2.update_layout(yaxis_title="개", margin=dict(l=10, r=10, t=10, b=10), height=280)
        st.plotly_chart(fig2, use_container_width=True)

    r1, r2 = st.columns([3, 2])
    with r1:
        st.subheader("최근 검사와 적재")
        show_dataframe(cs["recent"], "검사 기록이 없습니다.")
    with r2:
        st.subheader("파렛트 마감 이력")
        show_dataframe(cs["pallet_table"], "아직 마감된 파렛트가 없습니다.")

    with st.expander("계산 근거와 동작 설명"):
        st.markdown(
            f"""
- **집기 사이클** = 로봇이 집기 위치로 이동을 시작한 때부터 워크를 놓을 때까지의 시간입니다 (평균 {cs['avg_cycle_s']:.2f}초, 최소 {cs['min_cycle_s']:.2f}초, 최대 {cs['max_cycle_s']:.2f}초).
  프레스 라인이 8초마다 워크를 내보내므로, 이보다 빠르면 인피드에 워크가 쌓이지 않습니다.
- **불량 검출** = 비전 검사 결과가 불량(용접 불량)인 워크 수입니다. 불량은 파렛트에 쌓지 않고 NG 수납함에 넣어서 출하되지 않습니다.
- **비전 신뢰도**는 검사 장치가 알려 주는 확신 정도입니다 (이 시뮬레이터에서는 표시용 값입니다).
- **완성 파렛트**는 양품 5개가 차서 마감한 파렛트이고, 라인이 멈춘 뒤 셀이 비어서 모자란 채로 마감한 것은 "모자란 것"으로 따로 셉니다.
- 로봇팔은 어깨(좌우), 어깨, 팔꿈치, 손목 4관절이고, 집는 위치와 파렛트 칸은 역기구학으로 관절 각도를 계산합니다.
"""
        )

if auto_refresh:
    time.sleep(3)
    st.rerun()
