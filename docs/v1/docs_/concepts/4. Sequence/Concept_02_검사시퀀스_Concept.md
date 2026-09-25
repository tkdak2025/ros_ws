# Concept #2 - 검사시퀀스 Concept

**CCCIS - Contact-based Cable Connection Inspection System**\
**Doosan M0609 + OnRobot RG2 \| No-Vision Phase**

------------------------------------------------------------------------

## 1. 문서 목적

본 문서는 CCCIS 검사시퀀스를 검토하면서 합의한 설계 원칙과 판단 기준을
정리한 Concept 문서다.

개별 Sequence의 세부 구현 절차를 모두 기술하는 상세설계서가 아니라, 각
Sequence를 왜 분리하고 어떤 기준으로 연결하며 정상·일시정지·중단·복귀
상황을 어떤 원칙으로 처리할 것인지에 대한 공통 설계 기준을 정의한다.

------------------------------------------------------------------------

## 2. 검사시퀀스 설계 목표

-   검사 Point마다 전용 Robot 동작을 새로 Teaching하지 않고 Recipe 기반
    공통 검사 로직을 사용한다.
-   각 Inspection Point를 독립적인 닫힌 작업 단위로 구성하여
    이동·검사·복귀 기준을 명확하게 한다.
-   Robot Motion 전에 현재 상태를 반복적으로 재확인하여 과거의 정상
    상태를 그대로 신뢰하지 않는다.
-   비전이 없는 환경에서 Cable의 국부 위치·형상 불확실성을 인정하고
    Adaptive Grip과 Safe Escape로 대응한다.
-   Pause와 Stop/Error를 명확히 분리하여 Runtime Context 보존 여부를
    일관되게 관리한다.
-   검사결과와 시스템/로봇 오류를 분리하여 HMI와 Log에서 원인을 명확히
    식별한다.

------------------------------------------------------------------------

## 3. Flexible Inspection 설계 개념

Flexible Inspection은 단순히 Entry 이후의 위치 오차를 흡수하는 기능이
아니다.

> **검사 Point의 위치·방향 등 최소한의 Recipe 정보만 주면, Point마다
> 전용 동작 Sequence를 다시 Teaching하지 않아도 공통 검사 알고리즘이
> 해당 정보에 맞춰 작업하는 구조**

``` text
Flexible Inspection
├─ Recipe-based Position
├─ 3D Entry Direction
├─ Common Inspection Sequence
└─ Adaptive Grip
```

Adaptive Grip은 Flexible Inspection 전체를 의미하지 않으며, 실제 Cable의
국부 편차를 처리하기 위한 하위 기능이다.

------------------------------------------------------------------------

## 4. Pose 계층 및 역할

``` text
home_pose
   ↓
work_Access_safe_pose
   ↓
Point ready_pose
   ↓
Point entry_pose
```

  -----------------------------------------------------------------------
  Pose                                설계 역할
  ----------------------------------- -----------------------------------
  `home_pose`                         작업 수행 여부와 독립적으로
                                      정의되는 Robot의 기준 안전 원점

  `work_Access_safe_pose`             검사 작업영역으로 안전하게
                                      진입하거나 이탈하기 위한 공통 경유
                                      Pose

  `ready_pose`                        특정 Inspection Point의 시작점이자
                                      정상 종료 후 복귀점

  `entry_pose`                        실제 Cable Interaction 및
                                      Entry/Soft Grip을 시작하기 직전의
                                      Point별 Pose
  -----------------------------------------------------------------------

------------------------------------------------------------------------

## 5. Point Unit 설계 원칙

각 검사 Point는 `ready_pose`에서 시작하여 검사 후 동일 `ready_pose`로
복귀해야 하나의 Point 작업이 완료된 것으로 본다.

``` text
Point N

ready_pose
   ↓
entry_pose
   ↓
Inspection Operations
   ↓
Result
   ↓
ready_pose
   ↓
Point N Complete
```

핵심 원칙:

