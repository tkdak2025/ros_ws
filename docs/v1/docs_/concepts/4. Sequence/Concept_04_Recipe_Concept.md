# Concept #4 - Recipe Concept

**CCCIS - Contact-based Cable Connection Inspection System**\
**Doosan M0609 + OnRobot RG2 \| No-Vision Phase**

------------------------------------------------------------------------

## 1. 문서 목적

본 문서는 CCCIS 설계 과정에서 정의한 **Recipe의 역할, 데이터 구조, 적용
시점, 변경 정책 및 Validation 원칙**을 정리한 Concept 문서다.

Recipe는 단순한 Robot Pose 저장 파일이 아니라, 제품 및 검사 Point가
달라져도 동일한 공통 검사 알고리즘을 사용할 수 있도록 하는 **Flexible
Inspection의 핵심 설정 계층**이다.

본 문서에서는 Recipe를 다음 두 계층으로 분리한다.

-   **System Recipe**: 제품과 무관하게 시스템 전체에서 공통으로 사용하는
    설정
-   **Inspection Recipe**: 제품 및 검사 Point별로 달라지는 검사 설정

------------------------------------------------------------------------

## 2. Recipe 설계 의도

CCCIS는 검사 Point마다 별도의 Robot 프로그램이나 전용 Sequence를 다시
작성하는 방식을 지양한다.

> **검사 Point의 위치, 진입 방향, 활성 여부 등 최소한의 Recipe 정보를
> 제공하면 공통 검사 Sequence가 해당 정보에 맞춰 동작하도록 설계한다.**

이를 통해 다음을 목표로 한다.

-   제품 또는 검사 Point가 변경되어도 공통 검사 알고리즘을 유지한다.
-   Robot Motion Logic과 제품별 설정값을 분리한다.
-   HMI에서 검사 Point의 사용 여부와 검사 순서를 관리할 수 있도록 한다.
-   Recipe 변경이 실행 중인 Robot 동작에 즉시 반영되어 Sequence 일관성을
    깨뜨리는 것을 방지한다.
-   작업 시작 전에 정적으로 검증 가능한 오류를 최대한 차단한다.

------------------------------------------------------------------------

## 3. Recipe와 Flexible Inspection의 관계

``` text
Flexible Inspection
├─ Recipe-based Position
├─ 3D Entry Direction
├─ Common Inspection Sequence
└─ Adaptive Grip
```

Recipe는 Flexible Inspection에서 **어디에서, 어떤 방향으로, 어떤 Point를
검사할 것인지**를 제공한다.

반면 Adaptive Grip은 Recipe가 지정한 명목 위치에 도달한 이후 실제
Cable의 국부 위치·형상 편차를 흡수하는 하위 기능이다.

따라서 다음 두 개념을 구분한다.

  구분            역할
  --------------- ---------------------------------------------------------
  Recipe          검사 Point의 명목 위치·방향·사용 여부 등 작업 조건 정의
  Adaptive Grip   실제 Cable과의 물리적 상호작용을 통해 국부 편차 대응

Recipe가 모든 실제 Cable 위치를 정확하게 표현해야 하는 것은 아니다.

------------------------------------------------------------------------

## 4. Recipe 계층 구조

``` text
CCCIS Recipe
│
├─ System Recipe
│   ├─ home_pose
│   ├─ work_Access_safe_pose
│   ├─ max_escape_distance_mm
│   ├─ reject_place_pose
│   ├─ work_area_boundary
│   ├─ limit_boundary
│   └─ hmi_comm_timeout
│
└─ Inspection Recipe
    └─ Inspection Point[]
        ├─ point_id
        ├─ point_name
        ├─ enabled
        ├─ ready_pose
        ├─ entry_pose
        ├─ entry_direction
        │   ├─ frame
        │   └─ vector [dx, dy, dz]
        └─ max_entry_depth_mm
```

------------------------------------------------------------------------

## 5. System Recipe Concept

