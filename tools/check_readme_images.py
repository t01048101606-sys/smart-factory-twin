"""README.md 가 가리키는 이미지 파일이 모두 있는지 확인합니다 (공개 전에 한 번 실행).

실행 (프로젝트 폴더에서):  python tools/check_readme_images.py
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
text = (ROOT / "README.md").read_text(encoding="utf-8")
refs = re.findall(r"!\[[^\]]*\]\(([^)\s]+)\)", text)
missing = [r for r in refs if not r.startswith("http") and not (ROOT / r).exists()]
for r in refs:
    print(("없음  " if r in missing else "있음  ") + r)
print(f"\n이미지 {len(refs)}개 중 {len(missing)}개 없음")
sys.exit(1 if missing else 0)
