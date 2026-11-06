import time
from datetime import timedelta

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from src import oee
from src.db import fetch_dataframe
from src.ui import alert_badge, kpi_row, require_role, setup_page, show_dataframe

setup_page("설비 현황 / OEE")
require_role("ADMIN", "OPERATOR", "INSPECTOR")
st.title("설비 현황 · OEE")
st.caption("PLC 트윈이 보내는 설비 이벤트(machine_event)로 가동 상태와 OEE를 계산합니다.")

# ------------------------------------------------------------------ 조건
col_a, col_b, col_c = st.columns([2, 2, 1])
with col_a:
    period = st.selectbox("집계 기간", ["전체", "최근 10분", "최근 30분", "최근 1시간"])
with col_b:
    ideal_text = st.text_input("고정 소요 시간(초) 직접 지정 (비우면 관측 최솟값 사용)", value="")
with col_c:
    st.write("")
    auto_refresh = st.checkbox("자동 새로고침 (3초)", value=False)

since = None
minutes = {"최근 10분": 10, "최근 30분": 30, "최근 1시간": 60}.get(period)
if minutes:
    since = pd.Timestamp.now(tz="UTC") - timedelta(minutes=minutes)

ideal_override = None
if ideal_text.strip():
    try:
        ideal_override = float(ideal_text)
    except ValueError:
        st.warning("고정 소요 시간은 숫자로 입력하세요.")

# ------------------------------------------------------------------ 트윈 화면
with st.expander("가공 공정 2D 트윈", expanded=True):
    c1, c2, c3, c4 = st.columns([3, 2, 1, 1])
    with c1:
        twin_url = st.text_input(
            "트윈 서버 주소", value="http://localhost:5001",
            help="MES를 다른 컴퓨터에서 열었다면 localhost 대신 트윈 서버가 있는 컴퓨터의 주소를 넣으세요.")
    with c2:
        view_only = st.checkbox("조작 패널 숨기기 (보기 전용)", value=False)
    with c3:
        use_3d = st.checkbox("3D로 보기", value=False)
    with c4:
        height = st.number_input("높이", min_value=300, max_value=1200, value=720, step=20)
    src = f"{twin_url.rstrip('/')}/{'3d' if use_3d else ''}?embed={'view' if view_only else '1'}"
    try:
        import streamlit.components.v1 as components
        components.iframe(src, height=int(height), scrolling=True)
    except Exception:
        st.info("트윈 화면을 이 페이지 안에 표시하지 못했습니다. 아래 링크로 새 탭에서 여세요.")
    st.markdown(f"[새 탭에서 트윈 열기]({src})")

st.markdown("---")

# ------------------------------------------------------------------ OEE
events = oee.load_events(since, line_id="LINE-MACHINING-01")
result = oee.compute_oee(events, ideal_override)

if result is None:
    st.info("선택한 기간에 설비 이벤트가 없습니다. 트윈 서버와 어댑터(`mes_adapter.py`)가 켜져 있는지 확인하고, "
            "트윈 화면에서 연속동작을 눌러 주세요. 기간을 '전체'로 바꿔 보는 것도 방법입니다.")