System Recipe는 특정 제품의 개별 검사 Point가 아니라 **CCCIS 시스템
전체에서 공통으로 사용하는 설정값**을 관리한다.

  --------------------------------------------------------------------------
  항목                       역할                    현재 상태
  -------------------------- ----------------------- -----------------------
  `home_pose`                Robot의 기준 안전 원점  정의됨

  `work_Access_safe_pose`    검사 작업영역의 안전    정의됨
                             진입/이탈 공통 경유     
                             Pose                    

  `max_escape_distance_mm`   Safe Escape에서         30.0 mm
                             허용하는 최대 이탈거리  

  `reject_place_pose`        향후 분리 Cable 등의    데이터 구조 유지 / 실행
                             Reject/Recovery 위치    보류

  `work_area_boundary`       Cable/Fixture와         개념 정의 / 실제 좌표
                             상호작용 가능성이       TBD
                             있다고 판단하는 3D 영역 

  `limit_boundary`           Robot/TCP의 Software    개념 정의 / 상세 TBD
                             Operational Limit       

  `hmi_comm_timeout`         HMI 통신 복구 대기      값 TBD
                             허용시간                
  --------------------------------------------------------------------------

### 5.1 `home_pose`

작업 실행 여부와 독립적인 Robot의 기준 안전 원점이다.

`SYSTEM_READY`가 반드시 `home_pose`를 의미하지는 않으며, START 시에는
Home Return Sequence를 통해 Robot을 `home_pose`로 정규화한 뒤 작업영역에
진입한다.

### 5.2 `work_Access_safe_pose`

검사 작업영역에 진입하거나 이탈할 때 사용하는 공통 안전 경유 Pose다.

``` text
home_pose
   ↓
work_Access_safe_pose
   ↓
Point ready_pose
```

이 Pose는 특정 Point의 `ready_pose`와 역할이 다르다.

### 5.3 `max_escape_distance_mm`

Work Area 내부에서 Safe Escape를 수행할 때 사용할 수 있는 최대
이탈거리다.

현재 기준:

``` text
max_escape_distance_mm = 30.0
```

이는 **항상 30 mm를 이동한다는 의미가 아니라 최대 허용거리**다. 실제
Safe Escape 종료조건은 별도 검증 후 결정한다.

### 5.4 `reject_place_pose`

향후 Cable 회수 또는 Reject Handling을 위한 위치 데이터 슬롯으로
유지한다.

다만 실제 Harness에서는 Connector가 분리되어도 Cable이 다른 부분에 묶여
있거나 연결되어 있을 수 있으므로 **자동 Reject/Recovery Sequence는 현재
구현 범위에서 보류**한다.

### 5.5 `work_area_boundary`

Cable/Fixture와 물리적으로 상호작용하고 있을 가능성이 있다고 판단하기
위한 작업영역이다.

현재 기본 구조는 BASE 좌표계 기준 3D Cuboid다.

``` text
work_area_boundary:
  x_min
  x_max
  y_min
  y_max
  z_min
  z_max
```

1차 구현에서는 현재 TCP 위치를 이용해 Inside/Outside를 판단한다.

이 Boundary는 정밀 Collision Detector가 아니라 **Recovery 및 Safe Escape
판단을 위한 보수적 영역 분류**다.

### 5.6 `limit_boundary`

Robot/TCP가 운전 중 넘어가서는 안 되는 Software Operational Limit다.

`work_area_boundary`와 목적이 다르므로 두 Boundary를 합치지 않는다.

``` text
Work Area Boundary
→ Cable Interaction 가능성 판단

Limit Boundary
→ Robot 운전 허용범위 제한
```

------------------------------------------------------------------------

## 6. Inspection Recipe Concept

Inspection Recipe는 제품 또는 검사 구성에 따라 달라지는 **Point별 검사
데이터**를 관리한다.

기본 구조:

``` text
inspection_points:
  - point_id
  - point_name
  - enabled
  - ready_pose
  - entry_pose
  - entry_direction
      frame
      vector [dx, dy, dz]
  - max_entry_depth_mm
```

각 Point의 데이터는 공통 검사 Sequence가 Point별 전용 Teaching 없이
작업할 수 있도록 필요한 최소 정보를 제공하는 것이 목적이다.

------------------------------------------------------------------------

## 7. Point 식별 정보

### `point_id`

검사 Point를 시스템 내부에서 고유하게 식별하기 위한 값이다.

Result, Log, HMI 상태표시 및 Sequence 진행상태와 연결하는 기준으로
사용한다.

### `point_name`

운영자 및 개발자가 Point의 의미를 쉽게 파악하기 위한 표시명이다.

`point_id`와 역할을 분리하여 시스템 내부 식별값과 HMI 표시명을
독립적으로 관리한다.

------------------------------------------------------------------------

## 8. `enabled` Concept

`enabled`는 해당 Point를 현재 작업에서 실제 검사할 것인지 결정한다.

``` text
enabled = true
→ 검사 수행

enabled = false
→ 현재 작업에서 Skip
```