-   Point N의 `entry_pose`에서 Point N+1의 `ready_pose`로 직접 이동하지
    않는다.
-   Point 간 전환은 `ready_pose`를 기준으로 수행한다.
-   이 구조는 Point별 책임 범위를 분리하고 Pause/Resume 및 Recovery
    기준점을 단순화한다.

------------------------------------------------------------------------

## 6. 전체 Sequence Architecture

  --------------------------------------------------------------------------
  구성                    역할                       현재 설계 상태
  ----------------------- -------------------------- -----------------------
  Main Work               START부터 작업 완료까지    설계됨
                          전체 Sequence 호출 및 상태 
                          관리                       

  Work Initialize         Robot/HMI/Recipe/Enabled   설계됨
                          Point의 시작 조건 재검증   

  Home Return             현재 위치에서 안전하게     설계됨
                          `home_pose`로 복귀         

  Point Transition        다음 검사 Point의          상세설계 예정
                          `ready_pose`까지 안전 이동 

  Adaptive Grip           Cable의 국부 위치·형상     Concept 존재 / 상세화
                          편차를 흡수하며 파지       필요

  Pull Inspection         Grip 후 Pull Test 수행 및  기본 시험 구조 존재
                          검사 데이터 취득           

  Inspection Judgment     Point 검사결과 판정        결과 체계 정의 / 판정
                                                     기준 TBD

  Work Finish             마지막 Point 이후 작업     상세설계 예정
                          완료 처리                  

  Pause / Resume          Context를 유지한 안전      기본 정책 설계됨
                          일시정지 및 명시적 재개    

  HMI Communication       통신 단절 시 Safe Pause,   기본 정책 설계됨
  Recovery                복구 대기, Timeout 처리    

  Stop / Error Handling   작업 종료 및 오류 원인     상세설계 필요
                          관리                       

  Safe Escape             Work Area 내부에서 Cable   Home Return 내부 기능
                          Interaction 가능성을       
                          고려한 안전 이탈           
  --------------------------------------------------------------------------

------------------------------------------------------------------------

## 7. START 및 Work Initialize 설계 원칙

START는 `SYSTEM_READY` 상태에서만 허용한다.

`SYSTEM_READY`는 새로운 작업을 받을 수 있는 정지 대기 상태이며, Robot이
반드시 `home_pose`에 있다는 의미는 아니다.

``` text
SYSTEM_READY
   ↓ HMI START
START Validation
   ↓
Work Initialize
   ↓
Robot Operability Re-Check
   ↓
Home Return
   ↓
home_pose
   ↓
work_Access_safe_pose
   ↓
Inspection
```

Work Initialize의 핵심 의도는 이전 시점의 정상 상태를 신뢰하지 않고 실제
Motion 직전에 현재 Controller, Robot, Safety, Tool, HMI 및 Recipe 상태를
다시 취득하는 것이다.

**중요한 Motion 전의 반복 Check는 중복이 아니라 의도적인 방어적
설계다.**

  -----------------------------------------------------------------------
  검증 항목                           개념
  ----------------------------------- -----------------------------------
  Robot Operability                   Controller 통신, Robot 운전 가능
                                      상태, Servo/Motor, Safety/E-Stop,
                                      Blocking Fault, Joint/TCP 상태, RG2
                                      및 Tool/TCP 설정 등을 종합 확인

  HMI Communication                   작업 시작에 필요한 명령·상태 통신이
                                      정상인지 확인

  System Recipe                       Home, Work Access, Boundary 등 공통
                                      설정의 정적 유효성 확인

  Inspection Recipe                   Point별 필수 데이터, Entry
                                      Direction 등 정적 유효성 확인

  Enabled Point                       `enabled=true` Point가 최소 1개
                                      존재하는지 확인
  -----------------------------------------------------------------------

Initialize는 Fault를 임의로 자동 해제하는 기능이 아니라 이상을 검출하고
시작을 차단하며 원인을 HMI에 전달하는 기능으로 정의한다.

------------------------------------------------------------------------

## 8. Home Return 및 Safe Escape 설계 원칙

