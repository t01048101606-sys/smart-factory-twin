"""스마트 팩토리 현황: 종합, 가공 라인, 프레스 라인, 협동로봇 셀, 물류 출하를 한 메뉴 아래에서 전환해서 본다.

MES 왼쪽 메뉴는 파일 하나가 항목 하나라서 메뉴 안에 하위 메뉴를 둘 수 없다. 그래서 하위 화면의 코드는 sections/ 폴더에 두고,
이 페이지에서 고른 화면 하나만 실행한다 (고르지 않은 화면은 실행하지 않아서 트윈 서버 호출도 하지 않는다).
"""
import runpy
from pathlib import Path

import streamlit as st

from src import ui
from src.ui import require_role, setup_page

SECTIONS = {
    "종합": "overview.py",
    "가공 라인": "machining.py",
    "프레스 · 용접 · 도장 라인": "press.py",
    "협동로봇 셀": "cobot.py",
    "물류 · 출하": "logistics.py",
}

setup_page("스마트 팩토리 현황")
require_role("ADMIN", "OPERATOR", "INSPECTOR")
st.title("스마트 팩토리 현황")
choice = st.radio("보기", list(SECTIONS), horizontal=True, key="sf_section", label_visibility="collapsed")
st.divider()

# 하위 화면도 setup_page 를 부르는데 set_page_config 는 한 번만 부를 수 있으므로, 실행하는 동안만 아무 일도 하지 않게 바꿔 둔다
real_setup = ui.setup_page
ui.setup_page = lambda *a, **k: None
try:
    runpy.run_path(str(Path(__file__).resolve().parent.parent / "sections" / SECTIONS[choice]), run_name="__main__")
finally:
    ui.setup_page = real_setup
