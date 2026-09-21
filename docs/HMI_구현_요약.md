# 케이블 체결 검사 HMI — 구현 요약

작성일 2026-09-19 · 대상: `src/cable_hmi`, `src/cable_pkg` · 아직 git 커밋 전

---

## 1. 한눈에 보기

```
┌────────────┐  cable_inspection/command   ┌──────────────────────┐   두산 서비스(비동기)   ┌──────────────┐
│  PyQt HMI  │ ──────────────────────────▶ │  상태를 보내는 노드   │ ─────────────────────▶ │ 두산 드라이버 │──▶ M0609
│ (cable_hmi)│ ◀────────────────────────── │  (아래 3종 중 하나)   │ ◀───────────────────── │  (sodreal)   │
└────────────┘  status / result / log      └──────────────────────┘   /onrobot_joint_states └──────────────┘──▶ RG2
```

"상태를 보내는 노드"는 상황에 따라 셋 중 하나를 띄운다. HMI 는 누가 보내는지 모르고, 같은 토픽만 본다.

| 노드 | 위치 | 용도 | 상태 |
|---|---|---|---|
| `mock_inspection_node` | cable_hmi | 로봇 없이 HMI 전체 기능 시험. 값은 전부 가짜 | 완성 |
| `robot_monitor_node` | cable_hmi | **실제 로봇 값을 읽어 HMI 에 표시** (읽기 전용) | 완성, 실제 로봇에서 동작 확인 |
| 실제 검사 노드 | cable_pkg | 검사 시퀀스 수행 (이동·파지·Pull·판정) | **미구현** |

핵심 원칙 3가지
1. **HMI 는 로봇을 직접 부르지 않는다.** `DSR_ROBOT2` 함수는 응답이 올 때까지 멈추는 블로킹 호출이라, HMI 가 부르면 화면과 STOP 버튼이 같이 언다. HMI 는 publish/subscribe 만 한다.
2. **HMI 는 '렌더러'다.** 버튼을 눌러도 화면을 스스로 바꾸지 않는다. 명령만 보내고, 돌아온 status 로만 화면과 버튼 활성화를 갱신한다.
3. **통신 규격은 한 파일에만 있다.** `interface.py`. 팀 메시지가 확정되면 이 파일만 고친다.

---

## 2. 파일 구성 (파이썬 약 2,200줄 + .ui 1,440줄)

### cable_hmi (HMI 패키지. 두산 의존은 `robot_monitor_node` 의 `dsr_msgs2` 메시지 정의뿐 - HMI 화면은 두산 코드를 import 하지 않음)

| 파일 | 줄 | 역할 |
|---|---|---|
| `interface.py` | 267 | 토픽 이름, 메시지 타입, 데이터 구조(dataclass), 인코딩/디코딩. **통합 시 고칠 유일한 파일** |
| `ros_bridge.py` | 97 | ROS 수신 스레드 → Qt signal. 명령·heartbeat publish |
| `main_window.ui` | 1,440 | 화면 배치 + 스타일시트(QSS). **Qt Designer 로 편집** |
| `main_window.py` | 440 | 화면 동작. `.ui` 를 읽고 objectName 으로 위젯을 찾아 값 표시·버튼 연결 |
| `detail_dialog.py` | 115 | 검사 결과 상세 팝업 |
| `style.py` | 26 | 코드에서 동적으로 입히는 색 (PASS/FAIL/MISSING 등) |
| `hmi_main.py` | 34 | 실행 진입점 (`ros2 run cable_hmi hmi`) |
| `mock_inspection_node.py` | 469 | 가상 검사 노드 |
| `launch/hmi.launch.py` | 36 | HMI (+ mock) 실행 |
| `robot_monitor_node.py` | 494 | 실제 로봇 값 → status. 읽기 전용 모니터 |
| `launch/hmi_monitor.launch.py` | 36 | HMI + 모니터 노드 실행 |
| `hmi_progress.py` | 96 | **동작 코드에 붙이는 진행률 보고 부품** (`ProgressReporter`). 다른 동작 코드로 그대로 옮길 수 있음 |

