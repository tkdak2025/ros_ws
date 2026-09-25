# CCCIS Adaptive Grip 작업검증계획서 v0.1

-   **프로젝트:** CCCIS (Contact-based Cable Connection Inspection
    System)
-   **대상 시스템:** Doosan M0609 + OnRobot RG2
-   **검증 대상:** Flexible Inspection / Adaptive Grip / Grip-Pull Test
-   **상위 문서:** CCCIS BRD v0.2
-   **작성일:** 2026-09-20

------------------------------------------------------------------------

# 0. 검증계획 개요

본 문서는 CCCIS BRD v0.2에서 정의한 **Flexible Inspection 및 Adaptive
Grip 개념을 실제 로봇 동작으로 검증하기 위한 작업검증계획서**이다.

BRD에서 정의된 상위 개념은 다음과 같다.

> `Recipe -> Ready -> Entry -> Depth Compensation -> Soft Grip -> Micro-Wiggle -> Fine Alignment -> Hard Grip -> Grip Stability Check -> Grip-Pull Test`

현재 Recipe/Inspection Point, Ready Pose, Connector Axis, Soft/Hard
Grip의 역할과 Pull Test 방향은 개념적으로 정의되었다.\
남은 핵심 과제는 **Adaptive Grip이 실제 위치 편차를 보정할 수 있는지**,
그리고 보정 후 **반복 가능한 Grip-Pull 데이터를 확보할 수 있는지**를
실험적으로 확인하는 것이다.

## 0.1 검증 단계 요약

  -----------------------------------------------------------------------
  단계              검증 대상         핵심 질문         현재 상태
  ----------------- ----------------- ----------------- -----------------
  V01               Recipe /          Point별           설계 완료, 구현
                    Inspection Point  기준정보를        필요
                                      일관되게 불러올   
                                      수 있는가?        

  V02               Ready -\> Entry   작업공간 간섭     개념 정의
                                      없이 반복 진입    
                                      가능한가?         

  V03               Depth             Nominal 깊이      검증 필요
                    Compensation      오차를 비전 없이  
                                      보정할 수 있는가? 

  V04               Soft Grip         미세조정          검증 필요
                                      가능하면서 대상을 
                                      유지하는 파지     
                                      조건은 무엇인가?  

  V05               Micro-Wiggle      파지 위치 차이에  핵심 검증
                                      따라 Force        
                                      Response가        
                                      구분되는가?       

  V06               Fine Alignment    Wiggle Response를 핵심 검증
                                      이용해 파지       
                                      위치를 보정할 수  
                                      있는가?           

  V07               Hard Grip         Pull 중 Slip 없는 검증 필요
                                      반복 가능한       
                                      파지가 가능한가?  

  V08               Grip Stability    Pull 전에 파지    검증 필요
                                      실패/Slip         
                                      가능성을 판별할   
                                      수 있는가?        

  V09               Grip-Pull Logging Force와 TCP       구현 필요
                                      Displacement를    
                                      동기 기록할 수    
                                      있는가?           

  V10               Repeated          정상/이상 시편의  최종 검증
                    Grip-Pull         데이터 분포가     
                                      반복적으로        
                                      구분되는가?       

  V11               Judgment Logic    어떤 Feature로    데이터 확보 후
                                      PASS/FAIL 후보    
                                      기준을 만들       
                                      것인가?           

  V12               Cable Inspection  Connector 검사 외 후속 검토
                                      Cable 검사        
                                      위치/방법을       
                                      어떻게 정의할     
                                      것인가?           
  -----------------------------------------------------------------------

------------------------------------------------------------------------

# 1. 검증 목적

본 검증의 목적은 다음 네 가지이다.

1.  **Adaptive Grip 성립성 검증**\
    Recipe의 Nominal 위치에 오차가 존재하더라도 로봇이 실제 파지 가능한
    위치를 탐색하고 안정화할 수 있는지 확인한다.

2.  **Grip 반복성 검증**\
    Adaptive Grip 이후 Hard Grip 상태가 Grip-Pull Test를 수행하기에
    충분한 반복성과 안정성을 갖는지 확인한다.

