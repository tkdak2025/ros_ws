> 이 문서는 이전 설계·작업 기록입니다. 현재 기준은 [v4 문서 안내](../../v4/00_문서안내_v4.md)이며, 이후 변경 내용은 [최종결론](../../작업내역/18_최종결론_2026-09-25.md)을 참고하세요. 아래 본문은 이력으로 보존합니다.

> 2026-09-23 설계·구현 정합성 갱신: [05 보류항목 반영 결과](../../작업내역/05_시퀀스_보류항목_반영결과_2026-09-23.md)를 함께 적용한다. 같은 이름의 기존 PDF는 갱신 전 보존본이다.

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
- START는 진행 중인 Job·Worker가 없는 `SYSTEM_READY`/`STOPPED`/`ERROR`에서 허용한다. 이전 Job을 재개하지 않고 초기화부터 새로 실행한다.
- 실제 검사 전 Work Initialize와 현재 위치별 Work Access 준비를 수행한다. Home 복귀는 START 선행 조건이 아니다.
- Inspection Point 실행은 Recipe Snapshot에서 생성한 Execution List 순서로 수행한다.
- Point 간 이동은 Judgment 완료를 기다리지 않는다.
- 마지막 Point 종료 후 `work_Access_safe_pose`로 복귀하고 Work Finish에서 Job 완료 여부를 검증한다.
- Work Finish 성공 후 Work Access에서 SYSTEM_READY 대기로 전환한다. 자동 Home Return은 수행하지 않는다.

## 3. 진입 조건

- System State = `SYSTEM_READY` / `STOPPED` / `ERROR`
- 실행 중인 Job 없음
- HMI StartInspection 서비스로 request_id와 전체 레시피 정상 수신
- 선택된 Recipe 식별 가능

## 4. Sequence Flow

```text
SYSTEM_READY / STOPPED / ERROR
    |
    | HMI START
    v
START VALIDATION
    |
    +-- DENY --> HMI reason --> 기존 상태 유지
    |
    v
#01 WORK INITIALIZE
    |
    +-- FAIL --> HMI reason --> SYSTEM_READY
    |
    v
현재 위치 확인
    +-- Work Access 도달 상태 --> 이동 생략
    +-- 작업영역 내부 --> Open 25 mm 확인 --> Tool 반대 방향 30 mm 후퇴 --> Work Access
    +-- Home 등 작업영역 밖 --> Work Access
    |
    v
Work Access 도달 확인 (실패 시 검사 진입 금지)
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
Work Access 위치 유지
    |
    v
SYSTEM_READY (다음 START 대기)
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
- 전체 포인트 순회 완료, pending_judgments 없음, 각 포인트 motion_status=SUCCESS, 유효한 PASS/FAIL/SYSTEM_ERROR 결과 및 log_saved=true가 완료 조건이다. adaptive_grip_status/pull_status/judgment_status는 별도 완료 게이트로 검사하지 않는다. SYSTEM_ERROR도 이 조건을 만족하면 Job 종료 및 최종 Home이 가능하다.

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

## 파지 실패 후속 정책

Hard 파지 완료 타임아웃은 해당 포인트 SYSTEM_ERROR로 기록하고 Pull을 생략한다. Open 실측 폭 확인 → Entry 직선 후퇴 → Ready 복귀 성공 후 다음 포인트로 진행한다. Open/복귀 실패와 STOP·통신 오류는 중단한다. [09 상세 정책](../../작업내역/09_파지타임아웃_포인트복구_2026-09-23.md)을 따른다.


## START 기준 변경 (2026-09-25 사용자 확정)

검사 시작 위치는 Work Access다. STOP 후 별도 HOME 명령은 필수가 아니며 HMI와 terminal 모두 같은 접수 조건을 적용한다. Access 자체가 work_area 안에 있으므로 이미 Access에 있는지 먼저 확인하여 불필요한 후퇴를 하지 않는다. 작업영역 내부에서 필요한 Open·후퇴는 Home Return의 동일 Safe Escape 절차를 사용한다. 장비 준비·유효한 TCP·Open 폭·후퇴 목표·Access 도달 확인에 실패하면 포인트 검사를 시작하지 않는다. 검사 완료 후에는 Work Access에 머무른다. Home 복귀는 별도 HOME_RETURN 명령으로만 수행한다.
