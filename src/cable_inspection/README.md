# cable_inspection — 로봇 제어·검사 패키지

최신 요구·설계 기준: [CCCIS v4](../../docs/v4/00_문서안내_v4.md) · [최종결론](../../docs/작업내역/18_최종결론_2026-09-25.md) · [미해결 확인 항목](../../docs/v4/01_commons/02_변경추적_및_확인항목_v4.md)

이 문서의 날짜별 테스트 수치는 당시 검증 이력입니다. 최신 보존 보고서는 U01/U02 반영 후 자동시험 257건·정량 비교 72건이며, 실물 검증과 구분합니다.

실물·가상 M0609/RG2 검사 시퀀스를 실행합니다. HMI 화면, 레시피 원본 관리, 결과 이력 DB는 HMI 담당 범위입니다. `cable_interfaces`의 서비스·토픽 계약은 그대로 사용합니다.

## 검사파트에서 실행할 것

```bash
ros2 launch cable_inspection inspection.launch.py control_mode:=hmi robot_mode:=real
```

launch는 `main_sequence` 한 프로세스를 시작합니다. 상태 수집은 기존 Robot·GripperTool 노드가 담당하며 HmiNode가 조합해 발행합니다. Main 프로세스 안에는 작업 제어 `ccc_sequence_node`, HMI 통신 `ccc_hmi_node`, 비동기 판정 `ccc_inspection_node`, 레시피 처리 `ccc_recipe_node`, 로봇 통신용 `ccc_robot_node`, 그리퍼 통신용 `ccc_gripper_tool_node` ROS 노드가 있습니다. 두 장비 노드는 real/virtual 모두 같은 이름으로 실행됩니다.

| 실행 단위 | 코드 위치 | 책임 |
|---|---|---|
| Main ROS 노드 | `sequence/main/node_main.py` | 객체 구성, 명령 실행 판단과 단일 모션 Worker 수명 관리 |
| HMI 통신 노드 | `hmi/node_hmi.py`, `hmi/interface.py` | START·명령·Heartbeat·판정 요청 수신, 상태·측정·결과·로그·Snapshot 송신 |
| Main 시퀀스 | `sequence/main/seq_main.py` | #00·#01·#07, 단일 모션 Worker, Pause/STOP, 다음 포인트 요청과 단일 검사 실행 |
| Inspection 시퀀스 | `sequence/inspection/seq_inspection.py` | #03~#05 접근·진입·파지·Pull 및 측정 요청 |
| 판정 ROS 노드 | `sequence/inspection/node_inspection.py` | #06 비동기 판정·결과 보관 및 HMI 전달. 로봇 모션은 수행하지 않음 |
| Home Return 시퀀스 | `sequence/home_return/seq_home_return.py` | #02 Safe Escape·Work Access·Home. Main 실행권 안에서 호출 |
| Recipe | `recipe/recipe.py`, `recipe/node_recipe.py` | 통신·파일 입력의 공통 검증, 수신본 보관·배열 순회·결과와 진행률 관리 |
| Robot | `robot/m0609.py`, `robot/node_robot.py` | M0609 raw component를 상속한 Robot API 노드 |
| GripperTool | `gripper_tool/rg2.py`, `gripper_tool/node_gripper_tool.py` | RG2 raw component를 상속한 독립 GripperTool API 노드 |

START와 HOME은 Main의 한 Worker를 통해서만 로봇을 움직입니다. 두 동작은 동시에 실행되지 않습니다. 장비 서비스 클라이언트와 RG2 구독은 각 장비 노드 생성 시 한 번 만들고, 첫 Initialize에서 준비·검증합니다. 이후 Job/Resume/Home은 같은 연결을 사용하며 필요한 상태를 재확인합니다.

로봇/RG2 드라이버는 기존 sodreal 또는 별도 driver launch로 실행합니다. inspection.launch.py는 드라이버와 HMI 화면 프로그램을 실행하지 않습니다. 검사측 HMI 통신 노드는 함께 실행하고 START를 기다립니다.

통합 launch 대신 Main을 직접 실행해도 장비 상태 수집이 함께 동작합니다.

```bash
ros2 run cable_inspection main_sequence --control-mode hmi
```

