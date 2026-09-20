# cable_hmi

M0609 + RG2 케이블 체결 검사 PoC 의 PyQt5 HMI. 화면 구성은 `HMI최종UImockup1.drawio` 기준.

HMI 는 **publish/subscribe 만** 한다. `DSR_ROBOT2` 등 블로킹 서비스 호출 모듈을 import 하지
않으므로 로봇 쪽이 멈춰도 화면과 비상정지 버튼은 얼지 않는다. 화면은 검사 노드가 보내는
`status` 의 렌더러일 뿐이며, 버튼을 눌러도 스스로 상태를 바꾸지 않고 명령만 보낸다.

## 실행

```bash
source /opt/ros/jazzy/setup.bash
cd ~/ros_ws && colcon build --symlink-install --packages-select cable_hmi
source install/setup.bash

ros2 launch cable_hmi hmi.launch.py                        # HMI + 가상 검사 노드
ros2 launch cable_hmi hmi.launch.py random_outcomes:=true  # 결과 무작위
ros2 launch cable_hmi hmi.launch.py mock:=false            # HMI 만 (실제 검사 노드와 통합)
```

HMI 와 mock 은 두산 워크스페이스 없이도 빌드·실행된다. `robot_monitor_node` 를 실행할 때만 `sod`(dsr_msgs2)가 필요하다. launch 파일 추가 직후 첫 symlink 빌드가
`No such file ... launch/hmi.launch.py` 로 실패하면 한 번 더 빌드하면 된다.

가상 Recipe: `RECIPE_A` = PASS / FAIL_DISPLACEMENT / MISSING, `RECIPE_B` = PASS / FAIL_DETACHED / PASS / PASS.

## 구조

| 파일 | 역할 |
|---|---|
| `interface.py` | **통합 시 고칠 유일한 파일.** 토픽 이름, 메시지 타입, dataclass ↔ ROS 메시지 변환 |
| `ros_bridge.py` | ROS 수신 스레드 → Qt signal, 명령/heartbeat publish |
| `main_window.ui` | **화면 배치 + 스타일시트(QSS).** Qt Designer 로 편집 |
| `main_window.py` | 화면 동작. `.ui` 를 `uic.loadUi` 로 읽고 objectName 으로 위젯을 찾는다. ROS 를 모르고 `interface` 의 dataclass 만 사용 |
| `detail_dialog.py`, `style.py` | 상세 팝업, 코드에서 동적으로 입히는 색(PASS/FAIL/MISSING 등) |
| `mock_inspection_node.py` | 가상 검사 노드. 실제 검사 노드가 구현할 동작의 참조 구현 |
| `robot_monitor_node.py` | 실제 로봇 값 → status (두산 조회 서비스를 비동기로 읽음). STOP, Tool/TCP 자동 설정, 속도 설정, Home 이동. `dsr_msgs2` 가 필요한 유일한 파일 |
| `hmi_progress.py` | 동작 코드에 붙이는 진행률 보고 부품 (`ProgressReporter`) |

## 화면 수정 (Qt Designer)

```bash
designer ~/ros_ws/src/cable_hmi/cable_hmi/main_window.ui
```

- `.ui` 는 파이썬 패키지 폴더 안에 있어 `--symlink-install` 빌드에서는 **저장 후 HMI 만 다시 실행하면 반영**된다(재빌드 불필요).
- 위젯 위치·크기·글자·색은 자유롭게 바꿔도 된다. 색/모양은 `MainWindow` 의 `styleSheet` 속성에 있다.
- 코드는 objectName 으로 위젯을 찾는다 (`startBtn`, `pauseBtn`, `resumeBtn`, `estopBtn`, `estopResetBtn`, `homeBtn`,
  `failBtn`, `missingBtn`, `speedSlider`, `resultTable`, `logView`, `recipeCombo`, `toolName` ...).
  위젯을 **지우거나 이름을 바꾸면 그 항목만 화면에서 빠지고 HMI 는 그대로 뜬다.** 빠진 이름은 시작 시
  터미널과 "시스템 로그" 탭에 `main_window.ui 에 없는 위젯` 경고로 나온다. 값이 안 나오면 이 경고부터 볼 것.
- 예외: 비상정지 버튼 `estopBtn` 은 없으면 실행을 거부한다.
- 같은 모양을 여러 위젯에 주려면 objectName 대신 동적 프로퍼티 `role` 을 쓴다
  (Designer 속성 편집기 `+` → String → 이름 `role`). 값: `panel`, `subPanel`, `panelTitle`, `groupTitle`, `key`, `value`.
