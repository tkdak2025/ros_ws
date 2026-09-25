> 이 문서는 이전 설계·작업 기록입니다. 현재 기준은 [v4 문서 안내](../../v4/00_문서안내_v4.md)이며, 이후 변경 내용은 [최종결론](../../작업내역/18_최종결론_2026-09-25.md)을 참고하세요. 아래 본문은 이력으로 보존합니다.

> 2026-09-23 설계·구현 정합성 갱신: [05 보류항목 반영 결과](../../작업내역/05_시퀀스_보류항목_반영결과_2026-09-23.md)를 함께 적용한다. 같은 이름의 기존 PDF는 갱신 전 보존본이다.

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
- Work Area 내부에서는 Cable을 실제로 잡고 있는지 추정하지 않고 Safe Escape 수행. 현재 Tool 접근축을 거슬러 직선 후퇴하는 목적은 인접한 선, 특히 LAN 공유기처럼 촘촘한 배선과의 횡방향 충돌·간섭을 줄이는 것이다.
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
- 그리퍼는 25 mm Open 폭을 먼저 명령한 뒤 힘을 맞추고, 실측 폭이 목표 허용오차 이내인지 확인한 뒤 탈출한다. `gripper_busy`는 기록만 하고 탈출 허용 조건에는 사용하지 않는다. RG2의 힘 증감 명령은 현재 폭 목표를 재전송하므로 이전 Hard Close 목표가 반복되지 않게 한다.
- 현재 TCP의 XYZ에서 Tool −Z로 설정 거리(현재 30 mm)만큼 직선 이동한다. TCP 자세는 유지하고 TARGET_REACHED를 확인해야 완료다. 실패 후 Access/Home으로 건너뛰지 않는다.
- 내부: Open → Escape → Work Access → 0도 Home. 외부: 0도 Home 직접 복귀.
- home_joint_tolerance_deg 기본 0.1도. Tool 축/경로/허용오차 누락은 초기화에서 거절한다.
- work_area는 Home 진입 시 내부/외부 분기에만 사용한다. 후퇴 뒤 영역 밖인지 검사하지 않고 별도 contact_area도 추가하지 않는다. 30 mm의 실제 적합성과 이후 Access 경로는 실물 확인 대상이다.

구체화 근거: 사용자는 Tool 역방향 후퇴를 기존 Safe Escape 설계의 구체화로 설명했다. [06 전체 재대조 결과](../../작업내역/06_시퀀스_전체_재대조_결과_2026-09-23.md)를 따른다.

## 12. Work Finish의 검증된 Access 예외 (2026-09-25)

정상 Work Finish는 먼저 `work_Access_safe_pose`로 이동해 도달을 확인한다. 이 Pose는 `work_area` 내부에 있으므로 일반 Home 분기를 다시 적용하면 Open→Tool −Z 30 mm→Access 재이동이 발생한다. 사용자 결정에 따라 이 경우에는 Home 직전에 현재 TCP의 위치·자세가 Work Access 허용오차(위치 0.5 mm, 자세 1도) 안인지 재확인하고, 검증되면 설정된 0도 Home 경로로 직접 MoveJ한다. 재확인 실패 시 직접 Home을 중단한다. START 전 및 수동 HOME은 일반 내부/외부 분기를 유지한다.

이는 Work Access에서의 중복 후퇴만 제거한다. Work Access→Home의 MoveJ 중간 경로, 30 mm 후퇴 경로, Open 25 mm 해제 여부는 실물 확인 대상이다.
