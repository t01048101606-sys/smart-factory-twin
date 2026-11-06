import time
from datetime import timedelta

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from src import monitor, oee
from src.ui import alert_badge, kpi_row, require_role, setup_page, show_dataframe

setup_page("현장 모니터링")
require_role("ADMIN", "OPERATOR", "INSPECTOR")
st.title("현장 모니터링 · AI 이상 감지")
st.caption("PLC 트윈이 보내는 사이클 시간으로 설비 이상을 감지합니다. AI는 판정과 경보만 내고, 설비를 멈출지는 PLC가 판단합니다.")

Z_POINT, Z_EWMA = 6.0, 4.0  # src/anomaly.py 의 기본 임계값과 같은 값

col_a, col_b = st.columns([3, 1])
with col_a:
    period = st.selectbox("조회 기간", ["전체", "최근 10분", "최근 30분", "최근 1시간"])
with col_b:
    st.write("")
    auto_refresh = st.checkbox("자동 새로고침 (3초)", value=False)
minutes = {"최근 10분": 10, "최근 30분": 30, "최근 1시간": 60}.get(period)
since = pd.Timestamp.now(tz="UTC") - timedelta(minutes=minutes) if minutes else None

# ------------------------------------------------------------------ 트윈 (결함 주입은 여기서)
with st.expander("가공 공정 2D 트윈 · 결함 주입", expanded=True):
    c1, c2, c3 = st.columns([4, 1, 1])
    with c1:
        twin_url = st.text_input("트윈 서버 주소", value="http://localhost:5001",
                                 help="MES를 다른 컴퓨터에서 열었다면 localhost 대신 트윈 서버가 있는 컴퓨터의 주소를 넣으세요.")
    with c2:
        use_3d = st.checkbox("3D로 보기", value=False)
    with c3:
        height = st.number_input("높이", min_value=300, max_value=1300, value=860, step=20)
    src = f"{twin_url.rstrip('/')}/{'3d' if use_3d else ''}?embed=1"
    try:
        import streamlit.components.v1 as components
        components.iframe(src, height=int(height), scrolling=True)
    except Exception:
        st.info("트윈 화면을 이 페이지 안에 표시하지 못했습니다. 아래 링크로 새 탭에서 여세요.")
    st.markdown(f"[새 탭에서 트윈 열기]({src})")
    st.caption("사용법: 연속동작을 누르고 AI 상태가 '정상'이 될 때까지(처음 8사이클, 약 1분) 기다린 뒤, "
               "'결함 주입'에서 결함을 고르면 이 페이지에서 감지되는 모습을 볼 수 있습니다. 정상으로 되돌리면 경보가 해제됩니다. "
               "기준값은 정상 상태에서 학습해야 하므로, 결함을 켠 채로 시작했다면 '기준 다시 학습'을 누르세요.")

st.markdown("---")

events = oee.load_events(since)
j = monitor.judgements(events)
if events is None or events.empty or j.empty:
    st.info("아직 AI 판정이 없습니다. 트윈 서버(`server.py`)와 어댑터(`mes_adapter.py`)가 켜져 있는지 확인하고, "
            "트윈에서 연속동작을 누르세요. 기간을 '전체'로 바꿔 보는 것도 방법입니다.")