else:
    age = (pd.Timestamp.now(tz="UTC") - result["t1"]).total_seconds()
    last_kst = result["t1"].tz_convert("Asia/Seoul").strftime("%H:%M:%S")
    st.caption(f"마지막 설비 이벤트: {last_kst} ({age:.0f}초 전)")
    if age > 60:
        alert_badge("마지막 이벤트가 1분 넘게 전입니다. 어댑터(`mes_adapter.py`)가 꺼졌거나 트윈이 멈춰 있을 수 있습니다.", "warning")
    if result["cycles"] == 0 and result["total"] == 0:
        alert_badge("선택한 기간에 완료된 사이클이 없어서 OEE를 계산할 수 없습니다 (0%로 표시됩니다).", "warning")
    pct = lambda x: f"{x * 100:.1f}%"
    st.subheader("OEE (설비종합효율)")
    kpi_row(
        [
            ("OEE", pct(result["oee"]), "kpi-red"),
            ("가용률", pct(result["availability"]), "kpi-blue"),
            ("성능률", pct(result["performance"]), "kpi-purple"),
            ("품질률", pct(result["quality"]), "kpi-green"),
            ("분류된 작업물", f"{result['total']:,} 개", "kpi-gold"),
            ("불량(비금속)", f"{result['defect']:,} 개", "kpi-teal"),
        ],
        columns=3,
    )
    if result["oee"] < 0.6:
        alert_badge("OEE가 60% 미만입니다. 아래 세 지표 중 낮은 항목을 확인하세요.", "warning")

    with st.expander("계산 근거 보기", expanded=False):
        overhead = result["ideal_overhead_s"]
        st.markdown(
            f"""
- **가용률** = 가동 시간 / 계획 시간 = {result['run_s']:.0f}초 / {result['planned_s']:.0f}초 = **{pct(result['availability'])}**
- **성능률** = 이상 사이클 시간 합 / 가동 시간 = {result['ideal_total_s']:.0f}초 / {result['run_s']:.0f}초 = **{pct(result['performance'])}**
  - 이상 사이클 시간 = 고정 소요 시간({'-' if overhead is None else f'{overhead:.2f}'}초) + 가공 시간(D10 설정)
  - 완료 사이클 {result['cycles']}회
- **품질률** = 금속(정상) / 분류된 작업물 = {result['good']} / {result['total']} = **{pct(result['quality'])}**
- 비금속은 이종 재질 혼입 불량으로 봅니다 (MES 검사의 불량 사유 `MAT_MIX`와 같은 기준).
"""
        )

    left, right = st.columns(2)
    with left:
        st.subheader("사이클 시간 추이")
        cdf = result["cycle_df"]
        if cdf.empty:
            st.info("완료된 사이클이 없습니다.")
        else:
            x = list(range(1, len(cdf) + 1))
            fig = go.Figure()
            fig.add_trace(go.Scatter(x=x, y=cdf["cycle_time_s"], mode="lines+markers", name="실제"))
            fig.add_trace(go.Scatter(x=x, y=cdf["ideal_s"], mode="lines", name="이상", line=dict(dash="dash")))
            fig.update_layout(xaxis_title="사이클 번호", yaxis_title="초", margin=dict(l=10, r=10, t=10, b=10),
                              height=300, legend=dict(orientation="h"))
            st.plotly_chart(fig, use_container_width=True)
    with right:
        st.subheader("OEE 구성 요소")
        names = ["가용률", "성능률", "품질률", "OEE"]
        vals = [result["availability"], result["performance"], result["quality"], result["oee"]]
        fig2 = go.Figure(go.Bar(x=names, y=[v * 100 for v in vals], text=[pct(v) for v in vals], textposition="auto"))
        fig2.update_layout(yaxis=dict(range=[0, 100], title="%"), margin=dict(l=10, r=10, t=10, b=10), height=300)
        st.plotly_chart(fig2, use_container_width=True)

    st.subheader("최근 설비 이벤트")
    show_dataframe(oee.recent_events(events, 40), "표시할 이벤트가 없습니다.")

# ------------------------------------------------------------------ 작업지시별 이벤트
st.subheader("작업지시별 설비 이벤트 수")
try:
    wo_df = fetch_dataframe(
        """
        SELECT w.work_order_no AS 작업지시, w.status AS 상태, w.planned_qty AS 계획수량,
               COUNT(e.event_id) AS 이벤트수
        FROM work_order AS w
        LEFT JOIN machine_event AS e ON e.work_order_id = w.work_order_id
        GROUP BY w.work_order_id
        ORDER BY w.work_order_id DESC
        LIMIT 10
        """
    )
    show_dataframe(wo_df, "작업지시가 없습니다.")
except Exception:
    st.info("machine_event 테이블이 아직 없습니다. `python src\\mes_adapter.py --init-only`를 먼저 실행하세요.")

if auto_refresh:
    time.sleep(3)
    st.rerun()
