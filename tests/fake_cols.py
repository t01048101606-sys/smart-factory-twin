"""시험용 흉내 화면의 열(column): 눌러야 할 버튼 이름을 정해 두면 그 버튼만 눌린 것으로 돌려준다 (MES 페이지의 조작 버튼 시험)."""
from unittest.mock import MagicMock


class Col(MagicMock):
    clicks = set()

    def button(self, label, key=None, **k):
        return True if label in Col.clicks else MagicMock()

    def selectbox(self, label, options, index=0, key=None, **k):
        return options[index]
