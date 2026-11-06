"""도장(전착) 공정: 부품이 행거에 매달려 전착조 액 속으로 내려갔다 올라오는 동작.

전착 도장은 오버헤드 컨베이어의 행거가 부품을 탱크에 내리고(부품이 음극이 되어 전압을 건다), 도료가 입혀진 뒤 올려서 후수세와 건조로로 보낸다.
공정 진행도 p(0~1)에서 침지 깊이 0~1: 위에서 잠깐 대기 -> 내려감 -> 액 속에서 전압을 걸고 유지 -> 올라옴 -> 위에서 대기.
"""
import math

STATION_X, TOP_Y, DEPTH = 7.8, 1.42, 0.95        # 도장 위치 x, 부품 중심 높이(위), 액 속으로 내려가는 깊이 (아래 = 0.47)


def _smooth(x):
    return 0.5 - 0.5 * math.cos(math.pi * max(0.0, min(1.0, x)))


def dip(p, working=True):
    """침지 깊이 0(위) ~ 1(액 속)."""
    if not working:
        return 0.0
    if p < 0.12:
        return 0.0
    if p < 0.30:
        return _smooth((p - 0.12) / 0.18)
    if p < 0.70:
        return 1.0
    if p < 0.88:
        return 1.0 - _smooth((p - 0.70) / 0.18)
    return 0.0


def part_y(d):
    return round(TOP_Y - DEPTH * d, 3)