## 터미널 제어

```bash
# 터미널 1: Main·판정·로봇상태
ros2 launch cable_inspection inspection.launch.py control_mode:=terminal

# 터미널 2: 숫자 메뉴
ros2 run cable_inspection sequence_console
```

terminal 모드는 패키지의 검사 레시피 파일을 사용합니다. launch의 recipe 인자로 변경할 수 있습니다. hmi 모드는 StartInspection 서비스로 전체 레시피를 받으며 HMI Heartbeat가 필요합니다.

## 패키지 내부 구조

`robot/m0609.py`는 M0609 통신·raw 명령, `robot/node_robot.py`는 이를 상속한 Robot API를 제공합니다. `gripper_tool/rg2.py`와 `gripper_tool/node_gripper_tool.py`도 같은 구성이며 Robot을 참조하지 않습니다. 각 노드는 자체 서비스 클라이언트·피드백을 소유합니다. `HardwareContext` 중계 계층은 제거했습니다. Main은 두 장비 노드를 한 번 생성해 `SequenceMotion`에 전달합니다. `sequence/common/motion.py`는 장비를 상속하거나 연결하지 않고, 전달받은 API로 계측·모션 완료를 판단합니다. Safe Escape·Home 자세 검증과 경유 경로는 `sequence/home_return/seq_home_return.py`에 있습니다. 공통 운전 설정은 `sequence/*/data_models/의 개별 정의 파일`, 자세 오차·탈출 방향 계산은 `sequence/common/geometry.py`에 있습니다. 레시피 순회와 현황은 Recipe에서, Entry 방향은 Inspection에서 관리합니다. Main 시퀀스는 실행 순서·중단 처리와 HMI 연결·레시피 선택 판단을 소유합니다.

```text
cable_inspection/
├── robot/
│   ├── m0609.py                      # M0609 통신·raw 명령
│   └── node_robot.py                 # Robot API·비동기 상태 조회
├── gripper_tool/
│   ├── rg2.py                        # RG2 통신·raw 명령·피드백
│   └── node_gripper_tool.py          # GripperTool API·상태 유효성
├── sequence/
│   ├── main/
│   │   ├── seq_main.py              # 전체 작업 순서·상태 제어
│   │   ├── node_main.py             # 실행 객체·단일 Worker 관리
│   │   ├── console_main.py          # 터미널 제어 입력
│   │   └── data_models/
│   │       ├── job_context.py
│   │       └── system_state.py
│   ├── inspection/
│   │   ├── seq_inspection.py        # 한 포인트 검사·판정 관리
│   │   ├── node_inspection.py       # 판정 Queue·Worker·결과 저장·외부 발행
│   │   └── data_models/
│   │       ├── inspection_point_result.py
│   │       ├── judgment_request.py
│   │       ├── judgment.py
│   │       ├── inspection_result.py
│   │       ├── judgment_status.py
│   │       ├── pull_termination.py
│   │       └── grip_completion_timeout.py
│   ├── home_return/
│   │   └── seq_home_return.py       # 복귀 시퀀스
│   └── common/
│       ├── motion.py                # 공통 모션·계측
│       ├── geometry.py              # 자세·방향 계산
│       └── data_models/
│           ├── sequence_result.py
│           ├── sequence_status.py
│           └── robot_runtime_config.py
├── recipe/
│   ├── recipe.py                    # ROS 없는 입력·배열 순회·결과/현황 관리
│   └── node_recipe.py               # Recipe 실행 노드·메시지 변환 API
├── safety/workspace_boundary.py     # 작업영역 계산
├── hmi/
│   ├── interface.py                # HMI 요청·응답 처리
│   └── node_hmi.py                 # HMI ROS 서비스·토픽 소유
└── diagnostics/                     # 수동 조회·자동검증 도구
```

Recipe 노드는 Main과 같은 프로세스에서 생성되며 기존 START 수신부가 API를 호출합니다. 새로운 외부 서비스·토픽은 추가하지 않았습니다. Recipe는 실행 배열·현재 포인트·완료 수·판정 대기를 소유합니다. Controller는 next_point() 요청, 단일 검사, complete_point() 결과 반영을 수행합니다. 로봇 객체는 레시피 경로·원본·시스템 레시피를 보관하지 않습니다.

