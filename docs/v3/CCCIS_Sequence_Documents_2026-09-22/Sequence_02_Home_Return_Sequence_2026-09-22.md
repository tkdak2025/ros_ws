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
| Grip Relaxation | Safe Escape 전 Cable 손상/걸림 위험을 줄이기 위한 Grip 완화 |
| Safe Escape | Tool 접근축 역방향으로 작업영역을 벗어나는 동작 |
| Safe Home Route | Work Area 외부에서 home_pose까지의 검증된 복귀 경로 |

## 6. 세부 동작 및 판단 조건

- 1차 구현은 TCP Position으로 Work Area Inside/Outside 판정
- Work Area 내부에서는 Cable을 실제로 잡고 있는지 추정하지 않고 Safe Escape 수행
- `max_escape_distance_mm = 30.0`은 상한값이며 30 mm 강제 이동이 아님
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
