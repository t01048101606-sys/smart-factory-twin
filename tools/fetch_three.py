"""three.js(3D 화면용)를 src/static/vendor 에 내려받는다. 인터넷이 되는 곳에서 한 번만 실행하면,
그 뒤로는 인터넷이 없어도 /3d 화면이 열린다. (실행하지 않아도 인터넷이 되면 CDN에서 불러온다)

실행 (프로젝트 폴더에서):  python tools/fetch_three.py
"""
import urllib.request
from pathlib import Path

VERSION = "0.170.0"
BASE = f"https://cdn.jsdelivr.net/npm/three@{VERSION}"
ROOT = Path(__file__).resolve().parent.parent
FILES = {
    f"{BASE}/build/three.module.min.js": ROOT / "src" / "static" / "vendor" / "three.module.js",
    f"{BASE}/examples/jsm/controls/OrbitControls.js": ROOT / "src" / "static" / "vendor" / "addons" / "controls" / "OrbitControls.js",
}

for url, dst in FILES.items():
    dst.parent.mkdir(parents=True, exist_ok=True)
    with urllib.request.urlopen(url, timeout=30) as r:
        data = r.read()
    dst.write_bytes(data)
    print(f"저장: {dst.relative_to(ROOT)} ({len(data) / 1024:.0f} KB)")
print("완료. 트윈 서버를 다시 켜면 /3d 화면이 이 파일을 사용합니다.")
