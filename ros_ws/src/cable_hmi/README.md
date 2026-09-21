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
| `detail_dialog.py`, `style.py` | 상세 팝업 2개의 동작(값 채우기), 코드에서 동적으로 입히는 색(PASS/FAIL/MISSING 등) |
| `result_detail_dialog.ui`, `lookup_detail_dialog.ui` | **상세 팝업의 배치 + 스타일.** Qt Designer 로 편집 |
| `mock_inspection_node.py` | 가상 검사 노드. 실제 검사 노드가 구현할 동작의 참조 구현 |
| `robot_monitor_node.py` | 실제 로봇 값 → status (두산 조회 서비스를 비동기로 읽음). STOP, Tool/TCP 자동 설정, 속도 설정, Home 이동. `dsr_msgs2` 가 필요한 유일한 파일 |
| `hmi_progress.py` | 동작 코드에 붙이는 부품 (`ProgressReporter`): 진행률 보고 + HMI 의 검사 시작 / 일시정지 / 이어하기 / STOP 수신 |
| `recipe_catalog.py` | 레시피 JSON 폴더를 읽어 목록 · 버전 · 포인트(티칭 여부)를 돌려준다 |
| `recipe_db.py` | 레시피 정보(케이블, 판정 기준)를 SQLite 의 뷰 `v_recipe_point` 에서 읽는다. 읽기 전용, ROS·Qt 무관 |
| `lookup_tab.py` | '통합 조회' 탭. 레시피 DB · JSON · 저장된 검사 결과를 한 표에서 검색 (읽기 전용, 백그라운드 조회) |
| `result_db.py` | 검사 결과를 SQLite 테이블 `inspection_result` 에 쓰고 읽는다 |
| `result_recorder_node.py` | 결과 토픽을 받아 DB 에 저장하고 `db_saved=true` 로 다시 보내는 노드 (두 launch 파일이 함께 띄운다) |

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
- **상세 팝업**도 같은 방식이다: `result_detail_dialog.ui`(검사 결과 상세), `lookup_detail_dialog.ui`(레시피 포인트 상세).
  카드 위치·크기·순서, 제목 글자, 색, 여백, 창 크기는 자유롭게 바꿔도 된다. 코드는 **값이 들어가는 라벨**만 objectName 으로 찾는다
  (`recipeValue`, `badge`, `pointValue`, `timeValue`, `cableValue`, `limitValue`, `pullForceValue`, `productValue` ... - `detail_dialog.py` 의 `_load()` 참고).
  그 라벨을 지우거나 이름을 바꾸면 그 항목만 빠지고 창은 그대로 뜨며, 터미널에 `... .ui 에 없는 위젯` 경고가 나온다.
  배지 색(PASS/FAIL/MISSING)과 '저장 완료' 색은 상황에 따라 바뀌므로 코드(`style.py`)에 있다. 팝업은 코드에서 항상 비모달로 만든다(STOP 을 막지 않기 위해).
  스타일은 Designer 에서 실제와 같은 모양으로 보이도록 `main_window.ui` 의 규칙 일부를 각 `.ui` 에 복사해 두었다 - 공통 모양을 바꿀 때는 세 파일을 같이 고칠 것.
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
**Home 이동 버튼** 은 `motion/move_joint` 비동기 호출로 `home_joints`(launch 인자, 기본 `[0,0,90,0,90,0]` deg)까지 관절 이동한다. TP 의 사용자 홈 각도를 읽는 서비스가 없으므로 TP 의 사용자 홈과 같은 값으로 직접 맞출 것. 로봇이 STANDBY 이고 정지해 있을 때만 받고(동작 코드가 검사 중·이동 중·일시정지면 거부), Tool/TCP 설정은 조건이 아니다 - 관절 이동이라 TCP 와 무관하고 툴 무게는 힘 계산에만 영향을 주기 때문이다. Tool/TCP 가 미설정이면 경고만 로그에 남긴다. 끝나면 실제 도착 여부를 확인해 로그에 남긴다. 끄려면 `allow_home_move:=false`.

**속도 슬라이더** 는 `motion/change_operation_speed`(TP 속도 슬라이더와 같은 전체 배율, 코드의 vel 과 곱해짐)로 연결된다.
드라이버에 속도를 읽는 서비스가 없어 HMI 에는 '마지막으로 설정에 성공한 값' 을 표시하고, 설정 전이거나 드라이버 연결이 바뀌면 `—` 로 나온다.
노드 시작 시 자동 설정은 하지 않는다. Force Zero 는 읽는 서비스가 없어 미완료로 나온다.
RG2 가 `끊김` 이면 `sodreal` 터미널에서 `OnRobotRGControllerServer ... process has died` 를 확인할 것 (`python3-pymodbus` 미설치가 원인이었던 적 있음).

