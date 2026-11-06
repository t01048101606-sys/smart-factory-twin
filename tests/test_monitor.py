"""현장 모니터링(AI 이상 감지) 분석 모듈과 페이지를 시험합니다.

시뮬레이터에 결함을 주입한 이벤트를 MES 복사본의 DB에 넣고, 분석 함수와 새 페이지(13_현장모니터링.py)를
Streamlit 없이 끝까지 실행해 봅니다. 원본 MES는 바뀌지 않습니다.
실행:  python tests/test_monitor.py [MES 폴더 경로]
"""
import importlib.util
import runpy
import shutil
import sys
import tempfile
import types
from datetime import date
from pathlib import Path
from unittest.mock import MagicMock

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
from plc_sim import PlcSim                    # noqa: E402
from events import EventEmitter               # noqa: E402
from anomaly import CycleAnomalyDetector      # noqa: E402
from mes_adapter import MesAdapter            # noqa: E402

MES_SRC = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT.parent / "AutoParts-MES-Arduino"
T0 = 1793923800.0


def simulate(plan, seconds):
    clock = [T0]
    sim = PlcSim(str(ROOT / "plc" / "1102"))
    em = EventEmitter(now=lambda: clock[0], detector=CycleAnomalyDetector(), keep=10 ** 6)
    for s in range(int(seconds / 0.05)):
        t = s * 0.05
        clock[0] = T0 + t
        for at, mode in plan.items():
            if abs(t - at) < 1e-9:
                sim.set_fault(mode); em.sim_fault(mode)
        if s == 20:
            em.command("M101", "web")
        sim.scan(["M101"] if s == 20 else [])
        em.observe(sim.dev)
    return em.since(-1, 10 ** 7)


def to_df(ev):
    return pd.DataFrame([{"event_id": e["event_id"], "seq": e["seq"], "ts": pd.Timestamp(e["ts"]), "source": e["source"],
                          "event_type": e["type"], "piece_id": e["piece_id"], "work_order_id": None,
                          "payload": e["payload"]} for e in ev])


spec = importlib.util.spec_from_file_location("monitor", ROOT / "mes" / "addons" / "src" / "monitor.py")
monitor = importlib.util.module_from_spec(spec); spec.loader.exec_module(monitor)

# 정상 -> 120초에 실린더 속도 저하 -> 240초에 해제
ev = simulate({120.0: "cyl_slow", 240.0: "none"}, 330)
df = to_df(ev)

# ---- 1) 분석 함수 ---------------------------------------------------------------------
j = monitor.judgements(df)
assert (j["phase"] == "learning").sum() == 8 and (j["phase"] == "monitoring").sum() > 20
assert set(j.loc[j["phase"] == "monitoring", "sigma"].dropna()) and j["value"].notna().all()
f = monitor.faults(df)
assert list(f["mode"]) == ["cyl_slow", "none"]
al = monitor.alarms(df)
assert len(al) == 1 and al.iloc[0]["해제"] != "진행 중" and al.iloc[0]["지속(초)"] > 60, al
rep = monitor.detection_report(df)
assert list(rep["결과"]) == ["감지", "해제됨"], rep
assert rep.iloc[0]["경보 발생/해제까지(초)"] < 30 and rep.iloc[1]["경보 발생/해제까지(초)"] < 40
stt = monitor.current_status(df)
assert stt["phase"] == "monitoring" and stt["alarm"] is False and stt["ng_count"] > 0 and abs(stt["baseline"] - 3.4) < 0.1, stt
print("분석 함수 확인")
print(rep.to_string(index=False))
print(al.to_string(index=False))

# 결함이 켜진 채 끝나면 경보가 '진행 중'으로 남고 현재 상태도 경보
df2 = to_df(simulate({120.0: "cyl_slow"}, 200))
assert monitor.current_status(df2)["alarm"] is True and monitor.alarms(df2).iloc[0]["해제"] == "진행 중"
# 빈 입력
for fn in (monitor.judgements, monitor.faults, monitor.alarms, monitor.detection_report):
    assert fn(pd.DataFrame()).empty
assert monitor.current_status(pd.DataFrame())["phase"] == "none"
print("결함이 켜진 채 끝난 경우와 빈 입력 확인")

