"""스마트 팩토리 현황 허브 페이지: 고른 하위 화면 하나만 실행하고, set_page_config(setup_page)는 한 번만 부른다.
가짜 streamlit 과 가짜 src.ui 로 허브 코드만 검사한다 (하위 화면의 내용은 test_mes_*.py 가 검사한다)."""
import shutil
import sys
import tempfile
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
tmp = Path(tempfile.mkdtemp(prefix="hub_"))
(tmp / "pages").mkdir(); (tmp / "sections").mkdir(); (tmp / "src").mkdir()
shutil.copy2(ROOT / "mes" / "addons" / "pages" / "13_스마트팩토리현황.py", tmp / "pages")
names = ["overview", "machining", "press", "cobot", "logistics"]
for n in names:       # 하위 화면 대신: 자기 이름을 기록하고, 페이지 설정을 시도한다
    (tmp / "sections" / f"{n}.py").write_text(f"import streamlit as st\nfrom src.ui import setup_page\nsetup_page('{n}')\nst.RAN.append('{n}')\n", encoding="utf-8")
(tmp / "src" / "__init__.py").write_text("", encoding="utf-8")
(tmp / "src" / "ui.py").write_text("CALLS = []\ndef setup_page(t):\n    CALLS.append(t)\ndef require_role(*r):\n    pass\n", encoding="utf-8")
sys.path.insert(0, str(tmp))

st = types.ModuleType("streamlit")
st.RAN, st.titles, st.options = [], [], []
st.title = lambda t, **k: st.titles.append(t)
st.divider = lambda: None
def radio(label, options, **k):
    st.options = list(options)
    return st.options[st.pick]
st.radio = radio
sys.modules["streamlit"] = st
import runpy
import src.ui as ui

want = ["종합", "가공 라인", "프레스 · 용접 · 도장 라인", "협동로봇 셀", "물류 · 출하"]
for i, n in enumerate(names):
    st.pick = i; st.RAN.clear(); ui.CALLS.clear(); orig = ui.setup_page
    runpy.run_path(str(tmp / "pages" / "13_스마트팩토리현황.py"), run_name="__main__")
    assert st.options == want, st.options
    assert st.RAN == [n], (n, st.RAN)                                  # 고른 화면 하나만 실행된다
    assert ui.CALLS == ["스마트 팩토리 현황"], ui.CALLS                   # 하위 화면의 setup_page 는 무시되고, 허브가 한 번만 부른다
    assert ui.setup_page is orig                                       # 실행 뒤에는 원래대로 돌아와 있다
assert st.titles[-1] == "스마트 팩토리 현황"
print("허브: 5개 하위 화면을 각각 골랐을 때 그 화면만 실행, 페이지 설정은 한 번만, 메뉴 이름:", " / ".join(want))
print("\n테스트 통과")
