# cable_inspection — 독립 검사 노드 패키지

Main 시퀀스·검사 판정·상시 로봇상태를 포함한 독립 ROS 2 패키지입니다.
**cable_pkg와 cable_hmi가 없어도 실물 로봇을 구동하고 검사합니다.**
HMI 화면, 검사 레시피 원본 관리, 이력 DB 저장·조회 기능은 HMI 담당 범위입니다.
이 패키지는 실행 레시피 수신·검증, 장비 동작·판정, 상태·결과 발행을 담당합니다.
공통 메시지 패키지 cable_interfaces와 실물용 ROS/두산·RG2 드라이버 의존성은 필요합니다.

## 검사파트에서 실행할 것

```bash
ros2 launch cable_inspection inspection.launch.py control_mode:=hmi
```

이 launch는 다음 세 프로세스를 실행합니다. 기본 control_mode는 hmi입니다.

| 실행 항목 | ROS 노드 이름 | 실제 진입점 | 역할 |
|---|---|---|---|
| main_sequence | ccc_sequence_node | cable_inspection/sequence/main_node.py:main | 명령·레시피 접수, 시퀀스 실행, 작업상태 |
| inspection_judgment | inspection_judgment_node | cable_inspection/sequence/judgment_node.py:main | 검사 판정·결과 발행 |
| robot_state_node | ccc_robot_state | cable_inspection/diagnostics/robot_state_node.py:main | 상시 로봇상태 수집·발행 |

main_sequence 내부에는 장비 서비스용 cccis_inspection_real 노드도 생성됩니다(virtual 모드는 cccis_inspection_virtual). 별도 실행 항목은 아닙니다.
기존 run.py에 해당하는 진입점이 이 패키지 내부로 이관되어 있습니다.
Home/Point/Grip/Pull은 sequence/main_node.py 내부 메서드이며 따로 실행하는 노드가 아닙니다.

```text
inspection.launch.py
├── main_sequence       → sequence/main_node.py:main
├── inspection_judgment → sequence/judgment_node.py:main
└── robot_state_node    → diagnostics/robot_state_node.py:main
```

로봇/RG2 드라이버는 기존 sodreal 또는 별도 driver launch로 실행합니다.
inspection.launch.py는 드라이버/HMI를 실행하지 않고 START를 기다립니다.

개별 실행이 필요하면 각 터미널에서 다음을 실행합니다. 통합 launch와 중복 실행하지 않습니다.

```bash
ros2 run cable_inspection main_sequence --control-mode hmi
ros2 run cable_inspection inspection_judgment
ros2 run cable_inspection robot_state_node
```

## 터미널 제어

```bash
# 터미널 1: Main + 판정 + 로봇상태
ros2 launch cable_inspection inspection.launch.py control_mode:=terminal

# 터미널 2: 숫자 메뉴
ros2 run cable_inspection sequence_console
```

terminal 모드는 패키지에 설치된 검사 레시피를 사용합니다. launch의 recipe 인자로 파일을 변경할 수 있습니다.
hmi 모드는 StartInspection 서비스로 전체 레시피를 받습니다. HMI Heartbeat가 필요합니다.
명령·상태·결과 토픽 및 서비스 이름은 기존 계약을 유지합니다.

## 패키지 내부 구조

노드 하나를 수정할 때 해당 파일에서 통신과 담당 처리를 함께 확인합니다.

```text
cable_inspection/
├── launch/                     # 검사·드라이버 launch
├── config/                     # 시스템 레시피·Tool·TCP 설정
├── cable_inspection/
│   ├── sequence/               # 검사 순서·판정·운전 입력
│   │   ├── main_node.py
│   │   ├── judgment_node.py
│   │   ├── sequence_console.py
│   │   └── inspection_cli.py
│   ├── hardware/               # 실제 Doosan/RG2 연결·이동·측정
│   │   └── robot.py
│   ├── diagnostics/            # 상시·수동 로봇상태 조회
│   │   ├── robot_state_node.py
│   │   └── manual_check.py
│   ├── recipe/                 # 실행 레시피 처리와 교시 JSON
│   │   ├── inspection_recipe.py
│   │   └── inspection/*.json
│   ├── data_models/            # 공통 상태·결과 데이터
│   │   └── models.py
│   └── safety/                 # 작업영역 계산
│       └── workspace_boundary.py
└── test/
```

기능 구현 파일 10개를 기능별 폴더에 배치했습니다.
이전에 통합한 노드/레시피 파일은 유지하며, 폴더별 __init__.py만 추가했습니다.
단계별 `seq_00`~`seq_07` 디렉터리와 별도 단계 클래스는 사용하지 않습니다.
`sequence/main_node.py`의 MainSequenceNode가 SequenceController를 생성하고 소유합니다.
SequenceController는 작업 상태와 장비 Worker의 흐름을, InspectionSequence는 포인트 검사 구간을 담당하는
같은 파일의 내부 실행 클래스입니다. 별도 ROS 노드가 아닙니다.
Initialize/Home/Finish와 Point/Grip/Pull은 이 클래스들의 메서드로 묶었습니다.
ROS callback과 장비 Worker가 같은 노드를 동시에 spin하지 않는 실행 구조는 유지합니다.

