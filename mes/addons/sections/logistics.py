import time
from datetime import timedelta

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from src import factory_dash as fd
from src import oee, twin_api
from src.db import fetch_dataframe
from src.ui import alert_badge, kpi_row, require_role, setup_page, show_dataframe

setup_page("물류 · 출하")
require_role("ADMIN", "OPERATOR", "INSPECTOR")
st.header("물류 · 출하 구역")
st.caption("자재 입고, 자재 창고, 완제품 파렛트 보관, AGV 운반, 출하 트럭까지 물류의 흐름을 봅니다. 입고는 MES 원자재 입고로, 출하는 MES 출하 관리로 등록됩니다.")

c1, c2 = st.columns([3, 1])
with c1:
    period = st.selectbox("설비 이벤트 집계 기간 (실제 시각 기준)", ["전체", "최근 10분", "최근 30분", "최근 1시간"])
with c2:
    st.write("")
    auto_refresh = st.checkbox("자동 새로고침 (5초)", value=False)
minutes = {"최근 10분": 10, "최근 30분": 30, "최근 1시간": 60}.get(period)
since = pd.Timestamp.now(tz="UTC") - timedelta(minutes=minutes) if minutes else None

twin_url = st.text_input("트윈 서버 주소", value="http://localhost:5001",
                                 help="MES를 다른 컴퓨터에서 열었다면 localhost 대신 트윈 서버가 있는 컴퓨터의 주소를 넣으세요.")
twin_api.control_bar(st, twin_url, extra=[("입고 요청 (트럭 부르기)", "/api/logistics/request_inbound", {})], key="logi",
                     note='출하는 협동로봇이 파렛트를 마감해야 시작됩니다. 그래서 "라인 시작"이 프레스 라인 시작이고, 입고는 재고가 발주점 아래로 내려가거나 "입고 요청"을 누르면 트럭이 옵니다.')

with st.expander("3D 물류 · 출하 구역", expanded=True):
    t2, t3 = st.columns([3, 1])
    with t2:
        show_cards = st.checkbox("조작 카드 포함", value=False, help="'입고 요청' 버튼과 다른 라인의 카드를 3D 화면 위에 함께 표시합니다.")
    with t3:
        height = st.number_input("높이", min_value=300, max_value=1300, value=620, step=20)
    src = f"{twin_url.rstrip('/')}/3d/factory?embed={'1' if show_cards else 'scene'}&focus=logistics"
    try:
        import streamlit.components.v1 as components
        components.iframe(src, height=int(height), scrolling=False)
    except Exception:
        st.info("3D 화면을 이 페이지 안에 표시하지 못했습니다. 아래 링크로 새 탭에서 여세요.")
    st.markdown(f"[새 탭에서 열기]({src})")
    st.caption("사용법: 자재 재고가 발주점 아래로 내려가면 입고 트럭이 오고, '입고 요청' 버튼(조작 카드 포함)으로 바로 부를 수도 있습니다. "
               "협동로봇이 파렛트를 마감하면 AGV가 출하 도크로 옮기고 트럭이 싣고 출발합니다.")

st.markdown("---")

try:
    inv = fd.inventory(fetch_dataframe)
    ship = fd.shipments(fetch_dataframe)
    rec = fd.receipts(fetch_dataframe)
except Exception:
    st.error("MES 테이블을 읽지 못했습니다. `python src\\mes_adapter.py --init-only`를 먼저 실행하세요.")
    st.stop()
ev_l = oee.load_events(since, line_id=fd.LOGISTICS)
n_recv = int((ev_l["event_type"] == "lot.received").sum()) if not ev_l.empty else 0
n_pal = int((ev_l["event_type"] == "pallet.stored").sum()) if not ev_l.empty else 0
waiting_qty = int(ship["waiting"]["shippable"].sum()) if len(ship["waiting"]) else 0

st.subheader("한눈에 보기")
kpi_row(
    [
        ("입고 횟수", f"{n_recv} 회", "kpi-blue"),
        ("파렛트 보관", f"{n_pal} 개", "kpi-teal"),
        ("출하", f"{ship['qty']:,.0f} 개 ({ship['count']}건)", "kpi-green"),
        ("출하 대기", f"{waiting_qty:,} 개", "kpi-gold"),
        ("출하 차단 LOT", f"{len(ship['blocked'])} 개", "kpi-purple"),
        ("재고 부족 자재", f"{int(inv['low'].sum())} 종", "kpi-red"),
    ],
    columns=3,
)
if int(inv["low"].sum()):
    alert_badge("재고가 부족한 자재가 있습니다. 물류 구역이 곧 입고 트럭을 부르거나, '입고 요청'으로 바로 부를 수 있습니다.", "warning")

# ---------------------------------------------------------------- 재고
st.subheader("자재 재고")
inv_t = inv.rename(columns={"item_code": "자재코드", "item_name": "자재", "unit": "단위", "received": "입고", "consumed": "소비", "balance": "재고",
                            "per_unit": "단위당 소비", "makeable": "만들 수 있는 완제품(개)"}).copy()
inv_t["상태"] = ["자동 입고(시연)" if a else ("부족" if low else "충분") for a, low in zip(inv["auto"], inv["low"])]
inv_t = inv_t.drop(columns=["low", "auto"])
for col in ("입고", "소비", "재고", "만들 수 있는 완제품(개)"):
    inv_t[col] = inv_t[col].astype(float).round(2)
if len(inv):
    fig = go.Figure(go.Bar(x=inv["item_name"], y=inv["makeable"], marker_color=["#7a8696" if a else ("#ef4b4b" if low else "#2f9bff") for a, low in zip(inv["auto"], inv["low"])]))
    fig.update_layout(yaxis_title="남은 재고로 만들 수 있는 완제품(개)", margin=dict(l=10, r=10, t=10, b=10), height=260)
    st.plotly_chart(fig, use_container_width=True)
show_dataframe(inv_t, "등록된 자재가 없습니다.")
st.caption("부족 기준은 완제품 20개 분량(5개 작업지시 4건)입니다. 물류 구역은 재고가 발주점 아래로 내려가면 입고 트럭을 부릅니다. "
           "가공용 블랭크는 어댑터가 모자라면 자동으로 입고하는 시연용 자재라 부족으로 보지 않습니다.")

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


# ---------------------------------------------------------------- 입고 이력과 물류 이벤트
st.subheader("입고 이력 (MES 원자재 입고)")
show_dataframe(rec, "입고 기록이 없습니다.")
st.subheader("최근 물류 이벤트")
show_dataframe(oee.recent_events(ev_l, 25) if not ev_l.empty else ev_l, "물류 이벤트가 없습니다. 프레스 · 용접 · 도장 라인과 협동로봇 셀을 돌리면 파렛트 보관과 출하 이벤트가 쌓입니다.")

if auto_refresh:
    time.sleep(5)
    st.rerun()
