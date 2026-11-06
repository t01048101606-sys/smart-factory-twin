"""용어 사전(src/terms.json)과 그것을 쓰는 곳(MES 이벤트 표, MES 기준정보 이름, 설치)을 확인합니다.

실행 (프로젝트 폴더에서):  python tests/test_terms.py [MES 폴더 경로]
"""
import csv
import importlib.util
import json
import re
import shutil
import sqlite3
import sys
import tempfile
from datetime import date
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
MES_SRC = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT.parent / "AutoParts-MES-Arduino"
D = json.loads((ROOT / "src" / "terms.json").read_text(encoding="utf-8"))

# ---- 1) 사전 자체: 모든 항목에 현장 용어와 장비 원명칭이 있고, 태그가 태그맵과 맞는다
for group in ("terms", "tags"):
    for k, v in D[group].items():
        assert v.get("field") and v.get("lab"), (group, k)
tagmap = {r["tag_id"]: r for r in csv.DictReader(open(ROOT / "docs" / "tagmap.csv", encoding="utf-8-sig"))}
for tid, v in D["tags"].items():
    assert tid in tagmap, f"태그맵에 없는 태그: {tid}"
    assert v["lab"] == tagmap[tid]["name_ko"], (tid, v["lab"], tagmap[tid]["name_ko"])   # 장비 원명칭 = 태그맵의 기존 이름
missing = [t for t in tagmap if tagmap[t]["direction"] in ("IN", "OUT", "CMD", "DATA") and t not in D["tags"]]
assert not missing, f"사전에 없는 태그: {missing}"
print(f"사전 확인: 이름 {len(D['terms'])}개, 태그 {len(D['tags'])}개 (장비 원명칭은 태그맵의 기존 이름과 같음, 모든 입출력 태그 포함)")

# ---- 2) 화면 코드가 쓰는 키가 모두 사전에 있다
for js in ("twin3d.js", "twin3d.html", "index.html"):
    src = (ROOT / "src" / "static" / js).read_text(encoding="utf-8")
    keys = set(re.findall(r"data-term=\"([\w.]+)\"", src)) | set(re.findall(r"(?:label|Terms\.t)\('([\w.]+)'", src))
    bad = [k for k in keys if k not in D["terms"]]
    assert not bad, (js, bad)
print("3D, 2D 화면이 쓰는 이름 키가 모두 사전에 있음")

# ---- 3) MES 이벤트 표: 모드에 따라 이름이 바뀐다
spec = importlib.util.spec_from_file_location("oee", ROOT / "mes" / "addons" / "src" / "oee.py")
oee = importlib.util.module_from_spec(spec); spec.loader.exec_module(oee)
ts = pd.Timestamp("2026-11-06T00:00:00Z")
row = lambda typ, p: {"payload": p, "event_type": typ}
cases = [(row("cycle.step", {"step": "out_forward"}), "이송 푸셔 전진", "송출 전진"),
         (row("cycle.step", {"step": "eject"}), "분류 푸셔 동작 (정품 배출)", "금속 배출"),
         (row("piece.classified", {"kind": "nonmetal", "sensor": "x"}), "이종품 (재질 불일치)", "비금속 (이종 재질 혼입)"),
         (row("count.updated", {"metal": 3, "nonmetal": 2, "total": 5}), "정품 3 / 이종품 2 / 합계 5", "금속 3 / 비금속 2 / 합계 5")]
for r, field, lab in cases:
    assert oee.describe(r, "field") == field and oee.describe(r, "lab") == lab, (oee.describe(r, "field"), oee.describe(r, "lab"))
tbl = oee.recent_events(pd.DataFrame([{"ts": ts, "seq": 1, "event_type": "cycle.step", "piece_id": "P-1", "payload": {"step": "drilling"}}]), 5, "lab")
assert list(tbl["내용"]) == ["가공 중"]
print("MES 이벤트 표: 현장 용어 / 장비 원명칭 전환 확인 (예: 이송 푸셔 전진 <-> 송출 전진)")

# ---- 4) 어댑터: MES 기준정보 이름이 현장 용어로 등록되고, 예전 이름은 갱신되며, terms.json 이 설치된다
from mes_adapter import MesAdapter  # noqa: E402
tmp = Path(tempfile.mkdtemp(prefix="mes_terms_"))
mes = tmp / "mes"
shutil.copytree(MES_SRC, mes, ignore=shutil.ignore_patterns(".git", "__pycache__", "*.docx", "*.pdf", "*.db", "*.db-*"))
ad = MesAdapter(mes, today=lambda: date(2026, 11, 6), log=lambda m: None)
ad.init_db(); ad.seed_master()
db = mes / "sql" / "auto_parts.db"
q = lambda sql: sqlite3.connect(db).execute(sql).fetchall()
names = dict(q("SELECT equipment_code, equipment_name FROM equipment"))
assert names["EQ-FEED-01"] == "공급 푸셔" and names["EQ-DRILL-01"] == "드릴링 유닛" and names["EQ-CONV-01"] == "벨트 컨베이어·분류 푸셔", names
assert q("SELECT reason_name FROM defect_reason_code WHERE reason_code='MAT_MIX'")[0][0] == "이종품 혼입(재질 불일치)"
c = sqlite3.connect(db); c.execute("UPDATE equipment SET equipment_name='공급 실린더' WHERE equipment_code='EQ-FEED-01'"); c.commit(); c.close()
ad.seed_master()   # 예전 이름으로 등록되어 있던 DB: 다시 맞춘다
assert dict(q("SELECT equipment_code, equipment_name FROM equipment"))["EQ-FEED-01"] == "공급 푸셔"
ad.install_addons()
assert json.loads((mes / "src" / "terms.json").read_text(encoding="utf-8")) == D
print("MES 기준정보: 설비 공급 푸셔 / 드릴링 유닛 / 벨트 컨베이어·분류 푸셔, 불량 사유 '이종품 혼입(재질 불일치)', 예전 이름 갱신, terms.json 설치 확인")
print("\n테스트 통과")
