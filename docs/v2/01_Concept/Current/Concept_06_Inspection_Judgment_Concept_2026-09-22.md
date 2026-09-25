# Concept #06 - Inspection Judgment Concept

**작성일:** 2026-09-22  
**대상:** CCCIS (Contact-based Cable Connection Inspection System)

## 1. 문서 목적

본 문서는 Sequence #05 Pull Inspection에서 생성된 검사 데이터를 이용하여 Inspection Point의 최종 검사 결과를 분류하는 Inspection Judgment의 설계 개념을 정의한다.

Inspection Judgment는 Robot Motion Flow와 분리된 비동기 처리로 동작하며, 판정 완료가 다음 Inspection Point 이동을 Blocking하지 않는다.

## 2. 설계 의도

Inspection Judgment의 핵심은 **정상 체결 기준(PASS Criterion)을 명확하게 정의하는 것**이다.

Connector의 Detach와 Displacement를 별도의 불량 종류로 세분화하지 않고, 정상 체결 조건을 만족하지 못한 유효 검사 결과는 공통적으로 `FAIL`로 처리한다.

검사 결과는 다음 3개로 단순화한다.

- `PASS`: 정상 체결 기준 만족
- `FAIL`: 정상 체결 기준 불만족, 점검 필요
- `MISSING`: 유효한 정상/불량 판정을 만들 수 없는 검사

Robot, Controller, Safety, Tool 자체의 오류는 Inspection Result가 아니라 별도의 System Error로 관리한다.

## 3. 표준 판정값

| 항목 | LAN | USB |
|---|---:|---:|
| Required Pull Force | 20 N | 12 N |
| Normal Displacement Limit | ≤ 5 mm | ≤ 5 mm |

현재 프로젝트 표준값으로 위 값을 사용한다.

## 4. PASS 개념

PASS는 단순히 이동량이 작은 상태가 아니다.

**규정된 Pull Force를 실제로 견디는 동안 Connector의 Pull Displacement가 5 mm 이하인 상태**를 정상 체결로 정의한다.

```text
Required Pull Force 도달
        AND
Pull Displacement <= 5 mm
        |
        v
       PASS
```

따라서 Force 기준을 만족하지 않은 상태에서 이동량만 5 mm 이하라는 이유로 PASS 처리하지 않는다.

## 5. FAIL 개념

유효한 Pull Inspection이 수행되었으나 정상 체결 기준을 만족하지 못한 경우 `FAIL`로 처리한다.

대표적으로 Required Pull Force에 도달하기 전에 Pull Displacement가 5 mm를 초과한 경우가 해당한다.

Connector가 일부 이동한 경우와 완전히 이탈한 경우를 별도 Result로 구분하지 않는다. 두 경우 모두 정상 체결 조건을 만족하지 못한 점검 필요 상태로 취급한다.

## 6. MISSING 개념

`MISSING`은 제품의 체결 불량을 의미하지 않는다. 검사 과정 자체가 유효한 PASS/FAIL 결과를 만들 수 없었던 경우를 의미한다.

현재 주요 후보는 다음과 같다.

- Gripper-Cable Slip이 발생하여 Connector 이동량과 Robot Pull 이동량을 신뢰하기 어려운 경우
- 검사 도중 비정상 종료되어 정상적인 Pull Inspection 결과가 완성되지 않은 경우
- 필요한 검사 데이터가 유효하지 않거나 누락된 경우

## 7. Grip Slip 보조 판별

Pull Force와 Pull Displacement만으로는 Connector 이동과 Gripper-Cable Slip을 항상 구분할 수 없다.

따라서 RG2 Width 변화를 보조 Feature로 사용한다.

```text
Hard Grip 완료
    |
    v
grip_width_start 저장
    |
    v
Pull 수행 중 RG2 Width 기록
    |
    v
grip_width_change 계산
```

`grip_width_change`가 유의미하게 발생하면 Grip 상태 변화 또는 Slip 가능성을 판단하는 보조 근거로 사용한다.

단, Cable이 축방향으로 미끄러지는 경우 RG2 Width 변화가 작을 수 있으므로 Width만으로 Slip을 확정하지 않는다.

`Slip Width Threshold`는 반복시험을 통해 결정한다.

## 8. Judgment 입력 데이터

Sequence #05 Pull Inspection으로부터 최소 다음 데이터를 전달받는다.

- `point_id`
- `peak_pull_force`
- `pull_displacement`
- `termination_reason`
- `grip_width_change`

Raw Log에는 필요 시 다음 상세 데이터를 유지한다.

- Force time-series
- Displacement time-series
- RG2 Width time-series
- Timestamp / elapsed time
- Pull Motion state

## 9. Result와 Reason 분리

최종 Result는 3개로 유지하고, 상세 원인은 별도 통신 메시지의 `reason`으로 전달한다.

```text
result = PASS | FAIL | MISSING
reason = 상세 판정 원인
```

Reason 예시:

- `PASS_FORCE_DISPLACEMENT_OK`
- `FAIL_DISPLACEMENT_LIMIT`
- `MISSING_GRIP_SLIP`
- `MISSING_INVALID_DATA`
- `MISSING_ABNORMAL_TERMINATION`

Reason 명칭과 메시지 포맷은 HMI Interface 정의 시 최종 확정한다.

## 10. 비동기 처리 원칙

Inspection Judgment는 Robot Motion Flow를 Blocking하지 않는다.

```text
Sequence #05 Pull Inspection
        |
        +---- Result Data ----> Sequence #06 Inspection Judgment ----> HMI
        |
        +---- Soft Grip Open
                 |
                 v
              entry_pose
                 |
                 v
              ready_pose
                 |
                 v
        Next Point Transition
```

Robot은 Judgment 완료를 기다리지 않고 다음 Point로 이동한다.

## 11. 현재 확정 / TBD

### 확정
- Result: `PASS / FAIL / MISSING`
- LAN Required Pull Force: 20 N
- USB Required Pull Force: 12 N
- Normal Displacement Limit: 5 mm
- Force 기준과 Displacement 기준을 함께 사용
- Detach/Displacement 불량을 별도 Result로 분리하지 않음
- Result와 Reason을 분리하여 HMI 전달
- RG2 Width 변화를 Slip 판별 보조 Feature로 사용
- Judgment는 비동기 처리

### TBD / 검증 필요
- `Slip Width Threshold`
- RG2 Width 반복성 및 Cable 압축에 의한 정상 변화량
- 축방향 Slip처럼 Width 변화가 작은 Slip의 추가 판별 방법
- HMI Reason 코드 최종 명칭 및 통신 메시지 포맷