3.  **검사 데이터 유효성 검증**\
    Connector Axis 방향의 Tool Force와 TCP Displacement가 체결상태를
    구분하기 위한 정량 데이터로 사용 가능한지 확인한다.

4.  **Flexible Inspection 적용성 검증**\
    동일 검사 알고리즘을 여러 Inspection Point에 Recipe 변경만으로
    적용할 수 있는지 확인한다.

------------------------------------------------------------------------

# 2. 검증 범위와 제외 범위

## 2.1 포함 범위

-   Recipe 및 Inspection Point 조회
-   Point별 Ready Pose
-   Open Gripper 상태의 Entry
-   Depth Compensation / Search
-   Soft Grip
-   Micro-Wiggle
-   Fine Alignment
-   Hard Grip
-   Grip Stability Check
-   Connector Axis 기반 Grip-Pull Test
-   Tool Force / TCP Pose / TCP Displacement 기록
-   정상/이상 시편 반복시험
-   검사 Feature 및 Threshold 후보 도출

## 2.2 제외 범위

-   Vision 기반 위치/경계 검출
-   전기적 도통/통신 검사
-   자동 Re-seat 및 수리
-   임의의 미등록 케이블에 대한 완전 자율 검사
-   양산 수준의 최종 PASS/FAIL Threshold 확정

------------------------------------------------------------------------

# 3. 검증 전제조건

  -----------------------------------------------------------------------
  구분                                전제조건
  ----------------------------------- -----------------------------------
  Robot                               M0609이 정상 동작하고 TCP/Tool
                                      설정이 완료되어야 한다.

  Gripper                             RG2 Open/Close 및 파지력 제어가
                                      정상이어야 한다.

  Fixture                             반복시험 중 Fixture가 움직이지
                                      않도록 고정되어야 한다.

  Inspection Point                    Nominal Point, Connector Axis,
                                      Ready Pose가 정의되어야 한다.

  Safety                              Force/이동 제한과 비상정지 조건이
                                      사전에 설정되어야 한다.

  Data                                Tool Force와 TCP Pose를 반복적으로
                                      읽고 저장할 수 있어야 한다.

  Specimen                            정상 체결과 의도적으로 이상 상태를
                                      만든 비교 시편이 준비되어야 한다.
  -----------------------------------------------------------------------

------------------------------------------------------------------------

# 4. 전체 작업검증 흐름

``` text
[Recipe / Inspection Point 준비]
              |
              v
[Ready -> Entry 반복성 검증]
              |
              v
[Depth Compensation 검증]
              |
              v
[Soft Grip 조건 탐색]
              |
              v
[Micro-Wiggle Force Response 측정]
              |
              v
[Fine Alignment 로직 검증]
              |
              v
[Hard Grip 조건 검증]
              |
              v
[Grip Stability Check 검증]
              |
              v
[Grip-Pull + Data Logging]
              |
              v
[정상/이상 반복시험]
              |
              v
[Feature 분석 / Threshold 후보]
              |
              v
[다른 Inspection Point 적용]
```

검증은 위 순서를 기본으로 하며, 앞 단계가 불안정한 상태에서 다음 단계의
판정 기준을 확정하지 않는다.

------------------------------------------------------------------------

# 5. V01 - Recipe / Inspection Point 검증

## 목적

Work Order에서 전달된 Inspection Point ID를 기준으로 검사에 필요한
정보를 정확하게 불러오는지 확인한다.

## 검증 항목

-   `recipe_id`
-   `point_id`
-   `point_name`
-   Nominal Point
-   Connector Axis
-   Ready Pose
-   Entry/Depth 관련 Offset 또는 Search Range

## 합격 조건

-   동일 Point ID 호출 시 동일한 기준정보가 재현되어야 한다.
-   Point 변경 시 코드 수정 없이 Recipe 데이터만 변경되어야 한다.
-   잘못된 Point ID 입력 시 검사 동작을 시작하지 않아야 한다.

------------------------------------------------------------------------

# 6. V02 - Ready -\> Entry 접근 검증

## 목적