Home Return은 단순한 `movej(home_pose)`가 아니라 호출 시점의 Robot
위치와 Cable Interaction 가능성을 고려한 공통 안전복귀 Sequence다.

START 중에도 호출되므로 Home Return 자체가 `SYSTEM_READY` 상태를
강제하지 않고 `SUCCESS / FAIL`을 호출자에게 반환하는 **Context-neutral
Sequence**로 설계한다.

``` text
HOME_RETURN REQUEST
       ↓
Robot Operability Check
       ↓
Current TCP / Work Area Check
       ↓
   Inside Work Area?
     ├─ YES
     │    ↓
     │ Grip Relaxation
     │    ↓
     │ Safe Escape
     │    ↓
     │ work_Access_safe_pose
     │
     └─ NO
          ↓
       Safe Home Route
          ↓
       home_pose
          ↓
     SUCCESS / FAIL
```

비전이 없기 때문에 Work Area 내부에서는 Cable을 잡고 있는지, 접촉
중인지, 걸려 있는지를 신뢰성 있게 판단할 수 없다.

따라서 **Work Area 내부라면 Cable Interaction 가능성을 보수적으로
가정하고 Safe Escape를 기본 수행한다.**

-   Safe Escape는 Grip 상태를 완화한 뒤 Tool 접근축의 역방향으로
    이탈하는 개념을 기본으로 한다.
-   System Recipe의 `max_escape_distance_mm = 30.0`은 최대 허용거리이며
    항상 30 mm를 강제 이동한다는 의미가 아니다.
-   Safe Escape의 실제 종료조건과 Grip Relaxation 값은 검증을 통해
    확정한다.

------------------------------------------------------------------------

## 9. Work Area Boundary와 Limit Boundary

  -----------------------------------------------------------------------
  구분                    목적                    현재 개념
  ----------------------- ----------------------- -----------------------
  Work Area Boundary      Cable/Fixture와         BASE 기준 3D Cuboid,
                          물리적으로 상호작용     1차 구현은 TCP 위치로
                          중일 가능성이 있는      Inside/Outside 판단
                          영역을 분류             

  Limit Boundary          Robot/TCP가 운전 중     Work Area와 별도 개념,
                          넘어가서는 안 되는      상세 형상/범위 TBD
                          Software Operational    
                          Limit                   
  -----------------------------------------------------------------------

Work Area Boundary는 정밀 Collision Detector가 아니다.

TCP가 영역 내부에 있는 경우 Recovery 관점에서 Cable Interaction 가능성이
있다고 보수적으로 분류하기 위한 상태 판단 기준이다. TCP Point-in-Box
판정만으로 Robot 전체 Link나 RG2의 충돌 여부를 보장하지 않는다.

------------------------------------------------------------------------

## 10. Known Environment와 Cable Uncertainty

CCCIS의 대상 환경은 무작위 Cable 더미가 아니라 **전장 조립이 완료된 최종
점검 공정**이다.

-   Fixture, Table 등 고정 환경은 사전에 알고 있다.
-   Cable도 일정 수준 정리되어 있다고 가정한다.
-   그러나 실제 Cable의 국부 형상과 위치는 비전 없이 완전히 알 수 없다.
-   따라서 Cable 접촉 자체를 즉시 Collision Error로 간주하지 않는다.

``` text
Known Fixed Environment
   ↓
Boundary / Prevalidated Safe Pose & Path
   ↓
Future Model-based Collision Check / Planning

Unknown Local Cable Variation
   ├─ Entry Side    → Adaptive Grip
   └─ Recovery Side → Safe Escape
```

------------------------------------------------------------------------

## 11. Pause / Resume 및 Runtime Context

PAUSE는 작업 종료가 아니라 임시 정지이므로 현재 Job Runtime Context를
보존한다.

반대로 `STOP`, `ERROR`, 정상 `COMPLETE`, 새로운 `START`에서는 이전
Runtime Context를 유지하지 않는다.

