# CCCIS Business Requirements Document v0.2

## Flexible Inspection & Adaptive Grip

-   **프로젝트명:** CCCIS (Contact-based Cable Connection Inspection
    System)
-   **대상 도메인:** 자동차 전장 기반 케이블/커넥터 체결상태 검사
-   **로봇/툴:** Doosan Robotics M0609 + OnRobot RG2
-   **핵심 컨셉:** Flexible Inspection + Adaptive Grip +
    Force/Displacement 기반 체결검사
-   **PoC 제약:** Vision 미사용
-   **작성 기준일:** 2026-09-20

------------------------------------------------------------------------

# 0. 개정 개요 - 기존 BRD 대비 주요 변경점

이번 v0.2에서는 기존의 **Recipe 기반 고정 파지 후 Grip-Pull Test** 중심
구조를 **Minimal Recipe + Adaptive Grip + Connector Axis 기반 검사**
구조로 확장한다.

핵심 변경 방향은 다음과 같다.

  -----------------------------------------------------------------------
  구분                    기존 BRD 관점           v0.2 변경 방향
  ----------------------- ----------------------- -----------------------
  Flexible 환경           제품/검사 Point별       동일 검사 알고리즘을
                          Recipe로 대응           유지하고 Point별
                                                  작업공간 차이만
                                                  Recipe로 제공

  Recipe 역할             위치, 자세, 파지 및     케이블 체결상태와 로봇
                          검사조건을 상세 저장    진입조건 중심의 최소
                                                  정보 제공

  파지 위치               Teaching/Recipe 기반의  Nominal 위치에서
                          사전 정의 위치          Adaptive Grip으로 실제
                                                  파지 위치 보정

  로봇 진입               검사 위치로 이동 후     Point별 Ready Pose에서
                          파지                    Entry Point로 진입 후
                                                  깊이 편차 보정

  Grip                    단일 Grip 개념          Soft Grip과 Hard
                                                  Grip으로 역할 분리

  Soft Grip               명확한 별도 단계 없음   Micro-Wiggle과 Fine
                                                  Alignment를 이용한 파지
                                                  위치 안정화

  Hard Grip               Pull Test용 파지        Adaptive Grip 완료 후
                                                  검사 수행을 위한 고정
                                                  파지

  Wiggle                  검사 동작 후보          Hard Grip 검사에서는
                                                  제외하고 Soft Grip
                                                  정렬/안정화에 사용

  Pull Test               로봇 이동 방향 기반     Gripper 자세와
                                                  독립적으로 Connector
                                                  Axis 반대 방향으로 수행

  검사 데이터             Force 중심 검토         Connector Axis Force +
                                                  TCP Displacement를 동기
                                                  기록

  Push/Re-seat            Phase 1 제외            확장 기능으로 유지하되
                                                  Inspection과 Recovery를
                                                  분리
  -----------------------------------------------------------------------

## 0.1 v0.2의 핵심 설계 원칙

1.  **Recipe가 모든 동작을 가르치지 않는다.**
2.  Recipe는 최소한 **케이블 체결상태**와 **체결검사를 위한 Robot Ready
    Pose**를 제공한다.
3.  동일한 케이블이라도 작업공간에 따라 접근 자세가 달라질 수 있으므로
    Ready Pose는 Inspection Point별로 관리한다.
4.  실제 파지 위치의 오차는
    `Entry -> Depth Compensation -> Soft Grip -> Micro-Wiggle -> Fine Alignment`
    과정에서 보정한다.
5.  Adaptive Grip이 완료된 이후 Hard Grip으로 전환하고 Connector Axis
    기준의 Pull Test를 수행한다.
6.  Vision이 없으므로 Connector-Cable 경계를 직접 인식하지 못하는 한계가
    있으며, 현재 PoC에서는 Nominal Offset/Search Range로 대응한다.

세부 요구사항과 동작 정의는 이후 절에서 기술한다.

------------------------------------------------------------------------

# 1. 문서 목적

본 문서는 자동차 전장 작업공간에서 케이블 및 커넥터의 기계적 체결상태를
협동로봇으로 검사하기 위한 CCCIS의 비즈니스 및 상위 시스템 요구사항을
정의한다.

본 개정에서는 검사 포인트마다 상세 좌표와 파지 조건을 고정하는 전용
자동화 방식보다, 검사 대상의 기준 정보와 작업공간 진입 조건만 Recipe로
제공하고 실제 파지 편차를 로봇이 적응적으로 보정하는 **Flexible
Inspection**을 핵심 방향으로 정의한다.

