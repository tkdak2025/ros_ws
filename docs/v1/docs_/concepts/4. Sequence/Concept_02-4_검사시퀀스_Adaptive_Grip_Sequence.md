# Concept #2-4 검사시퀀스 - Adaptive Grip Sequence

**CCCIS | Contact-based Cable Connection Inspection System**  
**Doosan M0609 + OnRobot RG2 | No-Vision Phase**

---

## 1. 목적

Adaptive Grip Sequence는 각 Inspection Point의 `entry_pose`에서 시작하여, Recipe에 정의된 Soft Grip 상태로 Cable 진입 동작을 수행한 후 Hard Grip 상태로 전환하여 **Pull Inspection을 시작할 수 있는 파지 상태를 형성하는 것**을 목적으로 한다.

본 Sequence는 Cable 체결 정상/불량을 직접 판정하지 않는다. 체결 상태 검사는 이후 `Pull Inspection` 및 `Inspection Judgment`에서 수행한다.

---

## 2. 설계 의도

CCCIS는 Vision을 사용하지 않는 조건에서 Cable의 국부적인 위치·형상 편차를 물리적 상호작용으로 흡수해야 한다. Adaptive Grip은 이를 위해 다음 원칙으로 설계한다.

- `entry_pose` 이후 Cable 체결방향축과 나란한 `entry_direction`으로 진입한다.
- Entry 중에는 Recipe에 정의된 **Soft Grip** 상태를 사용한다.
- Soft Grip 단계에서 별도의 Grip 성공/실패 판정을 수행하지 않는다.
- Entry Motion의 실제 이동거리가 Recipe의 목표 거리보다 작더라도 이를 Grip 실패로 판정하지 않는다.
- Entry 위치 오차를 이용하여 Grip 성공/실패를 판단하지 않는다.
- Entry Motion 종료 후 별도의 Settling 동작 없이 즉시 **Hard Grip**으로 전환한다.
- Hard Grip은 Recipe에 정의된 Width/Force 값으로 수행하며, Cable 파지 성공 여부를 추론하지 않고 **Gripper 명령의 정상 수행 여부만 확인**한다.
- Cable Snag/걸림 판정은 본 Sequence의 현재 설계 범위에서 제외한다.
- `entry_pose` 접근 중 Tip Contact와 Periodic Motion 처리 가능성은 별도 단위시험 항목으로 관리하며, 본 기본 Sequence의 정상 Flow에는 포함하지 않는다.

---

## 3. 진입 조건

Adaptive Grip Sequence는 다음 조건을 만족한 상태에서 시작한다.

- Point Transition Sequence가 정상 완료되었을 것.
- Robot TCP가 현재 Inspection Point의 `entry_pose`에 위치할 것.
- 현재 Point의 Inspection Recipe가 유효할 것.
- Recipe에 `entry_direction`, `entry_depth_mm`, Soft Grip 설정값, Hard Grip 설정값이 정의되어 있을 것.
- `entry_depth_mm`는 시스템 최대 허용 진입거리인 **25 mm 이하**일 것.
- Robot / Controller / Safety / Tool 상태가 Motion 및 Grip 명령을 수행할 수 있는 상태일 것.

---

## 4. Sequence Flow

```text
ADAPTIVE_GRIP START
        |
        v
Current Point Recipe Load
        |
        v
Soft Grip Command
- Width = Recipe
- Force = Recipe
        |
        v
Soft Grip Operation Check
        |
        v
Entry movel
- Direction    = entry_direction
- Distance     = Recipe entry_depth_mm
- Max Distance = 25 mm
        |
        +-------------------------------+
        | Entry Motion Guard            |
        | - Timeout     : 10 s           |
        | - Force Limit : 5 N (검증값)  |
        +-------------------------------+
        |
        v
Entry Motion End / Stop
        |
        v
Hard Grip Command
- Width = Recipe
- Force = Recipe
        |
        v
Hard Grip Operation Check
        |
   +----+----+
   |         |
 NORMAL    TOOL ERROR
   |         |
   v         v
ADAPTIVE   Error Handling
GRIP DONE
   |
   v
Pull Inspection
```