``` text
RUNNING
   ↓ PAUSE
PAUSE_REQUEST
   ↓
Safe Pause
   ↓
PAUSED
   ↓ RESUME
Resume Point
   ↓
RUNNING
```

-   Pause 요청 순간의 정확한 millimeter/time 위치에서 그대로 재개하는
    것을 기본 요구사항으로 하지 않는다.
-   각 하위 Sequence는 `Pause Safe Point`와 `Resume Point`를 정의해야
    한다.
-   E-STOP은 Pause보다 우선하는 즉시 Safety 정지이며 별도 Recovery
    정책을 따른다.

------------------------------------------------------------------------

## 12. HMI Communication Loss 처리

작업 중 HMI 통신 단절은 Critical 조건으로 취급하되 즉시 일반 Error
종료하기 전에 Pause Safe 메커니즘을 사용한다.

``` text
RUNNING
   ↓
HMI COMM LOST
   ↓
Pause Safe
   ↓
PAUSED / COMM_LOST
   ↓
Communication Recovery Wait
   ├─ RECOVERED
   │    ↓
   │ Remain PAUSED
   │    ↓
   │ HMI State / Context Restored
   │    ↓
   │ User RESUME
   │    ↓
   │ RUNNING
   │
   └─ TIMEOUT
        ↓
     COMM_ERROR
        ↓
     Job Termination
```

통신이 복구되더라도 자동 Resume하지 않는다.

복구된 HMI에서 현재 상태와 Context를 다시 확인한 뒤 사용자가 명시적으로
`RESUME`해야 한다.

Heartbeat 주기와 Communication Timeout 값은 TBD다.

------------------------------------------------------------------------

## 13. STOP / ERROR / E-STOP 정책

  -----------------------------------------------------------------------
  상황              작업 Context      Home Return       핵심 정책
  ----------------- ----------------- ----------------- -----------------
  PAUSE             보존              수행 안 함        Resume 가능한
                                                        임시 정지

  STOP              폐기              자동 수행 안 함   작업 종료 후
                                                        사용자가 HMI에서
                                                        Home Return 요청

  ERROR             폐기              자동 수행 안 함   오류 원인 HMI
                                                        전달 후 작업 종료

  E-STOP            작업 중단         Safety 복구 후    즉시 정지가
                                      별도 판단         최우선이며 일반
                                                        Pause Safe를
                                                        기다리지 않음
  -----------------------------------------------------------------------

------------------------------------------------------------------------

## 14. Inspection Result와 System Error 분리

### Inspection Result

-   `PASS`: 유효한 검사가 완료되고 체결 유지 조건을 만족
-   `FAIL_DISPLACEMENT`: 유효한 검사에서 허용 변위 초과
-   `FAIL_DETACHED`: Cable/Connector의 완전 이탈 확인
-   `MISSING`: 검사를 시도했으나 Grip 등으로 유효한 검사를 완료하지 못함

`MISSING`은 제품 불량이나 Cable 부재를 의미하지 않는다.

### System Error

예:

-   Motion Error
-   Tool Error
-   Safety Error
-   Controller Error
-   HMI Communication Error

`MISSING`을 System Error에 포함시키지 않는다.

MISSING은 Point 검사 결과 계열이며, 시스템은 다음 Point를 계속 수행할 수
있는 상태를 전제로 한다.

------------------------------------------------------------------------

## 15. Recipe 및 정적 Validation 원칙

Recipe Validation에서는 다음처럼 정적으로 판단 가능한 항목을 사전에
검출한다.

-   필수 Field 누락
-   데이터 형식 오류
-   Zero Entry Direction
-   Boundary 위반
-   Enabled Point 존재 여부

그러나 Recipe Pose가 Boundary 내부에 있다는 사실만으로 실제 Robot Path가
Collision-free이거나 물리적으로 완전히 유효하다고 증명할 수는 없다.

향후 **Commissioning / Trial Mode**에서는 실제 Grip 없이 다음과 같이
Point 접근성을 실기 검증하는 기능을 고려한다.

