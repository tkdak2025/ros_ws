# CCCIS Test Case #1 - Motion Error / Grip Stability / Grip-Pull Verification

**작성일:** 2026-09-22  
**대상 시스템:** CCCIS (Contact-based Cable Connection Inspection System)  
**Robot / Tool:** Doosan M0609 / OnRobot RG2

# 0. 결론 요약

현재까지 수행한 검증은 크게 세 가지 Test Case로 정리할 수 있다.

| Test Case | 목적 | 핵심 결과 | CCCIS 설계 반영 |
|---|---|---|---|
| TC-01 Robot Motion Error Measurement | Robot 자체 위치/자세 오차가 Grip 위치 오차의 주요 원인인지 확인 | Y/Z 이동 및 자세 측정에서 약 1 mm / 1° 이내 수준으로 확인 | 현재 단계에서는 Robot 자체 오차보다 Flexible Cable의 위치/형상 변화가 주요 불확실성으로 판단 |
| TC-02 Grip Stability Verification | Pull 검사 중 케이블을 안정적으로 유지할 Grip 조건 확인 | LAN/USB별 Soft/Hard Grip 조건을 시험·정리. LAN Hard Grip 42.5 N, USB 35~40 N 범위 사용 | Adaptive Grip의 Soft Grip → Hard Grip 구조 및 케이블별 Recipe 적용 근거 |
| TC-03 Grip-Pull Inspection Verification | Hard Grip 후 Pull Motion에서 Force/Displacement를 측정하고 검사조건을 확인 | LAN/USB Pull 시험을 수행하고 Pull Limit 설정값을 정리. LAN 20 N, USB 12~15 N 참고 | Pull Inspection Sequence의 Force/Displacement 측정 및 케이블별 Force Limit Recipe 근거 |

세 Test Case의 연결 관계는 다음과 같다.

```text
TC-01 Robot Motion Error Measurement
        ↓
Robot 자체 오차 영향 확인
        ↓
TC-02 Grip Stability Verification
        ↓
케이블별 안정적인 Grip 조건 확보
        ↓
TC-03 Grip-Pull Inspection Verification
        ↓
Pull Force / Displacement 측정 및 Pull 조건 정리
        ↓
Adaptive Grip + Pull Inspection Sequence 설계
```

현재 결론은 **Robot 자체의 반복 위치/자세 오차보다 Flexible Cable의 위치와 형상 변화에 대응하는 Grip 과정이 더 중요한 설계 요소**라는 것이다. 따라서 CCCIS는 Point별 고정 Teaching만으로 Grip 위치를 결정하기보다 Adaptive Grip을 사용하고, 안정화된 Hard Grip 이후 Pull Inspection을 수행하는 구조로 설계한다.

---

# 1. TC-01 Robot Motion Error Measurement

## 1.1 테스트 목적

Grip 위치 오차가 Robot 자체의 이동 오차에서 발생하는지 확인하고, CCCIS에서 별도의 Robot Pose 보정 기능이 필요한지 판단한다.

특히 M0609의 Y/Z 방향 이동과 자세 변화에 대해 실제 오차 수준을 확인하여 이후 Grip 안정화 시험의 전제조건을 확보한다.

## 1.2 테스트 순서

```text
Robot 기준 Pose 설정
        ↓
Y / Z 방향 이동 명령
        ↓
실제 이동 위치 확인
        ↓
자세 변화 확인
        ↓
명령값과 실제값 비교
        ↓
Position / Orientation Error 정리
```

## 1.3 확인 항목

- Y 방향 이동 오차
- Z 방향 이동 오차
- Robot 자세 오차
- Grip 위치에 영향을 줄 정도의 누적 오차 존재 여부

## 1.4 결과

시험에서 확인한 Robot 이동/자세 오차는 대략 다음 범위였다.

- Position Error: 약 **1 mm 이내**
- Orientation Error: 약 **1° 이내**

현재 프로젝트 수준에서는 이 정도의 Robot 자체 오차를 Grip 실패의 주원인으로 보기 어렵다고 판단하였다.

## 1.5 결론 및 설계 반영

Robot BASE/TCP/Tool Chain을 정상적으로 구성한 상태에서는 Robot 자체 위치/자세 오차보다 **Flexible Cable의 실제 위치, 휘어짐 및 형상 변화**가 Grip 위치 불확실성에 더 큰 영향을 준다.

따라서 이후 검증의 중심을 Robot 위치 보정보다 **Grip 안정화와 Adaptive Grip**으로 이동하였다.

---

# 2. TC-02 Grip Stability Verification

## 2.1 테스트 목적

Pull Inspection을 수행하기 전에 RG2가 케이블을 안정적으로 Grip할 수 있는 조건을 확인한다.

Soft Grip은 Cable Entry/정렬 과정에서 사용하고, Hard Grip은 실제 Pull Inspection에서 케이블이 미끄러지지 않도록 유지하는 것을 목적으로 한다.

## 2.2 테스트 순서

```text
Inspection Point 접근
        ↓
Soft Grip 조건 적용
        ↓
Cable Entry / Grip
        ↓
Hard Grip 전환
        ↓
Pull 방향 하중 발생
        ↓
Grip Slip / 자세 유지 상태 확인
        ↓
Grip Force 조건 조정
        ↓
케이블별 Grip 조건 정리
```

## 2.3 주요 확인 항목

- Soft Grip 상태에서 Cable Entry 가능 여부
- Hard Grip 전환 후 케이블 유지 여부
- Pull 중 Grip Slip 발생 여부
- Grip Force 증가에 따른 안정성 변화
- 케이블/커넥터별 적정 Grip Force 차이

