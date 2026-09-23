# CCCIS 시퀀스 코드

HMI 토픽·명령·상태/결과 필드와 터미널 조작은 [HMI 인터페이스 및 수동 제어 명령](HMI_인터페이스_수동제어.md)을 참고한다.

## 코드 구조와 읽는 순서

문서의 #00~#07을 폴더 번호와 맞춘다. 단계의 동작은 `sequence.py`의 클래스가 맡고,
노드는 `node.py`, 실행 진입점은 `run.py`로 구분한다.

```text
sequence/
├── seq_00_main_work/          # sequence.py: SequenceController / node.py / run.py
├── seq_01_work_initialize/    # sequence.py: WorkInitializeSequence
├── seq_02_home_return/        # sequence.py: HomeReturnSequence
├── seq_03_point_transition/   # sequence.py: PointTransitionSequence
├── seq_04_adaptive_grip/      # sequence.py: AdaptiveGripSequence
├── seq_05_pull_inspection/    # sequence.py: PullInspectionSequence
├── seq_06_inspection_judgment/# node.py: InspectionJudgmentNode, JudgmentClient, 판정 함수
├── seq_07_work_finish/       # sequence.py: WorkFinishSequence, 완료 판정 함수
└── inspection/              # inspection.py: InspectionSequence / run.py: 검사 단독 실행
```

1. 전체 Job은 `seq_00_main_work/sequence.py`의 `SequenceController.run()`에서 읽는다.
2. 포인트 한 개의 검사는 `inspection/inspection.py`의 `run_point()`에서 읽는다.
3. 세부 동작은 각 번호 폴더의 `run()`으로 따라간다. #06은 별도 노드의 Worker가 실행한다.

`InspectionSequence`는 #03 → #04 → #05 호출 순서와 #06 결과 요청을 연결한다.
각 단계 클래스는 같은 hardware를 받아 직접 호출하며, 공통 부모 클래스는 두지 않는다.
Pause/Resume/STOP은 전체 작업 상태를 관리하는 `SequenceController`에 함께 둔다.

### 작성 형식

- 파일 상단에는 역할과 실행 순서를 5줄 이내로 적는다.
- `run()`에서는 순서를 읽고, 독립 기능의 세부 내용은 해당 메서드로 따라간다.
- 기능·인자·반환 설명은 `def` 위에 `#` 주석으로 적는다. 인자는 한 단계 들여쓴다.
- 반환 설명 앞에는 빈 주석 줄과 가로 구분선을 넣고, 메서드 사이는 빈 줄 3개를 둔다.

```python
# 기능: 레시피 조건으로 그리퍼를 개방한다.
#     point: 검사포인트 레시피의 Open 폭(mm)·힘(N).
#
#     ------------------------------------------------------------
#     반환: 개방 명령값과 실측 상태.
def open_gripper(self, point):
    ...
```

#06은 요청을 받는 노드이므로 `_work()`에서 판정 → 출력 → 결과 발행 순서를 읽는다.

## 통합 실행과 HMI 없는 운전

```text
system_bringup.launch.py
├── robot_bringup.launch.py       실물 M0609 + RG2
├── sequence_bringup.launch.py    Main + Judgment
└── HMI                          control_mode=hmi일 때만, mock=false
```

새 실행 파일과 launch를 설치한다.

```bash
colcon build --symlink-install --packages-select cable_pkg
source install/setup.bash
```

로봇 bringup을 아직 실행하지 않았다면 터미널 1에서:

```bash
ros2 launch cable_pkg system_bringup.launch.py control_mode:=terminal
```

기본 연결 주소는 로봇 `192.168.1.100`, RG2 `192.168.1.1`이다.
현장 주소가 다르면 `robot_host:=... gripper_host:=...`를 지정한다.
실물 전용이며 네임스페이스는 기존 코드에 맞춰 `/dsr01`이다.
이미 로봇/RG2 bringup이 실행 중이면 중복 실행하지 않고 아래 명령을 사용한다.

```bash
ros2 launch cable_pkg system_bringup.launch.py control_mode:=terminal start_robot:=false
```

터미널 2에서 환경을 source한 뒤 운전 메뉴를 실행한다.

```bash
ros2 run cable_pkg sequence_console
```