---

## 5. Flow 용어 설명

| 용어 | 설명 |
|---|---|
| `entry_pose` | Point Transition이 완료되는 Pose이자 Adaptive Grip이 시작되는 Point별 기준 Pose. Cable-Connector 경계를 기준으로 설정한다. |
| Soft Grip | Cable 진입 과정에서 사용하는 Recipe 기반 저강도/가이드 파지 상태. 성공/실패를 별도로 판정하지 않는다. |
| Entry Motion | Soft Grip 상태에서 `entry_direction` 방향으로 수행하는 `movel` 진입 동작. |
| `entry_depth_mm` | Point별 Recipe에 정의되는 Entry 이동거리. 시스템 허용 최대값은 25 mm이다. |
| Entry Motion Guard | Entry Motion이 과도하게 지속되거나 과도한 힘을 발생시키지 않도록 제한하는 보호 조건. |
| Entry Timeout | Entry Motion의 최대 수행 대기시간. 현재 10 s로 정의한다. |
| Entry Force Limit | Entry 중 더 이상 밀지 않기 위한 Force Guard. 현재 5 N을 후보값으로 사용하며 단위시험으로 검증한다. |
| Hard Grip | Pull Inspection 직전에 적용하는 최종 파지 상태. Width/Force는 Recipe 값을 사용한다. |
| Grip Operation Check | 지정된 Grip 명령이 Gripper에 정상적으로 전달되어 실제 동작했는지 확인하는 처리. Cable 파지 성공 여부를 판정하는 기능이 아니다. |
| `ADAPTIVE_GRIP_DONE` | Hard Grip 명령의 정상 동작 확인이 완료되어 Pull Inspection으로 전환할 수 있는 상태. |
| `MISSING` | 정상적인 검사 절차를 수행했으나 유효한 PASS/FAIL 검사결과를 만들 수 없는 경우의 Inspection Result. Adaptive Grip에서 직접 판정하지 않고 이후 검사/판정 단계에서 결정한다. |

---

## 6. 세부 동작 및 판단 조건

### 6.1 Recipe 적용

Adaptive Grip은 현재 Inspection Point의 Recipe에 정의된 값을 사용한다.

```yaml
grip_setting:
  soft:
    open_width_mm: <Recipe>
    close_width_mm: <Recipe>
    force_n: <Recipe>

  hard:
    close_width_mm: <Recipe>
    force_n: <Recipe>
```

Entry 관련 값은 다음과 같이 사용한다.

```yaml
entry_direction: [dx, dy, dz]
entry_depth_mm: <= 25.0
```

공통 Guard 기준:

```yaml
entry_timeout_sec: 10.0
entry_force_limit_n: 5.0   # 검증 필요
```

### 6.2 Soft Grip

- `entry_pose`에서 Recipe의 Soft Grip Width/Force 설정으로 Gripper를 동작시킨다.
- Soft Grip 명령이 Tool Error 없이 수행 가능한 상태인지 확인한다.
- Soft Grip 자체에 대해 Cable 파지 성공/실패 판정을 수행하지 않는다.
- Soft Grip Width 도달 오차를 Cable 파지 성공/실패 기준으로 사용하지 않는다.

### 6.3 Entry Motion

- Soft Grip 상태에서 `movel`을 사용한다.
- 이동방향은 Recipe의 `entry_direction`을 사용한다.
- 이동거리는 Point별 `entry_depth_mm`를 사용하며 시스템 최대 허용값은 25 mm이다.
- Entry Motion의 최대 대기시간은 10 s이다.
- Entry 중 Force가 5 N Limit에 도달하면 추가 진입을 제한하기 위한 Guard로 Motion을 정지한다.
- 5 N은 Grip 성공/실패 또는 제품 품질 판정 Threshold가 아니다.
- Entry Motion이 Recipe 거리보다 작게 수행되었다는 이유만으로 Grip 실패로 판정하지 않는다.
- Cable Snag/걸림 여부는 판단하지 않는다.