레시피 원본 DB·목록/저장 서비스·결과 이력 DB·조회 서비스는 이 패키지에 포함되지 않습니다. 검사 측정 원본과 실행 스냅샷의 로컬 파일 기록은 장비 동작 진단을 위해 유지합니다.

## 독립 워크스페이스에서 빌드

아래 두 소스 디렉터리만 새 워크스페이스에 복사합니다.

```text
inspection_ws/
└── src/
    ├── cable_interfaces/
    └── cable_inspection/
```

```bash
cd inspection_ws
source /opt/ros/jazzy/setup.bash
# 두산/RG2 인터페이스와 드라이버가 설치된 underlay
source ~/ws_cobot_pjt/ws_dsr/install/local_setup.bash
colcon build --packages-select cable_interfaces cable_inspection
source install/local_setup.bash
ros2 launch cable_inspection inspection.launch.py control_mode:=hmi
```

원래 검사 워크스페이스나 HMI 워크스페이스는 source하지 않아도 됩니다.
외부 의존성: rclpy, std_msgs, sensor_msgs, ament_index_python, rosidl_runtime_py,
launch/launch_ros/ros2launch, dsr_msgs2, onrobot_rg_msgs.
robot_bringup.launch.py는 추가로 dsr_bringup2/onrobot_rg_control 드라이버를 사용합니다.

실물 드라이버도 이 패키지의 launch로 실행하려면 별도 터미널에서 다음을 사용합니다.
이미 sodreal이 실행 중이면 중복 실행하지 않습니다.

```bash
ros2 launch cable_inspection robot_bringup.launch.py robot_host:=192.168.1.100 gripper_host:=192.168.1.1
```

## 검사 launch 인자

| 인자 | 기본값 |
|---|---|
| control_mode | hmi (terminal 선택 가능) |
| robot_mode | real (virtual 선택 가능; 드라이버 모드와 일치해야 함) |
| system_recipe | share/cable_inspection/config/system_recipe.json |
| recipe | share/cable_inspection/recipe/inspection/rcp_BMW_LWR_01.json (terminal만 사용) |
| results_dir | results/inspection_sequence |

시스템 레시피는 검사파트 소유로 유지합니다.
HMI 레시피는 실행 복사본으로만 사용하며 HMI 원본을 변경하지 않습니다.

## 추가 실행 항목

- manual_check: 로봇 상태 수동 조회.

## 외부 통신

검사파트:
- /cable_inspection/start: cable_interfaces/srv/StartInspection
- /cable_inspection/command: String JSON (PAUSE/RESUME/STOP/Home/SYNC)
- /cable_inspection/hmi_heartbeat: Empty
- /cable_inspection/robot_status, work_status, log, execution_snapshot: String JSON
- /cable_inspection/judgment_result: cable_interfaces/msg/InspectionResult

HMI용 상태·실행 Snapshot·로그·판정 결과 Publisher와 START 서비스는 모두 `hmi/node_hmi.py`의 HmiNode에 있습니다. RobotNode가 비동기 조회한 로봇 상태와 GripperToolNode가 수신한 폭의 유효성·시각을 HmiNode가 읽어 기존 `/cable_inspection/robot_status` 형식으로 발행합니다. 별도 상태 노드와 내부 중계 토픽은 제거했습니다.
두 PC의 ROS_DOMAIN_ID/Discovery 설정과 cable_interfaces 버전은 같아야 합니다.
기존 VOLATILE 결과 토픽의 과거 결과 자동 재전송 기능은 없습니다.

## 검증 방법

```bash
python3 -m pytest -q src/cable_inspection/test --ignore=src/cable_inspection/test/test_standalone_ros.py
```

cable_pkg/HMI가 설치되지 않은 독립 워크스페이스에서 실제 launch 통합시험:

```bash
CCCIS_STANDALONE_TEST=1 ROS_DOMAIN_ID=232 ROS_AUTOMATIC_DISCOVERY_RANGE=LOCALHOST python3 -m pytest -q src/cable_inspection/test/test_standalone_ros.py
```