- 새 버튼을 추가했다면 `_load_ui()` 에서 `clicked.connect(...)` 한 줄, 필요하면 `interface.py` 에 명령 하나를 추가한다.

## ROS 인터페이스 (현재: `std_msgs/String` + JSON)

| 토픽 | 방향 | 내용 |
|---|---|---|
| `cable_inspection/status` | 검사 노드 → HMI, 10 Hz | `SystemStatus` - 상태, 연결, Tool, 판정 기준, 현재 Point/단계/힘/변위/그리퍼 폭, 진행률 |
| `cable_inspection/result` | 검사 노드 → HMI | `PointResult` - Point 1개 완료마다 |
| `cable_inspection/log` | 검사 노드 → HMI | `LogEntry` - 시스템 로그 |
| `cable_inspection/command` | HMI → 검사 노드 | `Command{name, args}` |
| `cable_inspection/hmi_heartbeat` | HMI → 검사 노드, 2 Hz | `std_msgs/Empty`. 끊기면 검사 노드가 안전 정지할 것 |

| 버튼 | command | args | 활성 조건(status.state) |
|---|---|---|---|
| 검사 시작 | `START` | `recipe_id` | IDLE, DONE |
| 일시정지 | `PAUSE` | | RUNNING, MOVING |
| 이어하기 | `RESUME` | | PAUSED |
| 비상정지 | `ESTOP` | | 항상 |
| 비상정지 해제 | `ESTOP_RESET` | | estop == true |
| Home 이동 | `MOVE_HOME` | | IDLE, DONE |
| FAIL / MISSING 포인트 이동 | `MOVE_TO_POINT` | `point_id`, `reason` | IDLE, DONE + 해당 결과 존재 |
| 속도 슬라이더 | `SET_SPEED` | `percent` | 통신 정상 |
| (자동) | `SYNC` | | HMI 가 연결 직후 1회 - 현재 run 결과 재전송 요청, 미구현이어도 무방 |

status 가 1.5 s 이상 끊기면 HMI 는 "ROS2 통신 끊김" 으로 표시하고 비상정지 외 버튼을 잠근다.
HMI 비상정지는 소프트웨어 정지 요청일 뿐이며, 물리 비상정지 스위치와 TP 가 최종 권한이다.

## 실제 로봇 값 모니터링 (읽기 전용)

`robot_monitor_node`(이 패키지)가 두산 드라이버 조회 서비스를 비동기로 읽어 `status` 로 내보낸다.
로봇을 움직이는 호출은 없고, 예외로 HMI STOP 버튼만 `motion/move_stop`(Quick stop) 으로 연결된다.

```bash
# 터미널 1: sod && sodreal          (또는 sodvir)
# 터미널 2:
sod && source ~/ros_ws/install/setup.bash
ros2 launch cable_hmi hmi_monitor.launch.py
```

mock 과 동시에 띄우지 말 것 (둘 다 `status` 를 publish 한다).

**Tool/TCP 자동 설정.** 두산 드라이버를 재시작하면 컨트롤러의 Tool/TCP 선택이 풀려, 툴 무게가 0 으로 계산되고
힘 값에 툴 무게가 통째로 실린다. 모니터 노드는 이름이 비어 있는 것을 볼 때마다 launch 인자 `tool_name`(기본 `ToolWeight`),
`tcp_name`(기본 `GripperDA_v1`)으로 다시 설정한다. 비어 있을 때만, 로봇이 STANDBY 이고 정지해 있을 때만 호출하며,
TP 에서 다른 툴을 골라 둔 경우는 덮어쓰지 않고 `현재 알람` 에 불일치를 띄운다. 끄려면 `tool_name:='' tcp_name:=''`.
Tool Weight 는 드라이버에 읽는 서비스가 없어 `tool_weight_kg:=<TP 에 등록된 값>` 으로 받은 값을 표시한다(미지정 시 `—`).

| HMI 항목 | 출처 |
|---|---|
| Tool, TCP | `tool/get_current_tool`, `tcp/get_current_tcp` |
| Robot 연결, 비상정지, 현재 단계(`로봇 STANDBY` 등) | `system/get_robot_state`, `/dsr01/robot_disconnection` |
| 상태 배지 `모니터링 · 이동 중` | `motion/check_motion` |
| 현재 힘 값 (Fx·Fy·Fz 합력) | `aux_control/get_tool_force` - 6축 원본은 `/cable_inspection/tool_force` |
| 현재 위치, 현재 변위 | `aux_control/get_current_posx` - 원본은 `/cable_inspection/tcp_pose` |
| 현재 알람 | `/dsr01/error` |
| RG2 연결, 그리퍼 폭 | `/onrobot_joint_states` (OnRobot 드라이버). `finger_joint` 각도를 드라이버와 같은 RG2 상수로 폭(mm)으로 역산 |

