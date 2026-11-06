# 물류 · 출하 구역

공장의 입구(자재 입고)와 출구(완제품 출하)입니다. 프레스 · 용접 · 도장 라인의 이벤트로 움직이고, 입고와 출하는 MES에 기록됩니다.
시뮬레이터(`src/logistics_sim.py`)이고, 3D 장면은 `src/scenes/logistics.json`(`tools/make_logistics_scene.py`로 만듦)입니다.

```
프레스 라인 이벤트 ─(공정 완료 = 자재 소비, 라인 끝 양품 = 파렛트에 담기)─> 물류 시뮬레이터
   입고 트럭 -> 하역 -> 자재 창고            lot.received         ─> MES 원자재 입고 (RECEIPT LOT)
   양품 5개 = 파렛트 -> 완제품 창고 -> AGV -> 출하 도크 -> 트럭 출발
                                      pallet.stored, shipment.dispatched ─> MES 출하 관리
```

## 동작 규칙

- **입고**: 자재 재고가 발주점 아래로 내려가면 입고 트럭이 와서 하역합니다. 재고는 프레스 라인의 공정 완료마다 줄어듭니다 (MES BOM과 같은 단위당 수량).

  | 자재 | 처음 재고 | 발주점 | 입고량 | 공급업체 | 소비 |
  |---|---|---|---|---|---|
  | 냉연강판 RM-STEEL | 30 KG | 12 | 60 | 한국제철 | 프레스 1회 완료마다 0.5 |
  | 육각볼트 RM-BOLT | 150 EA | 60 | 300 | 대한볼트산업 | 용접 1회 완료마다 4 |
  | 전착도료 RM-PAINT | 2 L | 0.8 | 4 | 삼성도료 | 도장 1회 완료마다 0.05 |

- **출하**: 라인 끝의 **양품** 5개가 모이면 파렛트가 되어 완제품 창고에 쌓이고, AGV가 출하 도크로 옮기고, 트럭이 싣고 출발합니다. 라인이 멈추면 모자란 수량으로 파렛트를 마감합니다.
  **불량(용접 불량)은 불량 상자에 남고 출하되지 않습니다.** 트럭은 한 번에 파렛트 4개까지 싣습니다.
- **배속**은 프레스 라인과 같이 움직입니다 (`line.speed`).

## 이벤트 (`logistics_events.py`, 라인 ID `LINE-LOGISTICS-01`)

| 이벤트 | payload | MES |
|---|---|---|
| `lot.received` | `lot_no`, `item_code`, `qty`, `unit`, `supplier`, `material` | 원자재 입고(RECEIPT LOT) 등록: 품목, 수량, 공급업체 그대로 |
| `pallet.stored` | `pallet_id`, `qty`, `pieces`(작업물 번호들) | machine_event 에만 보관 |
| `shipment.dispatched` | `shipment_no`, `customer`(현대파츠), `pallets[{pallet_id, pieces}]` | 출하 등록: 작업물 번호(시리얼)로 완제품 LOT를 찾아 LOT별 수량으로 출하 |

- **불합격(FAIL) LOT는 MES의 출하 검증이 거절합니다.** 시험에서 정상 흐름에서는 FAIL LOT가 출하되지 않았고, 억지로 출하를 시도해도 MES가 "불합격 LOT"라며 막는 것을 확인했습니다.
- 출하 시점에 MES가 그 작업물들의 완제품 LOT를 아직 만들지 못했으면(같은 묶음의 마지막 작업물이 아직 라인 끝에 도착하지 않음) 출하를 **보류**해 두었다가 LOT가 만들어질 때 다시 시도합니다. 보류 목록은 어댑터 상태 파일에 저장되어 재시작해도 이어집니다(최대 400회 시도).

## 조작과 API

- 공장 화면의 물류 카드에서 **입고 요청** 버튼으로 재고와 상관없이 입고 트럭을 부를 수 있습니다.
- `GET /api/logistics/state`: 3D 화면이 읽는 상태 (재고, 파렛트 위치, AGV, 트럭, 카운트)
- `POST /api/logistics/request_inbound`: 수동 입고 요청

## 배치

공장 통합 화면에서 이 구역의 위치는 `src/scenes/factory.json`의 `offset` 한 줄입니다. 지금 값(`[-8, 0, 24]`)은 임시이고, 배치를 정하면 이 줄만 바꾸면 됩니다.
(실제 공장은 공정별 구역이 떨어져 있고 대차, AGV, 지게차로 연결됩니다.)

## 시험

`python tests\test_logistics.py`: 시뮬레이터(재고 하락, 입고, 파렛트, AGV, 출하 흐름, 불량은 출하하지 않음, 위치 값 범위)
`python tests\test_mes_logistics.py`: 이벤트 스키마, MES 입고와 출하 등록, FAIL LOT 거절, LOT 추적