통합시험은 격리 Domain에서 검사 launch만 실행합니다.
Main·판정 ROS 노드와 읽기 전용 상태 노드의 기동, 대기 작업상태·상시 로봇상태, 잘못된 START 거절, 결과 Publisher와 설치된 실행 항목을 확인합니다.
유효한 START/Home/STOP이나 실물 로봇 이동 명령은 보내지 않습니다.

## 2026-09-23 검토 피드백 반영

실제 로봇 제어·검사·판정·상태/결과 발행과 실행 레시피 검증은 cable_inspection가 담당합니다.
HMI 화면 구현은 별도 담당 범위이며 서비스/토픽으로 연동합니다.
cable_pkg 없이 실물 로봇을 구동하는 것이 독립화의 목표입니다.

- 감속 정지 대기 중의 모든 수집 샘플과 최종 샘플을 최대 힘 집계에 포함합니다.
  15 N은 정지 요청 기준입니다. 이 변경은 집계 누락을 고치며 물리적인 초과 힘을 줄이는 제어 변경은 아닙니다.
- 수동 HOME 요청이 시작되면 work_status.request_id를 비웁니다.
  검사 내부의 자동 HOME에서는 검사 요청 ID를 유지합니다.
  중복 START 방지용 접수 이력은 HOME/Initialize 때 지우지 않습니다.
- robot_mode 기본값은 real입니다. 가상 드라이버를 별도로 실행한 뒤
  `ros2 launch cable_inspection inspection.launch.py robot_mode:=virtual`로 선택할 수 있습니다.
  개별 Main 실행은 `ros2 run cable_inspection main_sequence --robot-mode virtual`입니다.
  가상 로봇상태 노드를 따로 실행할 때는 `--ros-args -p gripper_topic:=/dsr01/gripper_joint_states`를 지정합니다.
  모드/그리퍼 제공자 검증은 유지하며, 가상 모드도 드라이버를 통해 동작합니다.
  실물 연결 실패 시 가상으로 자동 전환하지 않습니다.
- 이번 목표는 정지 상태에서 수동 교시한 레시피의 실행입니다. 티칭 서비스는 후속 작업입니다.
  joint를 교시 기준으로 우선 기록하되, 현재는 같은 자세의 task도 필요합니다.
  Ready 접근은 MoveJ, Entry 접근은 미도달 결과 기록 후 진행을 허용하는 MoveJ, 검사 축은 Entry task의 자세각, 직선 복귀는 Entry task를 사용합니다.
  joint만 받는 레시피는 아직 지원하지 않습니다(FK 변환 후속 검토).
- 케이블 관리 식별자는 상태 토픽 분리와 무관합니다. 현재 point_id는 검사 위치 식별자입니다.
  cable_id와 product_id는 아직 메시지에 없으며, 케이블/제품의 종류 식별과 개체 추적을 구분해
  의미를 확정한 다음 레시피 → 실행 스냅샷 → 결과 → 조회까지 일관되게 추가해야 합니다.

### StartInspection 응답 계약

accepted=true인 경우:

| code | 뜻 |
|---|---|
| ACCEPTED | 새 검사 요청 접수. 실행 완료를 의미하지 않음 |
| ALREADY_ACCEPTED | 같은 ID·같은 레시피를 이미 접수함. 최초 run_id 반환, 재실행 없음 |

accepted=false일 때 run_id는 0입니다.

| code | 뜻 |
|---|---|
| INVALID_REQUEST_ID | 공백뿐인 ID 또는 128자 초과 |
| INVALID_RECIPE | 레시피 구조·좌표·검사조건 검증 실패 |
| REQUEST_ID_CONFLICT | 이미 접수된 ID로 다른 레시피를 보냄 |
| CONTROL_MODE_MISMATCH | Main이 hmi 제어 모드가 아님 |
| HEARTBEAT_MISSING | HMI heartbeat 미수신 또는 만료 |
| BUSY | Worker 실행/정지 처리 중 또는 작업 context가 남아 있음 |
| NOT_READY | 대기·정지·오류 상태가 아닌 실행·일시정지 상태 |
| NO_ENABLED_POINTS | 활성 검사포인트가 없음 |

