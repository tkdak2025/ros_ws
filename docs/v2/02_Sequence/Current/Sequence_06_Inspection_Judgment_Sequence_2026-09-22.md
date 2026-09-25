# Sequence #06 - Inspection Judgment Sequence

**작성일:** 2026-09-22  
**대상:** CCCIS (Contact-based Cable Connection Inspection System)

## 1. 목적

Sequence #05 Pull Inspection에서 전달된 대표 검사 데이터를 기반으로 해당 Inspection Point를 `PASS`, `FAIL`, `MISSING` 중 하나로 분류하고 상세 Reason과 함께 HMI에 전달한다.

본 Sequence는 Robot Motion Flow와 비동기로 동작한다.

## 2. 설계 의도

- 정상 체결 기준을 Force와 Displacement의 조합으로 판정한다.
- 정상조건을 만족하지 못한 유효 검사는 `FAIL`로 단순화한다.
- 유효한 검사 자체가 성립하지 않은 경우에만 `MISSING`으로 구분한다.
- 상세 원인은 Result와 분리하여 HMI 메시지로 전달한다.
- Judgment가 다음 Point 이동을 지연시키지 않도록 비동기 처리한다.

## 3. 진입 조건

Sequence #05 Pull Inspection으로부터 해당 Point의 검사 데이터가 전달되었을 것.

필수 입력:

- `point_id`
- `peak_pull_force`
- `pull_displacement`
- `termination_reason`
- `grip_width_change`

Point Recipe 또는 Judgment 설정에서 Cable Type에 따른 Required Pull Force를 확인할 수 있어야 한다.

- LAN: 20 N
- USB: 12 N
- Displacement Limit: 5 mm

## 4. Sequence Flow

```text
INSPECTION_JUDGMENT_START
        |
        v
Pull Result Data 수신
        |
        v
Input / Inspection Validity Check
        |
        +-- Invalid / Abnormal Completion --> MISSING
        |
        v
Grip Slip Evidence Check
        |
        +-- Slip 판단 --> MISSING
        |
        v
Required Pull Force 만족 여부
        |
        +-- NO --> FAIL
        |
        v
Pull Displacement <= 5 mm ?
        |
        +-- YES --> PASS
        |
        +-- NO  --> FAIL
        |
        v
Result + Reason 생성
        |
        v
HMI 비동기 전송
        |
        v
Result / Log 저장
        |
        v
INSPECTION_JUDGMENT_DONE
```

## 5. Flow 용어 설명

### Input / Inspection Validity Check
Pull Inspection 결과가 정상적인 판정에 사용할 수 있는 데이터인지 확인한다.

### Grip Slip Evidence Check
RG2 Width 변화량 등 확보된 Grip 상태 정보를 이용하여 Gripper-Cable Slip 가능성을 확인한다.

### Required Pull Force
Cable Type별 정상 판정에 필요한 Pull 하중이다.

- LAN: 20 N
- USB: 12 N

### Pull Displacement
Pull 구간에서 측정한 이동량이며 정상 허용 한계는 5 mm이다.

## 6. 세부 동작 및 판단 조건

### 6.1 유효성 검사

다음과 같은 경우 정상적인 PASS/FAIL 판정을 만들 수 없는 검사로 보고 `MISSING` 후보로 처리한다.

- 검사 데이터 누락/비정상
- 정상적인 Pull Inspection 완료가 아닌 비정상 종료
- Grip Slip으로 인해 Pull Displacement를 Connector 이동량으로 신뢰할 수 없음

Robot/Controller/Safety/Tool 자체 오류는 Result `MISSING`이 아니라 System Error 계열에서 처리한다.

### 6.2 Grip Slip 판별

`grip_width_change`를 Slip 판별의 보조 Feature로 사용한다.

```text
grip_width_change
        |
        +-- 정상 변동 범위 --> Judgment 계속
        |
        +-- Slip Threshold 초과 --> MISSING_GRIP_SLIP
```