1=START, 2=Pause, 3=Resume, 4=STOP, 5=Home, 6=레시피 선택, 7=상태, Q=STOP 요청 후 종료.
launch는 일반 터미널 입력을 자식 노드에 전달하지 않으므로 운전 메뉴만 별도 터미널에서 실행한다.
HMI 코드와 가짜 HMI Heartbeat를 사용하지 않는다. terminal 전용 명령·Heartbeat로 기존 Main을 제어한다.
운전 콘솔은 하나만 사용한다. Q/Ctrl+C/입력 종료는 STOP 요청을 보내고,
비정상 종료로 Heartbeat가 유실되면 기존 완료점 Pause/복구 만료 처리가 적용된다.
콘솔 재실행 후에는 상태를 확인하고 PAUSED일 때 Resume한다. STOPPED는 Home 성공 후 새 Job을 시작한다.

`sequence_bringup.launch.py`만 실행하면 드라이버/HMI 없이 Main+Judgment를 시작한다.
`system_bringup.launch.py control_mode:=hmi`는 기존 HMI launch를 포함한다. HMI의 새 인터페이스 대응은 별도 작업이다.
`system_recipe`, `recipe`, `results_dir` 인자로 설정 파일과 결과 경로를 지정할 수 있다.
기본 레시피는 BMW, Joint 속도는 System Recipe의 10 deg/s다. START 전 자동 검사 이동은 없다.
Home/Work Access/경계가 미입력이면 전체 Job은 초기화 단계에서 거부된다.
이 좌표를 임의로 넣거나 터미널 모드에서 검증을 우회하지 않는다.

## 전체 Job

`seq_00_main_work/run.py`가 장비와 명령 수신 노드를 만든다.
`seq_00_main_work/sequence.py`의 `SequenceController.run()`을 위에서 아래로 읽으면
전체 흐름을 볼 수 있다. 기존 `inspection_sequence` 명령은 검사 부분만 확인할 때 사용한다.
두 실행부를 같은 로봇에서 동시에 실행하지 않는다.

```text
START
 → #01 Work Initialize (실패하면 이동 없이 SYSTEM_READY)
 → #02 Home Return
 → Work Access Safe Pose
 → Recipe Snapshot의 활성 Point 순회
     #03 Open → Ready → Entry
     #04 Soft+추가진입 → Soft 실측 폭 → Hard 완료 확인
     #05 Pull 정지 → 비동기 #06 요청 → Open → Entry → Ready
 → Work Access Safe Pose
 → #07 모든 모션/판정/로그/통신 완료 확인
 → #02 Home Return → SYSTEM_READY
```

`hardware/sequence_robot.py`는 공통 장비 동작을 기존 `HardwareRobot`에 추가한다.
Home/Work Access 모션과 Recipe 조회를 담당하고, Job 정책은 Main Work에 둔다.
`seq_00_main_work/node.py`는 cable_pkg 내부의 명령 수신부다. cable_hmi 패키지를 수정하거나
import하지 않는다. 명령 수신과 장비 Worker를 분리하여 모션 중에도 STOP/PAUSE를 받는다.

## 공통 Joint 이동 속도

`config/system_recipe.json`의 `joint_speed_deg_s`로 MoveJ 속도를 설정한다. 현재 10 deg/s다.
전체 Job은 System Recipe 검증 시 적용하고, 검사 단독 실행도 같은 설정을 읽는다.
단독 실행은 Home/Boundary 미입력 상태에서도 속도 설정만 사용할 수 있으며,
필요하면 `--system-recipe <경로>`로 파일을 지정한다. 단독 측정의 `inputs.json`에도 설정을 저장한다.
Joint 가속도는 기존 10 deg/s², 직선 이동 속도는 검사 레시피 설정을 유지한다.

## 아직 입력해야 하는 위치값

`src/cable_pkg/config/system_recipe.json`의 다음 항목은 현장에서 입력한다.
미입력 상태에서는 노드만 대기할 수 있으며 START는 INIT_FAIL로 거부된다.

- `home_pose`, `work_Access_safe_pose`: `task`와 `joint`, 각각 6개 mm/deg 값.
- `work_area`: TCP 포함 여부로 Home 복귀 경유를 결정하는 작업영역. `x_min_mm`, `x_max_mm`, `y_min_mm`, `y_max_mm`,
  `z_min_mm`, `z_max_mm`를 가진 객체.
- Home 관절 목표는 모두 0도다. `safe_home_route` 경유점 설정은 사용하지 않는다.
- `tool_approach_axis`: 기존 Safe Escape 유틸리티용 선택 설정. 현재 Home 복귀에서는 사용하지 않는다.

