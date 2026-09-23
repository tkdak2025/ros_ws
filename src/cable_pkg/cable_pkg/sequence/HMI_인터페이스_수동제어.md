# HMI 인터페이스 및 수동 제어 명령

작성 기준: 2026-09-23, 현재 `cable_pkg` 구현. HMI 구현은 변경하지 않는다.
이 문서는 ROS 쪽 통신 계약과 현장 확인 명령을 정리한다. 미구현 항목은 마지막에 구분한다.

별도 PC 연동 요약: [HMI ROS 2 인계 문서](../../../../docs/HMI_ROS2_연동_2026-09-23.md).

## 1. 실행 구성

- `main_sequence`: HMI 명령 수신, 전체 Job 실행, 상태 발행.
- `inspection_judgment`: 비동기 Point 판정과 결과 발행.
- `inspection_sequence`: 터미널에서 검사 구간만 실행. HMI 명령 수신부가 아니다.
- `manual_check`: 현재 로봇 위치·속도·상태 조회 메뉴. 이동 기능은 없다.

로봇/RG2와 전체 Job launch가 준비되어 있다. [통합 실행 및 터미널 운전](README.md#통합-실행과-hmi-없는-운전)을 참고한다.
`sequence_hmi_test.launch.py`는 Mock용이며, 현재 등록되지 않은 `sequence_test_node`를 참조한다.

`ros_ws`에서 각 터미널에 환경을 적용한다.

```bash
source /opt/ros/jazzy/setup.bash
source install/setup.bash
```

터미널 1:

```bash
ros2 run cable_pkg inspection_judgment
```

터미널 2:

```bash
ros2 run cable_pkg main_sequence
```

기본 검사 레시피는 `rcp_BMW_LWR_01`, 순서는 `HARNESS_01 → HARNESS_02 → HARNESS_03`다.
다른 레시피도 선택하려면 `main_sequence --recipe <파일1> --recipe <파일2>`로 등록한다.
`--recipe`를 지정하면 기본 목록을 대체한다. 등록한 첫 레시피가 초기 선택값이다.
파일 등록과 HMI의 Recipe ID 선택은 별개이며, 임의 파일 경로를 HMI에서 보내는 기능은 없다.

전체 Job의 START/Home에는 System Recipe의 Home, Work Access, work_area 등 유효한 설정이 필요하다.
현재 work_area의 Z 최솟값은 60 mm다. 영역 안에서는 Work Access를 거친 뒤, 밖에서는 바로 전체 관절 0도로 한 번의 MoveJ 복귀를 수행한다.
별도 allowed_workspace와 safe_home_route 경유점은 사용하지 않는다. tool_approach_axis는 현재 Home 복귀에서 사용하지 않는다.
`main_sequence`와 `inspection_sequence`를 같은 로봇에서 동시에 실행하지 않는다.

## HMI 없는 terminal 모드

`system_bringup.launch.py control_mode:=terminal`과 별도 `ros2 run cable_pkg sequence_console`을 사용한다.
terminal 모드는 `/cable_inspection/terminal_command`와 `/cable_inspection/terminal_heartbeat`만 수신한다.
타입·JSON 명령은 HMI 모드와 같으며, HMI command/heartbeat는 terminal 모드에 영향을 주지 않는다.
상태에는 `control_mode`(hmi/terminal), `control_connected`(선택한 제어기의 Heartbeat 유효 여부)가 추가된다.
기존 command 토픽 예제는 hmi 모드용이다. terminal 모드의 직접 명령은 토픽을 terminal_command로 바꾼다.
콘솔은 입력을 기다리는 동안에도 Heartbeat를 보내며 종료 시 STOP을 요청한다. 콘솔은 한 개만 실행한다.

## 2. HMI 통신 토픽

기본 네임스페이스 기준이다. 코드는 상대 토픽명을 사용하므로 launch namespace를 지정하면 경로가 달라진다.

| 방향 | 토픽 | 타입 | 내용 |
|---|---|---|---|
| HMI → Main | `/cable_inspection/command` | `std_msgs/msg/String` | JSON 명령 |
| HMI → Main | `/cable_inspection/hmi_heartbeat` | `std_msgs/msg/Empty` | HMI 생존 신호 |
| Main → HMI | `/cable_inspection/status` | `std_msgs/msg/String` | 상태·레시피·진행률·집계 JSON |
| Main/Judgment → HMI | `/cable_inspection/log` | `std_msgs/msg/String` | 수준·메시지·팝업 여부 JSON |
| Judgment → HMI/Main | `/cable_inspection/judgment_result` | `cable_interfaces/msg/InspectionResult` | Point 판정과 측정값 |
| Inspection → Judgment | `/cable_inspection/judgment_request` | `std_msgs/msg/String` | 내부 판정 요청. HMI가 발행할 명령은 아님 |

상태 타이머는 0.1초 간격이다. 기본 ROS QoS를 사용하며 이력 재생용 transient-local 설정은 없다.
HMI는 실행 전에 상태·로그·결과를 구독하고 연결 후 SYNC로 상태를 요청한다.
결과 수신은 `(run_id, point_id)`로 식별한다. 동일 Point의 결과가 복귀 오류로 SYSTEM_ERROR로 갱신될 수 있다.
SYNC는 상태만 다시 보내며 과거 Point 결과를 재전송하지 않는다.

Heartbeat 제한은 System Recipe의 `heartbeat_timeout_s`이며 현재 2초다.
HMI는 제한시간보다 충분히 짧은 주기로 보내야 한다. 아래 수동 예제는 2 Hz다.
실행 중 유실되면 완료점에서 Pause를 요청한다. 복구만으로 재개하지 않으며 RESUME이 필요하다.
현재 복구 대기 상한은 30초다. 만료되면 COMM_ERROR로 종료 처리한다.

## 3. HMI 명령 계약

`String.data`에 아래 구조의 JSON 문자열을 넣는다.

```json
{"name": "SELECT_RECIPE", "args": {"recipe_id": "rcp_BMW_LWR_01"}}
```

| name | args | 허용 조건 / 동작 |
|---|---|---|
| `SELECT_RECIPE` | `recipe_id` 필수 | SYSTEM_READY, Context 없음, Worker 종료 상태에서 등록된 ID 선택. 이동 없음 |
| `START` | `recipe_id` 선택 | 위와 같은 대기 조건. 생략하면 선택값 사용. #01 초기화 이후 전체 Job 실행 |
| `PAUSE` | `{}` | RUNNING/PAUSE_REQUEST. 현재 원자 동작의 완료점에서 PAUSED로 전환 |
| `RESUME` | `{}` | PAUSED 및 Heartbeat 복구 상태. 보존된 완료점에서 이어서 실행 |
| `STOP` | `{}` | 진행 Job 정지 요청 및 Context 폐기. 자동 Home 복귀 없음. 대기 중이면 STOPPED로 전환 |
| `HOME_RETURN` | `{}` | SYSTEM_READY/STOPPED/ERROR, Worker 종료 상태. #02 경로에 따라 Home 복귀 |
| `MOVE_HOME` | `{}` | HOME_RETURN과 같은 명령 |
| `SYNC` | `{}` | 현재 상태를 즉시 발행. 이동 없음 |

START의 `recipe_id` 직접 지정도 선택값에 반영된다. 파일 내용은 START 초기화 시 다시 읽어 Snapshot으로 고정한다.
실행 중 선택 변경은 거부하고 기존 선택값을 유지한다. 레시피 선택 성공은 좌표/파일 전체 검증 성공을 뜻하지 않는다.

PAUSE는 즉시 모션 정지가 아니다. Ready/Entry/Hard 완료점 등에서 대기한다.
STOP도 ROS 프로그램을 통한 요청이며 하드웨어 비상정지와 동일한 기능이 아니다.
STOP 이후에는 RESUME할 Context가 없다. 원인을 해소하고 HOME_RETURN 성공으로 SYSTEM_READY에 돌아온 뒤 새 START를 보낸다.
HOME_RETURN은 Fault Reset 명령이 아니며 로봇 오류를 자동 해제하지 않는다.

현재 별도 ACK 토픽이나 `request_id`는 없다. 로그와 상태 변화를 함께 확인한다.
로그의 `RECIPE_SELECTED`는 선택 완료, `STOP_REQUESTED`는 정지 요청 접수이며 실제 동작 완료와 구분한다.
#07에서도 `JOB_COMPLETE` 로그가 나올 수 있으므로 이 문자열만으로 최종 Home 복귀 완료를 판단하지 않는다.

## 4. HMI가 받는 상태와 로그

| 상태 필드 | 의미 / 주의점 |
|---|---|
| `run_state` | SYSTEM_READY / RUNNING / PAUSE_REQUEST / PAUSED / STOPPED / ERROR |
| `state` | SYSTEM_READY만 IDLE로 표기하는 호환 필드. 제어 판단은 run_state 기준 |
| `alarm` | 제어 객체에 기록된 마지막 오류 문자열 |
| `available_recipes` | 현재 등록된 Recipe ID 목록 |
| `selected_recipe_id` | 다음 START에 사용할 선택값 |
| `recipe_id`, `recipe_version` | Context가 있으면 해당 Job의 레시피. 대기 중 ID는 선택값, version은 빈 문자열 |
| `run_id`, `job_id` | 실행 식별자. Context가 없으면 job_id는 빈 문자열이며 run_id는 이전 값이 남을 수 있음 |
| `execution_index` | 완료한 Point 수. 첫 Point 실행 중에는 0, 완료 후 1로 증가 |
| `total_points`, `current_point` | 활성 Point 수 / 현재 Point ID. 순회가 끝나면 current_point는 빈 문자열 |
| `current_step`, `resume_point` | 최근 기록한 단계·완료점. 모든 세부 모션을 실시간 표현하는 값은 아님 |
| `progress_percent` | 완료 Point 비율. 100%여도 #07 처리나 Home 복귀가 남을 수 있음 |
| `pending_judgments` | 아직 결과를 기다리는 Point 수 |
| `job_summary` | 결과 개수, 누락/대기 Point 등 마지막 검사 집계. 최종 Home 성공 플래그는 아님 |
| `robot_connected`, `gripper_connected` | 현재 동일한 backend.connected 값. 독립적인 실시간 연결 감시값은 아님 |
| `tool` | configured/name/tcp/force_zero_done. name/tcp는 설정값이며 force_zero_done은 현재 false 고정 |

현재 상태에는 Heartbeat 나이, Joint 속도, TCP 실측값, 그리퍼 실측 폭/힘의 실시간 필드가 없다.
연결 필드나 SYSTEM_READY만으로 실물 준비를 단정하지 않는다. 실제 준비 조건은 #01에서 확인한다.

로그 JSON:

```json
{"level": "INFO", "text": "RECIPE_SELECTED: rcp_BMW_LWR_01", "popup": false}
```

`level`은 INFO/WARN/ERROR, `popup`은 ERROR일 때 true다. 명령 거부도 log로 전달한다.

## 5. Point 검사 결과

정의: [InspectionResult.msg](../../../cable_interfaces/msg/InspectionResult.msg)

| 필드 | 의미 |
|---|---|
| `run_id`, `stamp` | 실행 ID / 판정 생성 시각(시간대 포함 ISO 문자열) |
| `recipe_id`, `recipe_version` | 실행한 레시피 식별자와 버전 |
| `point_id`, `point_name`, `cable_type` | 검사 대상 식별/표시 정보 |
| `result` | PASS / FAIL / SYSTEM_ERROR. MISSING은 없음 |
| `reason_code`, `reason` | 판정 사유 코드 / 설명 |
| `termination_reason` | FORCE_LIMIT / MAX_DISTANCE / TIMEOUT / MOTION_ERROR / ROBOT_ERROR / TOOL_ERROR / SAFETY_ERROR / INVALID_DATA |
| `judgment_status`, `sequence_status` | 판정 처리 상태 / 시퀀스 처리 상태. 제품 결과와 별개 |
| `max_force_n`, `required_pull_force_n` | Pull 시작 기준으로 보정한 당김축 힘의 최대값 / 레시피 기준값(N) |
| `displacement_mm`, `displacement_limit_mm` | Pull 시작부터 정지까지 축 방향 실제 변위 / 정상 허용 변위(mm) |
| `soft_width_mm` | 추가진입 후, Hard Grip 전 실측 폭(mm) |
| `pull_width_mm` | Pull 구간 최소 실측 폭(mm) |
| `width_delta_mm` | Pull 최소 폭 − Soft 기준 폭. 현재 기록용 |
| `grip_failure_width_mm` | 현재 고정 판정 기준 16 mm |
| `task`, `joint` | 레시피의 Entry TASK/JOINT. 실시간 현재 좌표가 아님 |
| `force_data_id` | 원시 기록 연결용 식별자. 현재 비어 있을 수 있음 |
| `db_saved` | 현재 false. DB 저장 확인 통신은 미구현 |

일반 결과는 judgment_status=COMPLETED, sequence_status=SUCCESS이며 제품 결과가 FAIL일 수도 있다.
오류 결과는 ERROR/INCOMPLETE 등으로 전달된다. 유효하지 않은 수치를 0.0으로 보내는 경우가 있으므로
SYSTEM_ERROR의 숫자를 정상 실측값처럼 사용하지 않는다.

현재 #06은 Pull 힘/변위와 16 mm 폭 기준을 사용한다. 추가진입 깊이·진입 종료 사유는 판정 요청에 포함되지 않는다.
이번 HARNESS_02처럼 간섭으로 얕게 파지해도 PASS가 가능한 한계가 확인되었으며, 파지 유효성 기준은 별도 보완 대상이다.
PENDING은 대기 상태이고 최종 제품 결과가 아니다. HMI는 pending_judgments와 Point 결과 수신을 함께 관리한다.

## 6. 터미널 수동 조작

아래 명령은 필요한 항목만 개별 실행한다. START와 HOME_RETURN은 실제 로봇을 움직일 수 있다.
HMI가 명령을 보내는 동안 수동 명령을 동시에 보내지 않는다.

먼저 이 터미널에 전송 함수를 정의한다. 함수 정의 자체는 명령을 보내지 않는다.

```bash
ccc_command() {
  ros2 topic pub --once /cable_inspection/command std_msgs/msg/String "{data: '$1'}"
}
```

| 목적 | 개별 실행 명령 |
|---|---|
| 현재 상태 요청 | `ccc_command '{"name":"SYNC","args":{}}'` |
| BMW 레시피 선택 | `ccc_command '{"name":"SELECT_RECIPE","args":{"recipe_id":"rcp_BMW_LWR_01"}}'` |
| 선택한 레시피로 Job 시작 | `ccc_command '{"name":"START","args":{}}'` |
| 완료점 일시정지 | `ccc_command '{"name":"PAUSE","args":{}}'` |
| 일시정지 재개 | `ccc_command '{"name":"RESUME","args":{}}'` |
| Job 정지 | `ccc_command '{"name":"STOP","args":{}}'` |
| Home 복귀 | `ccc_command '{"name":"HOME_RETURN","args":{}}'` |

HMI 없이 통신을 확인할 때만 별도 터미널에서 Heartbeat를 공급한다. 실제 HMI와 병행하면 HMI 유실을 가릴 수 있다.

```bash
ros2 topic pub -r 2 /cable_inspection/hmi_heartbeat std_msgs/msg/Empty '{}'
```

수신 확인은 각각 별도 터미널에서 실행한다.

```bash
ros2 topic echo /cable_inspection/status std_msgs/msg/String
ros2 topic echo /cable_inspection/log std_msgs/msg/String
ros2 topic echo /cable_inspection/judgment_result cable_interfaces/msg/InspectionResult
```

결과 파일은 실행 위치 기준 `results/inspection_sequence/<실행시각>/`에 저장된다.
inputs.json=실행 조건, samples.jsonl=실측 시계열, inspection_results.json=모션 결과,
judgment_results.json=판정, job_summary.json=집계, status.json=실행 종료 상태다.

## 7. 장비 수동 점검

### 현재 위치·속도·상태 조회

```bash
ros2 run cable_pkg manual_check
```

메뉴: 1=관절 위치, 2=BASE TASK 좌표, 3=속도, 4=상태/모드/TCP/Tool, 5=전체, Q=종료.
이 메뉴는 읽기 전용이며 Jog, Servo On/Off, 모드 변경은 하지 않는다.

BASE 기준 툴 힘/모멘트 한 번 조회:

```bash
ros2 service call /dsr01/dsr_controller2/aux_control/get_tool_force dsr_msgs2/srv/GetToolForce '{ref: 0}'
```

이는 현재 wrench 조회다. 검사 코드의 진입/Pull 시작값 보정과는 별개다.

### 그리퍼 폭 수동 명령

운영 시퀀스가 종료된 상태에서만 사용한다. 직접 명령은 시퀀스 내부의 폭/힘 추적값을 갱신하지 않는다.
서비스 타입은 `onrobot_rg_msgs/srv/SetCommand`이며 숫자 문자열은 목표 폭의 0.1 mm 단위다.

```bash
ros2 service type /onrobot/sendCommand
ros2 interface show onrobot_rg_msgs/srv/SetCommand
# 실제 그리퍼 폭 27 mm 명령. 힘을 10 N으로 설정하는 명령은 아니다.
ros2 service call /onrobot/sendCommand onrobot_rg_msgs/srv/SetCommand "{command: '270'}"
```

| BMW Point | Soft Open | Soft Close | Hard Close |
|---|---|---|---|
| HARNESS_01 | 27 mm → `'270'` | 24 mm → `'240'` | 21 mm → `'210'` |
| HARNESS_03 | 26 mm → `'260'` | 23 mm → `'230'` | 20 mm → `'200'` |
| HARNESS_02 | 26 mm → `'260'` | 23 mm → `'230'` | 20 mm → `'200'` |

현재 하드웨어 어댑터는 `i`/`d`를 힘 +2.5 N/−2.5 N 명령으로 사용한다.
절대 힘을 보내는 필드는 없으므로 현재 힘 기준을 모르면 증감 횟수만으로 10 N/20 N을 보장할 수 없다.
운영 시퀀스는 연결 시 힘 기준을 동기화하고 Soft 10 N, Hard 20 N을 설정한다.
폭만 보낸 위 예제를 Soft/Hard 기능 전체의 실행으로 해석하지 않는다.

### 로봇 직접 정지 서비스

```bash
ros2 service call /dsr01/dsr_controller2/motion/move_stop dsr_msgs2/srv/MoveStop '{stop_mode: 1}'
```

어댑터에서 사용하는 Quick Stop 요청이다. 이 서비스는 Job Context/상태를 정리하지 않는다.
일반 운영 정지는 위 STOP 명령을 사용한다. 직접 정지나 ROS STOP 모두 하드웨어 비상정지의 대체가 아니다.

## 8. 추가 구현이 필요한 HMI 수동 기능

아래는 현재 command에서 지원하지 않는다. 새 명령명을 전송해도 동작하지 않는다.

| 기능 | 현재 상태 / 구현 시 필요한 내용 |
|---|---|
| Joint/TASK Jog | HMI 진입점 없음. 좌표계, 방향, 속도, 누르고 있는 동안의 동작 및 해제/통신 유실 정지 필요 |
| 지정 Joint/TASK 이동 | 내부 MoveJ/MoveL만 있음. HMI 요청값 검증 및 자동 Job과 수동 조작의 실행권 구분 필요 |
| Ready/Entry 단독 이동 | 시퀀스 내부 메서드만 있음. 선택 Point와 허용 상태를 받는 수동 명령 필요 |
| 그리퍼 Open/Soft/Hard | 내부 구현과 드라이버 서비스만 있음. 폭·힘을 함께 적용하고 완료를 응답하는 수동 명령 필요 |
| 작업 이동 속도 설정 | 현재 System Recipe의 joint_speed_deg_s=10.0. HMI 설정 명령/현재 설정 응답/저장은 미구현 |
| 레시피 내용 편집·저장·추가 등록 | 현재 등록된 ID 선택만 지원. 좌표·폭 등의 파일 수정 API는 없음 |
| 실시간 위치·힘·그리퍼 상태 표시 | 조회 함수와 로그는 있으나 HMI용 통합 실시간 상태 전송은 없음 |
| 명령별 ACK | 현재 로그/상태 확인 방식. 요청 ID, 접수/거부/완료의 구조화 응답은 없음 |
| 결과 저장 ACK·재조회 | DB 저장 확인과 재접속 후 결과 재전송 없음 |
| 최종 Job 완료 이벤트 | #07 검사 집계와 최종 Home 완료를 명확히 구분하는 전용 이벤트 없음 |

속도 표시명을 바꿔도 단위는 유지해야 한다. Joint deg/s, TCP mm/s, 속도 비율 %는 서로 다른 값이다.
수동 조작과 속도 변경의 허용 상태, 설정 적용 시점은 해당 기능 구현 시 함께 정의한다.

## 9. 코드 위치

- [Main 통신 노드](seq_00_main_work/node.py): 명령·Heartbeat 수신, 상태·로그 발행.
- [Main 제어 클래스](seq_00_main_work/sequence.py): START/Pause/Resume/STOP/Home 정책.
- [Main 실행부](seq_00_main_work/run.py): 레시피 등록과 노드 시작.
- [판정 노드](seq_06_inspection_judgment/node.py): 결과 메시지 생성·발행.
- [수동 조회](../diagnostics/manual_check.py): 조회 메뉴와 읽기 서비스.
- [장비 어댑터](../hardware/dsr_rg2_base.py): DSR/RG2 서비스와 명령 인코딩.
- [시스템 레시피](../../config/system_recipe.json): 공통 좌표·속도·시간 설정.