레시피 처리는 `recipe/inspection_recipe.py`에 모았습니다. 이 파일은 노드가 아닌 실행 데이터 처리 모듈입니다.
레시피 원본 DB·목록/저장 서비스·결과 이력 DB·조회 서비스는 포함하지 않습니다.
검사 측정 원본과 실행 스냅샷의 로컬 파일 기록은 장비 동작 진단을 위해 유지합니다.
공통 레시피 import는 `cable_inspection.recipe.inspection_recipe`를 사용합니다.

내부 import와 리소스 조회는 cable_inspection만 사용합니다.
설정은 설치된 share/cable_inspection에서 읽으며 원래 cable_pkg 소스 경로를 참조하지 않습니다.
기존 cable_pkg와 cable_management는 cable_inspection으로 대체했습니다. 소스 및 설치 패키지에서 이전 이름을 사용하지 않습니다.

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

- inspection_sequence: 기존 단독 검사 구간 실행 도구. Main과 같은 로봇에서 동시 실행하지 않습니다.
- manual_check: 로봇 상태 수동 조회.

## 외부 통신

검사파트:
- /cable_inspection/start: cable_interfaces/srv/StartInspection
- /cable_inspection/command: String JSON (PAUSE/RESUME/STOP/Home/SYNC)
- /cable_inspection/hmi_heartbeat: Empty
- /cable_inspection/robot_status, work_status, log, execution_snapshot: String JSON
- /cable_inspection/judgment_result: cable_interfaces/msg/InspectionResult

상태 Publisher는 diagnostics/robot_state_node.py의 RobotStateNode와 sequence/main_node.py의 MainSequenceNode에 있습니다.
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
3개 검사 프로세스 기동, 대기 작업상태·상시 로봇상태, 잘못된 START 거절, 결과 Publisher와 설치된 실행 항목을 확인합니다.
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
  Ready 접근은 MoveJ, Entry 접근은 도달 확인을 요구하는 MoveL, 검사 축은 Entry task의 자세각, 직선 복귀는 Entry task를 사용합니다.
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
| NOT_READY | SYSTEM_READY 상태가 아님 |
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
execution_order, points가 있습니다. **points는 point_id를 키로 한 객체**이며 실행 순서는 execution_order 배열입니다.
ROS InspectionRecipe.msg의 points는 **실행 순서대로 나열한 배열**입니다. 이 두 표현을 구분해야 합니다.
각 point의 필드는 InspectionPoint.msg와 같습니다. 실행 중 스냅샷은 수정하지 않습니다.

## 책임 분리 검증

- cable_pkg/HMI 없는 독립 워크스페이스에서 일반 설치 빌드 성공.
- 검사 레시피·전송 검증·동작 흐름 회귀 테스트 110개 및 ROS launch 통합시험 1개 통과.
- Main·판정·로봇상태 3개 검사 프로세스, 작업/로봇 상태, START 거절 응답과 결과 Publisher 확인.
- 설치된 실행 항목은 main_sequence, inspection_judgment, robot_state_node, sequence_console, inspection_sequence, manual_check의 6개입니다.
- HMI 관리 노드·관리 launch·DB 조회 서비스가 설치/기동되지 않는 것 확인.
- 실제 로봇 이동 명령은 보내지 않았습니다.

## 2026-09-23 설계 불일치 보완

Home 내부 복귀는 25 mm Open 및 정지 확인 → 현재 Tool −Z로 30 mm 직선 후퇴·목표 도달 확인 → Work Access → 0도 Home이다. 외부에서는 기존 0도 Home 직접 복귀를 유지한다. `safe_home_route`에는 현재 Home 한 개만 설정하며, `home_joint_tolerance_deg`는 0.1도다. Open 실패·후퇴 미도달·모션 오류는 후속 이동을 차단한다. 별도 contact_area나 영역 경계 탈출 검사는 사용하지 않는다. `max_escape_distance_mm`은 호환성을 위해 이름을 유지하며 현재는 설정 후퇴거리(30 mm)다. 이전 escape_clearance_mm은 사용하지 않는다.

Entry는 MoveL 목표 도달 확인 후 파지를 진행한다. SYSTEM_ERROR/판정 ERROR/동작 INCOMPLETE는 정상 Job 완료와 자동 최종 Home을 차단한다. Entry/Pull 최대거리는 25 mm, timeout은 10 s를 넘길 수 없다. LAN 15 N 및 후속 Soft/Pull 폭 판정은 유지한다. 상세 설계 개정·검증은 [05 반영 결과](../../docs/05_시퀀스_보류항목_반영결과_2026-09-23.md)를 따른다.

전체 시퀀스 재대조와 Pause 중 오류 감시 보완은 [06 재대조 결과](../../docs/06_시퀀스_전체_재대조_결과_2026-09-23.md)를 따른다.
