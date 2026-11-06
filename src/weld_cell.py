"""용접 셀: 6축 스폿 용접 로봇(4관절 + 서보 건)의 동작을 용접 공정 진행도(0~1)로 계산한다.

실제 스폿 용접 로봇(Yaskawa Motoman SP 시리즈 등)은 가반 하중 100~210kg, 리치 2.2~3.1m이고, C형 서보 건(가압력 2~7kN)으로
부품 가장자리의 플랜지를 위아래에서 전극으로 물어 용접한다. 여기서는 부품 가장자리 세 점을 차례로 용접한다.

  - C형 건은 위에서 내려올 수 없다 (아래 전극 팔이 부품에 걸린다). 로봇 쪽(-z)에서 높이를 맞춘 뒤 수평으로 들어가 플랜지 아래에 아래 전극을 넣고,
    위 전극이 내려와 물고(건 닫힘), 용접하고, 건을 열고 수평으로 빠진다.
  - 용접 지그의 클램프는 용접하는 동안 닫혀 있다.
위치 상수는 3D 장면(tools/make_press_scene.py)과 같다. 관절 각도는 협동로봇과 같은 역기구학(cobot_sim.ik)으로 구한다.
"""
import math

from cobot_sim import fk, ik

ARM_W = {"base": (-0.5, 1.2, -2.6), "L1": 2.7, "L2": 2.5, "L3": 1.5}     # 어깨 위치, 아래팔, 위팔, 손목에서 위 전극 끝(TCP)까지
PART_TOP, PART_BOTTOM = 1.53, 1.31          # 용접 지그 위 부품(두께 0.22)의 위, 아래 면
GAP = 0.22                                  # 건이 닫혔을 때 위 전극 끝과 아래 전극 끝 사이 = 부품 두께
GUN_OPEN = 0.28                             # 건이 열렸을 때 위 전극이 TCP 보다 더 올라가 있는 높이
SPOTS = [(-0.78, -0.38), (-0.5, -0.38), (-0.22, -0.38)]                  # 용접 점 (x, z): 부품의 로봇 쪽 가장자리 플랜지
APPROACH = 0.7                              # 로봇 쪽으로 물러나 있는 거리 (부품 밖)
HOME = (-0.5, 3.0, -1.2)                    # 대기 자세 TCP


def _tcp(spot, dz=0.0, dy=0.0, closed=False):
    """TCP(위 전극이 닫혔을 때의 끝)의 위치. 접근과 빠짐에서는 아래 전극이 부품 아래 면보다 0.03 아래, 용접할 때는 아래 면에 닿는다."""
    y = (PART_TOP if closed else PART_BOTTOM + GAP - 0.03) + dy
    return (spot[0], y, spot[1] + dz)


def _keys():
    """(진행도, TCP, 건 0=열림 1=닫힘, 불꽃) 키프레임."""
    k = [(0.00, HOME, 0, 0)]
    t = 0.07
    for s in SPOTS:
        hov = _tcp(s, -APPROACH, 0.7)
        appr = _tcp(s, -APPROACH)
        k += [(t, hov, 0, 0), (t + 0.05, appr, 0, 0), (t + 0.10, _tcp(s), 0, 0),
              (t + 0.12, _tcp(s, closed=True), 1, 0), (t + 0.15, _tcp(s, closed=True), 1, 1), (t + 0.19, _tcp(s, closed=True), 1, 1),
              (t + 0.20, _tcp(s), 0, 0), (t + 0.24, appr, 0, 0)]
        t += 0.27
    k += [(0.94, _tcp(SPOTS[-1], -APPROACH, 0.7), 0, 0), (1.0, HOME, 0, 0)]
    return k


KEYS = _keys()
JOINTS = [ik(tcp, ARM_W) for _, tcp, _, _ in KEYS]          # 닿지 않는 자세가 있으면 여기서 오류가 난다


def _smooth(x):
    return 0.5 - 0.5 * math.cos(math.pi * max(0.0, min(1.0, x)))


def pose(p, working):
    """공정 진행도 p(0~1)에서의 로봇 관절(라디안), 건 열림(0~1 닫힘 정도), 불꽃, 지그 클램프(1 = 닫힘)."""
    if not working:
        j, gun, spark, clamp = JOINTS[0], 0.0, False, 0.0
    else:
        p = max(0.0, min(1.0, p))
        i = max(0, min(len(KEYS) - 2, next((n for n in range(len(KEYS) - 1) if KEYS[n][0] <= p < KEYS[n + 1][0]), len(KEYS) - 2)))
        t0, t1 = KEYS[i][0], KEYS[i + 1][0]
        k = _smooth((p - t0) / (t1 - t0)) if t1 > t0 else 1.0
        a, b = JOINTS[i], JOINTS[i + 1]
        j = {n: a[n] + (b[n] - a[n]) * k for n in a}
        gun = KEYS[i][2] + (KEYS[i + 1][2] - KEYS[i][2]) * k
        spark = bool(KEYS[i][3] and KEYS[i + 1][3])
        clamp = 1.0 if 0.03 <= p <= 0.97 else 0.0
    return {**{n: round(v, 4) for n, v in j.items()}, "gun": round(gun, 3), "spark": spark, "clamp": clamp}


def lower_tip(j, gun=0.0):
    """아래 전극 끝의 위치 (TCP 에서 GAP 만큼 아래)."""
    x, y, z = fk(j, ARM_W)
    return (x, y - GAP, z)