## Recipe 목록 (레시피 JSON 연결)

`robot_monitor_node` 가 `recipe_dir` 폴더의 레시피 JSON 을 읽어 `status.available_recipes` 로 보내고, HMI 의 Recipe 콤보가 그 목록으로 채워진다.
HMI 는 파일을 직접 읽지 않는다 — 동작 코드가 쓰는 레시피와 화면에 보이는 레시피가 어긋나지 않게 하기 위해서다.

```bash
ros2 launch cable_hmi hmi_monitor.launch.py recipe_dir:=/path/to/recipes     # 기본: ~/ros_ws/recipe_prototype/recipe/examples
```

- 파일 형식은 `recipe_prototype` 의 `InspectionRecipe.save_json()` 결과(JSON)다. `recipe_catalog.py` 는 그 파이썬 코드를 import 하지 않고 JSON 만 읽으며, 모르는 필드는 무시한다.
- HMI 에서 Recipe 를 고르면 `SELECT_RECIPE` 명령이 나가고, 노드가 받아들이면 status 에 id · 버전 · 포인트 수가 실려 콤보 · 버전 · "전체 N" 에 표시된다.
- **좌표가 전부 0 인 포인트는 "티칭 안 됨"** 으로 보고 시스템 로그에 경고한다 (예제 파일의 자리표시자. 그대로 로봇에 보내면 기계 원점으로 간다).
- 형식이 틀린 파일은 건너뛰고 이유를 경고로 남긴다. 폴더는 5 초마다 다시 확인하므로 파일을 고치거나 추가해도 노드를 다시 띄울 필요가 없다.
- 모니터 노드는 Recipe 로 로봇을 움직이지 않는다. 목록과 내용을 보여 줄 뿐이다. 검사 시작은 HMI 버튼을 받는 동작 코드가 붙어 있을 때만 열린다(아래 '동작 코드에서 검사 시작 / 일시정지 / 이어하기 받기').
- 단위는 두산 기준: `task` = mm · deg (BASE, ZYZ), `joint` = deg.

## 레시피 DB (SQLite)

케이블 번호·종류와 판정 기준(허용 변위, Pull 힘, 반복 횟수, 파지 폭)은 SQLite 에서 읽는다. 위치 좌표는 레시피 JSON, 케이블·기준은 DB 가 맡고 `recipe_id + point_id` 로 묶인다.

```bash
ros2 launch cable_hmi hmi.launch.py          recipe_db:=/path/to/inspection.db   # 기본: ~/ros_ws/results/inspection.db
ros2 launch cable_hmi hmi_monitor.launch.py  recipe_db:=/path/to/inspection.db
```

- **DB 는 노드가 읽고 HMI 는 읽지 않는다.** 노드가 결과 메시지에 케이블·기준을 채워 보내므로, 상세 팝업에는 항상 *판정 당시*의 기준이 보인다 (검사 후 DB 를 고쳐도 지난 결과의 표시가 바뀌지 않는다).
- **테이블 구조는 아직 정하지 않았다.** `recipe_db.py` 는 실제 테이블을 모르고 약속된 뷰 `v_recipe_point` 하나만 조회한다. 테이블을 설계한 뒤 아래 컬럼 이름으로 묶는 뷰만 만들면 코드 수정 없이 값이 채워진다.

  | 컬럼 | |
  |---|---|
  | `recipe_id`, `point_id` | 필수 |
  | `recipe_version`, `product_id`, `point_name`, `cable_id`, `cable_type` | 선택 |
  | `max_displacement_mm`, `pull_force_n`, `repeat_count`, `grip_width_mm` | 선택 |
  | `point_order` | 선택. 있으면 이 순서로 정렬 |

- DB 파일이 없거나 뷰가 아직 없으면 경고만 남기고 DB 없이 동작한다 (mock 은 내장 예제 레시피, 모니터 노드는 해당 칸 빈 값).
- 읽기 전용(`mode=ro`)으로 열기 때문에 이 코드가 DB 를 만들거나 고치는 일은 없다. DB 파일은 `.gitignore` 로 저장소에서 제외한다.
- mock: DB 를 읽을 수 있으면 Recipe 목록·케이블·기준을 DB 에서 가져온다 (Point 결과는 PASS → FAIL_DISPLACEMENT → MISSING 순으로 돌려 씀).
- 모니터 노드: Recipe 를 고르면 제품 ID 를 채우고, 레시피 JSON 과 DB 중 한쪽에만 있는 포인트를 경고한다. 이 노드에는 "현재 포인트" 가 없어서, 판정 기준 칸은 모든 포인트의 기준이 같을 때만 채운다.