### cable_pkg (로봇 동작 패키지 - HMI 관련 코드는 두지 않는다)

| 파일 | 줄 | 역할 |
|---|---|---|
| `pull_test_logger.py` | 231 | (기존) baseline 측정 스크립트. HMI 와 무관 |

---

## 3. 통신 규격 — `interface.py`

현재는 팀 공용 메시지(`cable_msgs`)가 없어 **`std_msgs/String` 에 JSON** 을 실어 보낸다.

| 토픽 | 방향 | 내용 |
|---|---|---|
| `cable_inspection/status` | 노드 → HMI, 10 Hz | `SystemStatus` : 상태, 연결, Tool, 판정 기준, 현재 위치/단계/힘/변위/그리퍼 폭, 진행률 |
| `cable_inspection/result` | 노드 → HMI | `PointResult` : Point 1개 끝날 때마다 |
| `cable_inspection/log` | 노드 → HMI | `LogEntry` : 시스템 로그 |
| `cable_inspection/command` | HMI → 노드 | `Command{name, args}` |
| `cable_inspection/hmi_heartbeat` | HMI → 노드, 2 Hz | HMI 생존 신호 |
| `cable_inspection/progress` | 동작 코드 → 노드 | `Progress` : 진행률 %, Point, 단계, 실행 중/중단 (동작 코드는 status 를 직접 보내지 않음) |
| `cable_inspection/tool_force`, `tcp_pose` | 노드 → (누구나) | 힘 6축, TCP 자세 원본 (HMI 는 안 씀. echo·기록용) |

- 상태값: `IDLE / RUNNING / PAUSED / MOVING / DONE / ESTOP / ERROR` + 모니터용 `MONITOR / MONITOR_MOVING`
- 결과 코드: `PASS / FAIL_DISPLACEMENT / FAIL_DETACHED / MISSING` (BRD 합의사항 그대로)
- 명령: `START, PAUSE, RESUME, ESTOP, ESTOP_RESET, MOVE_HOME, MOVE_TO_POINT, SET_SPEED, SYNC`
- 디코딩은 **모르는 키는 무시, 빠진 키는 기본값** → 필드가 늘거나 줄어도 HMI 가 죽지 않는다.
- FAIL / MISSING 포인트 이동은 둘 다 `MOVE_TO_POINT{point_id, reason}` 하나로 보낸다. 어느 Point 로 갈지는 HMI 가 고른다(선택된 행 → 없으면 차례로).

---

## 4. HMI 동작 — `ros_bridge.py`, `main_window.py`

**수신 구조**: ROS 콜백은 별도 스레드(executor)에서 돌고, 받은 데이터는 Qt signal 로만 GUI 스레드에 넘긴다. GUI 가 잠깐 멈춰도 수신이 밀리지 않고, 수신이 몰려도 GUI 가 멈추지 않는다.
heartbeat 만은 일부러 GUI 스레드 타이머로 보낸다 — 화면이 얼어 작업자가 STOP 을 못 누르는 상황이면 heartbeat 도 같이 끊겨야 하기 때문.

**`main_window.py` 의 흐름**

```
_load_ui()          .ui 로드, objectName 으로 위젯 찾기, 버튼 signal 연결
on_status()   ──▶  _render()            좌측 패널·판정 기준·진행률·속도 표시
                   _refresh_controls()  상태에 따라 버튼 활성/비활성
on_result()   ──▶  결과 테이블 행 추가/갱신, PASS/MISSING/FAIL 개수
on_log()      ──▶  시스템 로그 탭
_check_link()       status 가 1.5 s 끊기면 'ROS2 통신 끊김' + STOP 외 버튼 잠금
버튼 클릭     ──▶  _send()  명령 publish (화면은 바꾸지 않음)
```

**버튼 활성 조건** (전부 status.state 로 결정)

