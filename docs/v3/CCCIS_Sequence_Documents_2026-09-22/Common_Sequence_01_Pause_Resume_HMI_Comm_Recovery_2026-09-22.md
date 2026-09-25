# Common Sequence #01 - Pause / Resume & HMI Communication Recovery

**프로젝트:** CCCIS (Contact-based Cable Connection Inspection System)  
**환경:** Doosan M0609 + OnRobot RG2 / No-Vision Phase  
**작업 단위:** Recipe 1회 실행 = Job 1개  
**외부 Trigger:** HMI 통신 기반 START / PAUSE / RESUME / STOP / HOME_RETURN  
**작성 기준일:** 2026-09-22


## 1. 목적

HMI Pause Trigger 또는 작업 중 HMI 통신 단절 시 Robot을 안전한 일시정지 상태로 전환하고 Job Context를 보존한 뒤 명시적인 HMI RESUME으로 작업을 재개한다.

## 2. 설계 의도

- PAUSE는 STOP과 달리 Job을 종료하지 않는다.
- 정확한 순간 위치에서 정지/재개하는 대신 각 하위 Sequence의 Safe Pause Point 또는 원자 동작 완료점에서 PAUSED로 전환한다.
- HMI 통신이 복구되어도 자동 Resume하지 않는다.

## 3. 진입 조건

- RUNNING 중 HMI PAUSE Trigger 수신 또는 HMI Comm Loss 검출
- E-STOP은 본 Sequence가 아니라 Safety 계층 처리

## 4. Sequence Flow

```text
[USER PAUSE]
RUNNING
  | HMI PAUSE
  v
PAUSE_REQUEST
  |
  v
Lower Sequence Safe Pause
  |
  v
PAUSED
  | HMI RESUME
  v
Resume Point
  |
  v
RUNNING

[HMI COMM LOST]
RUNNING
  |
  v
Pause Safe Processing
  |
  v
PAUSED / COMM_LOST
  |
  v
Communication Recovery Wait
  +-- TIMEOUT --> COMM_ERROR --> Job Termination
  +-- RECOVERED --> remain PAUSED
                       |
                       v
                  HMI Context Restore
                       |
                       | HMI RESUME
                       v
                    RUNNING
```

## 5. Flow 용어 설명

| 용어 | 설명 |
|---|---|
| Safe Pause Point | 하위 Sequence가 안전하게 정지 가능한 지점 |
| Resume Point | PAUSED에서 재개할 하위 Sequence 기준점 |
| COMM_LOST | HMI Heartbeat/통신 유지 실패 |
| COMM_ERROR | Timeout 내 복구되지 않아 Job 지속 불가 상태 |

## 6. 세부 동작 및 판단 조건

- PAUSE 중 `job_id`, Recipe Snapshot, Execution Index, Current Point, Sequence State, Pending Judgment 상태 보존
- 통신 복구만으로 Motion 자동 재개 금지
- STOP Trigger가 들어오면 Context 폐기 후 Resume 불가

## 7. 정상 종료 조건

HMI RESUME 수신 후 정의된 Resume Point에서 RUNNING 복귀.

## 8. 비정상 / 예외 처리

- Comm Timeout -> COMM_ERROR -> Job Termination
- Pause 처리 중 Robot/System Error -> ERROR
- E-STOP -> Safety 우선
- STOP -> Job 종료

## 9. 상위·하위 Sequence Interface

**상위:** #00 / HMI Communication Monitor  
**하위:** 현재 실행 중인 Sequence의 Safe Pause / Resume Point

## 10. 코드 구현 포인트

- HMI Heartbeat Monitor와 Sequence State Machine 분리
- Context Snapshot 구조 정의
- 각 Sequence는 `pause_safe_state`를 명시적으로 노출하도록 설계
