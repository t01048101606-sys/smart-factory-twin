# 태그맵 (I/O 사전)

가공 공정(11/2 HMI연동 PLC 프로그램) 기준의 **PLC 태그 - Modbus 주소 - 트윈 오브젝트 - MES 사용처** 대응표입니다.
이후 게이트웨이, 3D/2D 트윈, MES, AI 연동은 모두 이 표를 기준으로 합니다.
기계가 읽는 원본은 `tagmap.csv`이고, 이 문서는 읽기 쉽게 정리한 것입니다.

- 근거: `plc/1102/*.csv`(GX Works2 명령어 목록), `plc/machining.st`(OpenPLC용), `src/modbus_plc.py`(게이트웨이)
- 장비: 미쓰비시 Q02H PLC, Pro-face HMI (원본) / OpenPLC (이식 버전)
- 태그 ID는 `machining.st`의 변수 이름과 같습니다. PLC 디바이스(X, Y, M, D)는 원본 래더 기준입니다.

## 1. 입력 (센서, 푸시버튼)
실제 장비 입력(%IX)과 시뮬레이션 입력(SIM_X*, 코일)을 OR로 합쳐서 씁니다. 게이트웨이는 시뮬레이션 코일에 값을 씁니다.

| 태그 ID | 디바이스 | 이름 | ST 주소 | Modbus(이산 입력/코일) | 트윈 오브젝트 |
|---|---|---|---|---|---|
| SUP_BWD_LS | X0 | 공급 후진 센서 | %IX0.0 (실제) / %QX3.0 (SIM_X0) | di 0 / coil 24 | supply_cylinder |
| SUP_FWD_LS | X1 | 공급 전진 센서 | %IX0.1 (실제) / %QX3.1 (SIM_X1) | di 1 / coil 25 | supply_cylinder |
| DRILL_DN_LS | X2 | 드릴 하강 센서 | %IX0.2 (실제) / %QX3.2 (SIM_X2) | di 2 / coil 26 | drill |
| DRILL_UP_LS | X3 | 드릴 상승 센서 | %IX0.3 (실제) / %QX3.3 (SIM_X3) | di 3 / coil 27 | drill |
| OUT_BWD_LS | X4 | 송출 후진 센서 | %IX0.4 (실제) / %QX3.4 (SIM_X4) | di 4 / coil 28 | out_cylinder |
| OUT_FWD_LS | X5 | 송출 전진 센서 | %IX0.5 (실제) / %QX3.5 (SIM_X5) | di 5 / coil 29 | out_cylinder |
| EJECT_BWD_LS | X6 | 배출 후진 센서 | %IX0.6 (실제) / %QX3.6 (SIM_X6) | di 6 / coil 30 | eject_cylinder |
| EJECT_FWD_LS | X7 | 배출 전진 센서 | %IX0.7 (실제) / %QX3.7 (SIM_X7) | di 7 / coil 31 | eject_cylinder |
| MAGAZINE_LOADED | X8 | 매거진 적재 센서 | %IX1.0 (실제) / %QX4.0 (SIM_X8) | di 8 / coil 32 | magazine |
| SENS_METAL | X9 | 금속 센서 | %IX1.1 (실제) / %QX4.1 (SIM_X9) | di 9 / coil 33 | sort_sensor |
| SENS_NONMETAL | X0A | 비금속 센서 | %IX1.2 (실제) / %QX4.2 (SIM_X0A) | di 10 / coil 34 | sort_sensor |
| PB_SINGLE | X0B | PB1 단속 | %IX1.3 (실제) / %QX4.3 (SIM_X0B) | di 11 / coil 35 | panel_buttons |
| PB_CONT | X0C | PB2 연속 | %IX1.4 (실제) / %QX4.4 (SIM_X0C) | di 12 / coil 36 | panel_buttons |
| PB_STOP | X0D | PB3 연속 정지 | %IX1.5 (실제) / %QX4.5 (SIM_X0D) | di 13 / coil 37 | panel_buttons |
| PB_RESET | X0E | PB4 리셋 | %IX1.6 (실제) / %QX4.6 (SIM_X0E) | di 14 / coil 38 | panel_buttons |

## 2. 출력 (Y)
Modbus 코일 0~11에서 읽습니다.