Inspection Point별 Ready Pose에서 검사 영역으로 안전하고 반복적으로 진입
가능한지 확인한다.

## 검증 방법

1.  Gripper를 Open 상태로 유지한다.
2.  `movej`로 Ready Pose에 이동한다.
3.  Entry Point로 이동한다.
4.  동일 동작을 반복한다.
5.  주변 구조물과의 간섭 및 TCP 도달 위치를 확인한다.

## 주요 기록값

-   TCP Pose
-   Joint Position
-   Entry 도달 오차
-   간섭 발생 여부

## 합격 조건

-   반복 접근 시 구조물 간섭이 없어야 한다.
-   동일 Inspection Point에서 Entry Pose가 반복적으로 재현되어야 한다.

------------------------------------------------------------------------

# 7. V03 - Depth Compensation 검증

## 목적

Vision 없이 Nominal Point와 실제 파지 대상 사이의 축방향 깊이 오차를
보정할 수 있는지 확인한다.

## 검증 방향

현재 우선 검토할 방식은 Connector/Cable Axis 방향의 짧은 `movel`과 Force
Condition을 이용한 Search이다.

단, 실제 Cable/Connector 형상에서 안정적인 접촉 신호를 얻을 수 있는지는
실험으로 확인해야 한다.

## 실험 변수

-   Nominal Depth Offset
-   Search Range
-   Search Speed
-   Force Detection 조건
-   Contact 발생 시 TCP Position

## 검증 결과

Depth Search 결과가 반복 가능할 경우 Entry 기준점 보정값으로 사용한다.\
접촉 신호가 불안정할 경우 Recipe 기반 Nominal Offset 방식과 병행한다.

------------------------------------------------------------------------

# 8. V04 - Soft Grip 조건 검증

## 목적

케이블을 놓치지 않으면서 Micro-Wiggle과 Fine Alignment가 가능한 파지
조건을 찾는다.

## 실험 변수

-   RG2 Grip Force
-   Grip Width
-   파지 깊이
-   Tool Orientation

## 확인 항목

-   Cable Slip 여부
-   Cable 과구속 여부
-   Wiggle 수행 가능 여부
-   파지 후 Tool Force 변화
-   Cable 손상 여부

## 주의

Soft Grip의 수치는 현재 미정이며 임의의 기준값을 고정하지 않는다.
반복시험을 통해 실험적으로 결정한다.

------------------------------------------------------------------------

# 9. V05 - Micro-Wiggle Force Response 검증

## 목적

Soft Grip 상태에서 Connector Axis에 수직인 미세 이동을 수행했을 때 파지
위치 차이에 따라 측정되는 Force Response가 달라지는지 확인한다.

## 기본 시험 개념

``` text
Soft Grip
   |
   +--> +Y Micro Move -> Force 측정
   |
   +--> 기준 위치 복귀
   |
   +--> -Y Micro Move -> Force 측정
   |
   v
좌/우 Force Response 비교
```

필요 시 Y축 외 다른 수직축도 추가 검토한다.

## 주요 기록값

-   이동 방향
-   이동 거리
-   이동 속도
-   TCP Position
-   Tool Force
-   Peak Force
-   복귀 후 위치
-   Slip 여부

## 핵심 판단

-   중심 파지와 편심 파지에서 Force Response 패턴이 구분되는가?
-   동일 파지조건에서 반복성이 확보되는가?
-   Micro-Wiggle 자체가 케이블 위치를 과도하게 변경시키지 않는가?

------------------------------------------------------------------------

# 10. V06 - Fine Alignment 알고리즘 검증

## 목적

Micro-Wiggle에서 얻은 Force Response를 이용해 실제 파지 위치를 더
안정적인 위치로 보정할 수 있는지 확인한다.

## 초기 알고리즘 개념

``` text
Soft Grip
   |
   v
+Direction Force 측정
   |
   v
-Direction Force 측정
   |
   v
Force Response 비교
   |
   v
보정 방향 결정
   |
   v
TCP 미세 이동
   |
   v
Micro-Wiggle 재측정
   |
   +--> 조건 만족 -> Alignment 완료
   |
   +--> 조건 불만족 -> 재보정 또는 실패
```

