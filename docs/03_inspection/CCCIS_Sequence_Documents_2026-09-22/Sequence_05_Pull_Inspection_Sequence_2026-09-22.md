> 이 문서는 이전 설계·작업 기록입니다. 현재 기준은 [v4 문서 안내](../../v4/00_문서안내_v4.md)이며, 이후 변경 내용은 [최종결론](../../작업내역/18_최종결론_2026-09-25.md)을 참고하세요. 아래 본문은 이력으로 보존합니다.

> 2026-09-23 설계·구현 정합성 갱신: [05 보류항목 반영 결과](../../작업내역/05_시퀀스_보류항목_반영결과_2026-09-23.md)를 함께 적용한다. 같은 이름의 기존 PDF는 갱신 전 보존본이다.

# Sequence #05 - Pull Inspection Sequence

**프로젝트:** CCCIS (Contact-based Cable Connection Inspection System)  
**환경:** Doosan M0609 + OnRobot RG2 / No-Vision Phase  
**작업 단위:** Recipe 1회 실행 = Job 1개  
**외부 Trigger:** HMI 통신 기반 START / PAUSE / RESUME / STOP / HOME_RETURN  
**작성 기준일:** 2026-09-22


## 1. 목적

Hard Grip 상태에서 Point별 체결 반대방향으로 `movel` Pull을 수행하면서 Force, Displacement, RG2 Width를 측정하고 대표 결과값을 #06 Inspection Judgment로 비동기 전달한다.

## 2. 설계 의도

- Pull은 Force Control이 아니라 Motion 기반 `movel`이다. Entry 자세의 Tool +Z 진입축 반대(−Z)로 직선 이동하여 인접 케이블 쪽의 횡방향 간섭을 줄인다.
- Force는 Target Control 값이 아니라 Motion Stop 기준이다.
- Required Pull Force에 도달하면 Pull을 정지한다.
- Required Pull Force 미도달 자체는 정지조건이 아니다.
- 정상 허용 이동량 5 mm는 Judgment 기준이며 Pull Motion 정지조건이 아니다.
- 5 mm를 초과하더라도 Force Limit/Max Distance/Timeout까지 계속 Pull할 수 있다.

## 3. 진입 조건

- #04 Adaptive Grip 완료
- Hard Grip 상태 유지
- `soft_width_mm` 저장 완료
- Point Recipe의 Pull 방향/Force Limit 유효

## 4. Sequence Flow

```text
PULL_INSPECTION_START
    |
    v
Pull 기준 상태 저장
- TCP start pose
- soft_width_mm
- start time
    |
    v
Pull movel 시작
- Direction = opposite fastening direction
- Speed = common parameter (5 or 10 mm/s, TBD)
- Max Distance = recipe.max_distance_mm (현재 예제 25 mm)
- Force Limit = LAN 15 N / USB 12 N
- Timeout = recipe.timeout_s (현재 예제 10 s)
    |
    v
Realtime Measurement
- Force
- TCP Displacement
- RG2 Width
- Time
    |
    v
First Termination Condition
+-- FORCE_LIMIT
+-- MAX_DISTANCE recipe.max_distance_mm
+-- TIMEOUT recipe.timeout_s
    |
    v
Pull Motion Stop
    |
    v
Generate Summary
- peak_pull_force
- pull_displacement
- termination_reason
- grip_width_change
    |
    +----------> async #06 Inspection Judgment
    |
    v
Soft Grip Open
    |
    v
entry_pose return
    |
    v
ready_pose return
    |
    v
PULL_INSPECTION_DONE -> Next #03 Point Transition
```

## 5. Flow 용어 설명

| 항목 | 정의 |
|---|---|
| Required Pull Force | 정상 체결 여부를 시험하기 위해 도달해야 하는 Pull Force. LAN 15 N, USB 12 N |
| MAX_DISTANCE | 레시피의 Motion 거리 제한. 정상 허용 이동량 5 mm와 별개 |
| pull_displacement | Pull 시작 Pose 기준 Robot/TCP 이동량 |
| grip_width_change | Soft 종료 실측 폭 대비 Pull 최소 실측 폭의 부호 있는 차이(기록용) |