else:
    stt = monitor.current_status(events)
    age = (pd.Timestamp.now(tz="UTC") - events["ts"].max()).total_seconds()
    st.caption(f"마지막 이벤트: {events['ts'].max().tz_convert('Asia/Seoul'):%H:%M:%S} ({age:.0f}초 전)")
    if age > 60:
        alert_badge("마지막 이벤트가 1분 넘게 전입니다. 어댑터가 꺼졌거나 트윈이 멈춰 있을 수 있습니다.", "warning")

    if stt["phase"] == "learning":
        ai_text, ai_css = f"학습 중 {stt['learned']}/8", "kpi-gold"
    elif stt["alarm"]:
        ai_text, ai_css = "이상 감지", "kpi-red"
    else:
        ai_text, ai_css = "정상", "kpi-green"
    unit = lambda v: "-" if v is None or pd.isna(v) else f"{v:.2f} 초"
    kpi_row(
        [
            ("AI 상태", ai_text, ai_css),
            ("활성 경보", "1 건" if stt["alarm"] else "0 건", "kpi-red" if stt["alarm"] else "kpi-teal"),
            ("최근 사이클 (가공 시간 제외)", unit(stt["last_value"]), "kpi-blue"),
            ("기준값", unit(stt["baseline"]), "kpi-purple"),
            ("이상 판정", f"{stt['ng_count']} / {stt['total']} 회", "kpi-gold"),
        ],
        columns=3,
    )
    if stt["alarm"]:
        alert_badge("이상 경보가 발생 중입니다. 설비 점검이 필요합니다. (AI는 정지를 요청만 하며, 정지는 PLC가 판단합니다)", "danger")

    mon = j[j["phase"] == "monitoring"].copy()
    fa = monitor.faults(events)
    kst = lambda s: s.dt.tz_convert("Asia/Seoul").dt.tz_localize(None)

    # ------------------------------------------------------------ 사이클 시간과 이상 범위
    st.subheader("사이클 시간 추이")
    lrn = j[j["phase"] == "learning"]
    fig = go.Figure()
    if not mon.empty:
        base, sigma = mon["baseline"].iloc[-1], mon["sigma"].iloc[-1]
        x = kst(mon["ts"])
        fig.add_trace(go.Scatter(x=x, y=[base + Z_POINT * sigma] * len(x), mode="lines", line=dict(width=0),
                                 showlegend=False, hoverinfo="skip"))
        fig.add_trace(go.Scatter(x=x, y=[base - Z_POINT * sigma] * len(x), mode="lines", line=dict(width=0),
                                 fill="tonexty", fillcolor="rgba(51,194,127,0.18)", name="정상 범위"))
        fig.add_trace(go.Scatter(x=x, y=[base] * len(x), mode="lines", line=dict(dash="dash"), name="기준값"))
        ok, ng = mon[mon["result"] == "ok"], mon[mon["result"] == "ng"]
        fig.add_trace(go.Scatter(x=kst(ok["ts"]), y=ok["value"], mode="lines+markers", name="정상 판정",
                                 marker=dict(color="#2f9bff")))
        fig.add_trace(go.Scatter(x=kst(ng["ts"]), y=ng["value"], mode="markers", name="이상 판정",
                                 marker=dict(color="#ef4b4b", size=11, symbol="x")))
    if not lrn.empty:
        fig.add_trace(go.Scatter(x=kst(lrn["ts"]), y=lrn["value"], mode="markers", name="학습 구간",
                                 marker=dict(color="#8a94a3")))
    for _, r in fa.iterrows():
        xr = r["ts"].tz_convert("Asia/Seoul").tz_localize(None)
        fig.add_shape(type="line", x0=xr, x1=xr, y0=0, y1=1, yref="paper", line=dict(color="#f2c230", dash="dot"))
        fig.add_annotation(x=xr, y=1, yref="paper", text=monitor.FAULT_KO.get(r["mode"], r["mode"]),
                           showarrow=False, yanchor="bottom", font=dict(size=11))
    fig.update_layout(yaxis_title="초 (가공 시간 제외)", margin=dict(l=10, r=10, t=30, b=10), height=340,
                      legend=dict(orientation="h"))
    st.plotly_chart(fig, use_container_width=True)

    # ------------------------------------------------------------ 이상 점수
    st.subheader("이상 점수")
    if not mon.empty:
        fig2 = go.Figure()
        x2 = kst(mon["ts"])
        fig2.add_trace(go.Scatter(x=x2, y=mon["score"], mode="lines+markers", name="점 z 점수 (갑작스러운 변화)"))
        fig2.add_trace(go.Scatter(x=x2, y=mon["ewma_score"], mode="lines", name="EWMA z 점수 (서서히 나빠짐)"))
        for lim, nm in ((Z_POINT, "점 임계값"), (Z_EWMA, "EWMA 임계값")):
            fig2.add_hline(y=lim, line_dash="dash", line_color="#ef4b4b", annotation_text=nm)
        fig2.update_layout(yaxis_title="z", margin=dict(l=10, r=10, t=10, b=10), height=280, legend=dict(orientation="h"))
        st.plotly_chart(fig2, use_container_width=True)

    # ------------------------------------------------------------ 검증과 이력
    st.subheader("감지 검증 (결함 주입 → 경보)")
    show_dataframe(monitor.detection_report(events), "아직 결함을 주입하지 않았습니다. 트윈 화면에서 '결함 주입'을 선택해 보세요.")

    left, right = st.columns(2)
    with left:
        st.subheader("경보 이력")
        show_dataframe(monitor.alarms(events), "경보 이력이 없습니다.")
    with right:
        st.subheader("최근 AI 판정")
        recent = j.tail(15).iloc[::-1]
        show_dataframe(pd.DataFrame({
            "시각": recent["ts"].dt.tz_convert("Asia/Seoul").dt.strftime("%H:%M:%S"),
            "작업물": recent["piece_id"].fillna(""),
            "단계": recent["phase"].map({"learning": "학습", "monitoring": "감시"}),
            "판정": recent["result"].map({"ok": "정상", "ng": "이상"}),
            "값(초)": recent["value"],
            "z": recent["score"],
        }), "판정 이력이 없습니다.")

with st.expander("이상 감지 방법 보기"):
    st.markdown(
        """
- **특징값**: 사이클 시간에서 가공 시간(D10 설정)을 뺀 값입니다. 공급, 이송 같은 기계 동작에 걸린 시간이라서, 가공 시간을 바꿔도 이상으로 보이지 않습니다.
- **학습**: 처음 8사이클의 중앙값을 기준값, MAD(중앙값 절대편차)로 산포를 정합니다. 이상값에 강한 방법입니다.
- **점 판정**: `z = (값 - 기준값) / 산포`가 6을 넘으면 이상입니다 (갑작스러운 변화).
- **추세 판정**: EWMA(지수 이동 평균)가 4를 넘으면 이상입니다 (서서히 나빠지는 열화).
- **경보**: 이상이 연속 2회 나오면 경보를 내고, 정상 범위(|z| < 3)가 연속 3회 이어지면 해제합니다.
- **안전 원칙**: AI는 판정(`ai.judgement`)과 경보(`alarm.raised`)만 발행합니다. 정지는 PLC가 판단합니다.
"""
    )

if auto_refresh:
    time.sleep(3)
    st.rerun()
