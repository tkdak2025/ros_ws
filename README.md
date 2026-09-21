# ros_ws — M0609 케이블 체결 검사

Doosan M0609 + OnRobot RG2 로 케이블·커넥터 체결 상태를 접촉식 Pull Test 로 검사하는 PoC 워크스페이스 (ROS 2 Jazzy).

## 구성

| 경로 | 내용 |
|---|---|
| [`src/cable_hmi/`](src/cable_hmi/) | **PyQt5 HMI.** 화면, ROS 통신, 실제 로봇 값 모니터 노드, 가상 검사 노드(mock), 진행률 보고 부품. 자세한 설명은 [패키지 README](src/cable_hmi/README.md) |
| [`src/cable_pkg/`](src/cable_pkg/) | **로봇 동작 패키지.** 현재 baseline 측정 스크립트 `pull_test_logger.py` |
| [`examples/`](examples/) | **동작 코드 예제 3개.** HMI 와 붙여 보는 시험용 코드 (아래 표) |
| [`recipe_prototype/`](recipe_prototype/) | 검사 레시피 JSON 과 생성 코드. launch 의 기본 `recipe_dir` |
| [`scripts/`](scripts/) | 레시피 DB 초기화 SQL 등 거드는 스크립트 |
| [`docs/`](docs/) | 문서 (md) |

## 문서 (`docs/`)

| 문서 | 내용 |
|---|---|
| [HMI 연동 가이드](docs/HMI_연동_가이드.md) | **동작 코드 담당자용.** 진행률·버튼·일시정지·통신 단절·결과 보고를 어떻게 붙이는지 |
| [HMI 구현 요약](docs/HMI_구현_요약.md) | HMI 가 어떻게 구현돼 있는지: 구조, 파일별 역할, 통신 규격, 실제 로봇 값 출처, 검증 상태, 실제 장비에서 알게 된 사실, 남은 일 |
| [BRD v0.1](<docs/M0609_전장판_케이블_커넥터_체결검사_BRD_v0.1 (1).md>) | 프로젝트 요구사항 (목표, 시나리오, Recipe, 결과 Sheet, KPI, Phase 구분) |
| [BRD 합의사항 요약](<docs/M0609_Cable_Inspection_BRD_Summary (1).md>) | 범위·검사항목·결과 코드(PASS / FAIL_DISPLACEMENT / FAIL_DETACHED / MISSING) 합의 내용 |
| [검사 시퀀스 컨셉](<docs/02_Inspection_Sequence_Concept (1).md>) | Inspection Point 마다 반복하는 표준 검사 절차 |

## HMI 구현 요약

```
[PyQt HMI] ──command──▶ [상태를 보내는 노드] ──두산 서비스(비동기)──▶ [두산 드라이버] ──▶ M0609 / RG2
           ◀─status/result/log──
```

- HMI 는 **publish/subscribe 만** 한다. 블로킹 호출이 있는 `DSR_ROBOT2` 를 import 하지 않으므로 로봇 쪽이 멈춰도 화면과 STOP 버튼은 얼지 않는다.
- HMI 는 받은 `status` 의 렌더러다. 버튼을 눌러도 화면을 스스로 바꾸지 않고, 돌아온 상태로만 표시와 버튼 활성화를 갱신한다.
- 통신 규격은 `src/cable_hmi/cable_hmi/interface.py` **한 파일**에 있다 (현재 `std_msgs/String` + JSON). 팀 공용 메시지가 확정되면 이 파일만 고친다.
- 화면 배치·스타일은 `main_window.ui` (Qt Designer 로 편집), 동작은 `main_window.py`.

"상태를 보내는 노드" 는 상황에 따라 하나를 띄운다.

| 노드 | 값 | 용도 |
|---|---|---|
| `mock_inspection_node` | 전부 가짜 | 로봇 없이 HMI 기능 시험 |
| `robot_monitor_node` | 실제 로봇 값 | 힘·위치·변위·그리퍼 폭·Tool/TCP·알람 표시, Tool/TCP 자동 설정, 속도 설정, Home 이동, STOP |
| 실제 검사 노드 | 실제 | 검사 시퀀스 수행 — **미구현** |