## 검증 항목

-   보정 전/후 Force Response 차이
-   보정 횟수
-   최종 TCP Position
-   최종 Grip 위치 반복성
-   Alignment 실패율

## 중요사항

Fine Alignment 판정식은 아직 확정하지 않는다.\
Force Difference, Force Ratio, Position 변화 등의 Feature를 비교한 뒤
결정한다.

------------------------------------------------------------------------

# 11. V07 - Hard Grip 검증

## 목적

Adaptive Grip 완료 후 Grip-Pull Test 동안 Cable Slip이 발생하지 않는
Hard Grip 조건을 찾는다.

## 실험 변수

-   Hard Grip Force
-   Grip Width
-   파지 위치
-   Pull 전 초기 Tool Force

## 확인 항목

-   Pull 중 Slip 여부
-   Cable 손상 여부
-   반복 파지 후 위치 변화
-   Tool Force 신호 안정성

Hard Grip의 목적은 위치 탐색이 아니라 **검사 중 파지 상태 유지**이다.

------------------------------------------------------------------------

# 12. V08 - Grip Stability Check 검증

## 목적

Grip-Pull Test를 시작하기 전에 현재 파지가 검사 가능한 상태인지
확인한다.

## 검토할 판정정보

-   Gripper Width 변화
-   TCP Position 변화
-   초기 Tool Force
-   짧은 사전 하중에 대한 Force/Displacement 반응

Hard Grip 상태에서 횡방향 Wiggle Force를 체결상태 판정에 사용하는 방식은
현재 제외한다.

Grip Stability Check는 **Connector 체결상태가 아니라 Gripper-Cable
파지상태를 판정**해야 한다.

------------------------------------------------------------------------

# 13. V09 - Grip-Pull Data Logging 검증

## 목적

Grip-Pull Test 중 검사 데이터가 손실 없이 동기화되어 기록되는지
확인한다.

## 필수 기록 항목

-   Timestamp
-   Recipe ID
-   Inspection Point ID
-   Trial Number
-   Test Phase
-   TCP Pose
-   TCP Displacement
-   Tool Force `(Fx, Fy, Fz)`
-   필요 시 Tool Torque
-   Connector Axis
-   Axial Force
-   Pull Distance
-   Pull Speed
-   Grip State
-   Connector 이탈 여부
-   Result / Manual Label

## 구현 방향

Data Logger 구현은 Codex와 별도 개발하며, 본 검증계획서에서는 필요한
데이터 필드와 검증 기준을 정의한다.

------------------------------------------------------------------------

# 14. V10 - 반복 Grip-Pull Test

## 목적

정상/이상 체결상태에서 Force/Displacement 데이터가 반복적으로 다른
분포를 보이는지 확인한다.

## 시험 구성

최소 두 상태를 비교한다.

-   정상 체결 시편
-   의도적으로 체결 이상을 만든 시편

필요 시 추가 이상 상태를 정의한다.

## 주요 분석 Feature 후보

-   Peak Axial Force
-   Pull Distance at Peak Force
-   Force-Displacement Curve
-   초기 강성 구간
-   Connector 이탈 시점
-   Pull 종료 후 잔류 변위

## 주의

기존 수동 Grip-Pull에서 관찰된 **최대 약 10 N 차이**는 2\~3회 수준의
예비 관찰값이다.\
현재 PASS/FAIL Threshold로 사용하지 않는다.

------------------------------------------------------------------------

# 15. V11 - 판정 로직 개발

반복시험 데이터가 확보된 이후 정상/이상 시편의 분포를 비교하여 판정
Feature를 선정한다.

판정 기준은 다음 순서로 개발한다.

1.  Raw Force/Displacement 확인
2.  반복시험 분산 확인
3.  Feature 추출
4.  정상/이상 분포 비교
5.  Threshold 후보 설정
6.  미사용 데이터로 재검증
7.  오검출/미검출 분석

단일 Peak Force만으로 충분하지 않을 경우 Force-Displacement 특성을 함께
사용한다.

