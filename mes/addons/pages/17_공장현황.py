import time
from datetime import timedelta

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from src import factory_dash as fd
from src import oee
from src.db import fetch_dataframe
from src.ui import alert_badge, kpi_row, require_role, setup_page, show_dataframe

setup_page("공장 현황")
require_role("ADMIN", "OPERATOR", "INSPECTOR")
st.title("스마트 팩토리 현황")
st.caption("가공 라인, 프레스 · 용접 · 도장 라인, 물류 · 출하 구역을 한 화면에서 봅니다. 숫자는 MES 기록(LOT, 시리얼, 검사, 출하)과 설비 이벤트에서 계산합니다.")

c1, c2 = st.columns([3, 1])
with c1:
    period = st.selectbox("설비 이벤트 집계 기간 (실제 시각 기준)", ["전체", "최근 10분", "최근 30분", "최근 1시간"])
with c2:
    st.write("")
    auto_refresh = st.checkbox("자동 새로고침 (5초)", value=False)
minutes = {"최근 10분": 10, "최근 30분": 30, "최근 1시간": 60}.get(period)
since = pd.Timestamp.now(tz="UTC") - timedelta(minutes=minutes) if minutes else None

with st.expander("3D 공장 화면", expanded=True):
    t1, t2 = st.columns([4, 1])
    with t1:
        twin_url = st.text_input("트윈 서버 주소", value="http://localhost:5001",
                                 help="MES를 다른 컴퓨터에서 열었다면 localhost 대신 트윈 서버가 있는 컴퓨터의 주소를 넣으세요.")
    with t2:
        height = st.number_input("높이", min_value=300, max_value=1300, value=560, step=20)
    src = f"{twin_url.rstrip('/')}/3d/factory?embed=1"
    try:
        import streamlit.components.v1 as components
        components.iframe(src, height=int(height), scrolling=False)
    except Exception:
        st.info("3D 화면을 이 페이지 안에 표시하지 못했습니다. 아래 링크로 새 탭에서 여세요.")
    st.markdown(f"[새 탭에서 열기]({src})")

# ---------------------------------------------------------------- 데이터
ev_m = oee.load_events(since, line_id=fd.MACHINING)
ev_p = oee.load_events(since, line_id=fd.PRESS)
ev_l = oee.load_events(since, line_id=fd.LOGISTICS)
ev_all = oee.load_events(since)
try:
    serial, wo = fd.production(fetch_dataframe)
    inv = fd.inventory(fetch_dataframe)
    ship = fd.shipments(fetch_dataframe)
    dist, reasons = fd.quality(fetch_dataframe)
except Exception:
    st.error("MES 테이블을 읽지 못했습니다. `python src\\mes_adapter.py --init-only`를 먼저 실행하세요.")
    st.stop()
overview, res = fd.line_overview(ev_m, ev_p, ev_l)

good, scrap = int(serial["good"].sum()), int(serial["scrap"].sum())
total = good + scrap
waiting_qty = int(ship["waiting"]["shippable"].sum()) if len(ship["waiting"]) else 0

st.subheader("한눈에 보기")
kpi_row(
    [
        ("양품 생산", f"{good:,} 개", "kpi-green"),
        ("불량", f"{scrap:,} 개 ({(scrap / total * 100) if total else 0:.1f}%)", "kpi-red"),
        ("출하 수량", f"{ship['qty']:,.0f} 개 ({ship['count']}건)", "kpi-blue"),
        ("출하 대기", f"{waiting_qty:,} 개", "kpi-gold"),
        ("출하 차단 LOT", f"{len(ship['blocked'])} 개", "kpi-purple"),
        ("재고 부족 자재", f"{int(inv['low'].sum())} 종", "kpi-teal"),
    ],
    columns=3,
)

st.subheader("주의가 필요한 일")
al = fd.alerts(ev_all, inv, ship, overview)
if al.empty:
    alert_badge("지금 주의가 필요한 항목이 없습니다.", "ok")
else:
    show_dataframe(al, "")

# ---------------------------------------------------------------- 라인
st.subheader("라인 현황")
show_dataframe(overview, "라인 데이터가 없습니다.")
st.caption("가공 라인과 프레스 라인의 OEE는 정의가 다릅니다 (아래 계산 근거). 물류 구역은 설비 효율 대신 입고와 출하 건수로 봅니다.")

# ---------------------------------------------------------------- 생산
st.subheader("생산")
if serial.empty:
    st.info("아직 시리얼이 부여된 완제품이 없습니다. 3D 화면에서 라인을 돌려 보세요.")
else:
    fig = go.Figure()
    fig.add_trace(go.Bar(x=serial["item_name"], y=serial["good"], name="양품", marker_color="#33c27f"))
    fig.add_trace(go.Bar(x=serial["item_name"], y=serial["scrap"], name="불량", marker_color="#ef4b4b"))
    fig.update_layout(barmode="stack", yaxis_title="작업물 수", margin=dict(l=10, r=10, t=10, b=10), height=280, legend=dict(orientation="h"))
    st.plotly_chart(fig, use_container_width=True)
    t = serial.rename(columns={"item_code": "품목코드", "item_name": "제품", "total": "합계", "good": "양품", "scrap": "불량"}).copy()
    t["불량률"] = (t["불량"] / t["합계"] * 100).round(1).astype(str) + "%"
    show_dataframe(t, "")
    wo_t = wo.pivot_table(index="item_code", columns="status", values="n", aggfunc="sum", fill_value=0).reset_index().rename(columns={"item_code": "품목코드"})
    show_dataframe(wo_t, "")
    st.caption("위 표는 제품별 작업지시 상태별 건수입니다.")

