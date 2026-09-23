> 2026-09-23 설계·구현 정합성 갱신: [05 보류항목 반영 결과](../05_시퀀스_보류항목_반영결과_2026-09-23.md)를 함께 적용한다. 같은 이름의 기존 PDF는 갱신 전 보존본이다.

# Sequence #02 - Home Return Sequence

**프로젝트:** CCCIS (Contact-based Cable Connection Inspection System)  
**환경:** Doosan M0609 + OnRobot RG2 / No-Vision Phase  
**작업 단위:** Recipe 1회 실행 = Job 1개  
**외부 Trigger:** HMI 통신 기반 START / PAUSE / RESUME / STOP / HOME_RETURN  
**작성 기준일:** 2026-09-22


## 1. 목적

START 전 위치 정규화, 정상 작업 완료, 또는 HMI의 명시적 HOME_RETURN 요청 시 Robot을 안전하게 `home_pose`로 복귀시키는 공통 Sequence다.

## 2. 설계 의도

- Work Area 내부에서는 비전이 없으므로 Cable Interaction 가능성을 보수적으로 가정한다.
- TCP가 Work Area 내부면 바로 home_pose로 이동하지 않고 Grip Relaxation + Safe Escape를 수행한다.
- Home Return은 호출 Context와 독립적인 공통 Sequence이며, 성공 후 상태 전이는 호출자가 결정한다.

## 3. 진입 조건

- 상위 Sequence 또는 HMI에서 HOME_RETURN 요청
- Safety 상태가 Motion 허용
- Robot Operability Check 가능

## 4. Sequence Flow

```text
HOME_RETURN REQUEST
    |
    v
Robot Operability Check
    |
    v
Acquire Current TCP Pose
    |
    v
Work Area Boundary Check
    |
    +-- INSIDE
    |     |
    |     v
    |  Grip Relaxation
    |     |
    |     v
    |  Safe Escape
    |  - reverse tool approach axis
    |  - max_escape_distance <= 30 mm
    |     |
    |     v
    |  work_Access_safe_pose
    |
    +-- OUTSIDE
          |
          v
      Safe Home Route
          |
          v
       home_pose
          |
          v
Home Reached Verification
          |
          v
   SUCCESS / FAIL
```

## 5. Flow 용어 설명

| 용어 | 설명 |
|---|---|
| Work Area Boundary | BASE 좌표계 기준 Cable/Fixture Interaction 가능 3D Cuboid |
| Grip Relaxation | 25 mm Open 후 실측 폭 허용오차 및 동작 종료 확인 |
| Safe Escape | 현재 Tool 자세에서 접근축 반대 방향으로 30 mm 후퇴하고 목표 도달을 확인하는 동작 |
| Safe Home Route | 설정된 safe_home_route. 현장 요청으로 현재는 home_pose 한 개, 전체 관절 0도로 직접 MoveJ |

## 6. 세부 동작 및 판단 조건

- 1차 구현은 TCP Position으로 Work Area Inside/Outside 판정
- Work Area 내부에서는 Cable을 실제로 잡고 있는지 추정하지 않고 Safe Escape 수행
- `max_escape_distance_mm = 30.0`을 현재 후퇴거리로 사용한다. 영역 경계까지 거리를 계산하지 않는다
- Safe Escape 후 `work_Access_safe_pose` 경유

## 7. 정상 종료 조건

`home_pose` 도달 검증 성공 후 호출자에게 `HOME_RETURN_SUCCESS` 반환.

## 8. 비정상 / 예외 처리

- Robot Operability 실패 -> Motion 시작 금지
- Safe Escape/Home Motion 실패 -> 임의 추가 경로 생성 금지
- Safety Stop/E-Stop -> 복귀 Motion 강제 수행 금지

## 9. 상위·하위 Sequence Interface

| 호출 Context | 성공 후 처리 |
|---|---|
| START | home_pose 정규화 후 work_Access_safe_pose로 이동하여 작업 시작 |
| Work Finish | home_pose 도달 후 Operating Stop / SYSTEM_READY |
| HMI HOME_RETURN | 복귀 완료 후 대기상태 |

## 10. 코드 구현 포인트

- `is_inside_work_area(tcp_pose)` 독립 함수
- `safe_escape()`는 Tool approach axis 역방향 Vector 계산을 명시적으로 분리
- Home 도달 tolerance는 Parameter화

## 11. 2026-09-23 확정 설정

- 접근축은 Tool +Z, Escape는 현재 TCP 자세 기준 Tool −Z다.
- 그리퍼는 25 mm로 Open하고 busy=false 및 목표 폭 허용오차 이내인지 확인한 뒤 탈출한다.
- 현재 TCP의 XYZ에서 Tool −Z로 설정 거리(현재 30 mm)만큼 직선 이동한다. TCP 자세는 유지하고 TARGET_REACHED를 확인해야 완료다. 실패 후 Access/Home으로 건너뛰지 않는다.
- 내부: Open → Escape → Work Access → 0도 Home. 외부: 0도 Home 직접 복귀.
- home_joint_tolerance_deg 기본 0.1도. Tool 축/경로/허용오차 누락은 초기화에서 거절한다.
- work_area는 Home 진입 시 내부/외부 분기에만 사용한다. 후퇴 뒤 영역 밖인지 검사하지 않고 별도 contact_area도 추가하지 않는다. 30 mm의 실제 적합성과 이후 Access 경로는 실물 확인 대상이다.

구체화 근거: 사용자는 Tool 역방향 후퇴를 기존 Safe Escape 설계의 구체화로 설명했다. [06 전체 재대조 결과](../06_시퀀스_전체_재대조_결과_2026-09-23.md)를 따른다.