검사는 위 표의 ID → 레시피 → 중복 → 모드 → heartbeat → BUSY → NOT_READY → 활성 포인트 순서로 확인합니다.
message에는 사람이 읽을 상세 사유가 들어갑니다. 장비 연결·초기화 실패는 접수 후 work_status/log로 알립니다.
request_id는 1~128자 문자열이며 공백만으로 구성할 수 없습니다. UUID 문자열 사용을 권장합니다.
ID를 자동 trim하지 않으므로 동일 요청은 원문 ID를 그대로 재사용해야 합니다.
새 실행에는 새 ID를 사용합니다. 중복 방지는 현재 Main 프로세스 수명 동안만 보장합니다.

### 작업 식별 및 실행 스냅샷

work_status.operation은 초기 `""`, 검사 `INSPECTION`, 별도 수동 복귀 `HOME`입니다.
마지막 작업 종류는 작업 종료 후에도 유지합니다. 실제 진행 여부는 work_active로 판단합니다.
request_id는 HMI 검사 START에서 받은 값이며 수동 HOME과 터미널 검사는 빈 문자열입니다.
검사 완료 후에는 마지막 검사 ID를 유지합니다.
HOME 상태의 run_id/레시피 등 검사 필드는 이전 검사 정보를 포함할 수 있으므로 새 검사 결과로 사용하지 않습니다.

execution_snapshot은 String JSON이며 최상위 필드는 다음과 같습니다.

| 필드 | 값 |
|---|---|
| run_id | 정수 실행 ID |
| request_id | HMI 요청 ID; 터미널이면 빈 문자열 |
| recipe_id / recipe_version | 접수한 레시피 식별자/버전 |
| recipe | 실행용 전체 레시피 복사본 |

recipe 내부에는 recipe_id, recipe_version, coordinate_frame, connector_type,
points가 있습니다. **points는 ROS InspectionRecipe.msg와 같은 실행 순서 배열**이며 별도 execution_order는 없습니다.
기존 파일의 points 객체와 execution_order는 입력 시에만 배열로 변환합니다. 실행 스냅샷 소비자는 배열 형식을 사용해야 합니다.
각 point의 필드는 InspectionPoint.msg와 같습니다. 실행 중 스냅샷은 수정하지 않습니다.

## 책임 분리 검증 이력

- cable_pkg/HMI 없는 독립 워크스페이스에서 일반 설치 빌드 성공.
- 검사 레시피·전송 검증·동작 흐름 회귀 테스트 167개 및 ROS launch 통합시험 1개 통과.
- 당시 Main·판정·로봇상태 노드 구성을 확인했다. 현재 로봇상태 수집은 장비 노드로 이관되어 독립 상태 노드가 없다.
- 설치된 실행 항목은 main_sequence, inspection_judgment, sequence_console, manual_check의 4개입니다.
- HMI 화면·DB 관리용 launch·조회 서비스는 설치하지 않습니다. 검사측 HMI 통신 노드는 main_sequence 내부에서 실행합니다.
- 실제 로봇 이동 명령은 보내지 않았습니다.

## 2026-09-23 설계 불일치 보완

Home 내부 복귀는 25 mm Open 및 실측 폭 확인 → 현재 Tool −Z로 30 mm 직선 후퇴·목표 도달 확인 → Work Access → 0도 Home이다. 외부에서는 기존 0도 Home 직접 복귀를 유지한다. `safe_home_route`에는 현재 Home 한 개만 설정하며, `home_joint_tolerance_deg`는 0.1도다. Open 실패·후퇴 미도달·모션 오류는 후속 이동을 차단한다. 별도 contact_area나 영역 경계 탈출 검사는 사용하지 않는다. `max_escape_distance_mm`은 호환성을 위해 이름을 유지하며 현재는 설정 후퇴거리(30 mm)다. 이전 escape_clearance_mm은 사용하지 않는다.

