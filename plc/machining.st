(*
  가공 공정 PLC 프로그램 (11/2 HMI연동 버전을 OpenPLC용 ST로 옮긴 것)
  원본: GX Works2 명령어 목록 READY / MAIN / TEST1 / HMI
  M0, M1 ... 같은 이름은 원본 래더의 내부 릴레이 번호를 그대로 쓴 것입니다.

  - 실제 장비 입력(HW_*, %IX)과 시뮬레이션 입력(SIM_*, %QX 코일)을 OR로 합칩니다.
    시뮬레이션 입력은 Modbus로 쓸 수 있고, 장비를 연결하면 HW_* 만 쓰면 됩니다.
  - POFF 동작(대기 프로그램 정지 시 출력 해제)은 가정이며 실제 PLC에서 확인이 필요합니다.
*)
PROGRAM prog0
  VAR
    (* ---------- 실제 입력 (X) ---------- *)
    HW_X0  AT %IX0.0 : BOOL;   (* 공급 후진 센서 *)
    HW_X1  AT %IX0.1 : BOOL;   (* 공급 전진 센서 *)
    HW_X2  AT %IX0.2 : BOOL;   (* 드릴 하강 센서 *)
    HW_X3  AT %IX0.3 : BOOL;   (* 드릴 상승 센서 *)
    HW_X4  AT %IX0.4 : BOOL;   (* 송출 후진 센서 *)
    HW_X5  AT %IX0.5 : BOOL;   (* 송출 전진 센서 *)
    HW_X6  AT %IX0.6 : BOOL;   (* 배출 후진 센서 *)
    HW_X7  AT %IX0.7 : BOOL;   (* 배출 전진 센서 *)
    HW_X8  AT %IX1.0 : BOOL;   (* 매거진 적재 센서 *)
    HW_X9  AT %IX1.1 : BOOL;   (* 금속 센서 *)
    HW_X0A AT %IX1.2 : BOOL;   (* 비금속 센서 *)
    HW_X0B AT %IX1.3 : BOOL;   (* PB1 단속 *)
    HW_X0C AT %IX1.4 : BOOL;   (* PB2 연속 *)
    HW_X0D AT %IX1.5 : BOOL;   (* PB3 연속 정지 *)
    HW_X0E AT %IX1.6 : BOOL;   (* PB4 리셋 *)

    (* ---------- 시뮬레이션 입력 (Modbus 코일로 쓰기) ---------- *)
    SIM_X0  AT %QX3.0 : BOOL;
    SIM_X1  AT %QX3.1 : BOOL;
    SIM_X2  AT %QX3.2 : BOOL;
    SIM_X3  AT %QX3.3 : BOOL;
    SIM_X4  AT %QX3.4 : BOOL;
    SIM_X5  AT %QX3.5 : BOOL;
    SIM_X6  AT %QX3.6 : BOOL;
    SIM_X7  AT %QX3.7 : BOOL;
    SIM_X8  AT %QX4.0 : BOOL;
    SIM_X9  AT %QX4.1 : BOOL;
    SIM_X0A AT %QX4.2 : BOOL;
    SIM_X0B AT %QX4.3 : BOOL;
    SIM_X0C AT %QX4.4 : BOOL;
    SIM_X0D AT %QX4.5 : BOOL;
    SIM_X0E AT %QX4.6 : BOOL;

    (* ---------- 출력 (Y) ---------- *)
    SUP_FWD_SOL    AT %QX0.0 : BOOL;  (* Y20 *)
    SUP_BWD_SOL    AT %QX0.1 : BOOL;  (* Y21 *)
    DRILL_DN_SOL   AT %QX0.2 : BOOL;  (* Y22 *)
    OUT_FWD_SOL    AT %QX0.3 : BOOL;  (* Y23 *)
    OUT_BWD_SOL    AT %QX0.4 : BOOL;  (* Y24 *)
    EJECT_FWD_SOL  AT %QX0.5 : BOOL;  (* Y25 *)
    EJECT_BWD_SOL  AT %QX0.6 : BOOL;  (* Y26 *)
    CONVEYOR       AT %QX0.7 : BOOL;  (* Y27 *)
    DRILL_MOTOR    AT %QX1.0 : BOOL;  (* Y28 *)
    LAMP_RED       AT %QX1.1 : BOOL;  (* Y29 *)
    LAMP_YELLOW    AT %QX1.2 : BOOL;  (* Y2A *)
    LAMP_GREEN     AT %QX1.3 : BOOL;  (* Y2B *)

    (* ---------- HMI ---------- *)
    HMI_START_SINGLE AT %QX2.0 : BOOL;  (* M100 *)
    HMI_START_CONT   AT %QX2.1 : BOOL;  (* M101 *)
    HMI_STOP         AT %QX2.2 : BOOL;  (* M102 *)
    HMI_COUNT_RESET  AT %QX2.3 : BOOL;  (* M103 *)

    (* ---------- 데이터 ---------- *)
    COUNT_METAL    AT %MW0 : INT;  (* D0 *)
    COUNT_NONMETAL AT %MW1 : INT;  (* D2 *)
    COUNT_TOTAL    AT %MW2 : INT;  (* D4 *)
    DRILL_TIME_SET AT %MW3 : INT;  (* D10, 단위 0.1초 *)
  END_VAR

  VAR
    (* ---------- 합성된 입력 ---------- *)
    SUP_BWD_LS : BOOL;  SUP_FWD_LS : BOOL;
    DRILL_DN_LS : BOOL; DRILL_UP_LS : BOOL;
    OUT_BWD_LS : BOOL;  OUT_FWD_LS : BOOL;
    EJECT_BWD_LS : BOOL; EJECT_FWD_LS : BOOL;
    MAGAZINE_LOADED : BOOL;
    SENS_METAL : BOOL;  SENS_NONMETAL : BOOL;
    PB_SINGLE : BOOL;   PB_CONT : BOOL;  PB_STOP : BOOL;  PB_RESET : BOOL;

    (* ---------- 내부 릴레이 ---------- *)
    M0 : BOOL; M1 : BOOL; M2 : BOOL; M3 : BOOL; M4 : BOOL; M5 : BOOL;
    M6 : BOOL; M7 : BOOL; M8 : BOOL; M9 : BOOL; M10 : BOOL;
    M11 : BOOL; M12 : BOOL; M13 : BOOL; M14 : BOOL; M15 : BOOL;
    M17 : BOOL; M110 : BOOL;
    FIRST_SCAN : BOOL := TRUE;     (* SM402 *)
    TEST1_ACTIVE : BOOL := FALSE;  (* PSCAN / POFF 로 켜고 끄는 프로그램 *)
    BLINK : BOOL;                  (* SM412 *)

    (* ---------- 타이머, 에지 ---------- *)
    T0 : TON; T1 : TON; T2 : TON; T3 : TON; T4 : TON;
    T2_PT : TIME;   (* 가공 시간 = 100 ms x D10 *)
    T2_SEC : TIME;  T2_FRAC : TIME;
    TB1 : TON; TB2 : TON;
    R_PB4 : R_TRIG; R_M11 : R_TRIG; R_XA : R_TRIG; R_M9 : R_TRIG; R_STOP : R_TRIG;
  END_VAR

  (* ===== 입력 합성 ===== *)
  SUP_BWD_LS := HW_X0 OR SIM_X0;      SUP_FWD_LS := HW_X1 OR SIM_X1;
  DRILL_DN_LS := HW_X2 OR SIM_X2;     DRILL_UP_LS := HW_X3 OR SIM_X3;
  OUT_BWD_LS := HW_X4 OR SIM_X4;      OUT_FWD_LS := HW_X5 OR SIM_X5;
  EJECT_BWD_LS := HW_X6 OR SIM_X6;    EJECT_FWD_LS := HW_X7 OR SIM_X7;
  MAGAZINE_LOADED := HW_X8 OR SIM_X8;
  SENS_METAL := HW_X9 OR SIM_X9;      SENS_NONMETAL := HW_X0A OR SIM_X0A;
  PB_SINGLE := HW_X0B OR SIM_X0B;     PB_CONT := HW_X0C OR SIM_X0C;
  PB_STOP := HW_X0D OR SIM_X0D;       PB_RESET := HW_X0E OR SIM_X0E;

  (* ===== READY (HMI는 항상 실행되므로 별도 처리 없음) ===== *)

  (* ===== MAIN ===== *)
  (* 가공 시간 초기값과 범위 제한 (0.5초 ~ 10초) *)
  IF FIRST_SCAN AND (DRILL_TIME_SET = 0) THEN
    DRILL_TIME_SET := 30;
  END_IF;
  FIRST_SCAN := FALSE;
  DRILL_TIME_SET := LIMIT(5, DRILL_TIME_SET, 100);

  M110 := PB_STOP OR HMI_STOP;
  M0 := (PB_CONT OR HMI_START_CONT OR M0) AND NOT M110 AND NOT PB_RESET;
  M1 := ((((PB_SINGLE OR HMI_START_SINGLE OR M0) AND MAGAZINE_LOADED AND SUP_BWD_LS
          AND DRILL_UP_LS AND OUT_BWD_LS) OR M1) AND NOT M10 AND NOT PB_RESET);

  R_PB4(CLK := PB_RESET);
  IF R_PB4.Q THEN TEST1_ACTIVE := FALSE; END_IF;   (* POFF TEST1 *)

  R_M11(CLK := M11);
  IF R_M11.Q THEN COUNT_METAL := COUNT_METAL + 1; END_IF;
  R_XA(CLK := SENS_NONMETAL);
  IF R_XA.Q THEN COUNT_NONMETAL := COUNT_NONMETAL + 1; END_IF;
  IF PB_RESET OR HMI_COUNT_RESET THEN
    COUNT_METAL := 0;
    COUNT_NONMETAL := 0;
  END_IF;
  COUNT_TOTAL := COUNT_METAL + COUNT_NONMETAL;

  (* 단계 체인 *)
  M2 := M1 AND (SUP_FWD_LS OR M2);
  M3 := M2 AND (SUP_BWD_LS OR M3);
  T0(IN := M3, PT := T#1s);
  M4 := M3 AND (T0.Q OR M4);
  T1(IN := M4, PT := T#1s);
  M5 := M4 AND (T1.Q OR M5);
  M6 := M5 AND (DRILL_DN_LS OR M6);
  (* 가공 시간 D10(0.1초 단위) -> TIME: 100 ms 에 D10 을 곱한다 *)
  (* 나노초 정수 오버플로를 피하려고 초 부분과 0.1초 부분을 나누어 곱한 뒤 더한다 *)
  T2_SEC := T#1s * (DRILL_TIME_SET / 10);
  T2_FRAC := T#100ms * (DRILL_TIME_SET MOD 10);
  T2_PT := T2_SEC + T2_FRAC;
  T2(IN := M6, PT := T2_PT);
  M7 := M6 AND (T2.Q OR M7);
  M8 := M7 AND (DRILL_UP_LS OR M8);
  M9 := M8 AND (OUT_FWD_LS OR M9);
  M10 := M9 AND (OUT_BWD_LS OR M10);

  SUP_FWD_SOL := M1 AND NOT M2;
  SUP_BWD_SOL := M2;
  DRILL_MOTOR := M4 AND NOT M7;
  DRILL_DN_SOL := M5 AND NOT M7;
  OUT_FWD_SOL := M8 AND NOT M9;
  OUT_BWD_SOL := M9;

  R_M9(CLK := M9);
  IF R_M9.Q THEN TEST1_ACTIVE := TRUE; END_IF;     (* PSCAN TEST1 *)
  R_STOP(CLK := M110);
  IF R_STOP.Q AND NOT M11 THEN TEST1_ACTIVE := FALSE; END_IF;  (* POFF TEST1 *)

  (* ===== TEST1 (분류, 배출, 컨베이어) ===== *)
  IF TEST1_ACTIVE THEN
    M11 := ((SENS_METAL AND EJECT_BWD_LS) OR M11) AND NOT M14;
    T3(IN := M11, PT := T#1500ms);
    M12 := M11 AND (T3.Q OR M12);
    M13 := M12 AND (EJECT_FWD_LS OR M13);
    M14 := (EJECT_BWD_LS OR M14) AND M13;
    EJECT_FWD_SOL := M12 AND NOT M13;
    EJECT_BWD_SOL := M13;
    M15 := (M9 OR M15) AND NOT M110 AND NOT T4.Q;
    T4(IN := M15 AND NOT M0 AND NOT M1 AND NOT M11, PT := T#5s);
    CONVEYOR := M15;
  ELSE
    (* POFF: 대기 프로그램의 출력을 해제한다고 가정 *)
    M11 := FALSE; M12 := FALSE; M13 := FALSE; M14 := FALSE; M15 := FALSE;
    EJECT_FWD_SOL := FALSE; EJECT_BWD_SOL := FALSE; CONVEYOR := FALSE;
    T3(IN := FALSE, PT := T#1500ms);
    T4(IN := FALSE, PT := T#5s);
  END_IF;

  (* ===== HMI (램프) ===== *)
  TB1(IN := NOT TB2.Q, PT := T#500ms);
  TB2(IN := TB1.Q, PT := T#500ms);
  BLINK := TB1.Q;
  M17 := M0 OR M1 OR M11 OR M15;
  LAMP_RED := NOT M17;
  LAMP_YELLOW := DRILL_MOTOR AND BLINK;
  LAMP_GREEN := M17;
END_PROGRAM

CONFIGURATION Config0
  RESOURCE Res0 ON PLC
    TASK task0(INTERVAL := T#50ms, PRIORITY := 0);
    PROGRAM instance0 WITH task0 : prog0;
  END_RESOURCE
END_CONFIGURATION
