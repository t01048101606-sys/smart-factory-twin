import time
from datetime import timedelta

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from src import lineoee, oee
from src.db import fetch_dataframe
from src.ui import alert_badge, kpi_row, require_role, setup_page, show_dataframe

LINE_ID = "LINE-PRESS-WELD-PAINT-01"

setup_page("프레스 · 용접 · 도장 라인")
require_role("ADMIN", "OPERATOR", "INSPECTOR")
st.title("프레스 · 용접 · 도장 라인 현황")
st.caption("라인 시뮬레이터의 설비 이벤트로 OEE와 공정별 가동 상태를 계산하고, 작업지시, LOT, 검사는 MES 기록과 이어서 봅니다.")

col_a, col_b = st.columns([3, 1])
with col_a:
    period = st.selectbox("집계 기간 (실제 시각 기준)", ["전체", "최근 10분", "최근 30분", "최근 1시간"])
with col_b:
    st.write("")
    auto_refresh = st.checkbox("자동 새로고침 (3초)", value=False)
minutes = {"최근 10분": 10, "최근 30분": 30, "최근 1시간": 60}.get(period)
since = pd.Timestamp.now(tz="UTC") - timedelta(minutes=minutes) if minutes else None

with st.expander("3D 라인 · 결함 주입", expanded=True):
    c1, c2 = st.columns([4, 1])
    with c1:
        twin_url = st.text_input("트윈 서버 주소", value="http://localhost:5001",
                                 help="MES를 다른 컴퓨터에서 열었다면 localhost 대신 트윈 서버가 있는 컴퓨터의 주소를 넣으세요.")
    with c2:
        height = st.number_input("높이", min_value=300, max_value=1300, value=640, step=20)
    src = f"{twin_url.rstrip('/')}/3d/line?embed=1"
    try:
        import streamlit.components.v1 as components
        components.iframe(src, height=int(height), scrolling=True)
    except Exception:
        st.info("3D 화면을 이 페이지 안에 표시하지 못했습니다. 아래 링크로 새 탭에서 여세요.")
    st.markdown(f"[새 탭에서 열기]({src})")
    st.caption("사용법: 3D 화면에서 **시작**을 누르고, 배속을 올려 몇 분 돌린 뒤 결함 주입(용접 속도 저하, 프레스 정지, 도장 정지)을 해 보세요. "
               "아래 OEE, 병목, 공정 상태가 따라 바뀝니다. 정지는 라인에 남은 부품이 모두 나온 뒤에 멈춥니다.")

st.markdown("---")

events = oee.load_events(since, line_id=LINE_ID)
res = lineoee.compute_line_oee(events)
if res is None:
    st.info("아직 이 라인의 설비 이벤트가 없습니다. 트윈 서버와 어댑터(`mes_adapter.py`)가 켜져 있는지 확인하고, 3D 화면에서 시작을 누르세요.")