Ready pose에서 Entry pose로의 접근은 MoveJ이며 실제 도달 확인 후 다음 단계로 진행한다. 접근 미도달은 정지·포인트 오류·Job 오류로 처리하고 후속 파지를 차단한다. 접촉 진입/Pull의 미도달 기록·판정 정책과 구분한다. Entry pose에서 Soft Grip과 함께 Tool +Z로 이동하는 구간이 진입이다. Entry 최대거리 25 mm 검증은 유지하고, Pull 거리 및 Entry/Pull 시간은 레시피의 유한한 양수 값을 사용한다. PR #10에서 추가한 Pull 25 mm·시간 10 s 상한은 제거했다. 전체 포인트 순회 완료, pending_judgments 없음, 각 포인트 motion_status=SUCCESS, 유효한 PASS/FAIL/SYSTEM_ERROR 결과 및 log_saved=true가 완료 조건이다. adaptive_grip_status/pull_status/judgment_status는 별도 완료 게이트로 검사하지 않는다. SYSTEM_ERROR도 이 조건을 만족하면 Job 완료가 가능하며 Work Access에서 대기한다. 자동 Home은 없다. 현재 정책은 v4를 따르고 PR 복원 문서는 변경 이력으로 참고한다.

전체 시퀀스 재대조와 Pause 중 오류 감시 보완은 [06 재대조 결과](../../docs/작업내역/06_시퀀스_전체_재대조_결과_2026-09-23.md)를 따른다.

## 파지 완료 타임아웃 복구

Hard 파지 완료 타임아웃은 포인트 SYSTEM_ERROR로 기록한 뒤 Open·Entry 후퇴·Ready 복귀에 성공하면 다음 포인트로 진행한다. Pull은 생략하며 Open/복귀 실패·STOP·통신 오류는 작업을 중단한다. 상세는 [09 복구 정책](../../docs/작업내역/09_파지타임아웃_포인트복구_2026-09-23.md)을 따른다.

## 접촉 이동의 거리 상한

Entry 위치에서 Soft Grip과 함께 진행하는 추가 진입은 Tool +Z, Pull은 반대 방향이다. 거리 값은 목표 도달 필수 조건이 아닌 상한이다. 힘 한계에 먼저 도달하면 실제 이동량으로 기록·판정한다. 힘·거리 한계 전에 로봇이 정지해도 별도 종료 사유로 기록하고 Job 전체를 중단하지 않는다.

용어: Ready pose → Entry pose는 **접근(approach)**, Entry pose에서 케이블 방향 Tool +Z로 Soft Grip하며 이동하는 구간은 **진입(entry)**이다. Pull은 진입 방향의 반대 방향이다.

정상 Work Finish에서는 Work Access 도달과 검사 완료 조건을 확인한 뒤 그 위치에서 SYSTEM_READY로 대기합니다. 수동 HOME은 현재 Access를 먼저 확인해 직접 Home으로 가며, Access 이외 작업영역 내부에서만 Escape를 수행합니다. START는 Home을 경유하지 않고 아래 Work Access 준비 절차를 사용합니다.

## 장비 API 사용 경계

Main은 `RobotNode(mode)`와 `GripperToolNode(mode)`를 각각 생성하고 Sequence에 전달합니다. 두 노드는 Main과 같은 프로세스에 있으며 API 메서드로 사용합니다. 장비 드라이버와의 통신은 각 component 내부의 기존 ROS 서비스·토픽을 사용합니다. 모든 노드의 ROS 콜백은 Main의 단일 executor가 처리합니다. 장비 API의 응답 대기는 별도 시퀀스 Worker에서 수행하며 spin하지 않습니다. 검사와 Home Return의 명령 순서는 한 Worker가 관리합니다. STOP 종료 중에도 executor는 응답을 처리한 뒤 장비 노드를 해제합니다.

Robot API: `check_ready`, `initialize`, `check_operability`, `verify_mode`, `verify_active_tool_tcp`, `move_joint`, `move_linear`, `stop_motion`, `motion_status`, `robot_state`, `read_joints`, `get_tcp`, `get_tool_wrench`, `safe_abort`.

GripperTool API: `check_ready`, `initialize`, `set_grip`, `read_width`. busy는 기록용 피드백이며 명령 허용 조건이 아닙니다. real/virtual 서비스 제공자는 RG2 스스로 확인합니다. 두 장비 사이의 운전 모드 일치와 준비 순서는 Sequence에서 확인합니다.