## 6. 세부 동작 및 판단 조건

- Force Limit: LAN 15 N, USB 12 N
- Max Distance: 레시피 값 (현재 예제 25 mm)
- Timeout: 레시피 값 (현재 예제 10 s)
- Pull Speed: 5 또는 10 mm/s 후보, 코드 검증 후 확정
- 5 mm 초과는 Pull 정지조건이 아니며 #06에서 FAIL 판단 근거가 됨
- Pull 중 Force는 지속적으로 측정되며 기준 Force에 도달한 순간 Motion을 정지
- Raw time-series는 Logging에 보존

#06 전달값:

1. `point_id`
2. `peak_pull_force`
3. `pull_displacement`
4. `termination_reason`
5. `grip_width_change`

## 7. 정상 종료 조건

- Pull Motion이 정의된 종료조건 중 하나로 정지
- 대표 측정값 생성
- #06 Async Queue/Task에 Result Data 전달 성공
- Soft Grip Open 후 entry_pose -> ready_pose 복귀

## 8. 비정상 / 예외 처리

- Robot/Tool/Safety Fault -> System Error
- `TIMEOUT`은 제품 결과 코드가 아니라 Pull Sequence의 비정상/미완료 가능 상태다. Grip Slip 여부와 함께 #06 Work Monitoring에 전달하여 Job 완료 가능 여부를 판단한다.
- 폭 자체는 #05에서 판정하지 않고 Soft 기준 폭, Pull 최소 폭, Force/Displacement를 #06에 전달

## 9. 상위·하위 Sequence Interface

**상위:** #04 Adaptive Grip  
**병렬 출력:** #06 Inspection Judgment  
**Robot Motion 다음 단계:** Soft Grip Open -> entry_pose -> ready_pose -> #03 Next Point

## 10. 코드 구현 포인트

- Pull Loop에서 Force/Displacement/Width Sampling 주기 정의
- `termination_reason` Enum 권장: `FORCE_LIMIT`, `MAX_DISTANCE`, `TIMEOUT`, `MOTION_ERROR`
- Motion Stop과 Judgment는 분리
- 비동기 Judgment Queue 전송 실패는 Work Monitoring Error로 추적

## 11. 2026-09-23 조건 확정

LAN은 사용자 지시에 따라 15 N을 유지한다. USB 12 N과 WIRING_HARNESS 15 N은 별도 레시피 조건이다. 속도·힘·변위 기준은 전송된 레시피/snapshot을 사용하며 종류 문자열로 덮어쓰지 않는다. Entry 진입은 MoveJ(allow_incomplete=True)이며, 목표 확인 시간 초과 시 감속 정지하고 미도달 결과를 기록한 뒤 후속 단계를 진행한다. Entry 최대거리 25 mm 검증은 유지하고, Pull 거리 및 Entry/Pull 시간은 레시피의 유한한 양수 값을 사용한다. PR #10에서 추가한 Pull 25 mm·시간 10 s 상한은 제거했다. 5 mm는 판정 기준이며 모션 정지 조건이 아니다. 감속 정지 완료까지의 힘·폭 샘플을 포함한다.

## 접촉 Pull 거리 해석

Tool −Z Pull의 `max_distance_mm`는 이동 상한이다. 힘 한계에 먼저 도달하면 실제 이동거리가 짧아도 `FORCE_LIMIT`로 판정한다. 로봇이 힘·거리 한계 전에 정지했다면 `STOPPED_SHORT`로 실제 변위를 기록하고 해당 포인트는 `SYSTEM_ERROR` 판정으로 처리한다. 목표 거리 미도달 자체 때문에 Job을 중단하지 않으며, Open과 복귀에 성공하면 다음 포인트로 진행한다. 움직이는 중 시간 제한에 도달하면 로봇을 감속 정지시키고 `TIMEOUT`으로 기록한다.
