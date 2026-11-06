"""가공 라인 페이지(14_가공라인.py: OEE + AI 이상 감지 + 2D/3D 트윈)를 Streamlit 없이 끝까지 실행해서 오류가 없는지 확인합니다.
설치할 때 합쳐져서 없어진 옛 페이지(13~17번)가 지워지고 새 페이지 5개가 설치되는지도 확인합니다.

Streamlit과 plotly는 흉내 내는 임시 모듈로 바꿔 끼우고, DB는 실제 어댑터가 채운 것을 씁니다.
MES 폴더는 임시 폴더로 복사해서 쓰므로 원본은 바뀌지 않습니다.
실행:  python tests/test_mes_page.py [MES 폴더 경로]
"""
import runpy
import sys
import types
from datetime import date
from pathlib import Path
from unittest.mock import MagicMock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tests"))
sys.argv = [sys.argv[0]] + sys.argv[1:2]
import test_mes_adapter as T  # noqa: E402  (어댑터 시나리오를 한 번 돌려 DB를 채운다)

from mes_adapter import MesAdapter  # noqa: E402

mes = T.mes
# 앞선 테스트가 MES 폴더 두 개를 번갈아 썼고 마지막에 시연 데이터도 지웠으므로,
# 시나리오 1의 MES 폴더로 어댑터를 새로 만들어(모듈을 다시 불러온다) 같은 이벤트를 처음부터 넣는다
ad = MesAdapter(mes, batch=4, today=lambda: date(2026, 11, 6), log=lambda m: None)
ad.init_db(); ad.seed_master()
for e in T.ev:
    ad.handle(e)
ad.install_addons()
page = mes / "sections" / "machining.py"
assert page.exists() and (mes / "src" / "oee.py").exists()
OLD = ("13_현장모니터링", "14_설비현황", "15_공정3D", "16_프레스라인", "17_공장현황")
NEW = ("sections/overview", "sections/machining", "sections/press", "sections/cobot", "sections/logistics")
GONE = ("13_공장현황", "14_가공라인", "15_프레스라인", "16_협동로봇셀", "17_물류출하")
assert not any((mes / "pages" / f"{n}.py").exists() for n in OLD + GONE), "합쳐져서 없어진 옛 페이지가 지워져야 합니다"
assert all((mes / f"{n}.py").exists() for n in NEW) and (mes / "pages" / "13_스마트팩토리현황.py").exists()
assert sorted(p.name for p in (mes / "pages").glob("1[3-9]_*.py")) == ["13_스마트팩토리현황.py"], "13번 이후 사이드바 항목은 스마트 팩토리 현황 하나뿐이어야 합니다"
print("페이지 정리: 옛 페이지 삭제, 스마트 팩토리 현황 1개 + 하위 화면 5개 설치:", ", ".join(NEW))

# ---- 흉내 내는 streamlit / plotly
calls = {"kpi": {}, "iframes": [], "dataframes": 0, "reruns": 0, "radio": 0, "hide": False}


class FakeSt(types.ModuleType):
    def __init__(self):
        super().__init__("streamlit")
        self.session_state = {"logged_in": True, "user_role": "ADMIN"}

    def columns(self, spec, **k):
        n = spec if isinstance(spec, int) else len(spec)
        return [MagicMock() for _ in range(n)]

    def selectbox(self, label, options, **k): return options[0]
    def text_input(self, label, value="", **k): return value
    def checkbox(self, label, value=False, **k): return calls["hide"] if "숨기기" in label else value
    def tabs(self, labels): return [MagicMock() for _ in labels]
    def radio(self, label, options, **k): return options[calls["radio"]]
    def number_input(self, label, value=0, **k): return value
    def dataframe(self, df, **k): calls["dataframes"] += 1
    def rerun(self): calls["reruns"] += 1
    def __getattr__(self, name): return MagicMock()


st = FakeSt()
comp = types.ModuleType("streamlit.components.v1")
comp.iframe = lambda src, **k: calls["iframes"].append(src)
st.components = types.SimpleNamespace(v1=comp)
sys.modules.update({"streamlit": st, "streamlit.components": st.components, "streamlit.components.v1": comp})
sys.modules["plotly"] = MagicMock()
sys.modules["plotly.graph_objects"] = MagicMock()

# 어댑터 시나리오 2(비금속만)가 'src' 모듈 캐시를 바꿔 놓았으므로, 시나리오 1의 MES 폴더로 다시 맞춘다
for name in [m for m in sys.modules if m == "src" or m.startswith("src.")]:
    del sys.modules[name]
sys.path.insert(0, str(mes))
import src.ui as ui  # noqa: E402  (MES의 공통 UI. streamlit을 흉내 낸 모듈 위에서 불러온다)
ui.kpi_row = lambda items, columns=3: calls["kpi"].update(dict((a, b) for a, b, _ in items))      # 합쳐진 페이지는 KPI 를 여러 번(OEE, AI) 낸다
runpy.run_path(str(page), run_name="__main__")

kpi = calls["kpi"]
print("KPI:", kpi)
print("iframe:", calls["iframes"], "| 이벤트 표 표시 횟수:", calls["dataframes"])
assert kpi and all(k in kpi for k in ("OEE", "가용률", "성능률", "품질률"))
assert calls["iframes"] == ["http://localhost:5001/?embed=1", "http://localhost:5001/3d?embed=view"], calls["iframes"]      # 2D(조작 포함)와 3D(보기 전용)가 동시에
assert calls["dataframes"] >= 2
q = float(kpi["품질률"].rstrip("%"))
assert 40 <= q <= 60, f"번갈아 투입이므로 품질률은 50% 안팎이어야 합니다: {q}"
a, p, o = (float(kpi[k].rstrip("%")) for k in ("가용률", "성능률", "OEE"))
assert abs(a * p * q / 10000 - o) < 0.2, (a, p, q, o)
# ---- 배치(좌우, 위아래)와 2D 조작 패널 숨기기: 어느 쪽이든 2D 와 3D 가 둘 다 나온다
for radio, hide, want2d in ((0, False, "http://localhost:5001/?embed=1"), (1, False, "http://localhost:5001/?embed=1"),
                            (0, True, "http://localhost:5001/?embed=view"), (1, True, "http://localhost:5001/?embed=view")):
    calls["radio"], calls["hide"], calls["iframes"] = radio, hide, []
    runpy.run_path(str(page), run_name="__main__")
    assert calls["iframes"] == [want2d, "http://localhost:5001/3d?embed=view"], (radio, hide, calls["iframes"])
print("가공 라인 페이지: 2D와 3D가 동시에 표시됨 (좌우 / 위아래, 2D 조작 패널 숨기기 선택에 따라 2D 주소만 바뀜)")

print("\n페이지 실행 테스트 통과")
