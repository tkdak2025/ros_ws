# HMI 연동 가이드 (동작 코드 담당자용)

동작 코드에 **몇 줄만 넣으면** HMI 의 검사 시작 / 일시정지 / 이어하기 / STOP / Home / 결과 표시가 붙는다.
HMI 화면, 토픽, 메시지 형식은 몰라도 된다 — `ProgressReporter` 하나만 쓰면 된다.

기준 문서: CCCIS Sequence #0 Main Work, #1 Work Initialize, #2 Home Return, Common Sequence #1 (v0.2).

## 1. 구조

```
[HMI 화면] --명령--> [동작 코드 + ProgressReporter] --두산 API--> 로봇
     ^                        |
     |                        | 진행 상황 · 결과
     +---- status ---- [robot_monitor_node] (로봇 값과 합쳐 HMI 로 보냄)
```

- 동작 코드는 **status 를 직접 보내지 않는다.** `ProgressReporter` 의 함수만 부른다.
- HMI 는 `ros2 launch cable_hmi hmi_monitor.launch.py` 로 띄운다 (HMI + 모니터 노드 + 결과 저장 노드).
- 동작 코드는 **한 번에 하나만** 실행한다.

## 2. 준비

```bash
sod && source ~/ros_ws/install/setup.bash     # cable_hmi 를 import 할 수 있어야 한다
```

```python
from cable_hmi import interface as itf
from cable_hmi.hmi_progress import HmiCommError, HmiStop, ProgressReporter
```

## 3. 넣을 코드 (문서의 Main Work 흐름 기준)

```python
progress = ProgressReporter(
    node, points=1, steps=['Transition', 'Entry', 'Grip', 'Pull', 'Judgment'],
    control=True,              # HMI 버튼을 받는다
    watch_heartbeat=True,      # HMI 통신 단절 감시 (Common Sequence #1)
    handles_home=True)         # HMI 'Home 이동' 을 이 코드의 Home Return 시퀀스가 처리한다

try:
    while True:                                                   # SYSTEM_READY
        name, args = progress.wait_for_command(auto_start=False)  # HMI 버튼을 기다린다
        try:
            if name == itf.CommandName.MOVE_HOME:                 # HMI 'Home 이동'
                progress.moving('HOME')
                ok, reason = home_return()
                progress.home_done(ok, reason)
                continue
            if name != itf.CommandName.START:
                continue

            if not start_allowed():                               # START VALIDATION
                progress.reject('다른 모션이 실행 중')             #   DENY -> HMI 팝업, 대기 그대로
                continue
            progress.start()                                      #   ACCEPT -> HMI '검사 중', 결과 표 비움

            progress.sequence('Work Initialize')
            reason = work_initialize(args['recipe_id'])
            if reason:
                progress.fail(reason)                             # INIT FAIL -> HMI 팝업, 대기로
                continue

            progress.sequence('Home Return');  home_return()
            progress.set_points(len(points))
            for i, point in enumerate(points):                    # POINT UNIT
                progress.sequence('Point Unit')
                progress.point(i, point.id, criteria=itf.Criteria(...))
                progress.step('Transition');  ...ready_pose 로...;  progress.check_pause()
                progress.step('Entry');       ...entry_pose 로...;  progress.check_pause()
                progress.step('Grip');        ...
                progress.step('Pull');        ...
                progress.step('Judgment')
                progress.report_result(itf.PointResult(point_id=point.id, result=itf.ResultCode.PASS, ...))
                ...ready_pose 로 복귀...;     progress.check_pause()

            progress.sequence('Work Finish');  ...완료 처리...
            progress.sequence('Home Return');  home_return()
            progress.finish()                                     # 제품 판정 계산, HMI '검사 완료' = SYSTEM_READY

        except HmiCommError:                                      # 통신이 제한 시간 안에 복구 안 됨
            progress.abort('(COMM_ERROR)', itf.EndReason.COMM_ERROR)
        except HmiStop:                                           # HMI STOP: 작업 종료, 자동 Home Return 없음
            progress.abort('(HMI STOP)', itf.EndReason.STOP)
        except RobotError as e:                                   # 자기 코드의 오류
            progress.error(str(e))                                # HMI 팝업, 작업 종료
finally:
    progress.close()                                              # rclpy.shutdown() 전에
```

`HmiCommError` 는 `HmiStop` 의 한 종류다. 구분할 필요가 없으면 `except HmiStop` 하나로 받아도 된다.

## 4. 함수 요약