## 빌드

```bash
source /opt/ros/jazzy/setup.bash
source ~/ws_cobot_pjt/ws_dsr/install/setup.bash      # 두산 워크스페이스 (별칭 sod)
cd ~/ros_ws && colcon build --symlink-install
source install/setup.bash
```

`--symlink-install` 로 빌드하면 파이썬 코드와 `.ui` 를 고친 뒤 프로그램만 다시 실행하면 반영된다.

## 실행

```bash
# 1) 가상 테스트 - 로봇 불필요. 화면의 값은 전부 가짜
ros2 launch cable_hmi hmi.launch.py

# 2) 실제 로봇 값 모니터링 - 다른 터미널에 두산 드라이버(sodreal 또는 sodvir)가 떠 있어야 한다
ros2 launch cable_hmi hmi_monitor.launch.py
```

1)과 2)를 동시에 띄우지 말 것 — 둘 다 `status` 를 publish 해서 값이 섞인다.

## 동작 코드 예제 (`examples/`)

세 개 모두 **HMI 와 붙여 보는 시험용**이고, 실제 검사 동작(측정·판정·그리퍼)은 아직 자리만 있다.
ROS 패키지가 아니라서 `ros2 run` 이 아니라 `python3` 로 실행한다. 실행 전에 `sod` 와
`source ~/ros_ws/install/setup.bash` 둘 다 필요하다 (`cable_hmi` 를 import 하기 때문).

| 파일 | 무엇을 보여 주는가 |
|---|---|
| [`move_async.py`](examples/move_async.py) | HMI 버튼 연동의 최소 형태. 비동기 모션 + 진행률 보고, 누른 자리에서 바로 멈추는 일시정지 |
| [`inspect_async.py`](examples/inspect_async.py) | 위 + 레시피 읽기(JSON·DB), Point 순회, 결과 보고, FAIL/MISSING 포인트 이동 |
| [`sequence_demo.py`](examples/sequence_demo.py) | 설계 문서(CCCIS Sequence v0.2) 흐름. Safe Pause Point 방식 일시정지, HMI 통신 단절 감시, Home Return 처리 |

### `move_async.py` — 왜 비동기인가

교육용 `rokey/move.py`(simple_move)와 같은 자세·순서로 움직이되, 모션을 비동기로 건다.

```bash
sod && source ~/ros_ws/install/setup.bash && python3 ~/ros_ws/examples/move_async.py
```

- 동기 모션(`movej`, `movel`)은 이동이 끝날 때까지 두산 드라이버가 다른 서비스에 답하지 못해, 이동 중 HMI 의 힘·위치·변위가 멈추고 "Robot 연결 끊김" 으로 보인다 (실제 장비에서 확인).
- 이 예제는 `amovej` / `amovel` 로 걸고 `check_motion` 을 반복 확인하며 기다린다. 코드는 동기처럼 한 줄씩 진행되지만 드라이버는 막히지 않아 **이동 중에도 HMI 값이 갱신된다.** (`mwait()` 는 드라이버 안에서 붙잡는 호출이라 쓰지 않는다.)
- `ProgressReporter` 로 HMI 진행률을 보고한다. 다른 동작 코드로 옮길 때는 `progress.` 로 시작하는 줄만 가져가면 된다.
- 먼저 `sodvir`(에뮬레이터)에서 확인한 뒤, 실제 로봇에서는 HMI 속도를 낮추고 TP 비상정지에 손을 올려 두고 실행할 것.

## 주의

HMI 의 STOP 은 소프트웨어 정지 요청(`move_stop`)일 뿐이다. 물리 비상정지 스위치와 TP 가 최종 권한이다.

## 작업 기록

- 09/17 11:30 `cable_pkg` 생성, rclpy · dsr_common2 의존성 추가
- 09/18 `cable_hmi` 패키지 생성
- 09/19 ~ 09/20 `cable_hmi` 구현: PyQt HMI(.ui), mock 검사 노드, 실제 로봇 모니터 노드, Tool/TCP 자동 설정, 속도 설정, Home 이동, 진행률 보고, 에러 팝업 / `docs/` 정리, `move_async.py` 추가