## 2.4 정리된 설정값

| 항목 | LAN | USB |
|---|---:|---:|
| Soft Grip Force | 10 N | 10 N |
| Hard Grip Force | 42.5 N | 35~40 N |

LAN의 Hard Grip 42.5 N은 시험 중 Grip Slip 보정을 반영하여 정리한 값이다.

USB는 커넥터 표면 및 몰딩부 특성을 고려하여 35~40 N 범위로 정리하였다.

## 2.5 결과 및 설계 반영

Grip을 하나의 고정 동작으로 처리하기보다 다음의 2단계 구조로 분리하는 것이 적합하다고 정리하였다.

```text
Soft Grip
    ↓
Cable Entry
    ↓
Hard Grip
    ↓
Pull Inspection
```

이 결과는 Sequence #4 Adaptive Grip의 기본 구조에 반영하였다.

Grip Force는 모든 케이블에 동일한 값으로 고정하지 않고 **케이블/Inspection Point 특성에 따라 Recipe에서 관리**하는 방향으로 정리하였다.

---

# 3. TC-03 Grip-Pull Inspection Verification

## 3.1 테스트 목적

Hard Grip 상태에서 케이블을 Pull하고, 이 과정에서 발생하는 Force와 Displacement를 측정하여 Pull Inspection Sequence의 기본 동작과 케이블별 Pull 조건을 확인한다.

LAN과 USB를 각각 시험 대상으로 사용하였다.

## 3.2 테스트 순서

```text
Hard Grip 완료
        ↓
Pull 시작
        ↓
Pull Force 연속 측정
        +
Pull Displacement 연속 측정
        ↓
Force / Distance 조건 감시
        ↓
Pull 종료
        ↓
Peak Force 및 이동거리 확인
        ↓
LAN / USB 시험결과 비교
        ↓
Pull 조건 정리
```

## 3.3 측정 항목

Pull 구간에서는 가능한 상세 데이터를 측정한다.

- Force time-series
- Displacement time-series
- Timestamp / elapsed time
- Pull Motion state

대표 결과값은 다음 항목을 사용한다.

- `peak_pull_force`
- `pull_displacement`
- `termination_reason`

현재 Force 대표값은 Pull 구간의 최대값인 `peak_pull_force`를 우선 사용한다. 평균 Force 등은 반복시험 결과에 따라 추가할 수 있다.

## 3.4 LAN / USB 시험 정리값

| 항목 | LAN | USB |
|---|---:|---:|
| Pull Limit Force | 20 N | 12~15 N |
| Max Pull Distance | 25 mm | 25 mm |
| Timeout | 10 s | 10 s |
| Pull Speed | 5 또는 10 mm/s 검증 예정 | 5 또는 10 mm/s 검증 예정 |

Pull Direction은 각 Inspection Point의 **체결 방향 반대 방향**으로 정의하며 Point별 Inspection Recipe에서 관리한다.

## 3.5 결과 및 설계 반영

LAN과 USB는 체결 방식과 요구 Pull Force가 다르므로 Force Limit은 케이블별 Recipe 값으로 관리한다.

반면 다음 조건은 가능한 한 공통 검사조건으로 유지한다.

- Max Pull Distance: **25 mm**
- Timeout: **10 s**
- Pull Speed: **5 또는 10 mm/s 중 검증 후 공통값 확정**

Pull Inspection은 PASS/FAIL을 직접 판정하지 않고 상세 측정 후 다음 대표 데이터를 Inspection Judgment에 전달한다.

```text
peak_pull_force
pull_displacement
termination_reason
```

Inspection Judgment는 Robot Motion Flow와 비동기로 동작하며, Robot은 판정 완료를 기다리지 않고 다음 Inspection Point로 이동한다.

---

# 4. 세 Test Case의 프로젝트 반영 관계

```text
[TC-01]
Robot Motion Error Measurement
        ↓
Robot 자체 오차가 주요 원인이 아님을 확인
        ↓
Flexible Cable 대응 필요

[TC-02]
Grip Stability Verification
        ↓
Soft Grip / Hard Grip 구조
        ↓
Sequence #4 Adaptive Grip

[TC-03]
Grip-Pull Inspection Verification
        ↓
Force / Displacement 기반 Pull 검사 구조
        ↓
Sequence #5 Pull Inspection
        ↓
Async Inspection Judgment
```

세 Test Case는 각각 독립적인 시험이라기보다 **CCCIS 검사 Sequence를 단계적으로 검증한 과정**으로 연결된다.

1. Robot Motion 정확도를 먼저 확인하여 기구/좌표 오차의 영향을 분리한다.
2. 이후 Grip 안정성을 확인하여 Pull Inspection의 선행조건을 확보한다.
3. 마지막으로 실제 Grip-Pull 시험을 통해 Pull Motion과 측정 데이터 구조를 검증한다.

---

# 5. 후속 검증 항목

현재까지의 시험 결과를 바탕으로 다음 항목을 추가 검증한다.

- Pull Speed 5 mm/s vs 10 mm/s 비교
- Max Distance 25 mm 동작 검증
- Timeout 10 s 동작 검증
- LAN/USB Force Limit 반복시험 및 보정
- `peak_pull_force` 반복성 확인
- `pull_displacement` 반복성 확인
- 필요 시 평균 Force 등 추가 Feature 검토
- Pull 종료 후 Soft Grip Open → `entry_pose` → `ready_pose` 연속 Motion 검증

이 후속 검증은 Sequence #5 Pull Inspection 코드 테스트와 연결하여 수행한다.
