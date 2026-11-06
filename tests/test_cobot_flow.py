"""프레스 라인 -> 협동로봇 셀 -> 물류 구역 -> MES 출하까지 한 흐름을 확인합니다.

프레스 라인, 협동로봇 셀, 물류 구역을 같은 이벤트 스트림에서 돌리고 MES 어댑터로 처리합니다.
 - 라인 끝으로 나온 모든 양품이 로봇을 거쳐 파렛트에 쌓이고, 물류가 그 파렛트를 출하한다
 - 로봇이 쌓지 않은 작업물은 출하되지 않는다. 불량은 NG 상자에 가고 출하되지 않는다
 - MES 에는 출하 수량이 양품 수와 같게 기록되고, 협동로봇 이벤트는 가공 라인 처리로 흘러가지 않는다
MES 폴더는 임시 폴더로 복사해서 쓰므로 원본은 바뀌지 않습니다.
실행 (프로젝트 폴더에서):  python tests/test_cobot_flow.py [MES 폴더 경로]
"""
import shutil
import sqlite3
import sys
import tempfile
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
from line_sim import LineSim                         # noqa: E402
from line_events import LineEventBridge              # noqa: E402
from cobot_sim import CobotSim                       # noqa: E402
from cobot_events import CobotEventBridge, LINE_ID as COBOT_ID   # noqa: E402
from logistics_sim import LogisticsSim               # noqa: E402
from logistics_events import LogisticsEventBridge, LINE_ID as LOGI_ID   # noqa: E402
from events import EventEmitter                      # noqa: E402
from mes_adapter import MesAdapter                   # noqa: E402

MES_SRC = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT.parent / "AutoParts-MES-Arduino"
T0 = 1793923800.0
clock = [T0]
em = EventEmitter(now=lambda: clock[0], keep=10 ** 7)
line = LineSim(); line.hook = LineEventBridge(em)
cobot = CobotSim(); CobotEventBridge(em, cobot)
logi = LogisticsSim(); LogisticsEventBridge(em, logi, from_cobot=True)


def run(seconds):
    for _ in range(int(seconds / 0.05)):
        clock[0] += 0.05
        line.advance(0.05); cobot.step(0.05); logi.advance(0.05)


line.start(); run(420)
line.stop()
run(600)                                          # 라인이 비워지고, 로봇이 남은 작업물을 처리하고, 모자란 파렛트를 마감하고, 물류가 출하한다
ev = em.since(-1, 10 ** 8)
by = {}
for e in ev:
    by.setdefault(e["type"], []).append(e)
exits = [e for e in by["piece.exited"]]
good_ids = [e["piece_id"] for e in exits if e["payload"]["result"] == "good"]
scrap_ids = [e["piece_id"] for e in exits if e["payload"]["result"] == "scrap"]
print(f"프레스 라인 끝으로 나온 작업물 {len(exits)}개 (양품 {len(good_ids)}, 불량 {len(scrap_ids)})")
assert len(good_ids) > 40 and scrap_ids

# 1) 모든 작업물이 비전 검사를 거치고, 양품은 파렛트에, 불량은 NG 상자에 놓인다
insp = {e["piece_id"]: e["payload"] for e in by["vision.inspected"]}
placed = {e["piece_id"]: e["payload"] for e in by["cobot.placed"]}
assert set(insp) == set(placed) == {e["piece_id"] for e in exits}
assert all(insp[i]["result"] == "good" and placed[i]["target"] == "pallet" for i in good_ids)
assert all(insp[i]["result"] == "scrap" and placed[i]["target"] == "ng_bin" for i in scrap_ids)
# 2) 로봇이 마감한 파렛트에 들어간 것은 정확히 양품 전부 (순서 유지), 마지막은 라인 정지로 마감한 모자란 파렛트
closed = by["cobot.pallet_closed"]
assert [x for e in closed for x in e["payload"]["pieces"]] == good_ids
assert all(not e["payload"]["partial"] and len(e["payload"]["pieces"]) == 5 for e in closed[:-1])
assert closed[-1]["payload"]["partial"] == (len(good_ids) % 5 != 0)
print(f"로봇: 비전 검사 {len(insp)}건, 파렛트 {len(closed)}개 마감 (양품 {len(good_ids)}개, 마지막 {len(closed[-1]['payload']['pieces'])}개), NG 상자 {len(scrap_ids)}개")
# 3) 물류: 로봇이 마감한 파렛트가 그대로 보관, 출하된다. 불량은 출하되지 않는다
stored = [x for e in by["pallet.stored"] for x in e["payload"]["pieces"]]
shipped = [x for e in by["shipment.dispatched"] for p in e["payload"]["pallets"] for x in p["pieces"]]
# 출하 트럭은 파렛트 4개가 차야 출발하므로, 4의 배수 파렛트만 나가고 나머지는 도크에서 다음 트럭을 기다린다
n_trucks = len(by["shipment.dispatched"])
assert stored == good_ids and set(shipped) <= set(good_ids) and len(shipped) == len(set(shipped)), (len(stored), len(shipped), len(good_ids))
assert all(len(e["payload"]["pallets"]) == 4 for e in by["shipment.dispatched"]) and n_trucks >= 1
waiting = [p for p in logi.pallets]
assert len(waiting) == len(closed) - 4 * n_trucks and len(waiting) < 4 and sum(len(p["pieces"]) for p in waiting) + len(shipped) == len(good_ids)
assert not set(shipped) & set(scrap_ids)
print(f"물류: 파렛트 {len(by['pallet.stored'])}개 보관, 출하 {len(by['shipment.dispatched'])}건 {len(shipped)}개 (전부 양품)")

