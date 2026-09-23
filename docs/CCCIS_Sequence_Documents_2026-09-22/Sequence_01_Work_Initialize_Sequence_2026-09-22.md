> 2026-09-23 설계·구현 정합성 갱신: [05 보류항목 반영 결과](../05_시퀀스_보류항목_반영결과_2026-09-23.md)를 함께 적용한다. 같은 이름의 기존 PDF는 갱신 전 보존본이다.

# Sequence #01 - Work Initialize Sequence

**프로젝트:** CCCIS (Contact-based Cable Connection Inspection System)  
**환경:** Doosan M0609 + OnRobot RG2 / No-Vision Phase  
**작업 단위:** Recipe 1회 실행 = Job 1개  
**외부 Trigger:** HMI 통신 기반 START / PAUSE / RESUME / STOP / HOME_RETURN  
**작성 기준일:** 2026-09-22


## 1. 목적

HMI START 승인 후 실제 Robot Motion에 진입하기 전에 Robot, HMI 통신, System Recipe, Inspection Recipe, Enabled Point 상태를 재검증하여 Recipe 단위 Job의 시작 가능 여부를 결정한다.

## 2. 설계 의도

- 이전 시점의 정상 상태를 현재도 정상이라고 가정하지 않는다.
- Initialize는 Fault를 자동 해제하지 않는다.
- 이상을 발견하면 START를 차단하고 원인을 HMI에 반환한다.
- START 시점에 선택된 Recipe를 Snapshot하고 Execution List를 생성할 수 있는 상태인지 확인한다.

## 3. 진입 조건

- #00 START Validation 승인
- HMI StartInspection 서비스 요청 ID와 전체 Recipe 수신 완료
- 신규 Job Context 생성 가능

## 4. Sequence Flow

```text
START ACCEPTED
    |
    v
Robot Operability Check
    |
    v
HMI Communication Check
    |
    v
System Recipe Validation
    |
    v
Inspection Recipe Validation
    |
    v
Enabled Point Check >= 1
    |
    v
ALL VALID ?
  +-- NO --> INIT FAIL --> HMI reason --> SYSTEM_READY
  |
  +-- YES
        |
        v
Recipe Snapshot / Execution List 준비
        |
        v
Robot Operability Re-Check
        |
        v
INIT SUCCESS --> #02 Home Return
```

## 5. Flow 용어 설명

| 용어 | 설명 |
|---|---|
| Robot Operability | Controller/Robot/Safety/Tool 상태가 Motion 가능한지 확인 |
| System Recipe | home_pose, work_Access_safe_pose, Boundary 등 공통 설정 |
| Inspection Recipe | Point별 ready/entry/Entry 자세 기반 방향/grip/pull 설정 |
| Enabled Point | 현재 Job에서 실제 검사 대상인 `enabled=true` Point |

## 6. 세부 동작 및 판단 조건

Robot Operability Check 후보:

- Controller 통신 정상
- Robot Motion 가능 상태
- Servo/Motor 사용 가능
- E-Stop / Protective Stop 비활성
- Blocking Fault 없음
- Joint Position / TCP Pose 취득 가능
- RG2 통신 및 상태 취득 가능
- Tool/TCP Configuration 유효

Recipe Validation에서는 필수 필드/형식/Boundary/zero vector 등을 확인하지만 Collision-free Path 자체를 증명하지 않는다.

## 7. 정상 종료 조건

모든 Check PASS + Robot Operability Re-Check PASS 후 #02 Home Return 호출 가능 상태.

## 8. 비정상 / 예외 처리

- HMI 통신 이상 -> START 실패
- Recipe Validation 실패 -> HMI Reason 전달 후 START 금지
- Robot Operability 실패 -> 자동 Fault Reset 금지, 원인 보고
- Enabled Point 없음 -> START 금지

## 9. 상위·하위 Sequence Interface

**입력:** `recipe_id`, HMI START, Robot/HMI 상태  
**출력:** `INIT_SUCCESS | INIT_FAIL`, reason, Recipe Snapshot 준비 상태  
**다음:** #02 Home Return

## 10. 코드 구현 포인트

- `validate_system_recipe()` / `validate_inspection_recipe()` 분리
- `build_execution_list(snapshot)`은 순서를 보존하고 disabled Point를 제외
- START 이후 Snapshot 변경 금지
- Validation 결과는 bool 하나보다 구조화된 reason code 목록으로 반환