## 통합 조회 탭

"시스템 로그" 옆의 **통합 조회** 탭에서 레시피 DB 와 레시피 JSON 의 내용을 한 표로 검색한다 (포인트 1개 = 1행).

- 검색어는 Recipe · Point · 이름 · 케이블 · 종류 · 제품 · 위치 상태에서 찾는다 (대소문자 무시, 띄어 쓰면 모두 포함). Recipe 콤보로 범위를 좁히고, 열 제목을 누르면 정렬된다.
- 표의 열은 '현재 검사 결과' 표와 같다: `Recipe / 검사 시간 / Point / 케이블 / 종류 / 결과 / 상세` (Recipe 를 하나 고르면 Recipe 열은 숨는다). 판정 기준, 좌표 등 나머지는 상세 팝업에 있다.
- 행의 바탕색은 레시피 JSON 과 대조한 결과다: JSON 에만 있고 DB 에 없는 포인트는 빨간색(케이블 칸에 `DB 없음`), 위치가 없거나 미티칭(좌표가 전부 0)인 포인트는 노란색. 자세한 상태는 말풍선과 상세 팝업의 배지(`티칭됨` / `미티칭` / `위치 없음` / `DB 없음`)에 나온다.
- 행을 누르면 그 포인트의 **상세 팝업**이 뜬다 (현재 검사 결과의 상세 팝업과 같은 구성, 비모달이라 STOP 을 막지 않음): 레시피·버전, Point·이름·케이블, 최근 검사 결과(DB), 판정 기준(DB), 위치 좌표 Task/Joint(레시피 JSON), 제품 ID, Force 원본 ID, DB·JSON 어느 쪽에 있는지.
- 이 탭은 진행 중인 검사가 아니라 **지금 DB·파일에 들어 있는 내용**을 보여 준다. 그래서 HMI 의 다른 부분과 달리 DB 를 직접 읽는다 (`recipe_db`, `recipe_dir` 실행 인자). 읽기 전용이고, 조회는 별도 스레드에서 하므로 DB 가 잠겨 있어도 화면과 STOP 은 멈추지 않는다. 검사에 쓰는 기준은 여전히 노드가 보낸 값이다.
- DB 를 고친 뒤에는 **조회** 버튼을 누르면 다시 읽는다. DB 파일이나 뷰가 없으면 이유를 아래 줄에 표시하고 레시피 JSON 의 포인트만 보여 준다.
- **결과 / 검사 시간** 열은 DB 에 저장된 그 포인트의 가장 최근 검사 결과다(없으면 `—`). 검색어에 `PASS`, `MISSING` 처럼 결과 코드를 넣어 찾을 수 있고, 상세 팝업의 '최근 검사 결과 (DB)' 패널에 결과 코드 · 검사 시간 · 대표 측정값 · 판정 사유 · 처리가 나온다. 검사를 마친 뒤 **조회** 를 눌러야 새 결과가 보인다.
- 같은 포인트의 지난 검사 이력 전체를 나열하는 기능은 아직 없다 (DB 에는 검사마다 쌓인다).

## 검사 결과 저장 (SQLite)

`result_recorder_node` 가 `cable_inspection/result` 를 받아 레시피와 같은 DB 파일(`recipe_db` 실행 인자, 기본 `~/ros_ws/results/inspection.db`)의
테이블 `inspection_result` 에 저장한다. 테이블은 없으면 만든다. 검사 1회(`run_id`)의 Point 1개가 1행이고, 같은 검사의 같은 Point 를 다시 저장하면 덮어쓴다.
열은 `PointResult` 의 필드 그대로 + `saved_at` 이다.

