# Sequence #3 - Point Transition Sequence

## 1. 목적

Point Transition은 현재 Inspection Point의 검사 동작이 종료된 상태에서 다음 Inspection Point의 `ready_pose`를 거쳐 `entry_pose`까지 이동하여, Sequence #4 Adaptive Grip을 시작할 수 있는 상태를 만드는 모션 기반 Sequence이다.

Point Transition은 Inspection Judgment의 완료를 기다리지 않는다. 이전 Point의 검사 결과 판정 및 HMI 통신은 후단에서 비동기로 수행되며, Robot Motion Flow는 다음 Point로 연속 진행한다.

## 2. 설계 의도

- Point 간 이동을 공통 Sequence로 표준화한다.
- Point별 전용 Robot Sequence를 별도로 Teaching하지 않는다.
- START 시 생성된 Execution List의 순서에 따라 다음 Inspection Point를 선택한다.
- `enabled=false` Point는 Execution List에서 제외한다.
- Point 간 이동은 `ready_pose -> ready_pose`를 기준으로 수행한다.
- 다음 Point의 `ready_pose -> entry_pose`는 직선 진입을 위해 `movel`을 사용한다.
- 매 Point 전환 시 `work_Access_safe_pose`를 경유하지 않는다.
- Cable 접촉, Grip, Entry 보정은 Point Transition의 책임이 아니며 Sequence #4 Adaptive Grip에서 수행한다.
- Inspection Judgment 및 HMI 결과 통신은 Point Transition을 Blocking하지 않는다.

## 3. 진입 조건

### First Point
- Work Initialize 완료
- Home Return을 통해 `work_Access_safe_pose`까지 접근 완료
- START 시 확정된 Execution List 존재
- 첫 번째 enabled Inspection Point가 결정됨

### Next Point
- 이전 Point의 Pull Inspection 완료
- Soft Grip Open 완료
- 이전 Point의 `entry_pose -> ready_pose` 복귀 완료
- Execution List에 다음 Inspection Point가 존재함

## 4. Sequence Flow

```text
[First Point]

work_Access_safe_pose
        ↓
Execution List의 First Point 선택
        ↓
movej(First Point ready_pose)
        ↓
movel(First Point entry_pose)
        ↓
POINT_TRANSITION_DONE
        ↓
Sequence #4 Adaptive Grip


[Next Point]

Current Point ready_pose
        ↓
Execution List Index 증가
        ↓
Next Inspection Point 선택
        ↓
movej(Next Point ready_pose)
        ↓
movel(Next Point entry_pose)
        ↓
POINT_TRANSITION_DONE
        ↓
Sequence #4 Adaptive Grip
```

Inspection Judgment는 별도 비동기 경로에서 수행된다.

```text
Previous Pull Result
        └────────────→ Inspection Judgment → HMI

Robot Motion Flow
Current ready_pose
        ↓
Next Point Transition
        ↓
Adaptive Grip
        ↓
Pull Inspection
        ↓
...
```

## 5. Flow 용어 설명

### Execution List
START 시 Inspection Recipe의 Point 순서와 `enabled` 상태를 기준으로 생성되는 실제 검사 실행 목록이다. RUNNING 중에는 해당 목록을 변경하지 않는다.

### ready_pose
Inspection Point 진입 전 안전하게 접근하기 위한 Point별 대기 Pose이다. Point 간 이동의 기준 Pose로 사용한다.

### entry_pose
Adaptive Grip을 시작하기 직전의 Point별 진입 Pose이다. Point Transition의 정상 종료 위치이다.

### First Point
작업 시작 후 처음 검사하는 enabled Point이다. `work_Access_safe_pose`에서 해당 Point의 `ready_pose`로 접근한다.

### Next Point
현재 Point 검사 완료 후 Execution List의 다음 순번에 해당하는 enabled Point이다.

## 6. 세부 동작 및 판단 조건

### 6.1 Point 선택

Point Transition은 START 시 확정된 Execution List를 사용한다.