| 태그 ID | 디바이스 | 이름 | ST 주소 | Modbus | 트윈 오브젝트 |
|---|---|---|---|---|---|
| SUP_FWD_SOL | Y20 | 공급 전진 | %QX0.0 | coil 0 | supply_cylinder |
| SUP_BWD_SOL | Y21 | 공급 후진 | %QX0.1 | coil 1 | supply_cylinder |
| DRILL_DN_SOL | Y22 | 드릴 하강 | %QX0.2 | coil 2 | drill |
| OUT_FWD_SOL | Y23 | 송출 전진 | %QX0.3 | coil 3 | out_cylinder |
| OUT_BWD_SOL | Y24 | 송출 후진 | %QX0.4 | coil 4 | out_cylinder |
| EJECT_FWD_SOL | Y25 | 배출 전진 | %QX0.5 | coil 5 | eject_cylinder |
| EJECT_BWD_SOL | Y26 | 배출 후진 | %QX0.6 | coil 6 | eject_cylinder |
| CONVEYOR | Y27 | 컨베이어 | %QX0.7 | coil 7 | conveyor |
| DRILL_MOTOR | Y28 | 드릴 모터 | %QX1.0 | coil 8 | drill |
| LAMP_RED | Y29 | 적색 램프 | %QX1.1 | coil 9 | lamp_red |
| LAMP_YELLOW | Y2A | 황색 램프 | %QX1.2 | coil 10 | lamp_yellow |
| LAMP_GREEN | Y2B | 녹색 램프 | %QX1.3 | coil 11 | lamp_green |

## 3. HMI 버튼 (명령)
게이트웨이가 코일 16~19에 약 150 ms 동안 씁니다. 웹 화면의 버튼이 이 명령을 보냅니다.

| 태그 ID | 디바이스 | 이름 | ST 주소 | Modbus | 설명 |
|---|---|---|---|---|---|
| HMI_START_SINGLE | M100 | HMI 단속 시작 | %QX2.0 | coil 16 | HMI 터치 단속 시작 (한 사이클) |
| HMI_START_CONT | M101 | HMI 연속 시작 | %QX2.1 | coil 17 | HMI 터치 연속 시작 |
| HMI_STOP | M102 | HMI 정지 | %QX2.2 | coil 18 | HMI 터치 연속 정지 |
| HMI_COUNT_RESET | M103 | HMI 카운트 초기화 | %QX2.3 | coil 19 | D0, D2 카운트를 0으로 |

## 4. 데이터 레지스터
홀딩 레지스터 1024~1027을 한 번에 읽습니다.

| 태그 ID | 디바이스 | 이름 | ST 주소 | Modbus | 설명 | MES 사용처 |
|---|---|---|---|---|---|---|
| COUNT_METAL | D0 | 금속 카운트 | %MW0 | hr 1024 | 금속 배출 시작 시 +1 (M11 상승) | 생산 실적(금속) |
| COUNT_NONMETAL | D2 | 비금속 카운트 | %MW1 | hr 1025 | 비금속 센서(X0A) 상승 시 +1 | 생산 실적(비금속) |
| COUNT_TOTAL | D4 | 합계 카운트 | %MW2 | hr 1026 | D0 + D2 | 생산 실적(합계) |
| DRILL_TIME_SET | D10 | 드릴 가공 시간 설정 | %MW3 | hr 1027 | 단위 0.1초, PLC가 5~100(0.5~10초)으로 제한 | 공정 파라미터 이력 |

## 5. 내부 릴레이와 타이머 (외부에 노출되지 않음)
사이클 단계는 PLC 내부 릴레이로 진행됩니다. 게이트웨이는 이 값을 직접 읽지 못하므로, 센서와 출력의 변화로 단계를 추정합니다.