| 버튼 | 활성 조건 |
|---|---|
| 검사 시작, Home 이동 | IDLE, DONE |
| FAIL / MISSING 포인트 이동 | IDLE, DONE + 해당 결과가 있을 때 |
| 일시정지 | RUNNING, MOVING |
| 이어하기 | PAUSED |
| **STOP** | **항상** (통신이 끊겨도 눌린다) |

**`.ui` 편집에 대한 내성**: Designer 에서 위젯을 지우거나 이름을 바꾸면 그 항목만 화면에서 빠지고 HMI 는 그대로 뜬다(`_widget()` 이 숨겨진 대역 위젯을 돌려줌). 빠진 이름은 시작 시 터미널과 시스템 로그에 경고로 나온다. 예외로 `estopBtn` 은 없으면 실행을 거부한다.
`.ui` 는 파이썬 패키지 폴더 안에 있어, `--symlink-install` 빌드에서는 **저장 후 HMI 만 다시 실행하면 반영**된다(재빌드 불필요).

---

## 5. 실제 로봇 값 읽기 — `robot_monitor_node.py`

`DSR_ROBOT2` 를 쓰지 않고 rclpy **비동기 호출(`call_async`)** 로 두산 드라이버의 조회 서비스를 주기적으로 읽는다. 서비스마다 "응답 대기 중이면 새 요청을 안 보낸다"(`Poller`) 라서 드라이버가 느려지거나 멈춰도 요청이 쌓이지 않고, 노드와 HMI 는 계속 돌면서 '끊김' 을 표시한다.

| HMI 항목 | 출처 | 주기 |
|---|---|---|
| Tool, TCP 이름 | `tool/get_current_tool`, `tcp/get_current_tcp` | 1 s |
| Robot 연결, 비상정지, 현재 단계 | `system/get_robot_state` (+ `/dsr01/robot_disconnection`) | 0.2 s |
| 상태 배지 "이동 중" | `motion/check_motion` | 0.2 s |
| 현재 힘 값 | `aux_control/get_tool_force` (베이스 좌표계) → `√(Fx²+Fy²+Fz²)` | 0.1 s |
| 현재 위치, 현재 변위 | `aux_control/get_current_posx` → 기준 자세와의 거리(mm) | 0.1 s |
| 현재 알람 | `/dsr01/error` 토픽 (30 s 유지), 로봇 상태(SAFE_STOP 등) | 이벤트 |
| RG2 연결, 그리퍼 폭 | `/onrobot_joint_states` 의 관절각(rad) → 드라이버와 같은 RG2 상수로 폭(mm) 역산 | 50 Hz |
| Tool Weight | **로봇에서 못 읽음.** launch 인자 `tool_weight_kg`(1.47) 를 표시만 함 | — |

- **진행률**: 모니터 노드는 검사를 하지 않아 진행률을 스스로 알 수 없다. 동작 코드가 `ProgressReporter` 로 알려 주면 status 의 진행률과 '현재 단계'(`Cycle 2 · 직선 이동 1`)에 넣는다.
  완료(100 %)는 다음 실행 전까지 유지, 중단(`abort`)되면 0 으로 복귀. 예: `~/ros_ws/examples/move_async.py`.
- 오래된 값은 표시하지 않는다: 1.5 s 안에 응답이 없으면 힘·위치·폭을 지운다.
- 변위 기준은 노드 시작 시 자세. `ros2 service call /cable_inspection/zero_displacement std_srvs/srv/Trigger` 로 다시 0 으로 잡는다.

**로봇에 '쓰는' 호출은 네 가지뿐이다** (로봇을 움직이는 것은 4번 Home 이동 하나)

1. **HMI STOP → `motion/move_stop`(Quick stop)**. 실제 로봇 옆에서 STOP 이 아무 일도 안 하면 안 되므로 연결해 둠.
   *한계: 모션만 멈춘다. 힘 제어는 풀리지 않는다. 서보 OFF 까지 가는 확장은 설계만 해 두고 보류함.*