- First Point: Execution List의 첫 번째 Point
- Next Point: 현재 Index의 다음 Point
- `enabled=false` Point: Execution List 생성 단계에서 제외

RUNNING 중 Point 순서나 enabled 상태를 다시 계산하지 않는다.

### 6.2 Point 간 이동

Next Point 전환 시:

1. 현재 Point의 `ready_pose`에서 시작한다.
2. `movej`로 Next Point의 `ready_pose`까지 이동한다.
3. `movel`로 Next Point의 `entry_pose`까지 이동한다.

`ready_pose -> ready_pose` 구간은 Point 간 장거리/자세 전환 구간이므로 `movej`를 사용하고, `ready_pose -> entry_pose` 구간은 Inspection Point로의 직선 진입 구간이므로 `movel`을 사용한다.

### 6.3 First Point 이동

First Point는 이전 Inspection Point가 없으므로 `work_Access_safe_pose`에서 First Point의 `ready_pose`로 이동한 뒤 `entry_pose`로 진입한다.

### 6.4 Inspection Judgment와의 관계

Point Transition은 이전 Point의 Inspection Judgment 결과를 기다리지 않는다.

Pull Inspection에서 생성된 결과 데이터는 별도 Judgment 경로로 전달되고, Robot Motion Flow는 즉시 다음 Point Transition을 수행한다.

따라서 검사 판정 연산이나 HMI 통신 지연이 Point 간 Robot Motion을 정지시키지 않는다.

### 6.5 Retry 정책

Point Transition 자체에는 자동 Motion Retry를 두지 않는다.

Robot, Controller, Safety 계열의 Motion Fault는 System Error 처리 정책을 따른다.

## 7. 정상 종료 조건

다음 조건을 만족하면 Point Transition이 정상 완료된 것으로 본다.

- 대상 Inspection Point가 Execution List 기준으로 정상 선택됨
- 대상 Point의 `ready_pose` 이동 완료
- 대상 Point의 `entry_pose` 이동 완료
- Sequence #4 Adaptive Grip을 시작할 수 있는 Robot 상태

정상 종료 위치는 대상 Point의 `entry_pose`이다.

## 8. 비정상 / 예외 처리

### Motion Timeout
`ready_pose` 또는 `entry_pose` 이동이 허용 시간 내 완료되지 않을 경우 Point Transition을 정상 완료하지 않는다.

Motion Timeout 값은 실제 Robot Motion 검증 후 충분한 여유를 두어 설정한다.

### Robot / Controller / Safety Fault
Point Transition 중 Robot, Controller 또는 Safety Fault가 발생하면 해당 Fault를 System Error로 전달하고 상위 Error Handling 정책을 따른다.

### Recipe / Execution List 이상
Point Transition 진입 전에 대상 Point 또는 필요한 Pose 정보가 유효하지 않은 경우 정상 이동을 시작하지 않는다. Recipe 유효성 검사는 기본적으로 Work Initialize / START Validation 단계에서 선행되어야 한다.

## 9. 상위·하위 Sequence Interface

### 입력

상위 Main Work / Execution List로부터:
- `point_id`
- Point execution index
- `ready_pose`
- `entry_pose`

Robot Motion Flow로부터:
- First Point: `work_Access_safe_pose` 상태
- Next Point: Current Point `ready_pose` 복귀 상태

### 출력

Sequence #4 Adaptive Grip으로:
- 대상 `point_id`
- 대상 Point `entry_pose` 도달 상태
- Adaptive Grip 시작 가능 상태

### 비동기 경로

이전 Point의 Inspection Result / Inspection Judgment / HMI 통신은 Point Transition과 독립적으로 수행한다.

## 10. TBD / 검증 필요사항

- `movej` / `movel` Motion Timeout 값
- Point 간 실제 이동 경로 및 Fixture 간섭 여부
- `ready_pose -> entry_pose` 진입 속도/가속도 공통값
- 다수 Point 반복 운전 시 연속 Motion 안정성

위 항목은 Robot Motion 검증을 통해 수치값을 확정하며, Point Transition의 기본 Sequence 구조는 유지한다.