MoveJ/MoveL API는 비동기 요청을 전송합니다. 목표 도달·Entry/Pull 종료·파지 성공과 Home 경로는 Sequence에서 판단합니다. 초기화는 양쪽 준비 확인 → 로봇 Tool/TCP 설정·검증 → 그리퍼 힘 동기화 → 계측 순서이며, 이후 Job/Home에서는 연결을 재생성하지 않습니다.

## 시퀀스 책임 경계

실행 진입점은 `sequence/main/node_main.py` 하나다. 여기서 Robot·GripperTool·Recipe와 공통 `SequenceMotion`과 `InspectionSequence`를 생성하고 `MainSequence`에 전달한다. 판정 노드 하나를 생성해 Inspection에 전달하고, HmiNode가 Main·판정 담당과 연결되어 모든 외부 HMI 통신을 맡는다. Main·Inspection·Home Return은 ROS 노드를 생성하지 않는 component다. Main의 단일 Worker만 모션을 실행한다.

`MainSequence`는 Recipe에 다음 포인트를 요청해 `InspectionSequence.run_point()`를 호출하고, 필요한 단계에서 `HomeReturnSequence.run()`을 호출한다. Inspection과 Home Return은 Main을 import하지 않는다. `motion.py`는 장비 클래스가 아니라 두 장비 API를 사용한 원시 계측·일반 이동 도달 확인 코드이며 새 연결을 만들지 않는다.

Inspection은 판정 노드의 submit/reset/snapshot/record_error API를 직접 호출한다. JudgmentClient와 내부 ROS 요청·결과 왕복은 제거했다. 판정 노드는 Queue·Worker·결과를 소유하고 외부 요청 구독과 결과 발행은 HmiNode가 담당한다. 판정 규칙은 InspectionJudgmentNode.judge_request(request)가 직접 처리하며 별도 Worker에서 호출한다. 종료는 실행 진입점에서 모션 Worker→판정 Worker→ROS 자원 순으로 처리한다. 기존 모션 순서·정지 조건·HMI 통신 필드는 유지한다.

Inspection은 전체 레시피를 보관하지 않고 실행 ID·레시피 ID·버전·케이블 종류와 현재 검사포인트만 사용한다. 판정 결과는 노드 내부에 직접 저장하며 모션 Worker와의 공유는 잠금과 복사본으로 보호한다. 실행 세대가 지난 결과와 복귀 오류 뒤의 정상 결과는 저장·발행하지 않는다.


### 공통 모션 책임 정리

- `main/seq_main.py`: 장비 준비·재확인 순서와 Work Access 이동 시점을 관리한다.
- `robot/node_robot.py`, `gripper_tool/node_gripper_tool.py`: 각 장비의 최초 초기화 성공 여부와 자체 점검을 관리한다. 반복 START/Home에서 연결이나 초기 설정을 다시 만들지 않는다.
- `inspection/seq_inspection.py`: 포인트의 Tool 축, Soft/Hard Grip 완료, Entry/Pull 종료 조건과 힘·변위·최소 폭 측정을 관리한다. 조건과 속도는 현재 포인트에서 직접 읽는다.
- `home_return/seq_home_return.py`: Safe Escape 및 Home 경로를 관리한다. Main의 장비 확인 후 실행한다.
- `common/motion.py`: 일반 MoveJ/MoveL 도달 확인, 상대 목표 계산, 정지 완료 대기, Open 폭 확인과 원시 측정 기록만 담당한다.

검사 시퀀스가 공통 계측 호출에 검사 측정값을 더하며, 감속 중 최대 힘과 최소 폭도 기록한다. 검사 외 공통 샘플에는 포인트·Entry/Pull 전용 필드를 붙이지 않는다. 일반 이동 결과에는 도달·오차·실제 이동량을, 접촉 이동 결과에는 기존 검사 전용 값을 함께 기록한다. 검사 속도를 공통 설정에 덮어쓰지 않으므로 Home 이동은 공통 속도를 사용한다.

검증은 장비 호출을 대체하는 오프라인 테스트와 실제 ROS 노드·서비스를 사용하는 격리 통합 테스트로 구분한다. `test_motion_feedback.py`는 위치·힘·폭만 가상으로 제공하고 실제 검사·공통 모션 코드를 실행한다. 실물 충돌 간섭이나 후퇴 거리의 적절성은 이 테스트의 검증 범위가 아니다.