- 저장에 성공하면 같은 결과를 `db_saved=true` 로 다시 보낸다. HMI 는 같은 run 의 같은 Point 를 덮어쓰므로 상세 팝업의 `○ 저장 안 됨` 이 `● 저장 완료` 로 바뀐다.
- 결과에는 검사 당시의 판정 기준과 **위치(`task`, `joint`)** 도 실려 와 함께 저장된다(좌표는 JSON 글자로). 그래서 나중에 레시피를 고쳐도 지난 결과의 상세 팝업은 검사 당시 값을 보여 준다. 위치를 채우지 않는 쪽(mock)의 결과는 위치 칸이 `—` 로 나온다.
- 결과를 누가 보냈는지는 따지지 않는다 (mock, 동작 코드의 `report_result()`). 그래서 결과를 보내는 쪽은 `db_saved` 를 채우지 않는다.
- HMI 화면 프로세스는 저장하지 않는다 - DB 가 잠겨 있어도 화면과 STOP 이 멈추면 안 되기 때문이다. 저장 실패는 시스템 로그에 경고로만 남고 검사는 계속된다.
- mock 은 실행할 때마다 `run_id` 가 1 부터라서, mock 을 다시 띄워 검사하면 지난 mock 결과를 덮어쓴다. 동작 코드(`ProgressReporter`)의 `run_id` 는 시각 기반이라 겹치지 않는다.
- '현재 검사 결과' 표의 열(`검사 시간 / Point / 케이블 / 종류 / 결과 / 상세`)과 두 상세 팝업의 구성은 통합 조회 탭의 용어에 맞췄다. 표의 열 제목은 코드(`main_window.RESULT_HEADERS`)가 정하며 `.ui` 에 적힌 제목보다 우선한다.

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

## 동작 코드에서 검사 시작 / 일시정지 / 이어하기 받기

모니터 모드(`hmi_monitor.launch.py`)에서는 원래 이 버튼들이 잠겨 있다. 동작 코드가 `control=True` 로 붙으면
그 코드가 알려 주는 상태(대기 / 검사 중 / 일시정지 / 검사 완료)를 모니터 노드가 그대로 HMI 에 표시해 버튼이 열린다.
명령은 동작 코드가 `cable_inspection/command` 에서 직접 받는다(모니터 노드는 실행하지 않는다).

```python
from cable_hmi.hmi_progress import HmiStop, ProgressReporter

progress = ProgressReporter(node, points=3, steps=[...], control=True)
try:
    while True:
        progress.wait_for_start()          # HMI '검사 시작' 을 누를 때까지 기다린다 (start() 대신)
        for i, point in enumerate(points):
            progress.point(i, point.name)
            progress.step('접근')
            progress.check_pause()         # 모션을 걸기 전: 일시정지가 눌려 있으면 이어하기까지 기다린다
            amovel(...)
            while check_motion() != 0:     # 모션을 기다리는 동안: 실제로 멈추고 / 이어 가는 함수를 넘긴다
                progress.check_pause(pause=pause_motion, resume=resume_motion)
                time.sleep(0.05)
        progress.finish()                  # HMI '검사 완료'. 다시 '검사 시작' 을 누를 수 있다
except HmiStop:                            # HMI STOP: 로봇은 모니터 노드가 이미 멈췄다. 더 움직이지 말고 끝낸다
    progress.abort('(HMI STOP)')
finally:
    progress.close()
```

- **비동기 모션에서만 된다.** 동기 모션(`movej`, `movel`, `mwait`)은 끝날 때까지 코드가 멈춰 있어 `check_pause()` 를 부를 수 없고,
  드라이버도 그동안 `move_pause` 에 답하지 않는다(`move_stop` 만 따로 처리된다).
- 두산 파이썬 라이브러리에는 `move_pause` / `move_resume` 함수가 없다. 서비스 `dsr_controller2/motion/move_pause`,
  `.../move_resume` (`dsr_msgs2/srv/MovePause`, `MoveResume`) 를 직접 부른다 - `move_async.py` 의 `pause_motion()` 참고.
- 일시정지 중에는 `check_motion` 을 묻지 않는다. 그 값이 '정지' 로 나와도 도착으로 착각해 다음 단계로 넘어가지 않게 하기 위해서다.
- 명령은 별도 스레드가 받아 표시만 하고, 로봇을 건드리는 호출은 전부 `check_pause()` 를 부른 스레드에서 한다.
- 부품은 0.5 초마다 상태를 다시 알린다. 프로그램이 죽어 2 초 넘게 소식이 없으면 HMI 는 '모니터링' 으로 돌아간다.
- 동작 코드가 검사 중·일시정지일 때 모니터 노드는 Home 이동을 거부하고, 시작 대기 중에 로봇이 움직이고 있으면(Home 이동 등)
  끝날 때까지 '검사 시작' 을 잠근다.