현재 Home 복귀는 작업영역 내부에서 먼저 Work Access Safe Pose로 이동한 뒤 전체 관절을 한 번의 MoveJ로 0도 복귀한다.
Work Access는 작업영역 내부에 있어도 된다. 이 분기에서는 Grip Relaxation/Safe Escape를 호출하지 않는다.
Work Access 이동 실패 시 Home 이동을 시작하지 않으며, 각 도착점에서 Pause/STOP을 처리한다.
영역 밖에서는 전체 관절을 한 번의 MoveJ로 0도 복귀한다.
Home의 TASK 도달 및 정지 상태와 전체 관절의 0도 오차 0.1도 이내를 확인한다. Work Access와 Home 완료점에서 Pause를 처리하며 이동 중 STOP을 감시한다.
`work_area`는 현재 TCP에 따른 복귀 경로 선택에만 사용한다. 별도의 허용 공간 입력이나 경계 기반 목표 이동 거부는 사용하지 않는다.
`heartbeat_timeout_s=2`, `communication_recovery_timeout_s=30`, `judgment_timeout_s=10`은
입력 템플릿의 초기값이며 System Recipe에서 조정한다.

## 실행

폴더와 실행 진입점이 변경되면 아래처럼 다시 빌드하고 환경을 로딩한다.
실행 명령 이름은 `main_sequence`, `inspection_sequence`, `inspection_judgment`를 유지한다.

```bash
colcon build --symlink-install --packages-up-to cable_pkg
source install/setup.bash
ros2 run cable_pkg inspection_judgment
# 별도 터미널 (source 후)
ros2 run cable_pkg main_sequence --system-recipe src/cable_pkg/config/system_recipe.json
```

`--recipe <경로>`를 여러 번 지정하면 Recipe ID별로 등록한다. 기본은 `rcp_BMW_LWR_01` 레시피다. 등록한 첫 레시피를 초기 선택값으로 사용한다.
START 때 해당 파일을 다시 읽어 Snapshot을 고정한다. 실행 중 변경은 다음 Job에 적용한다.

명령은 `/cable_inspection/command`의 `std_msgs/msg/String` JSON이다.
`name`: START / PAUSE / RESUME / STOP / HOME_RETURN / SELECT_RECIPE / SYNC.
SELECT_RECIPE의 `args.recipe_id`에 등록한 ID를 넣는다. 선택은 로봇을 움직이지 않는다.
`/cable_inspection/status`의 `available_recipes`는 등록된 ID 목록,
`selected_recipe_id`는 다음 START에 사용할 선택값이다. 선택 직후 상태를 발행한다.
`recipe_id`는 Job 중에는 실행 중인 ID, 대기 중에는 선택 ID를 나타낸다.
START의 `args.recipe_id`를 생략하면 선택된 레시피를 사용한다. 직접 지정해도 선택값에 반영한다.
미등록 ID 또는 Worker 동작 중 선택/START는 로그 토픽으로 거부 사유를 전달하며 선택값을 유지한다.
SYNC를 보내면 목록과 선택값을 다시 받을 수 있다. 파일 내용은 START 초기화 때 검증한다.
이 통신은 `main_sequence`에서 처리하며 `inspection_sequence`는 터미널 단독 실행용이다.

HMI 전송 JSON 예:
```json
{"name": "SELECT_RECIPE", "args": {"recipe_id": "rcp_BMW_LWR_01"}}
{"name": "START", "args": {}}
```
Heartbeat는 `/cable_inspection/hmi_heartbeat`의 `std_msgs/msg/Empty`다.
단독 확인 시에도 사용자가 Heartbeat를 공급해야 한다.

```bash
# 통신 확인용 별도 터미널 (HMI와 동시에 쓰지 않는다)
ros2 topic pub -r 2 /cable_inspection/hmi_heartbeat std_msgs/msg/Empty '{}'
# 실제 Job 시작: 로봇이 움직인다.
ros2 topic pub --once /cable_inspection/command std_msgs/msg/String \
  "{data: '{\"name\":\"START\",\"args\":{\"recipe_id\":\"rcp_BMW_LWR_01\"}}'}"
```

## Pause / Stop / 종료 보류

PAUSE는 Ready 도달, Entry 도달, Hard Grip 완료, Point Ready 복귀 등 완료점에서 대기한다.
Soft 추가진입 및 Pull→해제→복귀 도중에는 해당 원자 동작을 마친다.
RESUME은 같은 호출 위치에서 이어가므로 완료한 동작을 다시 실행하지 않는다.
통신 복구만으로는 재개하지 않는다. 복구 제한시간 초과는 COMM_ERROR로 끝낸다.
STOP은 서비스 대기/측정 중에도 감지하고 정지 요청 후 Context를 폐기한다. 자동 Home은 없다.
E-STOP/보호정지는 로봇 Safety 계층이 우선이며 코드가 Fault Reset을 하지 않는다.