``` text
ready_pose
   ↓
entry_pose
   ↓
No Grip / No Inspection
   ↓
ready_pose
   ↓
Next Point
```

현재 Main Work 구현 범위에는 포함하지 않는다.

------------------------------------------------------------------------

## 16. Collision 대응 계층

  -----------------------------------------------------------------------
  계층                                역할
  ----------------------------------- -----------------------------------
  1\. Workspace / Limit Boundary      간단한 위치 제한 및 Recovery 상태
                                      분류

  2\. Prevalidated Safe Pose / Path   현재 1차 구현의 고정환경 이동
                                      안전성 확보

  3\. Model-based Collision Check /   향후 Robot/Tool/Fixture 모델을
  Planning                            이용한 고정환경 Collision Avoidance
                                      확장

  4\. Adaptive Grip / Safe Escape     모델로 정확히 표현하기 어려운
                                      Cable의 국부 불확실성 대응
  -----------------------------------------------------------------------

Collision Detection 자체는 회피 경로를 생성하지 않는다.

향후 Model-based Collision Avoidance를 도입하려면 Robot/Tool 모델,
Environment 모델, Collision Checker와 Motion Planner가 함께 필요하다.

------------------------------------------------------------------------

## 17. Pull Test 및 판정값에 대한 현재 원칙

초기 수동 시험에서 Pull 시 Tool Force 차이가 최대 약 10 N 관찰되었지만
2\~3회의 비정식 측정이므로 품질 PASS/FAIL Threshold로 사용하지 않는다.

반복 자동시험과 CSV Logging을 통해 분포를 확보한 후 판정 기준을
결정한다.

  항목                    현재 단위시험 기준
  ----------------------- ---------------------------------------------------
  Entry speed             10 mm/s
  Max Entry Depth         25 mm
  Entry timeout           20 s
  Soft Grip / Hard Grip   TBD
  Pull speed              10 mm/s
  Max Pull Distance       50 mm
  Pull Force Limit        10 N - 시험 Upper Stop Limit, 판정 Threshold 아님
  Pull timeout            20 s
  Trial count             10
  Logging                 CSV

------------------------------------------------------------------------

## 18. 현재 Sequence 상세설계 진행 상태

기본 설계 원칙이 정리된 항목:

-   Main Work
-   Work Initialize
-   Home Return
-   Pause / Resume
-   HMI Communication Recovery

다음 상세설계 순서:

``` text
Point Transition
   ↓
Adaptive Grip
   ↓
Pull Inspection
   ↓
Inspection Judgment
   ↓
Work Finish
   ↓
Stop / Error Handling
```

------------------------------------------------------------------------

## 19. 보류 및 TBD

-   Point Transition의 실제 Motion 규칙 및 Point 순서 변경 처리 상세
-   Adaptive Grip의 Search/Alignment 세부 동작과 Soft/Hard Grip 설정
-   Safe Escape 종료조건 및 Grip Relaxation 값
-   Pull Inspection의 최종 데이터 취득 항목과 PASS/FAIL Threshold
-   Work Finish의 완료처리 세부 순서
-   HMI Heartbeat / Communication Timeout
-   Work Area Boundary 실제 좌표 및 Margin/Hysteresis
-   Limit Boundary 상세 정의
-   고정환경 Model-based Collision Planning 적용 여부
-   Cable 자동 회수 / Reject Handling - 현재 보류
-   Commissioning / Trial Mode - 향후 기능

------------------------------------------------------------------------

## 20. 본 Concept과 상세 Sequence 문서의 관계

본 Concept은 검사시퀀스 전반에 공통 적용되는 **설계 기준과 설계 의도**를
정의한다.

문서 역할은 다음과 같이 구분한다.

``` text
Concept #2 검사시퀀스 Concept
   └─ 공통 설계원칙 / 설계의도

검사시퀀스 Map
   └─ 전체 Sequence 구조 / 연결관계

개별 Sequence 상세문서
   └─ 실제 Flow / 진입조건 / 판단조건 / 예외처리 / Interface
```
