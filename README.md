# 스마트 팩토리 가공 공정 2D 디지털 트윈

부산인력개발원 AI스마트제조융합 과정(6개월)에서 배운 PLC, HMI, 웹(Flask), 데이터 처리를 하나로 묶어 만든
**가공 공정 시뮬레이션과 2D 디지털 트윈** 포트폴리오 프로젝트입니다.

![2D 트윈 화면](docs/screenshot.png)

## 무엇을 하는가
실습 장비(미쓰비시 Q02H PLC, Pro-face HMI)에서 만든 **가공 공정 PLC 프로그램**을 두 가지 방식으로 실행하고,
그 상태를 웹 화면(2D 트윈)에 실시간으로 보여 줍니다.

| 모드 | PLC 로직을 실행하는 곳 | 용도 |
| --- | --- | --- |
| 시뮬레이터 모드 | Python (`plc_sim.py`가 GX Works2 CSV를 읽어 스캔 단위로 실행) | 설치 없이 바로 실행 |
| OpenPLC 모드 | OpenPLC 런타임 (`plc/machining.st`) + Modbus TCP | 실제 PLC 런타임에 가까운 구조, 이후 장비 연결 대비 |

```
[센서 모델(Python 게이트웨이)] --SIM_* 코일--> [OpenPLC: machining.st] --출력 코일--> [게이트웨이] --> [웹 2D 트윈]
                                                     ^ HMI 버튼(M100–M103), 가공 시간 D10
```

공정 순서: 공급 실린더 → 드릴 가공 → 송출 실린더 → 컨베이어 → 금속/비금속 분류 → 배출

## 구성
| 파일 | 역할 |
| --- | --- |
| `plc/1102/*.csv` | 11/2 HMI연동 프로젝트의 프로그램 4개(MAIN, TEST1, READY, HMI) 명령어 목록 |
| `src/plc_sim.py` | CSV 명령어(LD, AND, OUT, MOV, 타이머, PSCAN, POFF 등)를 실행하는 PLC 시뮬레이터와 센서 모델 |
| `src/workpiece.py` | 실린더, 센서, 컨베이어 신호로 작업물 위치를 추정하는 추적기 |
| `src/server.py` | PLC(시뮬레이터 또는 OpenPLC)를 돌리고 상태를 JSON으로 내보내는 Flask 서버 |
| `plc/machining.st` | 11/2 PLC 로직을 OpenPLC용 구조적 텍스트(ST)로 옮긴 프로그램 |
| `src/modbus_plc.py` | OpenPLC에 Modbus TCP로 연결하는 게이트웨이(센서 모델, 코일 쓰기, 출력·카운트 읽기) |
| `src/modbus_probe.py` | Modbus 주소 배치 점검 스크립트 |
| `src/measure_drill.py`, `src/trace.py` | 드릴 시간 측정, 신호 변화 시각 기록(디버깅 도구) |
| `src/static/index.html` | 2D 트윈 화면(SVG): 실린더, 드릴, 컨베이어, 램프, 카운터, 조작 버튼 |

## 실행 (시뮬레이터 모드)
```
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install flask pymodbus
python src/server.py plc/1102
```
브라우저에서 http://localhost:5001 을 엽니다.

## 실행 (OpenPLC 모드)
필요: Docker Desktop(WSL 2). 부팅 설정에서 가상화(AMD는 SVM Mode, Intel은 VT-x)가 켜져 있어야 합니다.
```
git clone --config core.autocrlf=false https://github.com/thiagoralves/OpenPLC_v3.git
cd OpenPLC_v3
git submodule update --init --recursive
docker build -t openplc:v3 .
docker run -it --rm --privileged -p 8080:8080 -p 502:502 openplc:v3
```
1. http://localhost:8080 에 로그인(`openplc`/`openplc`)합니다.
2. Programs → Upload Program에서 `plc/machining.st`를 올리고 컴파일이 끝나면 Start PLC를 누릅니다.
3. 다른 창에서 `python src/server.py modbus`를 실행하고 http://localhost:5001 을 엽니다.

`--rm` 때문에 컨테이너를 끄면 올린 프로그램이 사라지므로 켤 때마다 다시 올려야 합니다.
주소 배치가 맞는지 보려면 `python src/modbus_probe.py`를 실행합니다.

### Modbus 주소
| 구분 | OpenPLC 주소 | Modbus |
| --- | --- | --- |
| PLC 출력 Y20–Y2B | %QX0.0–%QX1.3 | 코일 0–11 |
| HMI 버튼 M100–M103 | %QX2.0–%QX2.3 | 코일 16–19 |
| 시뮬레이션 센서 X0–X0E | %QX3.0–%QX4.6 | 코일 24–38 |
| 카운트 D0, D2, D4 / 가공 시간 D10 | %MW0–%MW3 | 홀딩 레지스터 1024–1027 |