`Slip Width Threshold`는 반복시험 전까지 TBD이다.

RG2 Width 변화가 없다는 사실만으로 Slip이 없다고 확정하지 않는다.

### 6.3 Force 조건

Cable Type별 Required Pull Force:

| Cable | Required Pull Force |
|---|---:|
| LAN | 20 N |
| USB | 12 N |

유효한 검사에서 Required Pull Force를 만족하지 못하면 정상 체결 조건을 만족하지 못한 것으로 보고 `FAIL` 처리한다.

### 6.4 Displacement 조건

Required Pull Force를 만족한 경우 Pull Displacement를 확인한다.

```text
pull_displacement <= 5 mm -> PASS
pull_displacement > 5 mm  -> FAIL
```

Connector의 부분 이동과 완전 이탈은 Result에서 별도로 구분하지 않는다.

### 6.5 Result / Reason 생성

Result:

- `PASS`
- `FAIL`
- `MISSING`

Reason 예시:

| Result | Reason 예시 | 의미 |
|---|---|---|
| PASS | `PASS_FORCE_DISPLACEMENT_OK` | Force/Displacement 정상조건 만족 |
| FAIL | `FAIL_DISPLACEMENT_LIMIT` | 정상 허용 이동량 초과 |
| FAIL | `FAIL_FORCE_REQUIREMENT` | Required Pull Force 조건 미충족 |
| MISSING | `MISSING_GRIP_SLIP` | Grip Slip으로 검사 유효성 상실 |
| MISSING | `MISSING_INVALID_DATA` | 유효 데이터 부족 |
| MISSING | `MISSING_ABNORMAL_TERMINATION` | 검사 비정상 종료 |

Reason 코드는 HMI Interface 정의에서 최종 확정한다.

## 7. 정상 종료 조건

다음을 만족하면 Inspection Judgment Sequence가 정상 완료된 것으로 본다.

- 입력 검사 데이터 처리 완료
- `PASS / FAIL / MISSING` 중 하나의 Result 생성
- Reason 생성
- HMI 전송 요청 수행
- Judgment 결과 Logging 완료

HMI 응답을 기다리기 위해 Robot Motion을 Blocking하지 않는다.

## 8. 비정상 / 예외 처리

### Judgment 내부 데이터 이상
유효한 검사 판정이 불가능하면 `MISSING`과 적절한 Reason을 생성한다.

### HMI 전송 문제
Judgment 결과 자체와 HMI 통신 상태를 분리한다. 통신 장애는 HMI Communication 정책에 따라 처리하며 제품 검사 Result를 변경하지 않는다.

### System Error
Robot, Controller, Safety, RG2 Tool 자체의 실행 오류는 Inspection Judgment의 `PASS / FAIL / MISSING` 결과로 대체하지 않는다.

## 9. 상위·하위 Sequence Interface

### 입력 - Sequence #05 Pull Inspection
- `point_id`
- `peak_pull_force`
- `pull_displacement`
- `termination_reason`
- `grip_width_change`

### 참조 - Recipe / Judgment Parameter
- Cable Type
- Required Pull Force
- Displacement Limit = 5 mm
- Slip Width Threshold = TBD

### 출력 - HMI / Log
- `point_id`
- `result`
- `reason`
- 필요 시 대표 측정값

### Motion Flow와의 관계

Inspection Judgment는 Robot의 다음 Point Transition과 병렬로 진행한다.

```text
Pull Inspection Data
      |
      +--> Inspection Judgment --> HMI
      |
Robot +--> Soft Grip Open --> entry_pose --> ready_pose --> Next Point
```

## 10. TBD / 검증 필요사항

- `Slip Width Threshold` 반복시험 확정
- RG2 Width 정상 변동 범위 확인
- Width 변화가 작게 나타나는 축방향 Slip의 추가 검출 필요성
- `termination_reason`별 MISSING/FAIL 세부 Mapping 검증
- HMI Reason Code 및 Message Schema 최종 확정