------------------------------------------------------------------------

# 2. 비즈니스 문제와 목표

  -----------------------------------------------------------------------
  구분                                정의
  ----------------------------------- -----------------------------------
  문제                                동일한 케이블/커넥터라도 BCM, VCU
                                      등 전장 모듈과 주변 구조물에 따라
                                      접근 가능 방향, 로봇 자세 및 실제
                                      파지 위치가 달라진다.

  기존 방식의 한계                    각 검사 Point에 상세 궤적과 정확한
                                      파지 좌표를 고정하면 제품 또는
                                      작업공간 변경 시 재티칭과 프로그램
                                      수정이 증가한다.

  비즈니스 목표                       Inspection Point별 최소 Recipe와
                                      Adaptive Grip을 통해 검사
                                      알고리즘의 재사용성을 높인다.

  검사 목표                           Connector Axis 기준
                                      Force/Displacement를 이용해
                                      케이블/커넥터의 기계적 체결상태를
                                      정량화한다.

  기술 목표                           M0609의 Force/Compliance 활용성을
                                      높이고 비전 없이도 제한된 위치
                                      편차에 적응 가능한 파지 절차를
                                      구현한다.
  -----------------------------------------------------------------------

------------------------------------------------------------------------

# 3. 적용 범위

## 3.1 Phase 1 PoC 포함 범위

-   자동차 전장 모듈의 케이블/커넥터 Inspection Point 관리
-   BCM, VCU 등을 예시 도메인으로 사용
-   Vision 없이 사전 등록된 검사 대상과 Nominal 위치 사용
-   Point별 Ready Pose 기반 진입
-   Entry/Depth 보정
-   Soft Grip
-   Micro-Wiggle 기반 파지 위치 안정화
-   Fine Alignment
-   Hard Grip
-   Grip Stability Check
-   Connector Axis 기반 Grip-Pull Test
-   Tool Force 및 TCP Displacement 데이터 기록
-   반복시험을 통한 정상/이상 분포 및 판정 기준 후보 도출

## 3.2 현재 제외 범위

-   Vision 기반 Connector/Cable 자동 인식
-   전기적 도통/통신 품질 검사
-   임의의 미등록 케이블에 대한 완전 자율 검사
-   Phase 1에서의 자동 재체결/수리

Push 또는 Re-seat는 향후 확장 기능으로 검토하되 **Inspection 기능과
Recovery 기능을 분리**한다.

------------------------------------------------------------------------

# 4. Flexible Inspection 정의

본 프로젝트에서 Flexible은 임의의 케이블을 Vision 없이 자유롭게
인식한다는 의미가 아니다.

검사 대상과 작업공간은 사전에 등록되지만, 검사 Point마다 별도의 로봇
프로그램을 작성하는 대신 **Recipe 변경과 Adaptive Grip을 통해 동일한
검사 로직을 재사용**하는 것을 의미한다.

## 4.1 역할 분담

  -----------------------------------------------------------------------
  Recipe가 제공                       로봇이 적응적으로 수행
  ----------------------------------- -----------------------------------
  Inspection Point 식별정보           실제 파지 위치 탐색/보정

  케이블/커넥터 종류와 타입           해당 대상에 대한 기본 검사 전략
                                      선택

  Nominal 검사 위치                   실제 Depth/Position 편차 보정

  Connector Axis / 체결 방향          Pull 방향 및 검사 기준축 생성

  작업공간에 적합한 Ready Pose        Entry 이후 실제 파지 위치 확보

  Nominal Offset 또는 Search Range    Soft Grip/Fine Alignment를 통한
                                      오차 흡수
  -----------------------------------------------------------------------

------------------------------------------------------------------------

# 5. Inspection Recipe 구조

Recipe는 로봇의 전체 궤적을 저장하는 명령 집합이 아니라, **Adaptive
Grip이 시작될 수 있는 기준 정보**를 제공한다.

## 5.1 반드시 필요한 두 가지 정보 그룹

### A. Cable Connection Condition

-   Connector 종류/타입
-   Cable 종류/타입
-   Nominal 검사 위치
-   Connector Axis / 체결 방향
-   필요 시 Connector 검사 및 Cable 검사에 사용되는 Nominal
    Offset/Search Range

### B. Robot Access Condition