변위 기준은 노드 시작 시 자세. 다시 0 으로 잡으려면
`ros2 service call /cable_inspection/zero_displacement std_srvs/srv/Trigger`.
**Home 이동 버튼** 은 `motion/move_joint` 비동기 호출로 `home_joints`(launch 인자, 기본 `[0,0,90,0,90,0]` deg)까지 관절 이동한다. TP 의 사용자 홈 각도를 읽는 서비스가 없으므로 TP 의 사용자 홈과 같은 값으로 직접 맞출 것. 로봇이 STANDBY·정지·Tool/TCP 정상일 때만 받고, 끝나면 실제 도착 여부를 확인해 로그에 남긴다. 끄려면 `allow_home_move:=false`.

**속도 슬라이더** 는 `motion/change_operation_speed`(TP 속도 슬라이더와 같은 전체 배율, 코드의 vel 과 곱해짐)로 연결된다.
드라이버에 속도를 읽는 서비스가 없어 HMI 에는 '마지막으로 설정에 성공한 값' 을 표시하고, 설정 전이거나 드라이버 연결이 바뀌면 `—` 로 나온다.
노드 시작 시 자동 설정은 하지 않는다. Force Zero 는 읽는 서비스가 없어 미완료로 나온다.
RG2 가 `끊김` 이면 `sodreal` 터미널에서 `OnRobotRGControllerServer ... process has died` 를 확인할 것 (`python3-pymodbus` 미설치가 원인이었던 적 있음).

## 에러 팝업

시스템 로그 메시지(`LogEntry`)에 `popup=true` 를 붙여 보내면 HMI 가 로그 탭에 더해 **팝업으로도** 띄운다.
작업자가 놓치면 안 되는 것에만 쓴다. 현재는 `robot_monitor_node` 가 Tool/TCP 설정 실패(그 이름이 TP 에 없음)에 사용한다.

- 팝업은 비모달이라 떠 있어도 STOP 등 화면 조작을 막지 않는다.
- 떠 있는 동안 다른 팝업 로그가 오면 새 창을 띄우지 않고 같은 창에 한 줄 추가한다(같은 문구는 중복으로 쌓지 않음).
- 검사 노드에서도 같은 방법으로 띄울 수 있다: `itf.LogEntry(stamp, 'ERROR', '문구', popup=True)`.

## 동작 코드에서 진행률 보고하기

동작 코드는 `status` 를 직접 보내지 않는다(발행자가 둘이 되면 값이 섞인다). 진행 상황만 보내면 모니터 노드가 로봇 값과 합쳐 HMI 로 보낸다.

```python
from cable_hmi.hmi_progress import ProgressReporter

progress = ProgressReporter(node, points=3, steps=['접근', '파지', 'Pull', '후퇴'])
progress.start()
for i, point in enumerate(points):
    progress.point(i, point.name)
    progress.step('접근');  ...
    progress.step('파지');  ...
progress.finish()                 # 100 %.  도중에 그만둘 때: progress.abort('사유')
```

진행률 = (끝난 Point 수 + 현재 Point 안의 단계 위치) ÷ 전체 Point 수. `steps` 에 없는 이름은 글자만 표시되고 퍼센트는 그대로다.
예제: `~/ros_ws/move_async.py`. 실행 전에 `sod` 와 `source ~/ros_ws/install/setup.bash` 둘 다 필요하다.

## 실제 검사 노드와 통합하기

1. 검사 노드(`cable_pkg`)가 위 토픽을 제공한다. 가장 빠른 방법은 `cable_hmi.interface` 를
   import 해서 `encode_status()` 등을 그대로 쓰는 것 (`mock_inspection_node.py` 참고).
   힘 값은 한 번 읽어 CSV 기록과 status publish 에 같이 써야 화면 값과 판정 값이 일치한다.
2. 팀 공용 메시지(`cable_msgs`, ament_cmake)가 확정되면 `interface.py` 의 `*_MSG_TYPE` 과
   `encode_*` / `decode_*` 본문만 바꾼다. UI 와 mock 은 수정할 필요가 없다.
3. 로봇 namespace 가 필요하면 `namespace:=dsr01` 처럼 launch 인자로 준다(토픽이 상대 이름).

## 테스트

```bash
cd ~/ros_ws/src/cable_hmi && python3 -m pytest test
```