# 4) MES: 출하 수량 = 양품 수, 협동로봇 이벤트는 저장만 되고 가공 라인 처리로 흘러가지 않는다
tmp = Path(tempfile.mkdtemp(prefix="mes_cobot_"))
mes = tmp / "mes"
shutil.copytree(MES_SRC, mes, ignore=shutil.ignore_patterns(".git", "__pycache__", "*.docx", "*.pdf", "*.db", "*.db-*"))
logs = []
ad = MesAdapter(mes, today=lambda: date(2026, 11, 6), log=logs.append, press_batch=5)
ad.init_db(); ad.seed_master(); ad.press.ensure()
for e in ev:
    ad.handle(e)
db = mes / "sql" / "auto_parts.db"
rows = lambda sql, p=(): [dict(r) for r in (lambda c: (setattr(c, "row_factory", sqlite3.Row), c.execute(sql, p).fetchall())[1])(sqlite3.connect(db))]
ship_qty = rows("SELECT COALESCE(SUM(qty),0) q FROM shipment_item")[0]["q"]
completed = rows("SELECT COUNT(*) n FROM unit_serial WHERE status='COMPLETED'")[0]["n"]
assert completed == len(good_ids) and ship_qty == len(shipped), (completed, ship_qty, len(shipped), len(good_ids))
assert not ad.state.get("pending_shipments"), ad.state.get("pending_shipments")
cnt = {r["line_id"]: r["n"] for r in rows("SELECT line_id, COUNT(*) n FROM machine_event GROUP BY line_id")}
assert cnt[COBOT_ID] == len(insp) + len(placed) + len(closed), cnt
assert rows("SELECT COUNT(*) n FROM work_order w JOIN item i ON i.item_id=w.product_item_id WHERE i.item_code='FG-DRILLPART'")[0]["n"] == 0   # 가공 라인 작업지시가 만들어지지 않았다
assert not [l for l in logs if "가공" in l and "작업지시" in l and "생성" in l and "프레스" not in l]
print(f"MES: 양품 시리얼 {completed}개 = 출하 {ship_qty:.0f}개 (보류 출하 없음), 협동로봇 이벤트 {cnt[COBOT_ID]}건은 저장만 되고 가공 라인 작업지시는 생기지 않음")

# 5) MES 공장현황 대시보드의 협동로봇 행
import importlib
ad.log = lambda m: None
ad.install_addons()
importlib.invalidate_caches()
from src import factory_dash as fd, oee      # noqa: E402  (MES 폴더에 설치된 모듈)
ev_c = oee.load_events(None, line_id=fd.COBOT)
ev_p, ev_l, ev_m = (oee.load_events(None, line_id=x) for x in (fd.PRESS, fd.LOGISTICS, fd.MACHINING))
ov, res = fd.line_overview(ev_m, ev_p, ev_l, now=ev_c["ts"].max(), ev_c=ev_c)
c = res["cobot"]
cyc = [p["cycle_s"] for p in placed.values()]
assert (c["inspected"], c["ng"], c["pallets"]) == (len(insp), len(scrap_ids), len(closed)) and abs(c["avg_cycle_s"] - sum(cyc) / len(cyc)) < 1e-9
assert 4.5 < c["avg_cycle_s"] < 6.0
row = ov[ov["라인"] == "협동로봇 팔레타이징 셀"].iloc[0]
assert row["상태"] == "가동" and f"비전 검사 {len(insp)}개" in row["처리"] and f"불량 검출 {len(scrap_ids)}개" in row["처리"], row["처리"]
assert len(fd.line_overview(ev_m, ev_p, ev_l, now=ev_c["ts"].max())[0]) == 3                  # ev_c 를 주지 않으면 예전처럼 3개 라인
print(f"대시보드: 협동로봇 행 '{row['처리']}'")