-   Inspection Point별 Ready Pose
-   Ready Pose의 Task/Joint 정보
-   Entry Point 생성 또는 진입을 위한 기준 정보
-   작업공간 간섭을 피하기 위한 Tool Orientation

## 5.2 Inspection Point 예시

  Point ID   Point Name             대상
  ---------- ---------------------- ----------------------
  BCM_P01    BCM_POWER_CONNECTOR    BCM Power Connector
  BCM_P02    BCM_CAN_CONNECTOR      BCM CAN Connector
  VCU_P01    VCU_POWER_CONNECTOR    VCU Power Connector
  VCU_P02    VCU_SIGNAL_CONNECTOR   VCU Signal Connector

명명 규칙은 `{기판}_{포인트 번호}`를 기본으로 한다.

동일한 케이블 또는 동일한 Connector Type이라도 작업공간이 다르면 Ready
Pose와 Tool Orientation은 달라질 수 있다.

------------------------------------------------------------------------

# 6. 좌표 및 방향 개념

## 6.1 Connector Axis

Connector가 Socket에 체결되는 축을 검사 기준축으로 정의한다.

-   `+Axis`: 체결/Push 방향
-   `-Axis`: 분리/Pull 방향
-   Axis에 수직인 방향: Adaptive Grip의 Micro-Wiggle/Fine Alignment에
    사용 가능

Gripper의 실제 자세가 Inspection Point마다 달라도 **검사 기준축은
Connector Axis를 유지**한다.

## 6.2 Ready Pose

Ready Pose는 주변 작업공간과 로봇 관절 구성을 고려하여 검사 영역에
안전하게 진입하기 위한 자세이다.

Ready Pose는 단순한 Connector Axis Offset만으로 생성하지 않고 Inspection
Point별 Teaching 정보로 관리할 수 있다.

## 6.3 Entry Point 및 Depth Offset

Ready Pose에서 Entry Point로 이동한 뒤, 열린 Gripper 상태로 케이블 축
방향의 짧은 진입 동작을 수행한다.

Depth Offset/Search Range는 Nominal 좌표와 실제 케이블 위치 사이의 깊이
편차를 흡수하기 위해 사용한다.

Vision이 없어 Connector-Cable 경계를 직접 검출할 수 없으므로 현재
PoC에서는 Connector 검사와 Cable 검사에 서로 다른 Nominal Offset이
필요할 수 있다.

향후 경계 위치를 안정적으로 검출할 수 있다면 단일 Reference Point 기반
상대 Offset 구조로 단순화할 수 있다.

------------------------------------------------------------------------

# 7. Adaptive Grip 정의

Adaptive Grip은 Recipe가 제공한 Nominal 정보로 검사 영역에 진입한 뒤,
Soft Grip과 Force/Position 반응을 이용하여 실제 파지 위치를 안정화하고
Hard Grip으로 전환하는 파지 전략이다.

## 7.1 기본 시퀀스

``` text
Load Inspection Recipe
        |
        v
MoveJ -> Ready Pose
        |
        v
Gripper Open
        |
        v
Entry Point
        |
        v
Depth Compensation / Search
        |
        v
Soft Grip
        |
        v
Micro-Wiggle
        |
        v
Fine Alignment
        |
        v
Hard Grip
        |
        v
Grip Stability Check
        |
        v
Grip-Pull Test
```

## 7.2 단계별 역할

  -----------------------------------------------------------------------
  단계                    주요 동작               목적
  ----------------------- ----------------------- -----------------------
  Ready                   `movej`로 Ready Pose    작업공간 간섭을 고려한
                          이동                    안전한 진입

  Entry                   열린 Gripper 상태에서   검사 대상 영역 확보
                          진입                    

  Depth Compensation      Offset/Search           Nominal 깊이 편차 보정

  Soft Grip               낮은 파지력으로 대상    대상 이탈 방지 +
                          구속                    미세조정 가능 상태 확보

  Micro-Wiggle            Connector Axis에 수직인 파지 위치 탐색 및 Force
                          미세 이동               Response 확인

  Fine Alignment          위치/자세 미세보정      안정적인 파지 위치 확보

  Hard Grip               검사용 파지력 적용      Pull Test 중 Slip 억제

  Stability Check         파지 상태 검증          검사 전 파지
                                                  실패/미끄럼 확인
  -----------------------------------------------------------------------

------------------------------------------------------------------------

# 8. Soft Grip과 Micro-Wiggle

