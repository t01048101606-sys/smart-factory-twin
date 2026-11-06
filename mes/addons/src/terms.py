"""화면에 보이는 이름 (현장 용어 / 장비 원명칭). 트윈 저장소의 src/terms.json 을 같이 쓴다.

MES 에 설치할 때(mes_adapter.py --install-addons) src/terms.json 이 MES 의 src/ 로 복사된다.
코드 안의 태그 ID, PLC 프로그램, 이벤트 이름은 그대로고, 사람이 읽는 이름만 바뀐다.
"""
from __future__ import annotations

import json
from pathlib import Path

MODES = {"field": "현장 용어", "lab": "장비 원명칭"}
_cache: dict | None = None


def data() -> dict:
    global _cache
    if _cache is None:
        here = Path(__file__).resolve()
        for p in (here.with_name("terms.json"), here.parents[3] / "src" / "terms.json"):   # MES 설치본, 트윈 저장소
            if p.exists():
                _cache = json.loads(p.read_text(encoding="utf-8"))
                break
        else:
            _cache = {"terms": {}, "tags": {}, "default_mode": "field"}
    return _cache


def t(key: str, mode: str = "field") -> str:
    e = data()["terms"].get(key)
    return e.get(mode) or e.get("lab") or key if e else key


def tag(tag_id: str, mode: str = "field") -> str:
    e = data()["tags"].get(tag_id)
    return e.get(mode) or e.get("lab") or tag_id if e else tag_id


def mode_selector(st, default: str = "field") -> str:
    """사이드바에 '용어' 선택칸을 만들고 고른 모드(field 또는 lab)를 돌려준다."""
    try:
        choice = st.sidebar.selectbox("용어", list(MODES.values()), index=0 if default == "field" else 1, key="terms_mode")
    except Exception:
        return default
    for k, v in MODES.items():
        if choice == v:
            return k
    return default
