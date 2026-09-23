# CCCIS 시퀀스 코드

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
Home/Safe Escape 모션과 Recipe 조회만 담당하고, Job 정책은 Main Work에 둔다.
`seq_00_main_work/node.py`는 cable_pkg 내부의 명령 수신부다. cable_hmi 패키지를 수정하거나
import하지 않는다. 명령 수신과 장비 Worker를 분리하여 모션 중에도 STOP/PAUSE를 받는다.

## 아직 입력해야 하는 위치값

`src/cable_pkg/config/system_recipe.json`의 다음 항목은 현장에서 입력한다.
미입력 상태에서는 노드만 대기할 수 있으며 START는 INIT_FAIL로 거부된다.

- `home_pose`, `work_Access_safe_pose`: `task`와 `joint`, 각각 6개 mm/deg 값.
- `work_area`: 상호작용 가능 영역. `x_min_mm`, `x_max_mm`, `y_min_mm`, `y_max_mm`,
  `z_min_mm`, `z_max_mm`를 가진 객체.
- `allowed_workspace`: 이동 목표 TCP 허용영역. 동일한 6개 경계 키.
- `safe_home_route`: 검증된 Pose 목록. 마지막 Pose는 `home_pose`와 같아야 한다.
- `tool_approach_axis`: Tool 좌표계의 접근축 3개 성분. 역방향을 Safe Escape에 사용한다.

Safe Escape는 현재 ZYZ 자세로 축을 BASE에 변환하고 경계 밖까지 필요한 거리만 이동한다.
상한 30 mm 안에서 벗어날 수 없으면 실패한다. Boundary 검사는 TCP 목표 확인이며
MoveJ의 링크/중간경로 충돌을 증명하지 않는다. 경유 좌표는 현장에서 확인된 값만 넣는다.
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

`--recipe <경로>`를 여러 번 지정하면 Recipe ID별로 등록한다. 기본은 LAN L2/L5 레시피다.
START 때 해당 파일을 다시 읽어 Snapshot을 고정한다. 실행 중 변경은 다음 Job에 적용한다.

명령은 `/cable_inspection/command`의 `std_msgs/msg/String` JSON이다.
`name`: START / PAUSE / RESUME / STOP / HOME_RETURN / SELECT_RECIPE / SYNC.
START/SELECT_RECIPE의 `args.recipe_id`에 등록한 ID를 넣는다.
Heartbeat는 `/cable_inspection/hmi_heartbeat`의 `std_msgs/msg/Empty`다.
단독 확인 시에도 사용자가 Heartbeat를 공급해야 한다.

```bash
# 통신 확인용 별도 터미널 (HMI와 동시에 쓰지 않는다)
ros2 topic pub -r 2 /cable_inspection/hmi_heartbeat std_msgs/msg/Empty '{}'
# 실제 Job 시작: 로봇이 움직인다.
ros2 topic pub --once /cable_inspection/command std_msgs/msg/String \
  "{data: '{\"name\":\"START\",\"args\":{\"recipe_id\":\"CCCIS_LAN_INSPECTION_V1\"}}'}"
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

운영 레시피는 `recipe/inspection/lan_inspection_recipe.json` 하나에 관리한다.
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
BASE 진입 방향:           (기존과 같으면 -Y)
추가 진입 최대거리(mm):   (L2는 5, L5는 6이므로 선택 필요)
검사 순서:               (미지정이면 기존 Point 뒤)
```

TASK 위치는 mm, 자세와 JOINT는 deg다. 새 포인트도 동일한 LAN 검사라면
Soft Open 25 mm, Soft Close 22 mm/10 N, Hard 16 mm/20 N,
진입 힘 상한 5 N, Pull 기준 힘 15 N/최대거리 25 mm/속도 10 mm/s,
정상 허용 변위 5 mm 조건을 유지한다. 다른 조건은 위치와 함께 명시한다.
위치가 없는 임시 Point를 실행 레시피에 넣지 않는다.
전체 Job 구동을 위한 Home/Work Access/Boundary/Safe Home Route는 별도의 System Recipe에 입력한다.
