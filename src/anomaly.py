"""사이클 시간 이상 감지 (통계 기반, 설명 가능).

입력: 사이클이 끝날 때마다 (사이클 시간, 가공 시간 설정)
특징값: 가공 시간을 뺀 사이클 시간 = 공급, 이송 같은 기계 동작에 걸린 시간
        (가공 시간 D10을 바꿔도 이상으로 보이지 않게 하려는 것)

방법
  1) 학습: 처음 N개 사이클의 중앙값과 MAD(중앙값 절대편차)로 기준값과 산포를 정한다 (이상값에 강함).
     산포에는 최솟값을 둔다: max(0.05초, 기준값의 4%). 실제 컴퓨터에서는 부하에 따라 사이클 시간이
     0.1~0.2초 정도 이동하는데, 이것까지 이상으로 보지 않기 위해서다 (tests/data 의 실측 데이터로 확인).
  2) 점 판정: z = (값 - 기준) / 산포  이 임계값을 넘으면 이상 (갑작스러운 변화)
     빨라지는 쪽(z < 0)은 점수를 절반으로 본다: 설비 이상은 대개 느려지는 쪽이다. 크게 빨라지면 여전히 이상.
  3) 추세 판정: EWMA(지수 이동 평균)를 같은 방식으로 판정 (서서히 나빠지는 열화)
     단, 현재 사이클도 같은 방향으로 1 산포 넘게 벗어나 있어야 한다. 한 번 튄 값의 "꼬리"가
     정상 사이클 뒤에도 EWMA에 남아서 이상 2연속이 되는 것을 막기 위해서다 (실측 데이터에서 확인).
  4) 경보: 이상이 연속으로 raise_after번 나오면 경보 발생, 정상 범위(|z| < 3)가 clear_after번 이어지면 해제
AI는 판정과 경보만 낸다. 설비를 멈출지는 PLC가 최종 판단한다 (interlock_requested는 요청일 뿐).
"""
from __future__ import annotations

import math
from statistics import median

MODEL = "cycle-time-zscore-ewma-v1"


class CycleAnomalyDetector:
    def __init__(self, warmup=8, z_point=6.0, z_ewma=4.0, lam=0.3, sigma_floor=0.05, rel_floor=0.04,
                 neg_factor=0.5, raise_after=2, clear_after=3, z_calm=3.0):
        self.warmup, self.z_point, self.z_ewma, self.lam = warmup, z_point, z_ewma, lam
        self.sigma_floor, self.rel_floor, self.neg_factor = sigma_floor, rel_floor, neg_factor
        self.raise_after, self.clear_after, self.z_calm = raise_after, clear_after, z_calm
        self.reset()

    def reset(self):
        """기준값을 버리고 처음부터 다시 학습한다."""
        self.values, self.base, self.sigma, self.ewma = [], None, None, None
        self.bad = self.calm = 0
        self.alarm = False

    def status(self):
        return {"phase": "monitoring" if self.base is not None else "learning",
                "learned": min(len(self.values), self.warmup), "warmup": self.warmup, "alarm": self.alarm,
                "baseline": self.base}

    def on_cycle(self, cycle_time_s, drill_time_set_ds):
        """사이클 1개를 판정하고, 발행할 이벤트 목록 [(type, payload), ...]을 돌려준다."""
        x = float(cycle_time_s) - drill_time_set_ds / 10
        out = []
        if self.base is None:  # ---- 학습 중
            self.values.append(x)
            if len(self.values) >= self.warmup:
                self.base = median(self.values)
                mad = median(abs(v - self.base) for v in self.values)
                self.sigma = max(1.4826 * mad, self.sigma_floor, self.rel_floor * abs(self.base))
                self.ewma = self.base
            out.append(("ai.judgement", {
                "model": MODEL, "result": "ok", "confidence": 0.0, "interlock_requested": False,
                "feature": "cycle_overhead_s", "value": round(x, 3), "baseline": self.base, "phase": "learning"}))
            return out

        eff = lambda v: v if v >= 0 else v * self.neg_factor  # 빨라지는 쪽은 절반만 반영
        z_raw = (x - self.base) / self.sigma
        z = eff(z_raw)
        if self.alarm and self.calm + (1 if abs(z) < self.z_calm else 0) >= self.clear_after:
            self.ewma = self.base  # 해제 직전에 추세값을 기준으로 되돌린다 (이전 이상값의 꼬리가 남지 않게)
        self.ewma = self.lam * x + (1 - self.lam) * self.ewma
        ze = eff((self.ewma - self.base) / (self.sigma * math.sqrt(self.lam / (2 - self.lam))))
        side = 1 if self.ewma >= self.base else -1
        ewma_ng = abs(ze) > self.z_ewma and z_raw * side > 1.0  # 추세가 높고, 지금 값도 그 방향으로 벗어나 있다
        ng = abs(z) > self.z_point or ewma_ng
        score = max(abs(z) / self.z_point, abs(ze) / self.z_ewma)  # 화면에 보이는 점수 (1을 넘으면 임계값 초과)
        score = max(score, 1.01) if ng else min(score, 0.99)       # 판정과 점수가 어긋나 보이지 않게
        anomaly = min(1.0, score / 2)
        self.bad = self.bad + 1 if ng else 0
        self.calm = self.calm + 1 if abs(z_raw) < self.z_calm else 0

        raised = cleared = False
        if not self.alarm and self.bad >= self.raise_after:
            self.alarm, raised = True, True
        elif self.alarm and self.calm >= self.clear_after:
            self.alarm, cleared = False, True
            self.bad = 0

        out.append(("ai.judgement", {
            "model": MODEL, "result": "ng" if ng else "ok", "confidence": round(anomaly if ng else 1 - anomaly, 3),
            "interlock_requested": self.alarm, "feature": "cycle_overhead_s", "value": round(x, 3),
            "baseline": round(self.base, 3), "sigma": round(self.sigma, 3), "score": round(z, 2),
            "ewma_score": round(ze, 2), "phase": "monitoring"}))
        if raised:
            sev = "critical" if abs(z) > 20 else "warning"
            out.append(("alarm.raised", {
                "code": "CYCLE_TIME_ANOMALY", "severity": sev,
                "message": f"사이클 시간(가공 시간 제외)이 기준 {self.base:.2f}초보다 {x - self.base:+.2f}초 벗어났습니다 (z={z:.1f}, EWMA z={ze:.1f})"}))
        if cleared:
            out.append(("alarm.cleared", {"code": "CYCLE_TIME_ANOMALY", "severity": "info",
                                          "message": "사이클 시간이 정상 범위로 돌아왔습니다"}))
        return out
