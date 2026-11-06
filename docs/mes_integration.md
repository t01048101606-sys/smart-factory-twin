# MES 연동 (Auto Parts MES)

트윈이 내보내는 공통 이벤트(`event_schema.json`)를 기존 **Auto Parts MES**(Streamlit + SQLite)에 넣는 방법입니다.
MES 코드는 수정하지 않고, MES의 `services.py` 함수를 그대로 불러 씁니다. 그래서 MES의 검증 규칙이 그대로 적용됩니다.

```
PLC/시뮬레이터 -> server.py (events.py) -> /api/events, logs/events.jsonl
                                                |
                                  src/mes_adapter.py  (MES services.py 호출)
                                                |
                        AutoParts-MES-Arduino/sql/auto_parts.db  <- Streamlit 화면
```

## 대응 규칙

MES는 작업지시당 공정 단계별 실행을 **1번만**, 검사와 시리얼 부여는 LOT당 **1번만** 허용합니다.
그래서 작업물 하나하나가 아니라, 작업물 N개(기본 5개)를 작업지시 1건으로 묶습니다.

| 트윈 이벤트 | MES 동작 |
|---|---|
| 첫 `cycle.started` | 작업지시(WO) 생성 (`planned_qty` = N) |
| N개 모두 `cycle.completed` | 1단계(DRILL, 드릴 가공) 공정 실행 1건. 블랭크 LOT를 N개 소비하고 WIP LOT 생성 |
| N개 모두 `bin_metal` / `end_nonmetal` | 2단계(SORT, 분류/배출) 공정 실행 1건. WIP를 소비하고 완제품(FINISHED) LOT 생성, WO 완료 |
| `piece_id` | 시리얼 번호. 금속 = `COMPLETED`, 비금속 = `SCRAPPED` |
| `piece.classified` | 완제품 LOT 검사: 비금속 수 = 불량 수, 사유 `MAT_MIX`(이종 재질 혼입) |
| 모든 이벤트 | `machine_event` 테이블에 보관 (`io.changed`는 기본 제외, `--store-io`로 포함) |
| `command.issued` 중 `reset` | 공정 실행이 없는 진행 중 WO는 취소 |
| `machine.state` 가 `idle`(정지) | 계획 수량에 못 미친 WO는 지금까지 만든 수량(실적)으로 공정 실행과 검사를 등록해 마감 (계획 수량은 그대로 남음) |

검사 결과: 불량 0개 = `PASS`, 일부 = `PARTIAL`, 전부 = `FAIL`. `FAIL` LOT는 MES가 출하를 자동으로 막습니다.

## 어댑터가 등록하는 기준정보 (처음 실행 시 자동, 여러 번 해도 안전)

- 공정: `DRILL`(드릴 가공), `SORT`(분류/배출)
- 설비: `EQ-FEED-01` 공급 실린더, `EQ-DRILL-01` 드릴, `EQ-CONV-01` 컨베이어·배출 실린더
- 품목: `RM-BLANK`(블랭크, 원자재) -> `SP-DRILLED`(드릴 가공품) -> `FG-DRILLPART`(가공 부품, 완제품)
- 라우팅: 가공 부품 표준공정 (1 DRILL, 2 SORT), BOM은 각 단계 1:1
- 불량 사유: `MAT_MIX` 이종 재질 혼입(비금속)
- 블랭크 재고가 모자라면 시연용으로 자동 입고합니다 (`--no-auto-receipt`로 끔).

## 실행

```
# 1) 준비 (처음 한 번): MES DB 만들기 + 기준정보 등록
python src\mes_adapter.py --init-only

# 2) 터미널 A: 트윈 서버
python src\server.py plc\1102

# 3) 터미널 B: 어댑터 (트윈 화면에서 연속동작을 누르면 MES에 쌓입니다)
python src\mes_adapter.py --batch 5

# 4) 터미널 C: MES 화면 (MES 폴더에서)
cd ..\AutoParts-MES-Arduino
python seed_admin.py            # 최초 관리자 계정 (직접 입력)
streamlit run app.py
```

- 어댑터는 처리한 위치를 `logs\mes_adapter_state.json`에 저장해서, 껐다 켜도 이어서 처리합니다. 처음부터 다시 하려면 `--reset-state`.
- 서버 없이 파일에서 읽으려면 `--file logs\events.jsonl`.
- MES 폴더 위치는 기본이 형제 폴더 `..\AutoParts-MES-Arduino`입니다. 다르면 `--mes <경로>` 또는 환경변수 `MES_ROOT`.
- 어댑터는 MES의 `db.py`를 쓰므로 `pandas`가 필요합니다 (`pip install pandas`).

## 설비 현황 · OEE 페이지 (MES 추가 페이지)

`mes/addons/` 의 파일을 MES 폴더에 복사해서 쓰는 추가 페이지입니다. 기존 MES 파일은 건드리지 않고 새 파일 2개만 추가합니다.

```
python src\mes_adapter.py --install-addons      # pages/14_가공라인.py 등 라인별 페이지, src/oee.py 를 MES 폴더에 복사
```