# ---- 2) 어댑터 -> DB -> 설치 -> 페이지 실행 -----------------------------------------------------
tmp = Path(tempfile.mkdtemp(prefix="mes_mon_"))
mes = tmp / "mes"
shutil.copytree(MES_SRC, mes, ignore=shutil.ignore_patterns(".git", "__pycache__", "*.docx", "*.pdf", "*.db", "*.db-*"))
# 이미 추가 파일이 설치된 MES 폴더를 복사했을 수 있으니, 설치 전의 원래 상태로 되돌려 놓고 시작한다
page13, bak13 = mes / "pages" / "13_현장모니터링.py", mes / "pages" / "13_현장모니터링.py.orig"
if bak13.exists():
    shutil.move(str(bak13), str(page13))
for extra in ("pages/14_설비현황.py", "src/oee.py", "src/monitor.py"):
    (mes / extra).unlink(missing_ok=True)
ad = MesAdapter(mes, batch=4, today=lambda: date(2026, 11, 6), log=lambda m: None)
ad.init_db(); ad.seed_master()
for e in ev:
    ad.handle(e)

orig_page = (mes / "pages" / "13_현장모니터링.py").read_text(encoding="utf-8")
logs = []
ad.log = logs.append
ad.install_addons()
bak = mes / "pages" / "13_현장모니터링.py.orig"
assert bak.exists() and bak.read_text(encoding="utf-8") == orig_page, "원래 현장모니터링 페이지가 백업되어야 합니다"
new_page = (mes / "pages" / "13_현장모니터링.py").read_text(encoding="utf-8")
assert new_page != orig_page and (mes / "src" / "monitor.py").exists()
ad.install_addons()                                   # 두 번째 설치에서도 원본 백업을 덮어쓰지 않는다
assert bak.read_text(encoding="utf-8") == orig_page
assert sum("원본 백업" in l for l in logs) == 1
print("설치 확인: 기존 13_현장모니터링.py 는 .orig 로 백업, 재설치해도 원본 유지")

calls = {"kpi": None, "dataframes": 0, "plots": 0, "iframe": None}


class FakeSt(types.ModuleType):
    def __init__(self):
        super().__init__("streamlit")
        self.session_state = {"logged_in": True, "user_role": "ADMIN"}
    def columns(self, spec, **k): return [MagicMock() for _ in range(spec if isinstance(spec, int) else len(spec))]
    def selectbox(self, label, options, **k): return options[0]
    def text_input(self, label, value="", **k): return value
    def checkbox(self, label, value=False, **k): return value
    def number_input(self, label, value=0, **k): return value
    def dataframe(self, df, **k): calls["dataframes"] += 1
    def plotly_chart(self, fig, **k): calls["plots"] += 1
    def rerun(self): pass
    def __getattr__(self, name): return MagicMock()


st = FakeSt()
comp = types.ModuleType("streamlit.components.v1")
comp.iframe = lambda src, **k: calls.__setitem__("iframe", src)
st.components = types.SimpleNamespace(v1=comp)
sys.modules.update({"streamlit": st, "streamlit.components": st.components, "streamlit.components.v1": comp,
                    "plotly": MagicMock(), "plotly.graph_objects": MagicMock()})
for name in [m for m in sys.modules if m == "src" or m.startswith("src.")]:
    del sys.modules[name]
if str(mes) in sys.path:
    sys.path.remove(str(mes))
sys.path.insert(0, str(mes))
import src.ui as ui  # noqa: E402
ui.kpi_row = lambda items, columns=3: calls.__setitem__("kpi", {a: b for a, b, _ in items})
runpy.run_path(str(mes / "pages" / "13_현장모니터링.py"), run_name="__main__")

print("KPI:", calls["kpi"], "| 그래프", calls["plots"], "개, 표", calls["dataframes"], "개, iframe", calls["iframe"])
assert calls["kpi"]["AI 상태"] == "정상" and calls["kpi"]["활성 경보"] == "0 건"   # 마지막에 정상으로 돌아와 있다
assert calls["plots"] == 2 and calls["dataframes"] >= 3
assert calls["iframe"] == "http://localhost:5001/?embed=1"
print("\n테스트 통과")