| 함수 | 언제 | HMI 에서 일어나는 일 |
|---|---|---|
| `wait_for_command(auto_start=False)` | 대기 | '대기' 또는 '검사 완료' 상태, 검사 시작 버튼이 열림. `('START', {'recipe_id': ...})`, `('MOVE_HOME', {})`, `('MOVE_TO_POINT', {'point_id', 'reason'})` 중 하나를 돌려줌 |
| `reject(사유)` | START 거부 | 팝업. 상태·결과 표는 그대로 |
| `start()` | START 승인 | '검사 중', 진행률 0 %, 결과 표 비움 (새 run_id) |
| `sequence(이름)` | 시퀀스가 바뀔 때 | '현재 단계' 와 진행률 옆에 `이름 · Point · 단계` 로 표시 |
| `set_points(n)` / `point(i, id, criteria=)` / `step(이름)` | Point·단계 진행 | 진행률(%) 계산, 검사 조건 칸 표시 |
| `check_pause()` | **안전한 정지 지점마다** | 일시정지가 요청돼 있으면 여기서 '일시정지' 가 되고 이어하기까지 기다림. STOP 이면 `HmiStop` 을 던짐 |
| `report_result(PointResult)` | Point 판정 후 | 결과 표에 한 줄, 상세 팝업, DB 저장 |
| `finish()` | 마지막 Point 후 | 100 %, 제품 판정(FAIL 있음 → FAIL / MISSING 있음 → 미검사 있음 / 아니면 PASS), '검사 완료' |
| `fail(사유)` / `error(사유)` | INIT FAIL / ERROR | 팝업, 작업 종료, 진행률 0 |
| `abort(메모, 종료사유)` | STOP·COMM_ERROR 처리 | 작업 종료, 로그 |
| `moving(대상)` … `moved()` / `home_done(성공, 사유)` | Home·포인트 이동 | '이동 중' → 이동 전 상태로 복귀. 결과 표는 그대로. 실패면 팝업 |
| `note(글)` | 알릴 것이 있을 때 | 시스템 로그에 경고 한 줄 |
| `close()` | 프로그램 종료 전 | 명령 수신 종료 |

## 5. 문서의 상태 ↔ HMI 상태

| 문서 | HMI 표시 | 열리는 버튼 |
|---|---|---|
| SYSTEM_READY | 대기 / 검사 완료(직전 결과가 남아 있음) | 검사 시작, Home, FAIL·MISSING 포인트 이동 |
| RUNNING | 검사 중 | 일시정지, STOP |
| PAUSE_REQUEST | 일시정지 요청 | STOP |
| PAUSED | 일시정지 (통신 단절이면 `일시정지 · 통신 단절`) | 이어하기, STOP |
| (Home Return·포인트 이동 중) | 이동 중 | 일시정지, STOP |
| 작업 종료(STOP / ERROR / COMM_ERROR) | 잠깐 '모니터링' 후 다시 대기 | |

STOP 은 어떤 상태에서도 열려 있다. HMI 의 STOP 을 누르면 **모니터 노드가 `move_stop` 을 보내 로봇을 멈추고**, 동작 코드에는 `HmiStop` 이 올라온다.

## 6. 일시정지 — 두 가지 방식

| 방식 | 쓰는 법 | 동작 |
|---|---|---|
| **Safe Pause Point** (문서 방식, 권장) | 원자 동작이 끝난 지점에서 `progress.check_pause()` | 버튼을 누르면 '일시정지 요청', 하던 동작을 마친 뒤 '일시정지'. 재개하면 다음 동작부터 |
| 그 자리에서 정지 | 모션을 기다리는 루프에서 `progress.check_pause(pause=멈추는함수, resume=이어가는함수)` | 누른 순간 `motion/move_pause`, 재개하면 `motion/move_resume` 으로 가던 길을 마저 감. 예: `~/ros_ws/examples/inspect_async.py` |

하위 시퀀스별 Safe Pause Point 는 **`check_pause()` 를 어디에 넣느냐** 로 정해진다. 힘 제어 중처럼 멈추면 안 되는 구간에는 넣지 않으면 된다.

## 7. HMI 통신 단절 (`watch_heartbeat=True`)

- 검사·이동 중에 HMI 신호가 `heartbeat_lost_sec`(기본 3 s) 넘게 끊기면 일시정지를 요청한다(사유 COMM_LOST). 정지 시점은 6 절과 같다.
- 통신이 돌아와도 **스스로 재개하지 않는다.** HMI 에 "확인 후 이어하기" 팝업이 뜨고 사용자가 이어하기를 눌러야 한다.
- `comm_timeout_sec`(기본 30 s) 안에 돌아오지 않으면 `check_pause()` 가 `HmiCommError` 를 던진다 → 작업 종료.
- 사용자가 이미 일시정지해 둔 상태에서 HMI 가 꺼진 것은 종료로 처리하지 않는다(작업 Context 보존).
- 두 시간 값은 문서에서 TBD 다. 정해지면 인자로 넘기면 된다.

## 8. 지켜야 할 것