------------------------------------------------------------------------

# 16. V12 - Cable Inspection 후속 검토

Connector Grip-Pull과 별도로 Cable 자체의 상태를 검사해야 할 경우 Cable
Inspection Point를 정의한다.

Vision이 없는 현재 시스템에서는 Connector-Cable 경계를 직접 인식할 수
없으므로 다음 방식을 검토한다.

-   Connector 기준 Nominal Offset
-   Cable 전용 Inspection Offset
-   별도 Inspection Point
-   제한된 Search Range

Connector Inspection과 Cable Inspection을 하나의 Offset으로 통합할 수
있는지는 실제 경계 검출 가능성을 확인한 후 판단한다.

------------------------------------------------------------------------

# 17. 검증 데이터 관리 원칙

Adaptive Grip 데이터와 체결검사 데이터는 목적이 다르므로 분리하여
관리한다.

  -----------------------------------------------------------------------
  데이터 구분             목적                    PASS/FAIL 직접 사용
  ----------------------- ----------------------- -----------------------
  Soft Grip Force         파지상태 확인           원칙적으로 사용 안 함

  Micro-Wiggle Response   Alignment               사용 안 함

  Fine Alignment 결과     Adaptive Grip 성공 여부 검사 전 조건으로 사용

  Hard Grip Stability     파지 유효성             검사 수행 가능 여부
                                                  판단

  Axial Pull Force        체결상태 검사           사용

  TCP Displacement        체결상태 검사           사용

  Force-Displacement      체결상태 검사           후보
  Feature                                         
  -----------------------------------------------------------------------

------------------------------------------------------------------------

# 18. 단계별 Gate

다음 단계로 넘어가기 위한 Gate를 둔다.

  Gate                통과 조건
  ------------------- ----------------------------------------------
  G1 Entry            Ready -\> Entry가 반복 가능하고 간섭이 없음
  G2 Adaptive Entry   Depth 오차에 대한 보정 방식이 결정됨
  G3 Soft Grip        Micro-Wiggle 가능한 파지 조건 확보
  G4 Alignment        위치 편차에 따른 Response와 보정 가능성 확인
  G5 Hard Grip        Pull 중 Slip 없는 조건 확보
  G6 Logging          Force/TCP 데이터 동기 기록 확인
  G7 Repeat Test      정상/이상 시편 반복 데이터 확보
  G8 Judgment         판정 Feature 및 Threshold 후보 도출

Gate를 통과하지 못한 경우 이후 시험의 결과를 판정 기준 확정에 사용하지
않는다.

------------------------------------------------------------------------

# 19. 최종 산출물

본 작업검증을 통해 다음 산출물을 확보한다.

1.  Inspection Recipe / Point 데이터 구조
2.  Adaptive Grip 동작 Sequence
3.  Depth Compensation 방식
4.  Soft Grip 조건
5.  Micro-Wiggle 시험 결과
6.  Fine Alignment 로직
7.  Hard Grip 및 Grip Stability 조건
8.  Grip-Pull 반복시험 Dataset
9.  Force-Displacement Feature 분석
10. PASS/FAIL Threshold 후보
11. Inspection Point 변경 적용성 결과
12. BRD 및 향후 SRS/SDD에 반영할 확정 요구사항

------------------------------------------------------------------------

# 20. 현재 우선순위

현재 가장 우선적으로 검증해야 할 구간은 다음과 같다.

> **Depth Compensation -\> Soft Grip -\> Micro-Wiggle -\> Fine
> Alignment**

이 구간이 실제 위치 편차를 흡수할 수 있어야 CCCIS의 Adaptive Grip 및
Flexible Inspection 개념이 기술적으로 성립한다.

이후 검증 순서는 다음과 같다.

> **Hard Grip -\> Grip Stability -\> Grip-Pull Logging -\> Repeated
> Grip-Pull -\> Judgment Logic**

따라서 다음 구현/실험 단계에서는 Grip-Pull Threshold를 먼저 확정하기보다
**Adaptive Grip 검증시험 v0.1**을 선행한다.