중요 원칙:

-   `enabled=false`는 검사 실패가 아니다.
-   `enabled=false`는 Cable이 없다는 의미가 아니다.
-   Recipe에는 Point가 존재하지만 현재 제품 또는 검사 조건에서는
    검사하지 않는다는 의미다.
-   Enabled Point가 0개이면 START를 허용하지 않는다.

HMI에서는 각 Point의 Enabled 상태를 확인하고 변경할 수 있도록 한다.

------------------------------------------------------------------------

## 9. Point Pose Concept

각 Inspection Point는 최소 두 개의 Pose를 가진다.

``` text
ready_pose
   ↓
entry_pose
   ↓
Inspection
   ↓
ready_pose
```

### `ready_pose`

특정 검사 Point로 접근하기 위한 안전 기준점이다.

Point Unit은 `ready_pose`에서 시작하고 정상적으로 동일 `ready_pose`에
복귀해야 완료된다.

Point 간 이동 역시 `ready_pose → ready_pose`를 기준으로 한다.

### `entry_pose`

실제 Entry Motion 및 Soft Grip을 시작하는 위치다.

`entry_pose`는 최종 Cable Grip Pose가 아니며 Cable로부터 일정 Offset을
가진 **Adaptive Grip 시작 기준 Pose**다.

------------------------------------------------------------------------

## 10. `entry_direction` Concept

`entry_direction`은 `entry_pose`에서 Cable 방향으로 진입할 **3차원 이동
방향**을 정의한다.

기본 구조:

``` text
entry_direction:
  frame: <coordinate frame>
  vector: [dx, dy, dz]
```

설계 원칙:

-   3D Vector로 표현한다.
-   Coordinate Frame을 반드시 명시한다.
-   Zero Vector는 허용하지 않는다.
-   실제 계산에서는 Vector를 Normalize하여 사용한다.
-   Tool Orientation은 `entry_pose`의 자세 정보가 담당하고,
    `entry_direction`은 Translation 방향을 담당한다.

Pull 방향은 기본적으로 Entry Direction의 반대 방향을 사용한다.

``` text
pull_direction = -normalize(entry_direction)
```

단, 최종 Coordinate Frame 정책은 실제 구현 전 다시 확정한다.

------------------------------------------------------------------------

## 11. `max_entry_depth_mm`

`entry_pose`에서 Entry Direction으로 진행할 수 있는 최대 깊이를
제한한다.

목적:

-   Entry 동작의 무제한 진행 방지
-   Adaptive Grip/Search 과정의 이동범위 제한
-   비정상 상황에서 Robot의 과도한 진입 방지

실제 값은 Point 특성 또는 검사조건에 따라 결정될 수 있으며, 단위시험에서
사용한 값과 실제 운영 Recipe 값을 동일하다고 가정하지 않는다.

------------------------------------------------------------------------

## 12. Recipe와 Point Unit의 관계

Recipe는 Point Unit이 실행되기 위해 필요한 입력값을 제공한다.

``` text
Inspection Recipe
      ↓
Select Enabled Point
      ↓
ready_pose
      ↓
entry_pose
      ↓
entry_direction + max_entry_depth
      ↓
Adaptive Grip
      ↓
Pull Inspection
      ↓
Result
      ↓
ready_pose
```

즉 Recipe가 Sequence 자체를 정의하는 것이 아니라 **공통 Sequence에
필요한 Point별 Parameter를 제공**한다.

------------------------------------------------------------------------

## 13. 검사 Point 순서

기본 검사 순서는 Recipe에 정의된 Point 순서를 따른다.

``` text
P01
 ↓
P02
 ↓
P03
 ↓
...
```

`enabled=false`인 Point는 해당 순서에서 Skip한다.

HMI에서 검사 순서를 변경할 수 있는 기능을 추가하는 방향으로 검토한다.

중요한 점은 순서를 변경하더라도 각 Point의 내부 실행 구조는 변하지
않는다는 것이다.

``` text
Point Unit
ready → entry → inspection → ready
```

따라서 HMI의 순서 변경은 **Point Unit의 실행 순서만 변경**하며 개별
Point Sequence 자체를 수정하지 않는다.

------------------------------------------------------------------------

## 14. Recipe 변경 정책

Recipe 변경사항은 **작업 시작 시점에만 반영**한다.

``` text
SYSTEM_READY
   ↓
Recipe Edit Allowed
   ↓
START
   ↓
Recipe Validation / Apply
   ↓
Recipe Lock
   ↓
RUNNING
```