- **FAIL / MISSING 포인트 이동**: `wait_for_start()` 대신 `name, args = progress.wait_for_command()` 를 쓰면 대기 중에 '검사 시작' 뿐 아니라
  HMI 의 포인트 이동 버튼(`MOVE_TO_POINT`, args `point_id`, `reason`)도 받는다. 이동 전 `progress.moving(point_id)`(HMI '이동 중' - 일시정지 / STOP 은
  검사 중과 똑같이 받고 '검사 시작' 은 잠긴다), 끝나고 `progress.moved()`(이동 전 상태로 복귀, 결과 표·제품 판정은 그대로). `inspect_async.py` 는 마지막으로
  검사한 레시피에서 그 Point 의 접근 자세(joint)로 **이동만** 한다(재검사 없음). 티칭 안 된 Point 와 레시피에 없는 Point 는 거부하고 시스템 로그에 남긴다.
  `wait_for_start()` 만 쓰는 코드(`move_async.py`)는 이 버튼을 무시하고 그 사실을 로그에 남긴다.
- 모션을 기다리는 루프가 끝난 직후에도 `progress.check_pause()` 를 한 번 부를 것: HMI STOP(모니터 노드의 `move_stop`)으로 모션이 끝난 것을 '도착' 으로
  처리하지 않기 위해서다 (`wait_motion()` 참고).
- **실제 장비 확인 필요**: `move_pause` 후 `move_resume` 이 가던 경로를 그대로 이어 가는지, 힘 제어 중 일시정지가 안전한지는
  아직 확인하지 않았다. `sodvir` 에서 먼저 확인할 것.

## 동작 코드에서 검사 결과 보고하기

모니터 노드는 판정하지 않는다. 동작 코드가 결과를 `cable_inspection/result` 로 직접 보내고, 모니터 노드는 동작 코드가 알려 준
`run_id` · 현재 Point 의 판정 기준 · 현재 판정 · 제품 판정을 status 에 옮겨 싣는다. HMI 의 '현재 검사 결과' 표, 상세 팝업,
PASS / MISSING / FAIL 집계, 제품 판정 배지가 그대로 채워진다.

```python
progress.point(i, point_id, criteria=itf.Criteria(max_displacement_mm, pull_force_n, repeat_count, grip_width_mm))
...
progress.report_result(itf.PointResult(
    recipe_id=..., recipe_version=..., product_id=..., point_id=point_id, cable_id=..., cable_type=...,
    result=itf.ResultCode.PASS, max_force_n=..., pull_force_n=..., displacement_mm=..., displacement_limit_mm=...,
    reason='...', action='...'))
...
progress.finish()                 # 보고된 결과로 제품 판정을 낸다: FAIL 있음 -> FAIL, MISSING 있음 -> 미검사 Point 있음, 아니면 PASS
```

- `run_id`(검사 1회의 번호)와 시각은 부품이 채운다. 검사를 시작할 때마다 새 번호가 되고 HMI 는 표를 비운다. 프로그램을 닫아도
  모니터 노드는 마지막 `run_id` 와 완료 표시(100 %, 제품 판정)를 유지하므로 표가 지워지지 않는다.
- HMI 를 검사 도중에 켜도 `SYNC` 로 이번 실행의 결과를 다시 받는다 (`control=True` 일 때).
- 예제: `~/ros_ws/inspect_async.py` - HMI 에서 고른 Recipe(JSON 위치 + DB 케이블·기준)의 Point 를 차례로 돌며
  `접근 -> 파지 -> Pull -> 후퇴` 를 하고 결과를 보고하는 **검사 뼈대**다. `sodvir` 에서 흐름과 화면을 미리 맞춰 보는 용도이며
  **측정·판정(`judge()`)과 그리퍼(`grip()` / `release()`)는 자리만 있다.** 측정이 없으므로 모든 Point 를
  `MISSING`(사유 '측정 미구현')으로 보고하고 제품 판정은 '미검사 Point 있음' 이 된다. 티칭 안 된(좌표가 전부 0) Point 는
  움직이지 않고 `MISSING`(사유 '미티칭')으로 보고한다.
- 예제 레시피 JSON 은 좌표가 전부 0 이라 움직이지 않는다. 가상 로봇에서 움직여 보려면 한 번
  `python3 ~/ros_ws/inspect_async.py --make-test-recipe` 를 실행한다. 레시피 폴더에 `virtual_test.json`(`VIRTUAL_TEST`, Point 3개)을
  만들며, task 좌표는 드라이버의 정기구학(`fkin`)으로 joint 에서 계산한다(로봇은 움직이지 않는다).

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