1. **status 토픽을 직접 보내지 말 것.** 발행자가 둘이 되면 HMI 값이 섞인다.
2. **`check_pause()` 는 두산 API 를 부르는 스레드(메인)에서 부를 것.** 명령은 부품이 별도 스레드에서 받아 표시만 해 둔다.
3. 기다리는 곳(`time.sleep`, 그리퍼 닫힘 대기 등)에도 `check_pause()` 를 넣어야 그 구간에서 STOP·일시정지가 늦지 않다.
4. **동기 모션(`movej`, `movel`)으로 짜도 시작 / Safe Pause / STOP / 통신 단절 처리는 된다.** 단, 동기 모션 중에는 두산 드라이버가
   다른 요청에 답하지 못해 **HMI 의 힘·위치·변위 값이 그동안 멈춘다**(STOP 의 `move_stop` 만 예외). Pull 중의 힘·변위를 실시간으로
   보거나 기록하려면 그 구간은 비동기(`amovel` + `check_motion` 폴링)로 짜야 한다. `mwait()` 도 같은 이유로 쓰지 말 것.
5. 두산 API 호출(`set_tool` 등)은 응답을 끝없이 기다린다. 드라이버가 떠 있는지 먼저 확인할 것(`inspect_async.py` 의 probe 참고).
6. Ctrl+C 뒤에는 ROS 연결이 닫혀 로봇에 명령을 보낼 수 없다. "끝낼 때 홈 복귀" 를 `finally` 에 두어도 Ctrl+C 에서는 실행되지 않는다.

## 9. 결과(`PointResult`)에 채울 것

`point_id`, `result`(`PASS` / `FAIL_DISPLACEMENT` / `FAIL_DETACHED` / `MISSING`), `reason`, `action` 은 꼭. 나머지는 아는 만큼:
`recipe_id`, `recipe_version`, `product_id`, `point_name`, `cable_id`, `cable_type`, `max_force_n`, `pull_force_limit_n`, `displacement_mm`,
`displacement_limit_mm`, `repeat_count`, `grip_width_mm`, `task`, `joint`, `force_data_id`(원본 힘 데이터 파일 식별자).
`run_id`, `stamp`, `db_saved` 는 비워 둔다(부품과 저장 노드가 채운다).
결과에 실은 검사 조건·위치는 "검사 당시 값" 으로 DB 에 남는다.

측정값과 조건을 짝지어 싣는다: `max_force_n`(측정한 최대 힘) ↔ `pull_force_limit_n`(Pull 정지 상한), `displacement_mm`(측정 변위) ↔ `displacement_limit_mm`(허용 변위). **`pull_force_limit_n` 은 합격선이 아니라 Pull 을 멈추는 안전 상한이다** - 합격 여부는 변위로 가른다. 상한에 닿아서 멈췄다면 그 사실을 `reason` 에 적을 것.

## 10. 아직 정해지지 않은 것 (정해지면 HMI 쪽을 맞춘다)

- 레시피 JSON 필드 이름: `enabled`, `ready_pose`, `entry_pose`, `entry_direction`, System Recipe(home, work_Access, Work Area 경계)
- STOP 과 E-STOP 을 HMI 에서 버튼 둘로 나눌지 (지금은 빨간 버튼 하나 = STOP)
- Heartbeat 끊김 판단 시간 / 통신 Timeout 값
- FAIL / MISSING 포인트 이동(문서에 없는 HMI 기능)을 유지할지, 유지한다면 ready_pose 경유 규칙
- Home 조건에 Tool/TCP 유효성을 다시 넣을지 (문서의 Robot Operability Check 에는 포함)
- 결과 코드 4종(`MISSING` 포함) 유지 여부
- **합격 기준 힘**: 값·비교 방향·판정 시점이 모두 미정. 지금 레시피 DB 에 있는 힘 값은 Pull 정지 상한(`pull_force_limit_n`)뿐이고 합격선이 아니다. 정해지면 상한과 구분되는 별도 필드로 추가한다

## 11. 로봇 없이 / 가상 로봇으로 시험

```bash
sodvir                                                                            # 터미널 1
sod && source ~/ros_ws/install/setup.bash && ros2 launch cable_hmi hmi_monitor.launch.py   # 터미널 2
sod && source ~/ros_ws/install/setup.bash && python3 <동작 코드>                  # 터미널 3
```

참고 예제: **`~/ros_ws/examples/sequence_demo.py`(이 가이드를 그대로 따른 시험 코드 - 3 절의 흐름, Safe Pause, 통신 단절, Home 처리)**,
`~/ros_ws/examples/inspect_async.py`(레시피 읽기 + 결과 보고 + 포인트 이동, 그 자리에서 멈추는 일시정지).
자세한 설명: `src/cable_hmi/README.md`, `src/cable_hmi/cable_hmi/hmi_progress.py` 의 머리말.
