# Concept #5 - Pull Inspection Concept

## 1. 목적

Pull Inspection은 Adaptive Grip에서 형성된 Hard Grip 상태를 유지한 채 케이블 체결 방향의 반대 방향으로 Pull Motion을 수행하고, 체결상태 판정에 필요한 Force 및 Displacement 데이터를 취득하는 검사 동작이다.

Pull Inspection 자체는 PASS/FAIL을 판정하지 않는다. 상세 측정 데이터를 취득한 뒤 대표 결과값을 비동기 Inspection Judgment에 전달하며, 로봇 모션은 판정 완료를 기다리지 않고 다음 Inspection Point로 계속 진행한다.

## 2. 핵심 설계 원칙

- Pull Inspection은 모션 기반 Sequence이다.
- Pull은 `movel` 기반으로 수행한다.
- Pull 방향은 각 Inspection Point의 체결 방향 반대 방향이며 Inspection Recipe에서 Point별로 정의한다.
- Pull 수행 중 Force, Displacement, Time을 상세 측정한다.
- Pull은 `FORCE_LIMIT`, `MAX_DISTANCE`, `TIMEOUT` 중 먼저 발생한 조건에서 종료한다.
- `Force Limit`, `Max Distance`, `Timeout`은 Pull Motion 종료 조건이며 PASS/FAIL 판정 기준과 분리한다.
- Pull 완료 후 Soft Grip Open 상태로 전환하고 `entry_pose -> ready_pose`로 복귀한다.
- Pull 결과는 Inspection Judgment에 비동기로 전달한다.
- Point Transition은 Inspection Judgment 완료를 기다리지 않는다.
- 검사 모션은 Point 간에 끊기지 않고 연속적으로 진행한다.

## 3. Pull 공통 조건

| 항목 | 현재 설계값 | 비고 |
|---|---:|---|
| Pull Speed | 5 또는 10 mm/s | 코드 검증시험 후 공통값 확정 |
| Max Distance | 25 mm | 공통값 |
| Timeout | 10 s | 공통값 |
| Pull Direction | Point별 Recipe | 체결 방향의 반대 |
| Force Limit | 케이블/Point별 Recipe | 시험 데이터 기반 설정 |

현재 참고 데이터:
- LAN: Pull Limit Force 20 N
- USB: Pull Limit Force 12~15 N
- 위 값은 현재 제공된 시험 결과를 참고한 설정값이며 최종 기준은 반복 검증시험을 통해 보정한다.

## 4. 데이터 정책

Pull 수행 중에는 상세 데이터를 기록한다.

- Force time-series
- Displacement time-series
- Timestamp / elapsed time
- Pull Motion state

Inspection Judgment에는 우선 다음 3개 대표값만 전달한다.

1. `peak_pull_force`
2. `pull_displacement`
3. `termination_reason`

`peak_pull_force`는 Pull 구간에서 측정된 Pull Force 중 최대값이다.

평균 Force 등의 추가 Feature는 상세 로그에 기반하여 필요 시 확장한다.

## 5. 비동기 검사 구조

```text
Robot Motion Flow

Adaptive Grip
    ↓
Pull Inspection
    ↓
Soft Grip Open
    ↓
entry_pose
    ↓
ready_pose
    ↓
Next Point Transition
    ↓
Next Adaptive Grip
    ↓
...

Pull Inspection Result
    └──────────────→ Inspection Judgment
                         ↓
                   Result Classification
                         ↓
                       HMI
```

Inspection Judgment와 HMI 통신은 Robot Motion Flow를 Blocking하지 않는다.

## 6. 검증 항목

Pull Inspection은 실제 로봇 모션 기반 검증이 필요하며, 코드 시험을 통해 다음을 확인한다.

- Pull Speed 5 mm/s와 10 mm/s 비교
- Max Distance 25 mm 동작
- Timeout 10 s 동작
- Force Limit 기반 Pull 종료
- Force/Displacement 상세 측정
- `peak_pull_force` 산출
- Pull 종료 후 Soft Grip Open
- `entry_pose -> ready_pose` 복귀
- 검사 결과 비동기 전달 구조

검증 결과에 따라 수치 파라미터를 보정하되, 본 Concept의 Sequence 구조는 유지한다.