작업이 시작된 이후에는 현재 Job에 적용된 Recipe를 변경하지 못하도록
Lock한다.

설계 의도:

-   실행 중 Pose 변경 방지
-   Point Enabled 상태의 중간 변경 방지
-   검사 순서의 중간 변경 방지
-   HMI와 Robot이 서로 다른 Recipe 상태를 참조하는 문제 방지
-   검사결과와 실제 수행 Recipe의 추적성 확보

작업 종료 후 다시 Recipe 편집을 허용한다.

------------------------------------------------------------------------

## 15. Runtime Recipe Snapshot Concept

작업 시작 시 Validation을 통과한 Recipe를 현재 Job에서 사용하는 **고정된
Runtime Recipe**로 취급한다.

개념적으로:

``` text
Editable Recipe
     ↓ START
Validation
     ↓
Runtime Recipe Snapshot
     ↓
Recipe Lock
     ↓
Current Job
```

현재 Job 실행 중에는 Runtime Recipe가 변경되지 않는다.

HMI에서 Recipe 편집 데이터가 변경되더라도 다음 작업 START 전까지 현재
실행 Job에는 반영하지 않는 구조가 적절하다.

구체적인 Copy/Version/Database 구현방식은 추후 Software Architecture에서
결정한다.

------------------------------------------------------------------------

## 16. Recipe Validation 원칙

START 시 Work Initialize에서 System Recipe와 Inspection Recipe를
검증한다.

### 정적으로 검증 가능한 항목

-   필수 Field 존재 여부
-   데이터 Type/Format
-   Pose 데이터 유효성
-   Entry Direction 존재 여부
-   Entry Direction Zero Vector 여부
-   Boundary 위반 여부
-   Enabled Point 존재 여부
-   Point ID 중복 여부
-   검사 순서 데이터의 유효성

### 정적 Validation으로 보장할 수 없는 항목

-   실제 Robot Path가 Collision-free인지 여부
-   Cable의 실제 위치
-   실제 Grip 성공 여부
-   Fixture/Cable의 물리적 간섭
-   실제 Robot Reachability의 모든 조건

따라서 Recipe Validation은 **실제 현장 동작 검증을 대체하지 않는다.**

------------------------------------------------------------------------

## 17. Boundary와 Recipe Validation

Recipe Pose에 대한 첫 번째 공간 검증 기준은 Boundary다.

예:

``` text
ready_pose
entry_pose
work_Access_safe_pose
```

등이 정의된 허용 영역을 벗어나는지 정적으로 확인할 수 있다.

다만:

> **Pose가 Boundary 내부에 있다는 사실은 해당 Pose까지의 경로가
> 안전하다는 것을 의미하지 않는다.**

따라서 Boundary Validation과 실제 Motion Validation은 별개의 단계로
관리한다.

------------------------------------------------------------------------

## 18. Commissioning / Trial Mode와 Recipe

향후 Recipe를 실제 Robot에서 검증하기 위한 Trial 기능을 고려한다.

``` text
ready_pose
   ↓
entry_pose
   ↓
No Grip
No Inspection
   ↓
ready_pose
   ↓
Next Point
```

목적:

-   Recipe Pose 확인
-   Point 접근 방향 확인
-   Ready/Entry 위치 확인
-   실제 Robot 접근성 확인
-   Teaching 데이터 검증

현재 Main Work 구현 범위에는 포함하지 않는다.

------------------------------------------------------------------------

## 19. HMI와 Recipe의 관계

HMI는 Recipe의 운영 인터페이스 역할을 담당한다.

현재 필요한 주요 기능 개념:

  -----------------------------------------------------------------------
  기능                                HMI 역할
  ----------------------------------- -----------------------------------
  Recipe 조회                         System/Inspection Recipe 현재 설정
                                      확인

  Point Enabled                       Point별 검사 ON/OFF 설정

  Point 순서                          검사 Point 실행순서 확인 및 향후
                                      변경 지원

  Recipe Validation 결과              START 실패 시 잘못된 Recipe 항목 및
                                      원인 표시

  Recipe Lock 상태                    RUNNING 중 Recipe 변경 불가 상태
                                      표시

  Current Point                       현재 실행 중인 Point 표시
  -----------------------------------------------------------------------

Robot 구동 중 상태 모니터링과 HMI 통신은 별도 Monitor/Communication
계층에서 지속적으로 수행한다.

Recipe가 Lock되어 있다는 것은 **상태 모니터링까지 중단한다는 의미가
아니다.**

