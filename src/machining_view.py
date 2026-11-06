"""가공 라인(PLC)의 3D 화면용 움직임 값.

PLC 센서/출력만으로는 "실린더가 지금 얼마나 나와 있는지"를 알 수 없다 (전진 센서도 후진 센서도 꺼져 있으면 이동 중).
솔레노이드 출력을 먼저 보고, 꺼져 있으면 센서를 보고, 둘 다 없으면 이전 값을 유지해서 0(후진/위) ~ 1(전진/아래) 값을 만든다.
3D 장면 JSON 은 이 값(derived.*)에 로드 길이와 머리 위치를 연결한다.
"""


class MachiningView:
    def __init__(self):
        self.d = {"sup": 0.0, "out": 0.0, "ej": 0.0, "tip": 0.0}

    def update(self, dev):
        g = lambda k: int(bool(dev[k]))
        pick = lambda prev, fwd_out, bwd_out, fwd_sw, bwd_sw: (
            1.0 if g(fwd_out) else 0.0 if g(bwd_out) else 1.0 if g(fwd_sw) else 0.0 if g(bwd_sw) else prev)
        d = self.d
        d["sup"] = pick(d["sup"], "Y20", "Y21", "X1", "X0")     # 공급 푸셔
        d["out"] = pick(d["out"], "Y23", "Y24", "X5", "X4")     # 이송 푸셔
        d["ej"] = pick(d["ej"], "Y25", "Y26", "X7", "X6")       # 분류 푸셔
        d["tip"] = 1.0 if g("Y22") else 0.0                     # 드릴 비트 (1 = 아래로 내려감)

    def snapshot(self):
        return dict(self.d)
