# Sequence #03 - Point Transition Sequence

**프로젝트:** CCCIS (Contact-based Cable Connection Inspection System)  
**환경:** Doosan M0609 + OnRobot RG2 / No-Vision Phase  
**작업 단위:** Recipe 1회 실행 = Job 1개  
**외부 Trigger:** HMI 통신 기반 START / PAUSE / RESUME / STOP / HOME_RETURN  
**작성 기준일:** 2026-09-22


## 1. 목적

현재 위치에서 대상 Inspection Point의 `ready_pose`를 거쳐 `entry_pose`까지 안전하게 이동하여 Adaptive Grip을 시작할 수 있는 상태를 만든다.

## 2. 설계 의도

- Point 간 전환 기준을 ready_pose로 통일한다.
- Point별 직접 경로를 별도 Teaching하지 않고 Recipe Pose를 공통 알고리즘으로 사용한다.
- 첫 Point와 이후 Point의 출발 위치 차이만 구분한다.

## 3. 진입 조건

- 첫 Point: Robot이 `work_Access_safe_pose`에 위치
- 이후 Point: 이전 Point의 `ready_pose` 복귀 완료
- 다음 Enabled Point가 Execution List에 존재
- Robot Operability 정상

## 4. Sequence Flow

```text
[First Point]
work_Access_safe_pose
    |
    v
movej(Point1 ready_pose)
    |
    v
movel(Point1 entry_pose)
    |
    v
POINT_TRANSITION_DONE

[Next Point]
Current Point ready_pose
    |
    v
movej(Next ready_pose)
    |
    v
movel(Next entry_pose)
    |
    v
POINT_TRANSITION_DONE
```

## 5. Flow 용어 설명

| 구간 | Motion | 이유 |
|---|---|---|
| safe/ready -> ready | `movej` | 장거리 자세 전환 효율 |
| ready -> entry | `movel` | 검사 Point 진입 방향/직선성 유지 |

## 6. 세부 동작 및 판단 조건

- 매 Point마다 `work_Access_safe_pose`로 돌아가지 않는다.
- Point N `entry_pose`에서 Point N+1 `ready_pose`로 직접 이동하지 않는다.
- Point Transition은 #06 Judgment 완료 또는 HMI 결과 통신을 기다리지 않는다.
- Motion Timeout은 충분히 넓게 설정하는 Guard이며 자동 Retry는 하지 않는다.

## 7. 정상 종료 조건

대상 Point의 `entry_pose` 도달 확인 후 #04 Adaptive Grip 호출 가능.

## 8. 비정상 / 예외 처리

- Robot/Safety Fault -> 상위 Error 처리
- Motion Timeout -> Transition 실패, 자동 Retry 없음

## 9. 상위·하위 Sequence Interface

**입력:** `target_point.ready_pose`, `target_point.entry_pose`  
**출력:** `POINT_TRANSITION_DONE | POINT_TRANSITION_FAIL`  
**다음:** #04 Adaptive Grip

## 10. 코드 구현 포인트

- 첫 Point 여부는 `execution_index == 0`로 판단 가능
- Pose frame과 Tool/TCP Configuration 일관성 검증
- `movej()`와 `movel()` Wrapper에서 timeout/error 공통 처리