# 6) 협동로봇 셀 페이지(16_협동로봇셀.py): 화면의 숫자를 이벤트에서 따로 센 값과 비교
import runpy
import types
from unittest.mock import MagicMock
seen = {"kpi": None, "plots": 0, "tables": 0, "iframe": None}
sys.path.insert(0, str(ROOT / "tests"))
import fake_cols            # noqa: E402
import fake_twin_server     # noqa: E402
twin_srv, TWIN, twin_log, _ = fake_twin_server.start()
fake_cols.Col.clicks = {"▶ 라인 시작", "파렛트 마감 (모자란 파렛트도 지금 마감)"}


class FakeSt(types.ModuleType):
    def __init__(self):
        super().__init__("streamlit")
        self.session_state = {"logged_in": True, "user_role": "ADMIN"}
    def columns(self, spec, **k): return [fake_cols.Col() for _ in range(spec if isinstance(spec, int) else len(spec))]
    def selectbox(self, label, options, **k): return options[0]
    def text_input(self, label, value="", **k): return TWIN if "트윈 서버 주소" in label else value
    def number_input(self, label, value=0, **k): return value
    def checkbox(self, *a, **k): return False
    def tabs(self, labels): return [MagicMock() for _ in labels]
    def radio(self, label, options, **k): return options[0]
    def plotly_chart(self, *a, **k): seen["plots"] += 1
    def stop(self): raise AssertionError("협동로봇 페이지가 st.stop() 으로 멈췄습니다")
    def __getattr__(self, name): return MagicMock()


fake = FakeSt()
comp = types.ModuleType("streamlit.components.v1")
comp.iframe = lambda src, **k: seen.__setitem__("iframe", src)
fake.components = types.SimpleNamespace(v1=comp)
sys.modules.update({"streamlit": fake, "streamlit.components": fake.components, "streamlit.components.v1": comp,
                    "plotly": MagicMock(), "plotly.graph_objects": MagicMock()})
for name in [m for m in list(sys.modules) if m == "src" or m.startswith("src.")]:
    del sys.modules[name]
import src.ui as ui   # noqa: E402
ui.kpi_row = lambda items, columns=3: seen.__setitem__("kpi", {a: b for a, b, _ in items})
ui.show_dataframe = lambda df, msg="": seen.__setitem__("tables", seen["tables"] + 1)
runpy.run_path(str(mes / "sections" / "cobot.py"), run_name="__main__")
kc = seen["kpi"]
n_partial = sum(e["payload"]["partial"] for e in closed)
print("협동로봇 페이지 KPI:", kc)
assert kc["비전 검사"] == f"{len(insp):,} 개" and kc["불량 검출"].startswith(f"{len(scrap_ids):,} 개") and kc["양품 적재"] == f"{len(good_ids):,} 개"
assert kc["완성 파렛트"] == f"{len(closed):,} 개 (모자란 것 {n_partial})" and kc["집기 사이클 평균"] == f"{sum(cyc) / len(cyc):.2f} 초", kc
assert seen["iframe"] == f"{TWIN}/3d/factory?embed=scene&focus=cobot" and seen["plots"] == 2 and seen["tables"] >= 2, seen
reqs = [(p, b) for m, p, b in twin_log if m == "POST"]
assert reqs == [("/api/line/control", {"action": "start"}), ("/api/cobot/control", {"action": "flush"})], reqs      # 페이지의 '라인 시작'과 '파렛트 마감' 버튼이 트윈 서버로 간다
print("협동로봇 페이지 버튼: '라인 시작'은 프레스 라인 시작, '파렛트 마감'은 셀 API 로 전달됨")
from src import factory_dash as fd2   # noqa: E402
import src.oee as oee2   # noqa: E402
cs = fd2.cobot_summary(oee2.load_events(None, line_id=fd2.COBOT))
assert len(cs["recent"]) == 20 and cs["recent"].iloc[0]["작업물"] == by["vision.inspected"][-1]["piece_id"]          # 최근 것이 위
by_piece = {r["작업물"]: r for _, r in cs["recent"].iterrows()}
for pid, r in by_piece.items():
    assert (r["판정"] == "양품") == (insp[pid]["result"] == "good")
    assert r["놓은 곳"] == ("NG 수납함" if insp[pid]["result"] == "scrap" else f"파렛트 {placed[pid]['slot'] + 1}번 칸"), r
assert list(cs["pallet_table"]["마감"]).count("라인 정지로 모자란 채 마감") == n_partial and cs["pallets"] == len(closed)
print(f"협동로봇 페이지: 검사 {len(insp)}, 불량 {len(scrap_ids)}, 파렛트 {len(closed)}(모자란 것 {n_partial}), 사이클 평균 {sum(cyc) / len(cyc):.2f}초, 최근 검사 20건의 판정과 놓은 곳이 이벤트와 일치")
print("\n테스트 통과")