Soft Grip은 최종 검사를 위한 파지가 아니라 **Adaptive Grip을 위한
탐색/정렬 상태**이다.

Micro-Wiggle은 사람이 케이블 체결상태를 확인할 때 축에 수직인 방향으로
미세하게 흔들어 위치와 상태를 확인하는 동작에서 착안한다.

Soft Grip 상태에서 Micro-Wiggle을 수행하면서 다음 정보를 사용할 수 있다.

-   Tool Force Response
-   좌/우 Force 비대칭
-   TCP Position 변화
-   파지 대상의 이동 가능성
-   주변 구조물 간섭 여부

Micro-Wiggle 결과는 **체결 PASS/FAIL 판정값으로 직접 사용하지 않고**,
Fine Alignment와 파지 안정화를 위한 데이터로 구분한다.

------------------------------------------------------------------------

# 9. Hard Grip 및 체결 검사

Adaptive Grip이 완료되면 Hard Grip으로 전환한다.

Hard Grip 이후에는 파지 위치를 다시 탐색하는 것보다 **Connector Axis
방향의 체결 검사**에 집중한다.

## 9.1 Pull Test

Pull Test는 Connector Axis의 반대 방향으로 수행한다.

``` text
+Axis : Push / Insert
-Axis : Pull / Extraction Test
```

주요 측정값:

-   Axial Tool Force
-   TCP Displacement
-   Peak Force
-   Force-Displacement 특성
-   시험 회차
-   Grip 상태
-   Connector 이탈 여부

## 9.2 Hard Grip 상태의 Wiggle

Hard Grip 상태에서 횡방향 Wiggle Force를 체결 판정에 사용하는 것은 현재
PoC에서 제외한다.

Hard Grip Wiggle Force에는 다음 요소가 함께 반영될 수 있기 때문이다.

-   케이블 굽힘 강성
-   파지 위치
-   Tool Orientation
-   TCP Moment
-   Fixture 강성
-   Connector 주변 구조물 간섭

따라서 체결상태의 핵심 정량값은 가능한 한 **Connector Axis 방향
Force/Displacement**로 단순화한다.

------------------------------------------------------------------------

# 10. Push 및 Re-seat 확장

Hard Grip 상태에서 Connector Axis의 `+Axis` 방향으로 Push 동작을
수행하는 기능은 확장 가능하다.

단, 다음 기능은 구분한다.

  기능        목적
  ----------- ------------------------------------------------
  Push Test   검사 목적으로 축방향 반응을 측정
  Re-seat     검사 실패 또는 이탈 이후 Connector를 다시 체결
  Pull Test   Connector Axis 반대 방향의 체결력 검사

Phase 1에서는 Pull Test 중심으로 검증하고 Re-seat는 확장 기능으로
관리한다.

------------------------------------------------------------------------

# 11. 기능 요구사항

  -----------------------------------------------------------------------
  ID                                  요구사항
  ----------------------------------- -----------------------------------
  FR-01                               시스템은 Work Order의 Inspection
                                      Point ID를 이용하여 해당 Recipe를
                                      조회할 수 있어야 한다.

  FR-02                               Recipe는 케이블/커넥터 종류,
                                      Nominal 위치, Connector Axis 및
                                      Point별 Ready Pose를 제공해야 한다.

  FR-03                               로봇은 Point별 Ready Pose로 `movej`
                                      이동할 수 있어야 한다.

  FR-04                               로봇은 열린 Gripper 상태에서
                                      Entry/Search 구간을 안전하게
                                      진입해야 한다.

  FR-05                               시스템은 Nominal 위치 편차를
                                      보정하기 위한 Depth
                                      Compensation/Search 기능을 제공해야
                                      한다.

  FR-06                               시스템은 Soft Grip 상태에서
                                      Micro-Wiggle/Fine Alignment를
                                      수행할 수 있어야 한다.

  FR-07                               Fine Alignment 완료 후 Hard
                                      Grip으로 전환할 수 있어야 한다.

  FR-08                               Pull Test 전에 Grip Stability를
                                      확인해야 한다.

  FR-09                               Pull Test 방향은 Gripper 자세가
                                      아니라 Connector Axis를 기준으로
                                      생성되어야 한다.

  FR-10                               Pull Test 중 Tool Force와 TCP
                                      Displacement를 동기화하여 기록해야
                                      한다.

  FR-11                               Soft Grip 정렬 데이터와 Hard Grip
                                      검사 데이터를 구분하여 저장해야
                                      한다.

  FR-12                               검사 중 Force/이동 안전 한계를
                                      초과하면 동작을 중단하고 안전
                                      절차로 전환해야 한다.

  FR-13                               동일 검사 알고리즘을 BCM/VCU 등
                                      복수 Inspection Point에서 Recipe
                                      변경만으로 재사용할 수 있어야 한다.

  FR-14                               Connector 검사와 Cable 검사가 서로
                                      다른 위치를 요구할 경우 Point별
                                      Nominal Offset/Search 정보를
                                      지원해야 한다.
  -----------------------------------------------------------------------