2. **Tool/TCP 자동 설정** (`NameSetter`). 두산 드라이버를 재시작하면 컨트롤러의 Tool/TCP **선택**이 풀려, 툴 무게가 0 으로 계산되고 힘 값에 1.47 kg(≈14 N)이 통째로 실린다. 그래서 이름이 비어 있는 것을 볼 때마다 `ToolWeight` / `GripperDA_v1` 로 다시 설정한다.
   - 비어 있을 때만 (TP 에서 고른 다른 툴은 덮어쓰지 않고 알람)
   - 로봇이 STANDBY 이고 정지해 있을 때만
   - 실패하면 알람을 내고 재시도 중단 (드라이버가 다시 연결되면 재시도)

3. **속도 슬라이더 → `motion/change_operation_speed`(1~100 %)**. TP 속도 슬라이더와 같은 전체 배율이라 코드의 `vel` 과 곱해진다(100 % 라도 코드 속도를 넘지 않음).
   읽는 서비스가 없어 HMI 에는 '마지막으로 설정에 성공한 값' 을 표시한다. 설정 전·드라이버 연결 변경 시 `—`. 노드 시작 시 자동 설정은 하지 않는다.

4. **Home 이동 → `motion/move_joint` 비동기(`sync_type=1`)**. `allow_home_move=true` 일 때만. 드라이버의 `move_home` 은 동기 호출이라 이동 중 다른 서비스를 막고,
   TP 의 사용자 홈 각도를 읽는 서비스도 없어서 홈 관절각을 launch 인자 `home_joints`(기본 `[0, 0, 90, 0, 90, 0]`)로 받는다.
   조건: 드라이버 연결, 로봇 STANDBY, 모션 없음, Tool/TCP 정상. 끝나면 `get_current_posj` 로 실제 도착했는지 확인한다(중간에 멈춘 것을 도착으로 오인하지 않음).
   HMI 는 누르면 확인 창을 띄운다.

그 밖의 HMI 명령(검사 시작, Point 이동 등)은 "읽기 전용 모니터 - 무시" 로그만 남긴다. 상태를 `MONITOR` 로 보내므로 HMI 에서 해당 버튼은 처음부터 잠겨 있다.

---

## 6. 가상 검사 노드 — `mock_inspection_node.py`

실제 검사 노드가 구현해야 할 동작의 **참조 구현**. 10 Hz 타이머로 상태머신을 돌린다.

- 검사 시퀀스(02_Inspection_Sequence_Concept 기준): `InspectionPointApproach → ToolPosAlign → Cable Approach → Contact Search → Cable Grip → Pull Test(3회) → Force Check → Retreat`
- 가짜 센서값: Pull 중 힘은 사인파, 변위는 결과에 따라 0.4 / 1.8 mm, 이탈 시 힘 급감 + 변위 급증, MISSING 은 그리퍼가 끝까지 닫힘
- 진행률 = (끝난 Point 수 + 현재 Point 의 단계 진행 비율) ÷ 전체 Point 수
- Recipe: `RECIPE_A` = PASS / FAIL_DISPLACEMENT / MISSING, `RECIPE_B` = PASS / FAIL_DETACHED / PASS / PASS
- HMI heartbeat 가 2 s 끊기면 자동 일시정지

---

## 7. 실행 방법

```bash
# 공통: 새 터미널마다
source ~/ros_ws/install/setup.bash          # 로봇 쪽(cable_pkg)을 쓸 땐 그 앞에 sod

# (1) 가상 테스트 — 로봇 불필요
ros2 launch cable_hmi hmi.launch.py
ros2 launch cable_hmi hmi.launch.py random_outcomes:=true

# (2) 실제 로봇 값 모니터링 — 다른 터미널에 sodreal(또는 sodvir)이 떠 있어야 함
ros2 launch cable_hmi hmi_monitor.launch.py
```