### HMI 통신 전담 노드

`ccc_hmi_node`는 기존 main_sequence 프로세스 안에서 실행되는 독립 ROS 노드다. 실행 명령과 launch 인자는 동일하며 별도 실행 명령이 필요하지 않다. HMI 화면 코드와 msg/srv 정의, 기존 외부 토픽·QoS는 변경하지 않았다.

| 방향 | 기존 외부 경로 | 처리 책임 |
|---|---|---|
| 수신 | `start` 서비스 | HMI가 request_id·모드·Heartbeat를 확인, Recipe가 레시피 해석·검증, Main이 실행 가능 여부 결정 |
| 수신 | `command`, `hmi_heartbeat` | HMI 통신 처리 후 Main에 제어·통신 상태 전달 |
| 수신 | `terminal_command`, `terminal_heartbeat` | terminal 모드에서 같은 HMI 노드가 대체 입력 처리 |
| 수신 | `judgment_request` | HMI가 판정 담당에 전달 |
| 송신 | `work_status`, `execution_snapshot`, `log` | HMI 노드가 기존 JSON 계약으로 발행 |
| 송신 | `judgment_result` | 판정 노드가 확정한 결과를 HMI 노드가 발행 |
| 송신 | `robot_status` | Robot/RG2의 비동기 상태를 HMI 노드가 합쳐 전달 |

모든 경로의 앞에는 `/cable_inspection/`이 붙는다. 장비 드라이버 통신과 상태 수집은 Robot·GripperTool이 담당하며 HMI 노드는 장비를 직접 조회하지 않는다. 노드 간 연결은 명시적인 API·약한 참조 콜백으로 구성하고 모션 Worker는 Main에 하나만 둔다. 판정 단독 실행 항목도 HMI 노드를 함께 생성해 외부 결과·로그 통신을 맡긴다.

통신 노드 분리 당시 검증 이력: 오프라인 209개, 격리 ROS 통합 7개 통과. ROS 그래프에서 외부 HMI 서비스·발행·구독의 소유 노드를 확인했다. 실제 ROS 메시지로 HMI/terminal 입력, 중복 START, 실행 Snapshot, 로봇 상태 전달, 판정 결과 및 통신 유실·복구를 확인했다. 모션 Worker는 테스트에서 대체했으며 실물 로봇은 구동하지 않았다.


### START의 위치 조건

진행 중인 Job·Worker가 없으면 SYSTEM_READY/STOPPED/ERROR에서 새 START를 접수한다. 장비 준비 점검 후 이미 Work Access이면 이동을 생략하고, 작업영역 안이면 Open → Tool 접근 반대 방향 30 mm 후퇴 → Work Access, Home 등 작업영역 밖이면 Work Access로 직접 이동한다. Work Access 도달 확인 후에만 첫 검사포인트로 접근한다. STOP 후 수동 Home 복귀는 필수가 아니다. 검사 완료 후 Work Access에서 대기하며 수동 HOME 명령은 유지한다.

HMI 화면이 SYSTEM_READY만 START 버튼 활성 조건으로 사용한다면 HMI 담당에서 위 접수 상태를 반영해야 한다. 검사파트 HMI 서비스와 terminal 입력은 같은 상태 기준을 사용한다. 실행 중인 프로세스에는 변경이 자동 반영되지 않으므로 코드 적용 후 검사 프로그램을 다시 실행한다.

### 검사 완료 후 대기 위치 변경

검사 완료 후 자동 Home Return을 제거했다. 마지막 포인트 검사 후 Work Access로 복귀하고, 판정·기록 완료를 확인하여 SYSTEM_READY로 전환한다. 다음 START는 현재 Access 도달 확인 후 검사를 시작한다. Home은 별도 HOME_RETURN/MOVE_HOME 명령으로만 실행한다.

상태 수집 이관 내역과 검증 범위: [17_로봇상태_장비노드_이관](../../docs/작업내역/17_로봇상태_장비노드_이관_2026-09-25.md).

U01/U02 반영 검증: [257건 자동시험·72건 정량 비교](../../docs/v4/03_inspection/03_verification/04_운영코드_반영_검증요약_v4.md).