------------------------------------------------------------------------

## 20. Recipe와 Result Traceability

검사결과를 해석하려면 어떤 Recipe 조건으로 검사했는지 추적할 수 있어야
한다.

따라서 향후 Result/Log에는 최소한 다음 정보와 연결할 수 있는 구조가
필요하다.

``` text
Job
├─ Product / Recipe Identification
├─ Point ID
├─ Point Name
├─ Executed Order
├─ Enabled State
├─ Inspection Result
└─ Error / Missing Reason
```

Recipe Version 또는 Snapshot ID를 실제 데이터 모델에 포함할지는 Software
Architecture에서 확정한다.

핵심 원칙은 **검사결과와 실제 실행 Recipe를 사후에 연결할 수 있어야
한다는 것**이다.

------------------------------------------------------------------------

## 21. System Recipe와 Inspection Recipe 분리 이유

두 Recipe를 분리하는 이유는 변경 책임과 적용 범위가 다르기 때문이다.

  -----------------------------------------------------------------------
  구분                    System Recipe           Inspection Recipe
  ----------------------- ----------------------- -----------------------
  적용 범위               시스템 전체             제품 / 검사 Point

  대표 데이터             Home, Work Access,      Ready, Entry,
                          Boundary                Direction, Enabled

  변경 빈도               상대적으로 낮음         제품/검사 구성에 따라
                                                  높음

  목적                    시스템 운전 기준 정의   실제 검사 조건 정의

  검사 Point 종속성       없음                    있음
  -----------------------------------------------------------------------

이 구조를 통해 제품 변경 시 System 공통 설정까지 함께 수정하는 것을
방지한다.

------------------------------------------------------------------------

## 22. 현재 확정사항

-   Recipe를 `System Recipe`와 `Inspection Recipe`로 분리한다.
-   `home_pose`와 `work_Access_safe_pose`는 서로 다른 역할을 가진다.
-   Inspection Point는 `ready_pose`, `entry_pose`, `entry_direction`,
    `max_entry_depth_mm`를 가진다.
-   `enabled`로 Point별 검사 여부를 제어한다.
-   Enabled Point가 0개이면 START를 허용하지 않는다.
-   기본 Point 실행순서는 Recipe 순서를 따른다.
-   HMI에서 Point 순서 변경 기능을 추가하는 방향으로 설계한다.
-   Recipe 변경은 작업 시작 전에만 반영하고 RUNNING 중에는 Lock한다.
-   START 시 Recipe Validation을 수행한다.
-   Boundary Validation은 실제 Collision-free Path를 보장하지 않는다.
-   Recipe는 Point별 전용 Sequence가 아니라 공통 Sequence의 Parameter를
    제공한다.
-   `reject_place_pose`는 데이터 구조에 유지하지만 실제 Reject
    Handling은 현재 보류한다.

------------------------------------------------------------------------

## 23. TBD / 추가 검토사항

-   `entry_direction.frame`의 최종 Coordinate Frame 정책
-   실제 Recipe 파일/DB Schema
-   Pose 데이터 표현 형식
-   HMI Recipe 편집 권한 및 저장 절차
-   Point 순서 변경 UI 및 데이터 구조
-   Recipe Version / Revision 관리방식
-   Runtime Recipe Snapshot 구현방식
-   Work Area Boundary 실제 좌표
-   Boundary Margin / Hysteresis
-   Limit Boundary 상세 정의
-   `hmi_comm_timeout` 값
-   `max_entry_depth_mm`의 제품/Point별 관리 정책
-   Commissioning / Trial Mode 구현
-   Recipe 변경 이력 및 Audit Log 필요 범위

------------------------------------------------------------------------

## 24. 다른 Concept 문서와의 관계

``` text
Concept #1 - 검사결과 Concept
   └─ Recipe 기반 검사 결과의 상태 정의

Concept #2 - 검사시퀀스 Concept
   └─ Recipe를 사용하는 공통 작업 Sequence 정의

Concept #3 - Adaptive Grip Concept
   └─ Recipe의 Entry 정보 이후 실제 Cable 편차 대응

Concept #4 - Recipe Concept
   └─ System / Inspection Recipe의 역할과 데이터 정책 정의
```

Recipe Concept은 검사시퀀스와 독립된 Robot 동작을 정의하는 문서가
아니라, **검사시퀀스가 참조하는 설정 데이터의 의미와 운영 원칙을
정의하는 문서**다.
