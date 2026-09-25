> 이 문서는 이전 설계·작업 기록입니다. 현재 기준은 [v4 문서 안내](../../v4/00_문서안내_v4.md)이며, 이후 변경 내용은 [최종결론](../../작업내역/18_최종결론_2026-09-25.md)을 참고하세요. 아래 본문은 이력으로 보존합니다.

> 2026-09-23 설계·구현 정합성 갱신: [05 보류항목 반영 결과](../../작업내역/05_시퀀스_보류항목_반영결과_2026-09-23.md)를 함께 적용한다. 같은 이름의 기존 PDF는 갱신 전 보존본이다.

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
movej(Point1 entry_pose)
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
movej(Next entry_pose)
    |
    v
POINT_TRANSITION_DONE
```

## 5. Flow 용어 설명

| 구간 | Motion | 이유 |
|---|---|---|
| safe/ready -> ready | `movej` | 장거리 자세 전환 효율 |
| ready -> entry | `movej` | 교시된 Entry pose로 접근 |

## 6. 세부 동작 및 판단 조건

- 매 Point마다 `work_Access_safe_pose`로 돌아가지 않는다.
- Point N `entry_pose`에서 Point N+1 `ready_pose`로 직접 이동하지 않는다.
- Point Transition은 #06 Judgment 완료 또는 HMI 결과 통신을 기다리지 않는다.
- Motion Timeout은 충분히 넓게 설정하는 Guard이며 자동 Retry는 하지 않는다.

## 7. 정상 종료 조건

Entry MoveJ 결과 기록 후 #04 Adaptive Grip을 호출한다. 목표 미도달은 아래 운영 정책에 따라 진행을 허용한다.

## 8. 비정상 / 예외 처리

- Robot/Safety Fault -> 상위 Error 처리
- 일반 이동 오류 -> Transition 실패. Entry 목표 확인 시간 초과는 allow_incomplete 정책 적용, 자동 Retry 없음

## 9. 상위·하위 Sequence Interface

**입력:** `target_point.ready_pose`, `target_point.entry_pose`  
**출력:** `POINT_TRANSITION_DONE | POINT_TRANSITION_FAIL`  
**다음:** #04 Adaptive Grip

## 10. 코드 구현 포인트

- 첫 Point 여부는 `execution_index == 0`로 판단 가능
- Pose frame과 Tool/TCP Configuration 일관성 검증
- `movej()`와 `movel()` Wrapper에서 timeout/error 공통 처리

## 11. 2026-09-23 도달 확인

Ready pose에서 Entry pose로의 접근은 MoveJ(allow_incomplete=True)이며, 목표 확인 시간 초과 시 감속 정지하고 미도달 결과를 기록한 뒤 후속 단계를 진행한다. Entry 최대거리 25 mm 검증은 유지하고, Pull 거리 및 Entry/Pull 시간은 레시피의 유한한 양수 값을 사용한다. PR #10에서 추가한 Pull 25 mm·시간 10 s 상한은 제거했다. 서비스 응답 오류 등 예외는 상위로 전달한다.

## 접근과 진입의 용어

Ready pose → Entry pose는 **접근(approach)**이다. Entry pose에서 케이블 방향 Tool +Z로 Soft Grip과 함께 움직이는 구간만 **진입(entry)**이라 부른다. #03은 접근, #04는 진입을 담당한다.