MES 화면(Streamlit)을 새로고침하면 왼쪽 메뉴에 **공장현황, 가공라인, 프레스라인, 협동로봇셀, 물류출하** 페이지가 생깁니다 (구성은 `mes_pages.md`).

- 위쪽: 트윈 화면(iframe). 트윈 서버(`server.py`)가 켜져 있어야 보입니다. 보기 전용(조작 패널 숨김) 선택 가능.
- OEE = 가용률 x 성능률 x 품질률
  - 가용률 = 가동 시간 / 계획 시간 (녹색 램프 = 운전 중인 구간, 계획 시간 = 선택한 기간의 첫~마지막 이벤트)
  - 성능률 = 이상 사이클 시간의 합 / 가동 시간 (이상 사이클 = 고정 소요 시간 + 가공 시간 설정, 고정 소요 시간은 관측된 최솟값, 직접 지정도 가능)
  - 품질률 = 금속(정상) 수 / 분류된 작업물 수 (비금속 = 이종 재질 혼입 불량)
- 사이클 시간 추이, OEE 구성 요소 그래프, 최근 설비 이벤트 표, 작업지시별 이벤트 수.
- 트윈 화면 주소 옵션: `/?embed=1`(제목 숨김), `/?embed=view`(제목과 조작 패널 숨김).

시험: `python tests\test_oee.py`(계산식 손계산 비교), `python tests\test_mes_page.py`(페이지를 끝까지 실행).

## 시연 데이터 초기화

시연 영상을 찍기 전에 쌓인 시험 데이터를 지우고 깨끗하게 시작할 수 있습니다. 트윈 서버를 켠 상태에서 실행하세요.

```
python src\mes_adapter.py --reset-demo        # 확인 질문에 y 입력
```

- 지우는 것: 작업지시, 공정 실행, LOT, 시리얼, 검사, 출하, 설비 이벤트
- 남기는 것: 품목, 공정, 설비, 라우팅, BOM, 거래처, 불량 사유, 사용자 계정
- 지금까지 쌓인 트윈 이벤트는 다시 처리하지 않고, 이후 이벤트부터 새로 처리합니다.

## 현장 모니터링 · AI 이상 감지 (MES 추가 페이지)

같은 `--install-addons`로 **가공라인** 페이지(`pages/14_가공라인.py`의 "AI 이상 감지" 탭)와 `src/monitor.py`도 설치됩니다.
MES에 원래 있던 `13_현장모니터링.py`(아두이노 센서용, 저장소에 없는 함수를 불러와 오류가 나던 파일)는
`13_현장모니터링.py.orig`로 백업한 뒤 지웁니다 (기능은 가공라인 페이지가 대신합니다). 자세한 내용은 `ai_anomaly.md`를 보세요.

## 프레스 · 용접 · 도장 라인

두 번째 공정(PLC 없는 시뮬레이터)도 같은 어댑터로 MES에 연결됩니다. 작업지시, 공정 실행 3단계(PRESS, WELD, PAINT), LOT 추적, OEE는 `line_mes.md`를 보세요.
이벤트의 `line_id`로 가공 라인과 구분해서 처리하며, MES 페이지도 라인별로 이벤트를 따로 읽습니다.

물류 · 출하 구역의 입고(`lot.received`)는 MES 원자재 입고로, 출하(`shipment.dispatched`)는 MES 출하 관리로 등록됩니다 (`logistics.md`).

## 검증

```
python tests\test_mes_adapter.py     # MES를 임시 폴더로 복사해서 확인 (원본 MES는 바뀌지 않음)
```

확인하는 것: 작업지시 완료(공정 실행 2단계, 완제품 LOT, 시리얼, 검사), 리셋 시 작업지시 취소, `machine_event` 중복 없음, 블랭크 소비량, 비금속만 투입했을 때 `FAIL`과 출하 차단.

## 알려진 한계

- 정지하면 계획 수량에 못 미친 마지막 작업지시는 실적 수량으로 마감됩니다. 단속 동작(한 사이클)도 같은 방식이라 작업지시가 1개짜리로 마감됩니다.
- PB4 리셋은 공정 실행이 시작되지 않은 작업지시만 취소할 수 있습니다. 이미 1단계 공정 실행이 있으면 MES 규칙상 취소할 수 없어 중단 처리만 합니다.
- OEE는 기간 안의 모든 이벤트를 쓰므로, 서버를 껐다 켜서 쉬는 시간이 길었던 기록이 섞이면 가용률이 낮게 나옵니다. 시연에는 \"최근 10분\" 등 기간을 고르세요.
- 단방향입니다 (트윈 -> MES). MES에서 작업지시를 내려 트윈을 제어하는 방향은 다음 단계입니다.
- SQLite는 파일 기반이라 트윈과 MES가 같은 컴퓨터에서 돌아야 합니다. 확장 시 PostgreSQL 전환을 고려합니다.
- 비금속의 컨베이어 끝 도착(`end_nonmetal`)은 컨베이어 가동 시간으로 추정한 값입니다.
- MES 저장소의 `13_현장모니터링.py`는 저장소에 없는 `log_handling_event` 함수와 `handling_event` 테이블을 쓰고 있어서, 저장소 그대로는 오류가 납니다 (이 연동과는 별개).