Work Finish의 판정 대기시간 초과는 Work Access에서 PAUSED로 보류한다.
결과/통신을 복구한 뒤 RESUME으로 다시 확인하거나 STOP으로 종료한다.
SYSTEM_ERROR라는 결과가 있다는 것만으로 모션 안전이 확인되는 것은 아니다.
모션이 실패한 Job은 ERROR로 끝나며 정상 Home 복귀를 강제로 실행하지 않는다.

## 결과 / 수동 확인

결과는 실행 디렉터리의 `results/inspection_sequence/<시각>/`에 저장한다.
`samples.jsonl`, `inputs.json`, `inspection_results.json`, `judgment_results.json`,
`job_summary.json`, `status.json`을 확인한다. `--results-dir`로 위치를 바꿀 수 있다.
커스텀 결과 토픽은 `/cable_inspection/judgment_result`, 타입은
`cable_interfaces/msg/InspectionResult`다. HMI의 기존 JSON 토픽과 별개다.

사용자 확인 함수는 `test_module/sequence_checks.py`에 모았다.
`check_00_main_work`부터 `check_07_work_finish`, `check_common_command`를 직접 호출한다.
#03~#05는 앞 단계에서 준비한 실제 로봇 상태를 사용한다. 각 함수 설명에 전제조건과
기대 흐름을 적었다. 운영 코드는 이 파일에 의존하지 않으므로 나중에 삭제해도 된다.

실물 없는 분기/호출 순서 확인은 `test_module/test_sequence_offline.py`에서 수행한다.
장비 대역은 ROS 노드를 생성하지 않고 명령만 기록한다. 가상 측정값의 검증 결과는
실제 이동 경로, 접촉 힘, 파지 성능의 검증을 의미하지 않는다.

## 검사포인트 추가

### 작업 레시피 명명 규칙

파일명은 `rcp_[브랜드3글자]_[ZONE2~3글자]_[관리번호2~4글자].json`으로 정하고,
JSON의 `recipe_id`도 확장자를 제외한 파일명과 동일하게 맞춘다.
브랜드와 Zone은 영문 대문자를 사용하며, 관리번호는 문자열로 관리해 앞자리 0을 유지한다.
내용의 개정 버전은 `recipe_version`에서 별도로 관리한다.

| Zone | 검사 대상 구역 |
|---|---|
| FL | 전방 좌측 |
| FR | 전방 우측 |
| RL | 후방 좌측 |
| RR | 후방 우측 |
| CTR | 중앙/실내 대시보드 |
| UPR | 상부/루프 |
| LWR | 하부/언더바디 |

템플릿의 `rcp_XXX_LWR_01`에서 `XXX`는 실제 브랜드 축약값을 넣을 자리다.
브랜드는 현대·테슬라·BMW 등 실제 자동차 브랜드를 기준으로 정한다.
현재 작업 레시피는 예시 브랜드 `BMW`, 하부 구역 `LWR`, 관리번호 `01`을 사용한다.
파일명을 바꾸면 실행 명령의 `--recipe` 경로도 맞춘다. 실행 중에 ID를 바꾸었다면
`main_sequence`를 재시작해 등록 목록을 갱신하고 START에도 변경한 ID를 사용한다.

### 와이어링 하네스 작업 레시피

`recipe/inspection/rcp_BMW_LWR_01.json`의 등록 순서는 `HARNESS_01 → HARNESS_02 → HARNESS_03`이다.
ID는 `rcp_BMW_LWR_01`이며 세 Point 모두 활성화되어 있다. 03은 다른 구역의 Ready/Entry 좌표를 사용한다.
03의 기준 파지 폭은 23 mm이며 Soft Open 26 / Soft Close 23 / Hard Close 20 mm로 확정했다.
Entry/Pull 제한과 Grip 힘은 기존 조건을 유지한다.
각 Point에 아래 값을 채운다. 좌표/폭이 미입력이면 레시피 로딩 단계에서 거부된다.

- `ready_pose.task`, `entry_pose.task`: `[X,Y,Z,A,B,C]` (위치 mm, 자세 deg).
- `ready_pose.joint`, `entry_pose.joint`: `[J1,J2,J3,J4,J5,J6]` (deg).
- `grip_setting.soft_open_width_mm`: 접근/복귀 시 개방 폭(mm).
- `grip_setting.soft_close_width_mm`: 추가진입 중 Soft 파지 목표 폭(mm).
- `grip_setting.hard_width_mm`: Pull 전 Hard 파지 목표 폭(mm).

