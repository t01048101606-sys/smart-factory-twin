import time
from datetime import timedelta

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from src import monitor, oee, terms
from src.db import fetch_dataframe
from src.ui import alert_badge, kpi_row, require_role, setup_page, show_dataframe

setup_page("가공 라인")
require_role("ADMIN", "OPERATOR", "INSPECTOR")
mode = terms.mode_selector(st)   # 사이드바: 현장 용어 / 장비 원명칭
T = lambda k: terms.t(k, mode)
st.title("가공 라인 (PLC)")
st.caption("PLC 트윈이 보내는 설비 이벤트(machine_event)로 가동 상태와 OEE를 계산하고, 사이클 시간으로 설비 이상을 감지합니다. "
           "AI는 판정과 경보만 내고, 설비를 멈출지는 PLC가 판단합니다.")

Z_POINT, Z_EWMA = 6.0, 4.0  # src/anomaly.py 의 기본 임계값과 같은 값

# ------------------------------------------------------------------ 조건
col_a, col_b, col_c = st.columns([2, 2, 1])
with col_a:
    period = st.selectbox("집계 기간", ["전체", "최근 10분", "최근 30분", "최근 1시간"])
with col_b:
    ideal_text = st.text_input("고정 소요 시간(초) 직접 지정 (비우면 관측 최솟값 사용)", value="")
with col_c:
    st.write("")
    auto_refresh = st.checkbox("자동 새로고침 (3초)", value=False)

minutes = {"최근 10분": 10, "최근 30분": 30, "최근 1시간": 60}.get(period)
since = pd.Timestamp.now(tz="UTC") - timedelta(minutes=minutes) if minutes else None

ideal_override = None
if ideal_text.strip():
    try:
        ideal_override = float(ideal_text)
    except ValueError:
        st.warning("고정 소요 시간은 숫자로 입력하세요.")

# ------------------------------------------------------------------ 트윈 화면 (2D 또는 3D, 결함 주입은 여기서)
with st.expander("가공 공정 트윈: 2D와 3D 동시에 보기 · 결함 주입", expanded=True):
    c1, c2, c3, c4 = st.columns([3, 2, 2, 1])
    with c1:
        twin_url = st.text_input(
            "트윈 서버 주소", value="http://localhost:5001",
            help="MES를 다른 컴퓨터에서 열었다면 localhost 대신 트윈 서버가 있는 컴퓨터의 주소를 넣으세요.")
    with c2:
        layout_kind = st.radio("배치", ["좌우", "위아래"], horizontal=True)
    with c3:
        view_only = st.checkbox("2D 조작 패널 숨기기 (보기 전용)", value=False)
    with c4:
        height = st.number_input("높이", min_value=300, max_value=1300, value=700, step=20)
    base = twin_url.rstrip("/")
    src2d = f"{base}/?embed={'view' if view_only else '1'}"      # 2D: 연속동작, 결함 주입 같은 조작은 여기서
    src3d = f"{base}/3d?embed=view"                               # 3D: 보기 전용 (같은 상태를 3D로)
    try:
        import streamlit.components.v1 as components
        if layout_kind == "좌우":
            left, right = st.columns(2)
        else:
            left = right = st.container()
        with left:
            st.markdown("**2D 트윈**")
            components.iframe(src2d, height=int(height), scrolling=True)
        with right:
            st.markdown("**3D 트윈**")
            components.iframe(src3d, height=int(height), scrolling=True)
    except Exception:
        st.info("트윈 화면을 이 페이지 안에 표시하지 못했습니다. 아래 링크로 새 탭에서 여세요.")
    st.markdown(f"[새 탭에서 2D 열기]({src2d}) · [새 탭에서 3D 열기]({base}/3d?embed=1)")
    st.caption("사용법: 2D 화면에서 연속동작을 누르고 AI 상태가 '정상'이 될 때까지(처음 8사이클, 약 1분) 기다린 뒤, "
               "'결함 주입'에서 결함을 고르면 아래 'AI 이상 감지' 탭에서 감지되는 모습을 볼 수 있습니다. 3D 화면은 같은 상태를 따라 움직입니다. "
               "정상으로 되돌리면 경보가 해제됩니다. 기준값은 정상 상태에서 학습해야 하므로, 결함을 켠 채로 시작했다면 '기준 다시 학습'을 누르세요.")

st.markdown("---")

events = oee.load_events(since, line_id="LINE-MACHINING-01")
result = oee.compute_oee(events, ideal_override)
j = monitor.judgements(events)

tab_oee, tab_ai, tab_ev = st.tabs(["설비 효율 (OEE)", "AI 이상 감지", "이벤트 · 작업지시"])

with tab_oee:
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
                (T("classified"), f"{result['total']:,} 개", "kpi-gold"),
                (T("ng_label"), f"{result['defect']:,} 개", "kpi-teal"),
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
    - **품질률** = {T('quality_basis')} = {result['good']} / {result['total']} = **{pct(result['quality'])}**
    - {T('ng_part')}은 재질 불일치(이종 재질 혼입) 불량으로 봅니다 (MES 검사의 불량 사유 `MAT_MIX`와 같은 기준).
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


with tab_ai:
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


with tab_ev:
    st.subheader("최근 설비 이벤트")
    show_dataframe(oee.recent_events(events, 40, mode) if events is not None and not events.empty else events, "표시할 이벤트가 없습니다.")
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
