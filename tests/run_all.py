"""모든 시험(tests/test_*.py)을 차례로 실행하고 결과를 표로 보여 줍니다.

실행 (프로젝트 폴더에서):  python tests/run_all.py            전체
                          python tests/run_all.py cobot line  이름에 cobot 또는 line 이 들어간 시험만
각 시험은 별도 프로세스로 돌리고, 마지막 줄이 '테스트 통과'(또는 '페이지 실행 테스트 통과')이면 통과로 봅니다.
Node.js 가 없으면 3D 뷰어 시험(test_factory, test_linescene, test_twin3d)은 스스로 건너뜁니다.
"""
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
LONG = {"test_mes_press_line": 400, "test_cobot_flow": 300, "test_mes_logistics": 300, "test_monitor": 300, "test_mes_page": 300}   # 오래 걸리는 시험은 제한 시간을 넉넉히
want = sys.argv[1:]
files = sorted(f for f in HERE.glob("test_*.py") if not want or any(w in f.stem for w in want))
rows, t00 = [], time.time()
for f in files:
    t0 = time.time()
    try:
        r = subprocess.run([sys.executable, str(f)], capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=LONG.get(f.stem, 180), cwd=HERE.parent)
        out = [l for l in r.stdout.strip().splitlines() if l.strip()]
        ok = r.returncode == 0 and bool(out) and out[-1].strip().endswith("통과")
        note = "" if ok else ((r.stderr.strip().splitlines() or out or ["(출력 없음)"])[-1][:90])
    except subprocess.TimeoutExpired:
        ok, note = False, "시간 초과"
    rows.append((f.stem, ok, time.time() - t0, note))
    print(f"{'통과' if ok else '실패'}  {f.stem:<24}{rows[-1][2]:6.1f}초  {note}", flush=True)
bad = [r for r in rows if not r[1]]
print(f"\n{len(rows) - len(bad)} / {len(rows)} 통과 ({time.time() - t00:.0f}초)")
sys.exit(1 if bad else 0)