(1)과 (2)를 동시에 띄우지 말 것 — 둘 다 `status` 를 publish 해서 값이 섞인다.
환경: `ROS_DOMAIN_ID=50`, `rmw_fastrtps_cpp`, Fast DDS 화이트리스트 프로파일 (`.bashrc`).

---

## 8. 검증 상태

| 검증 | 방법 | 결과 |
|---|---|---|
| HMI ↔ mock 전 기능 | 별도 도메인에서 HMI 버튼을 실제로 클릭하는 자동 시험 (시작/일시정지/이어하기/STOP/해제/Home/FAIL/MISSING/속도/통신 끊김) | 32 항목 통과 |
| 모니터 노드 → HMI | 두산 드라이버와 같은 이름·타입의 **가짜 서비스 서버**로 시험 (값 표시, 변위, STOP→move_stop, Tool/TCP 자동 설정 5가지 경우, 그리퍼 폭, 속도 설정, 이동 중 표시, Home 이동, 진행률, 드라이버 멈춤) | 76 항목 통과 |
| 단위·린트 | `pytest` (interface 왕복/전방 호환, flake8, pep257) | 9 통과 |
| 실제 로봇 | 사용자가 직접 실행 | Tool/TCP 자동 복구, 힘 4.4 N, 위치, 그리퍼 폭 20.4 mm, Tool Weight 1.47 kg 표시 확인 |

자동 시험 스크립트는 임시 폴더에 있고 저장소에는 아직 넣지 않았다.

---

## 9. 실제 장비에서 알게 된 사실

- `/dsr01/joint_states` 는 106 Hz 로 나오지만 **힘·TCP 위치는 토픽이 없고 서비스로만** 읽을 수 있다 (`/rt_topic` 은 기본 꺼짐).
- 툴 무게·Force Zero 상태·속도 % 는 **읽는 서비스 자체가 없다** (`dsr_msgs2`, `dsr_common2` 모두 확인). 설정한 쪽이 값을 기억해야 한다.
- 아무것도 안 잡아도 힘이 **약 4 N** 나온다. M0609 는 손목 힘 센서가 없고 관절 토크로 추정하기 때문. 대부분 수평 성분이라 툴 무게 오차만으로는 설명되지 않는다. → **판정은 절대값이 아니라 파지 직후 대비 증가분, 그리고 당김 축 성분으로 해야 한다.**
- RG2 드라이버는 `python3-pymodbus` 가 없으면 시작 즉시 죽는다 (설치로 해결). 폭(mm)을 직접 내보내지 않고 관절각으로만 내보낸다. `Grip detected` 신호는 토픽으로 나오지 않는다.
- `pull_test_logger.py` 는 `set_tool('Tool Weight_1')` 을 호출하는데 실제 이름은 `ToolWeight` 다 (반환값을 확인하지 않아 실패해도 모르고 지나감). **아직 수정 안 함.**

---

## 10. 남은 일

| 항목 | 상태 |
|---|---|
| **실제 검사 노드** (HMI 버튼으로 로봇이 실제로 검사 수행) | 미구현. 티칭 좌표(Home, 각 Place), Pull 조건 필요 |
| Force Zero (영점) 기능 — 힘을 증가분으로 표시 | 제안만 함 |
| 속도 슬라이더 → `change_operation_speed` | **구현 완료** (가짜 드라이버 시험 통과, 실제 로봇 확인 전) |
| STOP 확장 (정지 + 힘 제어 해제 + 서보 OFF, 해제는 TP 에서만) | 방향 결정됨, 구현 보류. 필요한 서비스는 드라이버에 모두 있음 |
| 그리퍼 폭: HMI 값과 OnRobot 웹 클라이언트 값이 약 4 mm 차이 | 미해결 (핑거팁 오프셋 기준 차이로 추정) |
| 팀 공용 메시지(`cable_msgs`)로 전환 | 팀 합의 후 `interface.py` 만 수정 |
| git 커밋 | 아직 안 함 |