실제 장비 입력(`HW_*`, %IX)과 시뮬레이션 입력(`SIM_*`)은 OR로 합쳐서, 장비를 연결하면 `SIM_*`만 끄면 됩니다.

- 단속동작, 연속동작, 연속정지, 리셋, 카운트 초기화는 실제 HMI 버튼(M100–M103, PB4)과 같은 입력입니다.
- 드릴 가공 시간(D10)을 바꾸면 PLC 프로그램의 제한 로직(0.5–10초)이 그대로 적용됩니다.
- 작업물 종류(금속, 비금속, 번갈아)를 선택해 분류 경로를 확인할 수 있습니다.

## 실제 장비 기준 확인한 것
- HMI 화면 부품의 디바이스: M100–M103(버튼), Y27–Y2B(표시, 램프), D0/D2/D4(카운터), D10(가공 시간)
- 입출력 맵: X0–X0E(센서, 버튼), Y20–Y2B(솔레노이드, 모터, 램프)

## 트러블슈팅 기록
- **OpenPLC v3 Docker 빌드가 "성공"인데 실행이 안 됨**: 설치 스크립트가 `| tee`로 로그를 남기는 구조라 중간에 실패해도 빌드가 성공으로 끝납니다.
  이미지 안의 `install_log.txt`를 확인하니 MatIEC 컴파일러 빌드(autoreconf)가 실패했고, 원인은 Windows Git이 소스를 CRLF로 바꾼 것이었습니다.
  `git clone --config core.autocrlf=false`로 다시 받아 해결했습니다.
- **ST 컴파일 오류 169개**: 첫 오류만 보면 됩니다. MatIEC는 한 `VAR` 블록에 `AT` 주소가 있는 변수와 없는 변수를 섞으면 거부하고, 이 오류 하나가 뒤 문장을 연쇄로 망가뜨렸습니다. 선언 블록을 둘로 나누어 해결했습니다.
- **드릴 가공 시간이 맞지 않음**: `INT_TO_TIME(D10*100)`은 드릴 단계에서 멈췄고(단위 불일치로 추정), 100 ms 펄스를 세는 방식은 한 펄스에 약 4스캔이 걸려 6초가 되었습니다.
  `T#100ms * D10`은 0.1초 안팎으로 끝났는데, 시간 구조체의 나노초 정수(32비트)가 1억 x 30 = 30억에서 넘치는 것으로 추정했습니다.
  초 부분과 0.1초 부분으로 나누어 곱하고 더하는 방식으로 바꾸자 약 3.1초(설정 3.0초 + 센서·스캔 지연)가 측정되었습니다.
- 디버깅 방법: 추측으로 고치지 않고 `trace.py`로 신호 변화를 시각과 함께 기록해서, 어느 단계가 어떻게 끝나는지 확인한 뒤 수정했습니다.

## 한계와 가정
- 실린더 동작 시간과 센서는 단순한 지연 모델이며 실제 장비와 다릅니다.
- 금속 감지는 송출 전진이 끝나는 시점에 시뮬레이터가 정한 값으로 대체했습니다.
- `POFF`가 대기 프로그램의 출력을 끈다고 가정했습니다(실제 PLC에서 추가 확인 필요).
- 작업물 위치는 PLC 값이 아니라 신호 변화로 추정한 값입니다.
- OpenPLC 모드의 ST 프로그램은 11/2 래더를 옮긴 것으로, 같은 입력에 대한 출력 순서와 카운트, 드릴 시간 약 3초, 가공 시간 입력 제한(2 입력 시 5, 200 입력 시 100)을 확인했습니다.
  원본 래더와 모든 조건에서 동일한지는 검증하지 않았습니다.
- OpenPLC v3는 유지보수가 끝난 버전입니다(후속 v4는 웹 화면이 없는 구조). 학습용으로 v3를 사용했고, ST 코드는 옮겨 쓸 수 있습니다.

## 로드맵
1. 11/3 최종 PLC 로직 반영
2. ~~OpenPLC로 이식하고 Modbus TCP로 태그 읽기(파이썬 게이트웨이)~~ 완료
3. 기존 SMART LINE MES(Flask, SQLite) 및 AI 모듈(품질, PPE, 설비보전)과 연동
4. 안전 정지 로직은 PLC에서 판단하고 AI는 입력 신호만 제공