### 6.4 Entry Motion 종료 후 처리

Entry Motion이 종료 또는 Guard에 의해 정지하면 별도의 위치 오차 판정이나 Soft Grip 성공 판정 없이 Hard Grip 단계로 전환한다.

Entry Motion 종료 사유는 Logging 대상으로 유지한다.

- `ENTRY_DISTANCE_REACHED`
- `ENTRY_FORCE_LIMIT`
- `ENTRY_TIMEOUT`

각 종료 사유는 **Grip 성공/실패 판정값이 아니라 Sequence 실행 이력**으로 취급한다.

### 6.5 Hard Grip

- Entry Motion 종료 후 별도의 Settling Time 없이 즉시 Hard Grip 명령을 수행한다.
- Hard Grip Width/Force는 현재 Point Recipe 값을 사용한다.
- Hard Grip에서는 Cable을 정상적으로 잡았는지 별도 센서 추론을 수행하지 않는다.
- 필요한 확인은 **Recipe 기반 Gripper 명령이 정상적으로 수행되었는지 여부**이다.
- Gripper 명령/Tool 자체의 동작 이상이 확인되면 System Error 계열의 Tool Error로 처리한다.

### 6.6 MISSING Result와의 관계

Adaptive Grip 및 이후 Pull Inspection 명령이 시스템적으로 정상 수행되었더라도, 실제로 유효한 검사 데이터를 확보하지 못해 정상/불량 판정이 성립하지 않을 수 있다.

이 경우 System Error로 처리하지 않고 Inspection Result를 `MISSING`으로 기록한다.

```text
정상 명령 수행
   ↓
Adaptive Grip
   ↓
Pull Inspection
   ↓
유효한 PASS / FAIL 판정 가능?
   ├─ YES → PASS / FAIL 계열
   └─ NO  → MISSING
```

즉 다음을 구분한다.

| 상황 | 처리 |
|---|---|
| RG2 명령 자체 실패 / Tool 동작 이상 | Tool Error / System Error |
| Robot Motion 자체 오류 | Motion Error / System Error |
| 정상 절차를 수행했으나 유효한 검사 결과 확보 불가 | `MISSING` |
| 유효한 Pull Inspection 완료 | Inspection Judgment에서 PASS / FAIL 계열 판정 |

---

## 7. 정상 종료 조건

다음 조건을 만족하면 Adaptive Grip Sequence를 정상 완료한다.

- Soft Grip 명령이 정상 수행되었을 것.
- Entry Motion이 정의된 Guard 범위 내에서 종료되었을 것.
- Hard Grip 명령이 현재 Point Recipe 값으로 수행되었을 것.
- Hard Grip Gripper 동작이 정상적으로 확인되었을 것.
- Robot / Controller / Tool Error가 발생하지 않았을 것.

정상 종료 시 `ADAPTIVE_GRIP_DONE` 상태를 반환하고 `Pull Inspection`으로 전환한다.

Cable 파지 자체의 품질이나 Connector 체결 상태는 Adaptive Grip 정상 종료 조건에 포함하지 않는다.

---

## 8. 비정상 / 예외 처리

