"""가공 라인 3D 장면(디테일링한 센서, 실린더 부속, 제어반)을 숫자로 확인합니다. 3D 화면을 눈으로 볼 수 없으므로 겹침과 연결을 계산합니다.

실행 (프로젝트 폴더에서):  python tests/test_machining_scene.py
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sc = json.loads((ROOT / "src" / "scenes" / "machining.json").read_text(encoding="utf-8"))
objs = sc["objects"]
ids = [o["id"] for o in objs if o.get("id")]
assert len(ids) == len(set(ids)), [i for i in ids if ids.count(i) > 1]
by = {o["id"]: o for o in objs if o.get("id")}

# 1) 연결: LED, 램프가 읽는 PLC 값이 서버가 보내는 상태 키에 있다 (X0~X0A, Y20~Y2B, D*)
import re  # noqa: E402
src = (ROOT / "src" / "server.py").read_text(encoding="utf-8")
assert 'f"X{i}" if i < 10 else f"X0{i:X}" for i in range(0, 11)' in src and 'f"Y{i:X}" for i in range(0x20, 0x2C)' in src      # 서버의 STATE_KEYS 정의 (flask 없이 같은 식으로 계산)
keys = set([f"X{i}" if i < 10 else f"X0{i:X}" for i in range(0, 11)] + [f"Y{i:X}" for i in range(0x20, 0x2C)] + ["D0", "D2", "D4", "D10"])
used = {a["path"] for o in objs for a in o.get("anim", []) if a["prop"] in ("emissive", "color", "lamp", "visible") and not a["path"].startswith(("ai.", "derived."))}
assert used <= keys, used - keys
leds = [i for i in ids if "_led" in i]
assert {by[i]["anim"][0]["path"] for i in leds if i.endswith(("_back", "_front", "_down", "_up"))} == {"X0", "X1", "X2", "X3", "X4", "X5", "X6", "X7"}   # 리드 스위치 8개 = 실린더 위치 입력 전부
assert by["sensor_metal_led"]["anim"][0]["path"] == "X9" and by["sensor_nonmetal_led"]["anim"][0]["path"] == "X0A"
assert by["belt_motor"]["anim"][0]["path"] == "Y27"

# 2) 겹침: 새로 붙인 정적 부속이 움직이는 부분(푸셔 머리, 드릴 비트, 작업물 경로)의 이동 범위와 겹치지 않는다
def aabb(o):
    if o["shape"] == "box":
        h = [v / 2 for v in o["size"]]
    elif o["shape"] == "cylinder":
        r = o["r"]; h = [r, o["h"] / 2, r] if not o.get("rot") else [r, r, o["h"] / 2]
        if o.get("rot") and abs(o["rot"][0] - 1.5707963) < 1e-6:
            h = [r, r, o["h"] / 2]
    elif o["shape"] == "sphere":
        h = [o["r"]] * 3
    else:
        return None
    p = o["pos"]
    return [(p[i] - h[i], p[i] + h[i]) for i in range(3)]

PY = 0.8
SWEEPS = {   # 이름: ((x0, x1), (y0, y1), (z0, z1))
    "공급 푸셔": ((-9.8, -4.15), (PY - 0.45, PY + 0.45), (-0.45, 0.45)),
    "이송 푸셔": ((-3.95, -3.05), (PY - 0.45, PY + 0.45), (-3.2, 2.55)),
    "분류 푸셔": ((2.3, 3.2), (PY - 0.45, PY + 0.45), (1.8, 4.95)),
    "드릴 비트": ((-3.62, -3.38), (1.1, 3.3), (-0.12, 0.12)),
    "작업물 경로(공급, 가공, 이송)": ((-7.4, -3.0), (0.5, 1.1), (-0.45, 3.65)),
    "작업물 경로(벨트)": ((-3.5, 10.5), (0.5, 1.1), (2.75, 3.65)),
    "작업물 경로(분류)": ((2.3, 3.2), (0.2, 1.1), (3.2, 6.6)),
}
NEW = ("feed_cap", "feed_port", "feed_led", "transfer_cap", "transfer_port", "transfer_led", "sort_cap", "sort_port", "sort_led", "drill_fin", "drill_cap",
       "drill_sleeve", "drill_led", "sensor_", "belt_gearbox", "belt_motor", "panel_", "frl_")
hit = []
for o in objs:
    if not o.get("id", "").startswith(NEW):
        continue
    b = aabb(o)
    for nm, sw in SWEEPS.items():
        if all(b[i][0] < sw[i][1] - 1e-9 and b[i][1] > sw[i][0] + 1e-9 for i in range(3)):
            hit.append((o["id"], nm))
# 허용: 푸셔 본체에 붙은 캡, 포트, LED 는 자기 푸셔의 이동 범위 끝(몸통)과 맞닿는 곳이라 이동 범위와 겹치지 않아야 한다. 드릴 슬리브는 비트가 지나는 통로
# 앞쪽 캡은 피스톤 로드가 지나가는 구멍(글랜드)이라 자기 푸셔의 범위에 걸치는 것이 맞다
hit = [h for h in hit if not (h[0] == "drill_sleeve" and h[1] == "드릴 비트") and not (h[0].endswith("_cap_front") and h[1].endswith("푸셔"))]
assert not hit, hit
n_new = sum(1 for o in objs if o.get("id", "").startswith(NEW))

# 3) 센서 높이: 작업물 윗면(1.1m)보다 위, 작업물 중심선과 겹치지 않고, 브래킷이 벨트 레일(z=4.1)을 피한다
assert aabb(by["sensor_metal"])[1][0] > 1.1 and aabb(by["sensor_nonmetal"])[1][0] > 1.1
assert abs(by["sensor_metal"]["pos"][2] - 3.2) < 1e-9 and by["sensor_post"]["pos"][2] > 4.2
# 4) 제어반 / 에어 유닛은 컨베이어, 수납함, 푸셔와 떨어져 있다
for nm in ("panel_body", "frl_stand"):
    b = aabb(by[nm])
    for o in objs:
        if o.get("id", "").startswith(("conveyor_body", "ok_bin", "ng_bin", "transfer_body", "feed_body", "sort_body", "magazine", "transfer_plate", "rail")):
            c = aabb(o)
            assert not all(b[i][0] < c[i][1] - 1e-9 and b[i][1] > c[i][0] + 1e-9 for i in range(3)), (nm, o["id"])
print(f"가공 라인 장면: 디테일 {n_new}개, LED 8개가 실린더 위치 입력(X0~X7)과 연결, 센서 X9/X0A, 정적 부속이 푸셔 · 비트 · 작업물 경로와 겹치지 않음")
print("\n테스트 통과")
