> 이 문서는 이전 설계·작업 기록입니다. 현재 기준은 [v4 문서 안내](../../v4/00_문서안내_v4.md)이며, 이후 변경 내용은 [최종결론](../../작업내역/18_최종결론_2026-09-25.md)을 참고하세요. 아래 본문은 이력으로 보존합니다.

# CCCIS Code Implementation Handoff

**프로젝트:** CCCIS (Contact-based Cable Connection Inspection System)  
**환경:** Doosan M0609 + OnRobot RG2 / No-Vision Phase  
**작업 단위:** Recipe 1회 실행 = Job 1개  
**외부 Trigger:** HMI 통신 기반 START / PAUSE / RESUME / STOP / HOME_RETURN  
**작성 기준일:** 2026-09-22


## 1. 구현 대상 문서

현재 코드 기준 Sequence는 다음 9개 문서로 고정한다.

| ID | Sequence | 역할 |
|---|---|---|
| #00 | Main Work | Recipe 1회 Job 전체 상태 제어 |
| #01 | Work Initialize | START 전 상태/Recipe 검증 |
| #02 | Home Return | 공통 안전 원점복귀 |
| #03 | Point Transition | ready_pose -> entry_pose 진입 |
| #04 | Adaptive Grip | Soft Entry + Hard Grip + Width 기준값 |
| #05 | Pull Inspection | Motion 기반 Pull + 측정 |
| #06 | Inspection Judgment & Work Monitoring | PASS/FAIL/MISSING + 진행상태 관리 |
| #07 | Work Finish | Job 종료 가능 여부 검증 |
| Common #01 | Pause/Resume & HMI Recovery | Context 보존 일시정지/통신복구 |

## 2. 최상위 구현 원칙

```text
External Control Trigger = HMI
Internal Sequence Transition = Automatic State Machine
Job Unit = One Selected Recipe Execution
No Scheduler / No Recipe Queue in current phase
```

## 3. 권장 Runtime Data Model

```python
JobContext:
    job_id
    recipe_id
    recipe_snapshot
    execution_list
    execution_index
    state
    start_time
    end_time
    pending_judgments
    point_runtime

PointRuntime:
    point_id
    motion_status
    adaptive_grip_status
    grip_width_hard
    pull_status
    peak_pull_force
    pull_displacement
    termination_reason
    grip_width_change
    judgment_status
    result
    reason
    log_saved
```

## 4. 권장 Enum

```text
SystemState:
  SYSTEM_READY, RUNNING, PAUSED, STOPPED, ERROR

SequenceStatus:
  IDLE, RUNNING, SUCCESS, FAIL, INCOMPLETE

JudgmentStatus:
  PENDING, COMPLETED, ERROR

InspectionResult:
  PASS, FAIL, MISSING

PullTermination:
  FORCE_LIMIT, MAX_DISTANCE, TIMEOUT, MOTION_ERROR
```

## 5. HMI Trigger / Message Contract

External Trigger 후보:

```text
START(recipe_id)
PAUSE
RESUME
STOP
HOME_RETURN
```

Status/Result 후보:

```text
SYSTEM_STATUS
JOB_STATUS
POINT_STATUS
INSPECTION_RESULT
ERROR_STATUS
```

중요: #07 완료 후 Work Access에서 SYSTEM_READY로 대기한다. #02 Home Return은 별도 HOME_RETURN 명령으로 실행한다.

## 6. 구현 순서 권장

1. Data Model / Enum / Recipe Loader
2. Robot Motion Wrapper (`movej`, `movel`, wait/stop, pose/force read)
3. RG2 Wrapper (soft/hard/open, actual width read)
4. #03 Point Transition
5. #04 Adaptive Grip
6. #05 Pull Inspection + Raw Logger
7. #06 Judgment Worker + Point Runtime
8. #01 Work Initialize
9. #02 Home Return
10. #07 Work Finish
11. #00 Main Work State Machine
12. Common #01 Pause/Resume/HMI Recovery
13. HMI Interface integration

## 7. 시퀀스 간 핵심 데이터 흐름

```text
#01
Recipe Snapshot / Execution List
   |
   v
#03 -> #04 -> #05 --------------------+
             |                         |
             | grip_width_hard         | peak_force
             |                         | displacement
             |                         | termination_reason
             +-------------------------| grip_width_change
                                       v
                                      #06
                                  Result + Monitoring
                                       |
                                       v
                                      #07
                               Completion Verification
                                       |
                                       v
                                      #02
                                  Home Return
```

## 8. 현재 확정 Parameter

```yaml
system:
  max_escape_distance_mm: 30.0

adaptive_grip:
  max_entry_distance_mm: 25.0
  entry_timeout_sec: 10.0
  entry_force_guard_n: 5.0   # candidate / validation required

pull:
  max_distance_mm: 25.0
  timeout_sec: 10.0
  speed_mm_s: TBD            # 5 or 10 candidate
  required_force_n:
    LAN: 20.0
    USB: 12.0

judgment:
  normal_displacement_limit_mm: 5.0
  slip_width_threshold_mm: TBD
```

## 9. 코드 시작 전 남은 TBD

Blocking하지 않아도 되는 TBD:

- Pull Speed 5 vs 10 mm/s
- Slip Width Threshold
- RG2 Width 정상 변동 범위
- Entry Force Guard 5 N 최종 검증
- Home Reached Tolerance
- HMI Heartbeat/Timeout 값
- 각 Sequence Safe Pause/Resume Point

코드 구조 자체를 막는 TBD는 아니므로 Parameter/TODO로 두고 구현 시작 가능하다.

## 10. 테스트 시작점

최소 Unit/Integration Test 순서:

```text
T-A: Point Transition pose 이동
T-B: Adaptive Grip + grip_width_hard 취득
T-C: Pull Force/Displacement/Width Logging
T-D: LAN Force Limit 20 N Stop
T-E: USB Force Limit 12 N Stop
T-F: PASS <= 5 mm 판정
T-G: FAIL > 5 mm 판정
T-H: Slip -> MISSING 판정
T-I: Async Judgment 중 Next Point 진행
T-J: Last Point -> work_Access_safe_pose -> Work Finish -> SYSTEM_READY
```

## 11. 구현 시 주의사항

- `5 mm`는 Pull Motion Stop Limit가 아니다.
- `25 mm`는 Pull Motion Max Distance다.
- Required Pull Force 미도달은 독립적인 Stop Condition가 아니다.
- `MISSING`은 현재 Grip Slip 중심으로 정의한다.
- Timeout/System Fault를 억지로 PASS/FAIL/MISSING으로 매핑하지 않는다.
- #06은 비동기지만 #07의 Job Completion에는 Blocking 조건이다.
- FAIL/MISSING Point가 존재해도 모든 Point가 정상 처리되었다면 Work Finish는 SUCCESS 가능하다.