| 상황 | 처리 |
|---|---|
| Recipe 누락 또는 잘못된 Grip 설정 | Recipe Error로 처리하고 Adaptive Grip 시작 금지 |
| `entry_depth_mm > 25 mm` | Recipe Validation Error로 처리 |
| Soft Grip 명령 수행 불가 | Tool Error로 현재 작업 Error 처리 |
| Entry `movel` 자체의 Robot/Controller 오류 | Motion Error로 현재 작업 Error 처리 |
| Entry Force Limit 도달 | 실패로 판정하지 않고 Entry Motion 정지 후 Hard Grip 진행 |
| Entry Timeout 10 s 도달 | Grip 성공/실패로 판정하지 않고 Entry Motion 종료 이력으로 기록 후 Hard Grip 진행 |
| Hard Grip 명령 수행 불가 / Tool 동작 이상 | Tool Error로 현재 작업 Error 처리 |
| 정상 절차 수행 후 유효 검사결과 생성 불가 | 이후 Inspection Judgment에서 `MISSING` 처리 |
| Cable Snag/걸림 | 현재 기본 Sequence 판단 범위에서 제외 |
| E-STOP / Safety Fault | Adaptive Grip 로직보다 Safety 처리 우선 |

PAUSE / HMI Communication Lost / STOP은 Concept #2의 공통 상태처리 정책을 따른다.

---

## 9. 상위·하위 Sequence Interface

| 구분 | 대상 | Interface |
|---|---|---|
| 상위 | Point Transition | `entry_pose` 도달 및 Adaptive Grip 시작 가능 상태 전달 |
| 현재 | Adaptive Grip | Soft Grip → Entry Motion → Hard Grip 수행 |
| 하위 | Pull Inspection | `ADAPTIVE_GRIP_DONE` 후 Pull Inspection 시작 |
| 하위 | Inspection Judgment | Pull Inspection 결과를 이용해 PASS / FAIL / `MISSING` 결정 |
| 공통 | Robot Status / Tool Status Monitor | Motion 및 Gripper 동작 가능 상태, Error 상태 확인 |
| 공통 | Pause / Resume | 공통 Sequence 정책 적용 |
| 공통 | HMI Communication Recovery | 통신 단절 시 공통 Safe Pause/Recovery 정책 적용 |

주요 Sequence 연결관계:

```text
Point Transition
   ↓
entry_pose
   ↓
Adaptive Grip
   ↓ ADAPTIVE_GRIP_DONE
Pull Inspection
   ↓
Inspection Judgment
   ↓
PASS / FAIL_* / MISSING
```

---

## 10. TBD / 검증 필요사항

다음 항목은 Sequence 구조를 변경하기 위한 미결정 사항이 아니라 **실장 및 단위시험을 통해 검증할 Parameter/동작 특성**이다.

- Entry Force Limit **5 N**의 적정성 검증
- RG2 Soft Grip Recipe Width/Force 명령에 대한 실제 동작 특성 확인
- RG2 Hard Grip Recipe Width/Force 명령에 대한 실제 동작 특성 확인
- 코드에서 Soft/Hard Grip 명령의 정상 동작 완료를 확인할 수 있는 상태값/방법 확정
- Entry 최대거리 25 mm와 실제 Point별 `entry_depth_mm` 설정 검증
- Entry Timeout 10 s가 실제 Entry Speed 및 최대거리 조건에서 충분한지 검증
- `ENTRY_DISTANCE_REACHED`, `ENTRY_FORCE_LIMIT`, `ENTRY_TIMEOUT` Logging 구현
- `entry_pose` 접근 중 Tip Contact 감지 시 Periodic Motion을 이용한 처리 가능성 단위시험
- Periodic Motion 관련 축, Amplitude, Period, 반복 조건은 시험 결과 후 결정

---

## 문서 관계

본 문서는 **Concept #2 - 검사시퀀스 Concept**의 하위 상세 Sequence 문서이다.

```text
Concept #2 - 검사시퀀스 Concept
   ↓
Concept #2-4 검사시퀀스 - Adaptive Grip Sequence   ← 본 문서
   ↕
Concept #3 - Adaptive Grip Concept
   ↓
작업검증 결과 / Parameter Validation
```

Concept #3에서 정의한 Adaptive Grip의 설계 개념과 실제 작업검증 결과를 본 Sequence의 구현 Parameter에 반영한다.