HARNESS_01/02는 BASE -Z로 추가진입하고 +Z로 Pull한다. 두 Entry의 B=180°에서 Tool +Z는 BASE -Z를 향한다.
HARNESS_03은 Entry ABC에 따라 BASE 방향벡터 약 [-0.017379, -0.396447, -0.917893]로 추가진입하며 Pull은 반대다.
진입 방향은 `entry_pose.task`의 ABC에서 자동 계산하며, Tool +Z를 케이블 체결축에 맞춰 교시한다.
수동 `entry_direction`은 운영 레시피에서 제거했다. 이전 파일에 해당 항목이 남아 있어도
로더는 사용하지 않으며 ABC를 기준으로 계산한다. Pull 방향과 힘 감시 축에도 같은 계산값을 사용한다.
추가진입 5 mm/힘 변화 상한 5 N, Soft 10 N/Hard 20 N, Pull 15 N/최대 25 mm를 적용한다.
판정 코드의 `Pull 실측 폭 < 16 mm → FAIL`은 현재 공통 고정값이며 Hard 목표 폭과는 별개다.
하네스 폭을 정할 때 이 판정 기준의 적용 여부도 확인한다.

좌표/폭을 입력한 뒤 `ros_ws`에서 검사 구간을 단독 실행하려면:

```bash
source install/setup.bash
ros2 run cable_pkg inspection_judgment
# 별도 터미널에서 source 후 실행. START 확인을 받으면 실제 로봇이 움직인다.
ros2 run cable_pkg inspection_sequence \
  --recipe src/cable_pkg/cable_pkg/recipe/inspection/rcp_BMW_LWR_01.json
```

전체 Job은 `main_sequence`에도 동일한 `--recipe`를 지정하며, System Recipe와 Heartbeat가 필요하다.

### 템플릿으로 새 레시피 작성

새 검사 레시피는 `recipe/inspection/inspection_recipe.template.json`을 별도 파일명으로
복사해서 작성한다. Point 한 개의 형식이며 Grip/Pull 조건은 기존 LAN 조건을
예시로 넣었다. 진입 방향은 Entry ABC에서 계산한다. Ready/Entry 좌표는 비워 두었으므로
작성 전에는 로딩 검증을 통과하지 않는다.

- `recipe_id`는 다른 레시피와 겹치지 않게 정하고, `connector_type`은 검사 대상에 맞춘다.
- `ready_pose`와 `entry_pose`의 `task`에 `[X,Y,Z,A,B,C]`, `joint`에 `[J1,J2,J3,J4,J5,J6]`을 입력한다.
- 이름·Entry 자세·조건을 확인하고 해당 포인트의 `enabled`를 `true`로 바꾼다.
- 포인트를 추가할 때는 Point 객체를 복사하고 `points`의 키, `point_id`, `execution_order`를 맞춘다.
- 새 파일은 실행 시 `--recipe <파일 경로>`로 지정한다. 실행 중인 Job에는 변경이 반영되지 않는다.

기존 LAN 검사포인트는 `recipe/inspection/lan_inspection_recipe.json` 한 파일에서 관리한다.
현재 `LAN_L2 → LAN_L5`를 유지하며 신규 Point는 기본적으로 실행목록 마지막에 추가한다.
`OperatingInspectionRecipe.add_point(point)`는 기존 ID를 덮어쓰지 않고 Point와 실행 순서를
함께 추가한다. `save_json(path)`로 저장하면 다음 START에서 다시 읽는다.
실행 중인 Job의 Snapshot은 바뀌지 않는다.

사용자 제공 형식:

```text
Point ID / 이름:
Ready TASK [X,Y,Z,A,B,C]:  (기존 L2/L5와 같으면 '기존 Ready 사용')
Ready JOINT [J1,J2,J3,J4,J5,J6]:
Entry TASK [X,Y,Z,A,B,C]:
Entry JOINT [J1,J2,J3,J4,J5,J6]:
진입축:                   Entry ABC에서 Tool +Z를 BASE로 변환해 자동 계산
추가 진입 최대거리(mm):   (L2는 5, L5는 6이므로 선택 필요)
검사 순서:               (미지정이면 기존 Point 뒤)
```

TASK 위치는 mm, 자세와 JOINT는 deg다. 새 포인트도 동일한 LAN 검사라면
Soft Open 25 mm, Soft Close 22 mm/10 N, Hard 16 mm/20 N,
진입 힘 상한 5 N, Pull 기준 힘 15 N/최대거리 25 mm/속도 10 mm/s,
정상 허용 변위 5 mm 조건을 유지한다. 다른 조건은 위치와 함께 명시한다.
위치가 없는 임시 Point를 실행 레시피에 넣지 않는다.
전체 Job 구동을 위한 Home/Work Access/Boundary는 별도의 System Recipe에 입력한다.