# ---------------------------------------------------------------- 재고
st.subheader("자재 재고")
inv_t = inv.rename(columns={"item_code": "자재코드", "item_name": "자재", "unit": "단위", "received": "입고", "consumed": "소비", "balance": "재고",
                            "per_unit": "단위당 소비", "makeable": "만들 수 있는 완제품(개)"}).copy()
inv_t["상태"] = inv["low"].map({True: "부족", False: "충분"})
inv_t = inv_t.drop(columns=["low"])
for col in ("입고", "소비", "재고", "만들 수 있는 완제품(개)"):
    inv_t[col] = inv_t[col].astype(float).round(2)
if len(inv):
    fig = go.Figure(go.Bar(x=inv["item_name"], y=inv["makeable"], marker_color=["#ef4b4b" if v else "#2f9bff" for v in inv["low"]]))
    fig.update_layout(yaxis_title="남은 재고로 만들 수 있는 완제품(개)", margin=dict(l=10, r=10, t=10, b=10), height=260)
    st.plotly_chart(fig, use_container_width=True)
show_dataframe(inv_t, "등록된 자재가 없습니다.")
st.caption("부족 기준은 완제품 20개 분량(5개 작업지시 4건)입니다. 물류 구역은 재고가 발주점 아래로 내려가면 입고 트럭을 부릅니다.")

# ---------------------------------------------------------------- 출하
st.subheader("출하")
s1, s2 = st.columns(2)
with s1:
    st.markdown("**최근 출하**")
    show_dataframe(ship["recent"], "아직 출하 기록이 없습니다. 프레스 라인의 양품 5개가 파렛트가 되면 출하됩니다.")
with s2:
    st.markdown("**출하 대기 LOT** (출하 가능 수량 > 0)")
    w = ship["waiting"][["lot_no", "item_name", "result", "shippable"]].rename(columns={"lot_no": "LOT", "item_name": "제품", "result": "검사", "shippable": "출하 가능"})
    show_dataframe(w, "출하 대기 중인 LOT가 없습니다.")
if len(ship["blocked"]):
    st.markdown("**출하가 막힌 LOT** (검사 불합격 FAIL: MES가 출하 등록을 거절합니다)")
    b = ship["blocked"][["lot_no", "item_name", "lot_qty", "scrap"]].rename(columns={"lot_no": "LOT", "item_name": "제품", "lot_qty": "LOT 수량", "scrap": "불량"})
    show_dataframe(b, "")
if ship["other_lots"]:
    st.caption(f"가공 부품(FG-DRILLPART) 완제품 LOT {ship['other_lots']}개는 물류 · 출하 구역과 연결되어 있지 않아 위 표에 넣지 않았습니다.")

# ---------------------------------------------------------------- 품질
st.subheader("품질 (완제품 LOT 검사)")
q1, q2 = st.columns(2)
with q1:
    if dist.empty:
        st.info("검사 기록이 없습니다.")
    else:
        colors = {"PASS": "#33c27f", "PARTIAL": "#f2c230", "FAIL": "#ef4b4b"}
        fig = go.Figure(go.Bar(x=dist["result"], y=dist["lots"], marker_color=[colors.get(r, "#7a8696") for r in dist["result"]]))
        fig.update_layout(yaxis_title="LOT 수", margin=dict(l=10, r=10, t=10, b=10), height=260)
        st.plotly_chart(fig, use_container_width=True)
with q2:
    if reasons.empty:
        st.info("불량 사유 기록이 없습니다.")
    else:
        fig = go.Figure(go.Bar(x=reasons["reason"], y=reasons["qty"], marker_color="#ef4b4b"))
        fig.update_layout(yaxis_title="불량 수량", margin=dict(l=10, r=10, t=10, b=10), height=260)
        st.plotly_chart(fig, use_container_width=True)

# ---------------------------------------------------------------- 계산 근거
with st.expander("계산 근거 보기"):
    p, m = res["press"], res["machining"]
    st.markdown(
        f"""
**생산**: 시리얼(작업물 번호)의 상태를 센 값입니다. `COMPLETED`는 양품, `SCRAPPED`는 불량이고, 불량률 = 불량 / (양품 + 불량) = {scrap} / {total}.

**재고**: 입고한 자재 LOT 수량 - 공정 실행이 소비한 수량입니다. "만들 수 있는 완제품" = 재고 / BOM 단위당 소비량
(냉연강판 0.5kg, 볼트 4개, 도료 0.05L, 블랭크 1개).

**출하**: 출하 가능 수량 = 양품 시리얼 수 - 이미 출하한 수량. 불량 시리얼은 LOT 안에 남아 있지만 출하 대상이 아닙니다.
검사 결과가 FAIL인 LOT는 MES가 출하 등록을 거절합니다 (`register_shipment`).

**가공 라인 OEE**: 가용률 x 성능률 x 품질률. 성능률은 사이클 시간에서 가공 시간(D10)을 뺀 값(순수 이송 시간)을 이상 사이클로 보고 계산하고,
품질률은 정품 / 판별한 워크입니다 ({f"{m['good']} / {m['total']}" if m else "-"}).

**프레스 라인 OEE**: 가용률 = (가동 시간 - 정지 시간) / 가동 시간, 성능률 = 병목 공칭 사이클 x 완성 수량 / 정지 없이 가동한 시간,
품질률 = 양품 / (양품 + 불량) ({f"{p['good']} / {p['done']}" if p else "-"}). 시간은 시뮬레이터 시간(`sim_t`)이라 배속과 무관합니다.

두 라인의 OEE는 정의가 달라서 **더하거나 평균 내지 않습니다**. 라인마다 따로 봅니다.
"""
    )

if auto_refresh:
    time.sleep(5)
    st.rerun()