| 태그 ID | 디바이스 | 이름 | 설명 |
|---|---|---|---|
| RUN_CONT | M0 | 연속운전 유지 | 연속 동작 중 |
| CYCLE_ACTIVE | M1 | 사이클 진행 | 가공 사이클 진행 중 (M10에서 해제) |
| STEP_SUP_FWD_DONE | M2 | 공급 전진 완료 | X1 도달 후 유지 -> 공급 후진 |
| STEP_SUP_BWD_DONE | M3 | 공급 후진 완료 | X0 도달 후 유지 -> T0 대기 |
| STEP_DRILL_MOTOR | M4 | 드릴 모터 단계 | T0 1초 경과 후 (드릴 모터 ON) |
| STEP_DRILL_DN | M5 | 드릴 하강 단계 | T1 1초 경과 후 (드릴 하강) |
| STEP_DRILLING | M6 | 가공 중 | X2 도달 후 (T2 가공 시간 시작) |
| STEP_DRILL_DONE | M7 | 가공 시간 경과 | T2 경과 후 (드릴 상승) |
| STEP_DRILL_UP_DONE | M8 | 드릴 상승 완료 | X3 도달 후 (송출 전진) |
| STEP_OUT_FWD_DONE | M9 | 송출 전진 완료 | X5 도달 후 (송출 후진, 분류 시작) |
| STEP_CYCLE_END | M10 | 사이클 종료 | X4 도달 후 (M1 해제) |
| SORT_METAL | M11 | 금속 분류 동작 | 금속 센서 + 배출 후진 시 시작 |
| SORT_EJECT_CMD | M12 | 배출 전진 지시 | T3 1.5초 경과 후 |
| SORT_EJECT_FWD_DONE | M13 | 배출 전진 완료 | X7 도달 후 |
| SORT_EJECT_BWD_DONE | M14 | 배출 후진 완료 | X6 도달 후 (M11 해제) |
| CONVEYOR_HOLD | M15 | 컨베이어 유지 | 송출 완료 후 가동, T4 5초 정지 지연 |
| RUNNING_LAMP | M17 | 운전 중 표시 | M0, M1, M11, M15 중 하나라도 ON |
| STOP_CMD | M110 | 정지 명령 | PB3 또는 HMI 정지 |
| TMR_SUP_WAIT | T0 | 공급 후진 후 대기 | 1.0초 (K10) |
| TMR_MOTOR_WAIT | T1 | 드릴 모터 기동 대기 | 1.0초 (K10) |
| TMR_DRILL_TIME | T2 | 드릴 가공 시간 | D10 x 0.1초 |
| TMR_EJECT_DELAY | T3 | 배출 전진 지연 | 1.5초 (K15) |
| TMR_CONV_STOP | T4 | 컨베이어 자동 정지 | 5.0초 (K50) |

## 6. 공정 순서와 센서, 출력

1. `Y20` 공급 전진 -> `X1` 도달 -> `Y21` 공급 후진 -> `X0` 도달
2. 1초 후 `Y28` 드릴 모터 ON, 1초 후 `Y22` 드릴 하강 -> `X2` 도달
3. 가공 시간(T2 = D10 x 0.1초) 후 드릴 상승 -> `X3` 도달
4. `Y23` 송출 전진 -> `X5` 도달(금속 `X9` 또는 비금속 `X0A` 판별) -> `Y24` 송출 후진 -> `X4` 도달 (사이클 종료)
5. 컨베이어 `Y27` 가동. 금속이면 `Y25` 배출 전진(`X7`) -> `Y26` 후진(`X6`), 비금속이면 컨베이어 끝까지 이동
6. 카운트: 금속은 배출 시작(M11 상승)에 D0 +1, 비금속은 `X0A` 상승에 D2 +1

## 7. Modbus 주소 요약

| 영역 | 주소 | 내용 |
|---|---|---|
| 코일 0~11 | %QX0.0~%QX1.3 | 출력 Y20~Y2B (읽기) |
| 코일 16~19 | %QX2.0~%QX2.3 | HMI 버튼 M100~M103 (쓰기) |
| 코일 24~38 | %QX3.0~%QX4.6 | 시뮬레이션 입력 X0~X0E (쓰기) |
| 이산 입력 0~14 | %IX0.0~%IX1.6 | 실제 입력 X0~X0E (실제 장비 연결 시) |
| 홀딩 레지스터 1024~1027 | %MW0~%MW3 | D0, D2, D4, D10 |

## 8. 알려진 한계와 가정
- `POFF`(대기 프로그램 정지 시 출력 해제)는 OpenPLC 이식에서 가정한 동작이며, 실제 PLC에서 확인이 필요합니다.
- 작업물 위치와 일련번호는 PLC가 알려 주는 값이 아니라, 센서와 출력 변화로 서버가 추정한 값입니다.
- 실린더와 센서의 동작 시간은 단순한 지연 모델이며 실제 장비와 다릅니다.
- 현재 PLC에는 경보(알람) 로직이 없습니다. 이벤트 스키마의 경보 항목은 예약입니다.
