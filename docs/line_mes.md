# 프레스 · 용접 · 도장 라인과 MES 연동

PLC 없이 파이썬 시뮬레이터로 돌리는 자동차 부품 라인(`src/line_sim.py`)을 Auto Parts MES에 연결합니다.
3D 화면(`/3d/line`) -> 공통 이벤트 -> 어댑터 -> MES(작업지시, 공정 실행, LOT 추적, 시리얼, 검사) -> OEE 페이지.

```
LineSim (src/line_sim.py)
   | hook
LineEventBridge (src/line_events.py)  -> 공통 이벤트 (line_id = LINE-PRESS-WELD-PAINT-01, sim_t 포함) -> logs/events.jsonl
   |
mes_adapter.py + mes_press_line.py   -> MES DB (작업지시, 공정 실행 3단계, LOT, 시리얼, 검사) + machine_event
   |
MES 페이지 16_프레스라인.py (OEE, 공정별 시간 구성, 결함 영향) / LOT추적 / 검사관리 / 시리얼관리
```

## 이벤트

| 이벤트 | 내용 |
|---|---|
| `cycle.started` | 블랭크 투입 (작업물 번호 `B-날짜-0001`) |
| `station.completed` | 공정 완료: 공정(press, weld, paint), 작업 시간, 공칭 사이클, 용접은 불량 여부 |
| `station.state` | 공정 상태 변화: working(작업 중), blocked(막힘), starved(대기), down(정지) |
| `piece.exited` | 라인 끝: good(양품) 또는 scrap(불량) |
| `machine.state` | 시작, 정지 요청(drain), 정지(비워진 뒤), 리셋 |
| `sim.fault` | 결함 주입: weld_slow, press_down, paint_down, none |

모든 이벤트에 `sim_t`(시뮬레이터 시간)가 있어서 **배속을 올려도 OEE 시간 계산이 맞습니다.**

## MES 대응 (MES 샘플 데이터와 같은 구성)

작업물 5개(`--press-batch`)를 작업지시 1건으로 묶고, 그 5개가 한 공정을 모두 마칠 때마다 그 단계의 공정 실행을 1건씩 등록합니다.

| 단계 | 공정 / 설비 | 소비 자재 (BOM, 단위당) | 만드는 LOT |
|---|---|---|---|
| 1 | PRESS / EQ-PRESS-01 | 냉연강판 RM-STEEL 0.5 kg | 반제품 SP-BRKA-PRS |
| 2 | WELD / EQ-WELD-01 | 볼트 RM-BOLT 4개, 프레스품 SP-BRKA-PRS 1개 | 반제품 SP-BRKA-WLD |
| 3 | PAINT / EQ-PAINT-01 | 도료 RM-PAINT 0.05 L, 용접품 SP-BRKA-WLD 1개 | 완제품 FG-BRKA (브라켓 A) |

- 소비 자재는 MES의 BOM에서 읽습니다. MES 샘플 BOM에는 반제품 줄이 없어서, LOT 추적이 끊기지 않도록 어댑터가 처음에 **반제품 줄을 BOM에 추가**합니다 (`--init-only` 또는 어댑터를 켤 때, 이미 있으면 건너뜀).
- 시리얼은 작업물 번호이고, 용접 불량은 `SCRAPPED`, 나머지는 `COMPLETED`입니다.
- 완제품 LOT 검사: 불량이 없으면 PASS, 일부면 PARTIAL, 전부면 FAIL. 불량 사유는 `WELD_CRACK`(용접 균열)이고, FAIL LOT는 MES가 출하를 자동으로 막습니다.
- **정지**는 새 투입을 멈추고 라인에 남은 부품이 모두 나온 뒤 멈춥니다(run-out). 그 시점에 계획 수량(5개)에 못 미친 작업지시는 실적 수량으로 마감합니다.
- **리셋**은 라인을 비웁니다. 아직 공정 실행이 없는 작업지시는 취소하고, 이미 공정 실행이 있는 작업지시는 MES 규칙상 취소할 수 없어 중단 처리만 합니다(상태는 IN_PROGRESS로 남음).

## OEE (`mes/addons/src/lineoee.py`)

- **가용률** = (가동 시간 - 정지 시간) / 가동 시간. 정지 시간 = 가동 중 어느 한 공정이라도 정지(프레스 정지, 도장 정지)였던 시간
- **성능률** = 병목 공칭 사이클 x 완성 수량 / 정지 없이 가동한 시간. 용접이 느려지면 병목이 옮겨가 처리량이 줄어 떨어집니다.
- **품질률** = 양품 / (양품 + 불량)
- 공정별 시간 구성(작업 중, 막힘, 대기, 정지 %), 결함 구간별 처리량(평상시 대비)도 보여 줍니다.

시뮬레이터 측정 예: 정상, 용접 속도 저하 240초, 프레스 정지 90초를 포함한 1,088초에서 가용률 91.7% x 성능률 90.6% x 품질률 91.2% = OEE 75.7%.
용접 저하 구간 처리량 4.75개/분(평상시의 67%), 프레스 정지 구간 2.67개/분(37%, 라인에 남은 부품만 나옴).

## 실행

```
python src\mes_adapter.py --install-addons     # 처음 한 번, 그리고 MES 추가 파일이 바뀐 뒤: 16_프레스라인.py, lineoee.py 설치
python src\server.py plc\1102                  # 트윈 서버 (/3d/line)
python src\mes_adapter.py --batch 3 --press-batch 5
```

3D 화면(http://localhost:5001/3d/line)에서 **시작**을 누르면 MES에 작업지시와 LOT가 쌓입니다. MES의 **프레스라인** 페이지에서 OEE를, **LOT추적**에서
냉연강판 LOT를 정방향으로 추적하면 프레스품 -> 용접품 -> 완제품까지 이어집니다.

## 시험

`python tests\test_line.py`(시뮬레이터), `test_line_events.py`(이벤트), `test_lineoee.py`(OEE 손계산과 시뮬레이터), `test_mes_press_line.py`(MES 연동과 페이지).
`test_mes_press_line.py`는 가공 라인과 프레스 라인을 같은 이벤트 스트림, 같은 DB에서 동시에 돌려서 서로 섞이지 않는지도 확인합니다.