------------------------------------------------------------------------

# 12. 데이터 기록 요구사항

## 12.1 Adaptive Grip 데이터

-   Recipe ID
-   Inspection Point ID
-   Ready/Entry 상태
-   Soft Grip 상태
-   Micro-Wiggle Tool Force Response
-   TCP Position/Displacement
-   Fine Alignment 결과
-   Hard Grip 전환 결과
-   Grip Stability 결과

## 12.2 Grip-Pull Test 데이터

-   Timestamp
-   Recipe ID / Point ID
-   시험 회차
-   TCP Pose
-   TCP Displacement
-   Tool Force
-   Connector Axis
-   Axial Force
-   Pull 거리
-   Pull 속도
-   Peak Force
-   Connector 이탈 여부
-   시험 결과

예비 수동시험에서 관찰된 약 10 N 수준의 최대 차이는 판정 Threshold가
아니다. 반복시험을 통해 분포와 반복성을 확보한 후 판정 기준 후보를
결정한다.

------------------------------------------------------------------------

# 13. PoC 검증 순서

1.  Recipe/Inspection Point 구조 구현
2.  BCM/VCU 예시 Point에 Ready Pose 등록
3.  `Ready -> Entry` 접근 동작 검증
4.  Open Gripper 상태의 Depth Compensation/Search 검증
5.  Soft Grip 동작 검증
6.  Micro-Wiggle 및 Fine Alignment 반복 검증
7.  Hard Grip 및 Grip Stability 검증
8.  Grip-Pull 1회 정상동작 검증
9.  Force/TCP Displacement 데이터 기록 검증
10. N회 반복시험 수행
11. 정상/이상 조건 Force-Displacement 분포 분석
12. Threshold 후보 도출
13. 다른 Inspection Point에 동일 Adaptive Grip/Inspection 알고리즘
    적용성 검증

------------------------------------------------------------------------

# 14. 주요 미결정 사항

  -----------------------------------------------------------------------
  항목                                현재 상태
  ----------------------------------- -----------------------------------
  Soft Grip Force/Width               반복시험 필요

  Micro-Wiggle 방향/진폭/속도         반복시험 필요

  Fine Alignment 판정 조건            개발/검증 필요

  Depth Search Range                  Point/Fixture 기준 실험 필요

  Connector/Cable 검사 Offset         Vision 미사용으로 현재 별도 관리
                                      가능성 있음

  Hard Grip Force                     Slip 방지 반복시험 필요

  Pull 거리/속도                      반복시험 필요

  Force Safety Limit                  시스템 안전 기준과 함께 확정 필요

  PASS/FAIL Threshold                 반복 데이터 확보 후 결정

  Push Test                           확장 검토

  Re-seat                             Phase 1 이후 확장 검토
  -----------------------------------------------------------------------

------------------------------------------------------------------------

# 15. v0.2 결론

CCCIS v0.2의 핵심은 **고정된 파지 Recipe를 만드는 것이 아니라, 최소한의
Recipe를 기반으로 로봇이 실제 파지 위치에 적응하는 검사 구조를 만드는
것**이다.

Recipe는 케이블 체결상태와 작업공간에 적합한 Robot Access Condition을
제공하고, M0609은 Entry 이후 Soft Grip, Micro-Wiggle, Fine Alignment를
통해 실제 파지 오차를 보정한다.

Adaptive Grip 완료 후 Hard Grip으로 전환하고, Gripper 자세와 독립적인
Connector Axis 기준의 Pull Test를 수행하여 Force/Displacement 데이터를
확보한다.

이를 통해 제품 또는 검사 Point가 변경되더라도 로봇 프로그램 자체의
변경을 최소화하고, Recipe 변경과 동일 검사 알고리즘의 재사용을 통해
Flexible한 케이블 체결검사를 구현하는 것을 목표로 한다.