else:
    age = (pd.Timestamp.now(tz="UTC") - events["ts"].max()).total_seconds()
    st.caption(f"마지막 이벤트: {events['ts'].max().tz_convert('Asia/Seoul'):%H:%M:%S} ({age:.0f}초 전) · 시뮬레이션 시간 {res['t1'] - res['t0']:.0f}초")
    if age > 60:
        alert_badge("마지막 이벤트가 1분 넘게 전입니다. 라인이 정지했거나 어댑터가 꺼졌을 수 있습니다.", "warning")

    pct = lambda x: f"{x * 100:.1f}%"
    st.subheader("OEE (라인 종합효율)")
    kpi_row(
        [
            ("OEE", pct(res["oee"]), "kpi-red"),
            ("가용률", pct(res["availability"]), "kpi-blue"),
            ("성능률", pct(res["performance"]), "kpi-purple"),
            ("품질률", pct(res["quality"]), "kpi-green"),
            ("처리량", f"{res['throughput_per_min']:.2f} 개/분", "kpi-gold"),
            ("양품 / 불량", f"{res['good']} / {res['scrap']} 개", "kpi-teal"),
        ],
        columns=3,
    )
    if res["bottleneck"]:
        alert_badge(f"병목 공정: {lineoee.NAMES[res['bottleneck']]} (가동 시간 중 작업 중 + 정지 "
                    f"{(res['util'][res['bottleneck']]['working'] + res['util'][res['bottleneck']]['down']) * 100:.0f}%). "
                    "앞 공정은 막히고 뒤 공정은 일감을 기다립니다.", "warning" if res["performance"] < 0.8 else "ok")

    with st.expander("계산 근거 보기"):
        st.markdown(
            f"""
- **가용률** = (가동 시간 - 정지 시간) / 가동 시간 = ({res['run_s']:.0f}초 - {res['down_s']:.0f}초) / {res['run_s']:.0f}초 = **{pct(res['availability'])}**
  - 정지 시간: 가동 중에 어느 한 공정이라도 정지(프레스 정지, 도장 정지)였던 시간
- **성능률** = 병목 공칭 사이클 x 완성 수량 / 정지 없이 가동한 시간 = {res['ideal_cycle_s'] or 0:.1f}초 x {res['done']}개 / {res['work_s']:.0f}초 = **{pct(res['performance'])}**
  - 용접이 느려지면 병목이 옮겨가 처리량이 줄고 성능률이 떨어집니다.
- **품질률** = 양품 / (양품 + 불량) = {res['good']} / {res['done']} = **{pct(res['quality'])}** (불량 = 용접 불량)
- 시간은 시뮬레이터 시간(`sim_t`) 기준이라 배속을 올려도 맞습니다.
"""
        )

    st.subheader("공정별 시간 구성")
    tbl = lineoee.station_table(res)
    fig = go.Figure()
    for key, color in (("작업 중", "#33c27f"), ("막힘", "#f2c230"), ("대기", "#7a8696"), ("정지", "#ef4b4b")):
        fig.add_trace(go.Bar(x=tbl["공정"], y=tbl[key], name=key, marker_color=color))
    fig.update_layout(barmode="stack", yaxis_title="가동 시간 대비 %", margin=dict(l=10, r=10, t=10, b=10), height=300,
                      legend=dict(orientation="h"))
    st.plotly_chart(fig, use_container_width=True)
    show_dataframe(tbl, "공정 데이터가 없습니다.")

    st.subheader("결함 주입의 영향")
    show_dataframe(lineoee.fault_report(events, res), "아직 결함을 주입하지 않았습니다. 3D 화면에서 '결함 주입'을 선택해 보세요.")

st.subheader("작업지시 · LOT · 검사")
try:
    wo = fetch_dataframe(
        """
        SELECT w.work_order_no AS 작업지시, w.status AS 상태, w.planned_qty AS 계획수량,
               (SELECT MAX(o.qty) FROM operation AS o WHERE o.work_order_id = w.work_order_id) AS 실적수량,
               (SELECT COUNT(*) FROM operation AS o WHERE o.work_order_id = w.work_order_id) AS 공정실행,
               (SELECT i.result FROM inspection AS i JOIN operation AS o ON o.output_lot_id = i.lot_id
                 WHERE o.work_order_id = w.work_order_id) AS 검사결과,
               (SELECT i.defect_qty FROM inspection AS i JOIN operation AS o ON o.output_lot_id = i.lot_id
                 WHERE o.work_order_id = w.work_order_id) AS 불량수
        FROM work_order AS w JOIN item AS p ON p.item_id = w.product_item_id
        WHERE p.item_code = 'FG-BRKA'
        ORDER BY w.work_order_id DESC LIMIT 12
        """
    )
    show_dataframe(wo, "이 라인의 작업지시가 아직 없습니다.")
except Exception:
    st.info("MES 테이블을 읽지 못했습니다. `python src\\mes_adapter.py --init-only`를 먼저 실행하세요.")
st.caption("자재가 어느 완제품이 되었는지는 **LOT추적** 페이지에서 냉연강판(RM-STEEL) LOT를 정방향으로 추적해 보세요.")

if res is not None:
    st.subheader("최근 설비 이벤트")
    show_dataframe(oee.recent_events(events, 30), "표시할 이벤트가 없습니다.")

if auto_refresh:
    time.sleep(3)
    st.rerun()
