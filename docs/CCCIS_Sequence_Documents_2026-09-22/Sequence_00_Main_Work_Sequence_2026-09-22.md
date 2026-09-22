# Sequence #00 - Main Work Sequence

**프로젝트:** CCCIS (Contact-based Cable Connection Inspection System)  
**환경:** Doosan M0609 + OnRobot RG2 / No-Vision Phase  
**작업 단위:** Recipe 1회 실행 = Job 1개  
**외부 Trigger:** HMI 통신 기반 START / PAUSE / RESUME / STOP / HOME_RETURN  
**작성 기준일:** 2026-09-22


## 1. 목적

CCCIS의 Recipe 단위 1회 작업을 시작부터 종료까지 관리하는 최상위 Sequence다. 외부 작업 Trigger는 HMI로부터 수신하고, 내부 하위 Sequence 간 전이는 자동으로 수행한다.

## 2. 설계 의도

- Scheduler나 다중 Recipe Queue를 현재 범위에 포함하지 않는다.
- `Selected Recipe 1건 = Job 1건`으로 관리한다.
- START는 `SYSTEM_READY`에서 HMI Trigger를 수신했을 때만 허용한다.
- 실제 검사 전 Work Initialize와 Home Return으로 상태와 시작 위치를 정규화한다.
- Inspection Point 실행은 Recipe Snapshot에서 생성한 Execution List 순서로 수행한다.
- Point 간 이동은 Judgment 완료를 기다리지 않는다.
- 마지막 Point 종료 후 `work_Access_safe_pose`로 복귀하고 Work Finish에서 Job 완료 여부를 검증한다.
- Work Finish 성공 후 Home Return을 수행하고 Robot을 정지/대기 상태로 전환한다.

## 3. 진입 조건

- System State = `SYSTEM_READY`
- 실행 중인 Job 없음
- HMI START Trigger 정상 수신
- 선택된 Recipe 식별 가능

## 4. Sequence Flow

```text
SYSTEM_READY
    |
    | HMI START
    v
START VALIDATION
    |
    +-- DENY --> HMI reason --> SYSTEM_READY
    |
    v
#01 WORK INITIALIZE
    |
    +-- FAIL --> HMI reason --> SYSTEM_READY
    |
    v
#02 HOME RETURN
    |
    v
home_pose
    |
    v
work_Access_safe_pose
    |
    v
Execution List 생성 / Recipe Snapshot Lock
    |
    v
+----------------------------------------------+
| Enabled Inspection Point Loop                |
|                                              |
| #03 Point Transition                         |
|      -> ready_pose -> entry_pose             |
| #04 Adaptive Grip                            |
| #05 Pull Inspection                          |
|      +--> async #06 Inspection Judgment      |
|      -> Soft Grip Open                       |
|      -> entry_pose                           |
|      -> ready_pose                           |
|      -> Next Point                           |
+----------------------------------------------+
    |
    v
work_Access_safe_pose
    |
    v
#07 WORK FINISH
    |
    +-- NOT COMPLETE / ERROR --> 종료 보류 및 상태 통보
    |
    v
#02 HOME RETURN
    |
    v
home_pose
    |
    v
OPERATING STOP / SYSTEM_READY
```

## 5. Flow 용어 설명

| 용어 | 설명 |
|---|---|
| Recipe Snapshot | START 시점의 선택 Recipe를 실행 중 변경되지 않도록 고정한 복사본 |
| Execution List | Snapshot에서 `enabled=true` Point만 Recipe 순서대로 생성한 실행 목록 |
| work_Access_safe_pose | 검사 작업영역의 공통 안전 진입/이탈 Pose |
| Async Judgment | #05 결과를 #06에 전달하되 Robot의 다음 Point 이동을 기다리지 않는 구조 |
| Work Finish | Job이 종료 가능한 상태인지 검증하는 마무리 Sequence |

## 6. 세부 동작 및 판단 조건

- `enabled=false` Point는 실행하지 않으며 검사 실패로 기록하지 않는다.
- START 이후 Recipe Snapshot은 RUNNING 동안 수정하지 않는다.
- Point Transition은 #06 Judgment 완료 여부와 HMI 결과 통신을 기다리지 않는다.
- 마지막 Point의 Robot Motion이 끝나면 `work_Access_safe_pose`로 복귀한 후 #07에 진입한다.
- #07이 모든 Point/Judgment/Logging 완료를 확인해야 Job을 종료할 수 있다.
- 제품 검사 결과에 FAIL 또는 MISSING이 포함되어도 모든 Point가 정상적으로 처리되었다면 Work Finish 자체는 SUCCESS가 될 수 있다.

## 7. 정상 종료 조건

- Execution List의 모든 Point 수행 완료
- #07 Work Finish SUCCESS
- #02 Home Return SUCCESS
- `home_pose` 도달 확인
- Robot Operating Stop 후 `SYSTEM_READY` 또는 `IDLE` 전환

## 8. 비정상 / 예외 처리

| 상황 | 처리 |
|---|---|
| PAUSE | Common #01 Safe Pause 처리, Context 보존 |
| STOP | 현재 Job 종료, Context 폐기. 자동 Home Return 없음 |
| ERROR | Job 종료/보류, 원인 HMI 통보. 자동 Home Return 없음 |
| E-STOP | Safety 계층 즉시 정지. 일반 Sequence보다 우선 |
| HMI COMM LOST | Common #01 통신복구 정책 적용 |

## 9. 상위·하위 Sequence Interface

**상위:** HMI / System State Manager  
**하위:** #01 Work Initialize, #02 Home Return, #03 Point Transition, #04 Adaptive Grip, #05 Pull Inspection, #06 Inspection Judgment, #07 Work Finish, Common #01

## 10. 코드 구현 포인트

- `run_main_work(job_context)` 형태의 상위 상태 머신 권장
- 모든 내부 Sequence는 성공/실패/상태코드를 반환하되 직접 System State를 임의 변경하지 않도록 역할 분리
- HMI Trigger 수신부와 Robot Sequence 실행부를 분리
- #06은 비동기 Worker/Task로 실행하고 `pending_judgments`로 추적
