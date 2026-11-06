"""src/terms.json 에서 용어 문서(docs/glossary.md)를 만들고, 태그맵(docs/tagmap.csv)에 '현장 명칭' 열을 채운다.
용어를 바꾼 뒤 실행하면 문서가 따라 바뀐다.

실행 (프로젝트 폴더에서):  python tools/make_glossary.py
"""
import csv
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
D = json.loads((ROOT / "src" / "terms.json").read_text(encoding="utf-8"))
T, TAGS = D["terms"], D["tags"]

# ---- 태그맵: name_ko(장비 원명칭) 옆에 field_name(현장 명칭) 열
path = ROOT / "docs" / "tagmap.csv"
rows = list(csv.DictReader(open(path, encoding="utf-8-sig")))
cols = list(rows[0].keys())
if "field_name" not in cols:
    cols.insert(cols.index("name_ko") + 1, "field_name")
for r in rows:
    r["field_name"] = TAGS.get(r["tag_id"], {}).get("field", "")
with open(path, "w", newline="", encoding="utf-8-sig") as f:
    w = csv.DictWriter(f, fieldnames=cols)
    w.writeheader(); w.writerows(rows)

# ---- 용어 문서
parts = [("magazine", "적층한 워크를 쌓아 두고 한 개씩 내보내는 곳"), ("feed_pusher", "공급기의 워크를 가공 위치로 미는 실린더"),
         ("drill", "워크에 구멍을 내는 가공 장치 (모터, 헤드, 상하 실린더)"), ("transfer_pusher", "가공이 끝난 워크를 컨베이어 쪽으로 미는 실린더"),
         ("conveyor", "워크를 옮기는 벨트"), ("sort_pusher", "재질 판별 결과가 정품이면 수납함으로 밀어내는 실린더"),
         ("ok_bin", "정품이 모이는 상자"), ("ng_bin", "이종품(재질 불일치)이 모이는 상자"), ("stack_light", "설비 상태 표시등 (녹색 가동, 황색 대기·주의, 적색 이상)"),
         ("workpiece", "가공 대상 부품")]
sort = [("ok_part", "인덕티브 근접센서로 재질을 판별해 금속이면 정품"), ("ng_part", "금속이 아니면 이종품(재질 불일치). MES 검사에서는 이종품 혼입 불량 (사유 MAT_MIX)")]
L = ["# 용어 사전", "",
     "화면에 보이는 이름은 `src/terms.json` 한 곳에서 정합니다. 3D, 2D 화면의 **용어** 선택칸과 MES 사이드바의 **용어** 선택으로 현장 용어와 장비 원명칭을 전환할 수 있습니다.",
     "코드 안의 태그 ID(예: `SUP_FWD_SOL`), PLC 프로그램, 이벤트 이름은 그대로입니다. 장비 원명칭은 학원 실습 장비(미쓰비시 Q02H PLC, Pro-face HMI)에서 쓰던 이름입니다.",
     "", "## 장비와 부품", "", "| 현장 용어 | 장비 원명칭 | 설명 |", "|---|---|---|"]
L += [f"| {T[k]['field']} | {T[k]['lab']} | {d} |" for k, d in parts]
L += ["", "## 재질 분류", "", "| 현장 용어 | 장비 원명칭 | 설명 |", "|---|---|---|"]
L += [f"| {T[k]['field']} | {T[k]['lab']} | {d} |" for k, d in sort]
tm = {r["tag_id"]: r for r in rows}
L += ["", "## 센서, 출력, 데이터 (PLC 디바이스)", "", "| 디바이스 | 태그 ID | 현장 명칭 | 장비 원명칭 |", "|---|---|---|---|"]
for tid, v in TAGS.items():
    L.append(f"| {tm[tid]['plc_device']} | `{tid}` | {v['field']} | {v['lab']} |")
(ROOT / "docs" / "glossary.md").write_text("\n".join(L) + "\n", encoding="utf-8")
print("docs/glossary.md, docs/tagmap.csv 갱신")
