# Sequence #5 - Pull Inspection Sequence

## 1. 목적

Adaptive Grip 완료 후 Hard Grip 상태에서 Pull Motion을 수행하여 Force와 Displacement를 측정하고, 검사 판정에 필요한 대표 결과 데이터를 생성한다. Pull 완료 후 케이블을 해제하고 `ready_pose`까지 복귀하여 다음 Inspection Point로 즉시 전환 가능한 상태를 만든다.

## 2. 설계 의도

Pull Inspection은 체결상태를 직접 판정하는 Sequence가 아니라 검사 모션과 데이터 취득을 담당한다.

Inspection Judgment는 Pull Inspection 결과를 후단에서 비동기로 처리하며, 로봇은 판정 완료를 기다리지 않고 다음 Point 검사 동작을 계속 수행한다.

## 3. 진입 조건

- Sequence #4 Adaptive Grip 정상 완료
- Hard Grip 상태 형성
- 대상 Point의 Inspection Recipe 확보
- Pull Motion 수행 가능한 Robot/Tool 상태

## 4. Sequence Flow

```text
PULL_INSPECTION_START
        ↓
Pull 기준 상태 저장
        ↓
Pull movel 시작
- Direction    = Point Recipe
                 (체결 방향의 반대)
- Speed        = Common Parameter (5 or 10 mm/s, TBD)
- Max Distance = 25 mm
- Force Limit  = Cable/Point Recipe
- Timeout      = 10 s
        ↓
Force / Displacement / Time 상세 측정
        ↓
Pull 종료조건 감시
├─ FORCE_LIMIT
├─ MAX_DISTANCE
└─ TIMEOUT
        ↓
Pull Motion 종료
        ↓
대표 결과값 생성
├─ peak_pull_force
├─ pull_displacement
└─ termination_reason
        ├────────────→ Async Inspection Judgment → HMI
        │
        ↓
Soft Grip Open
        ↓
entry_pose 복귀
        ↓
ready_pose 복귀
        ↓
PULL_INSPECTION_DONE
        ↓
Next Point Transition
```

## 5. Flow 용어 설명

### Pull 기준 상태 저장
Pull 시작 시점의 기준 상태를 확보한다. 이후 Pull 구간의 Force와 Displacement 측정 기준으로 사용한다.

### Pull Direction
각 Inspection Point의 체결 방향 반대 방향이다. Point마다 방향이 다를 수 있으므로 Inspection Recipe에서 정의한다.

### Force Limit
Pull Motion의 종료 조건이다. PASS/FAIL 판정 기준 자체가 아니다.

### Max Distance
Pull Motion이 허용되는 최대 이동거리이다. 현재 공통값은 25 mm이다.

### Timeout
Pull Motion의 최대 허용시간이다. 현재 공통값은 10 s이다.

### peak_pull_force
Pull 구간에서 측정된 Pull Force 중 최대값이다.

### termination_reason
Pull Motion이 종료된 원인을 나타낸다.
- `FORCE_LIMIT`
- `MAX_DISTANCE`
- `TIMEOUT`

## 6. 세부 동작 및 판단 조건

### 6.1 Pull Motion

Hard Grip 상태에서 Point Recipe에 정의된 Pull Direction으로 `movel`을 수행한다.

현재 Pull Speed 후보는 5 mm/s와 10 mm/s이며 코드 기반 검증시험 후 하나의 공통값으로 확정한다.

### 6.2 Pull 종료

다음 조건 중 먼저 발생한 조건에서 Pull Motion을 종료한다.

1. Force Limit 도달
2. Max Distance 25 mm 도달
3. Timeout 10 s 발생

이 종료 사유 자체로 체결상태 PASS/FAIL을 판정하지 않는다.

### 6.3 상세 측정

Pull Motion 동안 다음 데이터를 상세 기록한다.

- Force time-series
- Displacement time-series
- Timestamp / elapsed time
- Pull Motion state

상세 로그는 검증, 기준값 보정 및 향후 Feature 확장에 사용한다.

### 6.4 결과 데이터 생성

Pull 완료 후 다음 3개 값을 Inspection Judgment에 전달한다.

- `peak_pull_force`
- `pull_displacement`
- `termination_reason`

현재 Force 대표값은 Peak 값만 사용한다. 평균값 등은 필요 시 향후 추가한다.

### 6.5 Pull 종료 후 복귀

Pull Motion 종료 후:
1. Soft Grip Open 상태로 전환한다.
2. `entry_pose`로 복귀한다.
3. `ready_pose`로 복귀한다.
4. 다음 Point Transition을 시작한다.

Inspection Judgment 결과를 기다리지 않는다.

## 7. 정상 종료 조건

다음 조건을 만족하면 Pull Inspection Sequence가 완료된 것으로 본다.

- Pull Motion 종료
- 대표 결과 데이터 생성 및 Judgment 경로 전달
- Soft Grip Open 수행
- `entry_pose` 복귀
- `ready_pose` 복귀
- 다음 Point Transition 수행 가능 상태

## 8. 비정상/예외 처리

Robot, Controller, Safety, Tool 자체의 이상은 Pull 검사 판정 결과가 아니라 System Error 계열로 처리한다.

Pull Motion이 정상적으로 실행되었으나 유효한 검사 결과를 만들 수 없는 경우의 최종 분류는 Inspection Judgment에서 처리한다.

## 9. 상위·하위 Sequence Interface

### 입력
Sequence #4 Adaptive Grip으로부터:
- Hard Grip 완료 상태
- 대상 Inspection Point
- Point Recipe

### 출력 - Motion Flow
- `ready_pose` 복귀 상태
- Next Point Transition 실행 가능 상태

### 출력 - Async Judgment Flow
- `point_id`
- `peak_pull_force`
- `pull_displacement`
- `termination_reason`

Inspection Judgment는 Motion Flow와 비동기로 동작하며 로봇의 다음 Point 이동을 Blocking하지 않는다.

## 10. TBD / 검증 필요사항

- Pull Speed: 5 mm/s vs 10 mm/s 최종 선정
- 케이블/Point별 Force Limit 반복시험 보정
- 평균 Force 등 추가 Feature 필요성 검토

현재 참고 설정:
- LAN Pull Limit: 20 N
- USB Pull Limit: 12~15 N
- Max Distance: 25 mm
- Timeout: 10 s
