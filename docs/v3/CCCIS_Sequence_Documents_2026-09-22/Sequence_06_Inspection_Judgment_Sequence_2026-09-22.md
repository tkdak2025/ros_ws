# Sequence #06 - Inspection Judgment & Work Monitoring Sequence

**프로젝트:** CCCIS (Contact-based Cable Connection Inspection System)  
**환경:** Doosan M0609 + OnRobot RG2 / No-Vision Phase  
**작업 단위:** Recipe 1회 실행 = Job 1개  
**외부 Trigger:** HMI 통신 기반 START / PAUSE / RESUME / STOP / HOME_RETURN  
**작성 기준일:** 2026-09-22


## 1. 목적

#05 Pull Inspection에서 전달된 Point 검사 데이터를 이용하여 `PASS / FAIL / MISSING` 중 하나의 제품 검사 결과를 생성하고, 상세 Reason과 함께 HMI에 전달한다. 동시에 Recipe 단위 Job의 Point별 검사 완료상태와 Pending Judgment를 관리하여 #07 Work Finish가 종료 가능 여부를 확인할 수 있도록 한다.

## 2. 설계 의도

- Result는 `PASS / FAIL / MISSING` 3개만 사용한다.
- 상세 원인은 별도 `reason` 메시지로 전달한다.
- 제품 판정과 System/Sequence Error를 분리한다.
- Judgment는 Robot의 다음 Point 이동을 Blocking하지 않는다.
- Work Finish가 사용할 Point별 완료상태/Result/Logging 상태를 관리한다.

## 3. 진입 조건

#05에서 다음 값 수신:

- `point_id`
- `peak_pull_force`
- `pull_displacement`
- `termination_reason`
- `grip_width_change`

참조 Parameter:

- LAN Required Pull Force = 20 N
- USB Required Pull Force = 12 N
- Normal Displacement Limit = 5 mm
- Slip Width Threshold = TBD

## 4. Sequence Flow

```text
PULL RESULT RECEIVED
    |
    v
Register Judgment Task / Point Monitoring
    |
    v
Grip Slip Evidence Check
    |
    +-- Slip confirmed --> MISSING
    |
    v
Pull Completion Validity Check
    |
    +-- Sequence/System abnormal --> POINT INCOMPLETE / ERROR
    |                              (no product result forced)
    |
    v
Required Pull Force reached ?
    |
    +-- YES --> pull_displacement <= 5 mm ?
    |               +-- YES --> PASS
    |               +-- NO  --> FAIL
    |
    +-- NO --> termination_reason == MAX_DISTANCE ?
                    +-- YES & no slip --> FAIL
                    +-- NO/TIMEOUT --> POINT INCOMPLETE / ERROR
    |
    v
Generate result + reason
    |
    v
Save Point Result / Log Status
    |
    v
HMI Result Message
    |
    v
Mark Judgment Completed
```

## 5. 결과 정의

| Result | 의미 |
|---|---|
| PASS | Required Pull Force를 견디며 Pull Displacement가 5 mm 이하 |
| FAIL | 유효한 Pull 검사에서 정상조건을 만족하지 못함. 부분 이동/완전 이탈을 별도 Result로 구분하지 않음 |
| MISSING | Grip Slip으로 파지 신뢰성이 상실되어 유효한 체결검사가 성립하지 않음 |

System Error / Sequence Error는 위 3개 제품 결과와 별도로 관리한다.

## 6. 세부 동작 및 판단 조건

### 6.1 PASS

```text
Required Pull Force reached
AND
pull_displacement <= 5 mm
AND
no confirmed grip slip
```

### 6.2 FAIL

대표 Case:

- Required Pull Force 도달 시점/종료 시 `pull_displacement > 5 mm`
- Slip 없이 Connector가 계속 이동하여 `MAX_DISTANCE = 25 mm` 도달

5 mm는 Motion Stop이 아니라 Judgment 기준이다.

### 6.3 MISSING

- Grip Slip이 확인되어 Robot Pull 이동량을 Connector 이동량으로 신뢰할 수 없는 경우
- `grip_width_change`를 Slip 보조 Feature로 사용
- Width 변화만으로 모든 축방향 Slip을 검출할 수 없으므로 Threshold/판별법 검증 필요

### 6.4 TIMEOUT / 비정상 완료

`TIMEOUT`은 자동으로 MISSING이나 FAIL로 치환하지 않는다. Slip이 아닌데 정상적인 Pull 종료조건을 만족하지 못한 경우에는 Point 검사 상태를 `INCOMPLETE/ERROR`로 관리하여 #07 Work Finish가 Job 종료를 승인하지 않도록 한다.

### 6.5 HMI Message

예시 필드:

```text
job_id
recipe_id
point_id
result = PASS | FAIL | MISSING
reason
peak_pull_force
pull_displacement
grip_width_change
termination_reason
judgment_status
```

Reason 예시:

- `PASS_FORCE_DISPLACEMENT_OK`
- `FAIL_DISPLACEMENT_LIMIT`
- `FAIL_MAX_DISTANCE`
- `MISSING_GRIP_SLIP`

## 7. 정상 종료 조건

- Point Result 생성 또는 Point Incomplete/Error 상태 확정
- Logging 완료 여부 기록
- HMI Result/Status 송신 요청 완료
- `pending_judgments`에서 해당 Point 제거

## 8. 비정상 / 예외 처리

- HMI 통신 실패가 제품 Result를 변경하지는 않는다.
- HMI Comm 상태는 Common #01 정책으로 관리한다.
- Judgment 내부 처리 실패/데이터 누락은 Point Incomplete/Error로 관리하고 #07에서 종료 보류.

## 9. 상위·하위 Sequence Interface

**입력:** #05 Pull Result Data  
**출력:** Point Result/Reason, Judgment Status, Job Progress/Monitoring State, HMI Message  
**소비자:** #07 Work Finish, HMI, Logger

## 10. 코드 구현 포인트

권장 Runtime 상태:

```text
point_runtime[point_id]:
  motion_completed
  judgment_status = PENDING | COMPLETED | ERROR
  result = PASS | FAIL | MISSING | None
  reason
  log_saved
```

- `pending_judgments` Set/Counter 유지
- Judgment Worker는 Robot Motion Thread와 분리
- Work Finish는 이 Runtime 상태를 조회하여 완료 여부 판단
