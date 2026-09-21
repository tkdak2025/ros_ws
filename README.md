# ros_ws — M0609 케이블 체결 검사

Doosan M0609 + OnRobot RG2 로 케이블·커넥터 체결 상태를 접촉식 Pull Test 로 검사하는 PoC 워크스페이스 (ROS 2 Jazzy).

## 빠른 실행

```bash
# 빌드 (한 번)
source /opt/ros/jazzy/setup.bash
source ~/ws_cobot_pjt/ws_dsr/install/setup.bash      # 두산 워크스페이스 (별칭 sod)
cd ~/ros_ws && colcon build --symlink-install
source install/setup.bash
```

| 하고 싶은 것 | 명령 |
|---|---|
| 로봇 없이 HMI 시험 (값은 전부 가짜) | `ros2 launch cable_hmi hmi.launch.py` |
| 실제 로봇 값 모니터링 | `ros2 launch cable_hmi hmi_monitor.launch.py` |
| 가상 로봇 띄우기 / 실물 연결 | `sod && sodvir` / `sod && sodreal` |
| 동작 코드 예제 실행 | `python3 ~/ros_ws/examples/sequence_demo.py` |
| 레시피 DB 만들기 | `sqlite3 ~/ros_ws/results/inspection.db < ~/ros_ws/scripts/init_recipe_db.sql` |
| 테스트 | `cd ~/ros_ws/src/cable_hmi && python3 -m pytest test` |

- `sod` / `sodvir` / `sodreal` 은 두산 워크스페이스용 shell 별칭이다. 없으면 이렇게 쓴다.
  ```bash
  alias sod='source ~/ws_cobot_pjt/ws_dsr/install/setup.bash'
  alias sodvir='ros2 launch m0609_rg2_bringup bringup.launch.py mode:=virtual host:=127.0.0.1 port:=12345 model:=m0609'
  alias sodreal='ros2 launch m0609_rg2_bringup bringup.launch.py mode:=real host:=<로봇 IP> port:=12345 model:=m0609'
  ```
- `hmi.launch.py` 와 `hmi_monitor.launch.py` 를 **동시에 띄우지 말 것** — 둘 다 `status` 를 publish 해서 값이 섞인다.
- `--symlink-install` 로 빌드하면 파이썬 코드와 `.ui` 를 고친 뒤 프로그램만 다시 실행하면 반영된다.
- 동작 코드 예제는 ROS 패키지가 아니라서 `ros2 run` 이 아니라 `python3` 로 실행한다. 실행 전에 `sod` 와
  `source ~/ros_ws/install/setup.bash` 둘 다 필요하다 (`cable_hmi` 를 import 하기 때문).

## 파일별 요약

### 최상위

| 경로 | 내용 |
|---|---|
| [`src/cable_hmi/`](src/cable_hmi/) | **PyQt5 HMI 패키지.** 화면, ROS 통신, 실제 로봇 모니터 노드, 가상 검사 노드, 결과 저장. [패키지 README](src/cable_hmi/README.md) 에 자세히 |
| [`src/cable_pkg/`](src/cable_pkg/) | **로봇 동작 패키지.** 현재는 baseline 측정 노드 `pull_test_logger.py` 하나 |
| [`examples/`](examples/) | 동작 코드 예제. HMI 와 붙여 보는 시험용 |
| [`recipe_prototype/`](recipe_prototype/) | 검사 레시피 JSON 과 생성 코드. launch 의 기본 `recipe_dir` |
| [`scripts/`](scripts/) | 레시피 DB 초기화 SQL |
| [`docs/`](docs/) | 문서 |
| `results/` | 검사 결과·레시피 DB. `.gitignore` (공개 저장소라 올리지 않는다) |

### `src/cable_hmi/cable_hmi/` — 주요 파일

전체 목록과 설명은 [패키지 README](src/cable_hmi/README.md#구조) 에 있다.

| 파일 | 역할 |
|---|---|
| `interface.py` | **통합 시 고칠 유일한 파일.** 토픽·메시지·dataclass 정의 (현재 `std_msgs/String` + JSON) |
| `main_window.ui` / `main_window.py` | 화면 배치·스타일(Qt Designer) / 화면 동작 |
| `robot_monitor_node.py` | 실제 로봇 값 → `status`. Tool/TCP 자동 설정, 속도, Home 이동, STOP. `dsr_msgs2` 가 필요한 유일한 파일 |
| `mock_inspection_node.py` | 가상 검사 노드. 실제 검사 노드가 구현할 동작의 참조 구현 |
| `hmi_progress.py` | 동작 코드에 붙이는 부품 `ProgressReporter` — 진행률 보고 + HMI 버튼 수신 |
| `result_db.py` / `result_recorder_node.py` | 결과를 SQLite 에 저장 · 조회, 결과 파일 내보내기 |
| `recipe_catalog.py` / `recipe_db.py` | 레시피 JSON 폴더 읽기 / 레시피 DB(뷰 `v_recipe_point`) 읽기 |
| `lookup_tab.py` / `detail_dialog.py` | '통합 조회' 탭 / 상세 팝업 2종 |

### `examples/`

둘 다 **HMI 와 붙여 보는 시험용**이고, 실제 검사 동작(측정·판정·그리퍼)은 아직 자리만 있다.
모든 Point 를 `MISSING`(사유 '측정 미구현')으로 보고한다.

| 파일 | 무엇을 보여 주는가 |
|---|---|
| [`inspect_async.py`](examples/inspect_async.py) | 레시피 읽기(JSON·DB) → Point 순회 → 결과 보고. HMI 의 검사 시작 / 일시정지(그 자리에서 정지) / 이어하기 / STOP / 포인트 이동 |
| [`sequence_demo.py`](examples/sequence_demo.py) | 설계 문서(CCCIS Sequence v0.2) 흐름. Safe Pause Point 방식 일시정지, HMI 통신 단절 감시, Home Return 처리 |

**모션은 비동기로 건다.** 동기 모션(`movej`, `movel`)은 이동이 끝날 때까지 두산 드라이버가 다른 서비스에
답하지 못해, 이동 중 HMI 의 힘·위치·변위가 멈추고 "Robot 연결 끊김" 으로 보인다(실제 장비에서 확인).
그래서 `amovej` / `amovel` 로 걸고 `check_motion` 을 반복 확인하며 기다린다 — 코드는 동기처럼 한 줄씩
진행되지만 드라이버는 막히지 않는다. (`mwait()` 는 드라이버 안에서 붙잡는 호출이라 쓰지 않는다.)

실제 로봇에서 돌리기 전에 `sodvir`(에뮬레이터)에서 먼저 확인하고, 실물에서는 HMI 속도를 낮추고
TP 비상정지에 손을 올려 두고 실행할 것.

### `docs/`

| 문서 | 내용 |
|---|---|
| [HMI 연동 가이드](docs/HMI_연동_가이드.md) | **동작 코드 담당자용.** 진행률·버튼·일시정지·통신 단절·결과 보고를 어떻게 붙이는지 |
| [HMI 구현 요약](docs/HMI_구현_요약.md) | HMI 구조, 통신 규격, 실제 로봇 값 출처, 검증 상태, 남은 일 |
| [BRD v0.1](<docs/M0609_전장판_케이블_커넥터_체결검사_BRD_v0.1 (1).md>) | 프로젝트 요구사항 (목표, 시나리오, Recipe, 결과 Sheet, KPI, Phase) |
| [BRD 합의사항 요약](<docs/M0609_Cable_Inspection_BRD_Summary (1).md>) | 범위·검사항목·결과 코드(PASS / FAIL_DISPLACEMENT / FAIL_DETACHED / MISSING) |
| [검사 시퀀스 컨셉](<docs/02_Inspection_Sequence_Concept (1).md>) | Inspection Point 마다 반복하는 표준 검사 절차 |

## 구조

```
[PyQt HMI] ──command──▶ [상태를 보내는 노드] ──두산 서비스(비동기)──▶ [두산 드라이버] ──▶ M0609 / RG2
           ◀─status/result/log──
```

- HMI 는 **publish/subscribe 만** 한다. 블로킹 호출이 있는 `DSR_ROBOT2` 를 import 하지 않으므로 로봇 쪽이 멈춰도 화면과 STOP 버튼은 얼지 않는다.
- HMI 는 받은 `status` 의 렌더러다. 버튼을 눌러도 화면을 스스로 바꾸지 않고, 돌아온 상태로만 표시와 버튼 활성화를 갱신한다.
- 통신 규격은 `interface.py` **한 파일**에 있다. 팀 공용 메시지가 확정되면 이 파일만 고친다.

"상태를 보내는 노드" 는 상황에 따라 하나를 띄운다.

| 노드 | 값 | 용도 |
|---|---|---|
| `mock_inspection_node` | 전부 가짜 | 로봇 없이 HMI 기능 시험 |
| `robot_monitor_node` | 실제 로봇 값 | 힘·위치·변위·그리퍼 폭·Tool/TCP·알람 표시, Tool/TCP 자동 설정, 속도 설정, Home 이동, STOP |
| 실제 검사 노드 | 실제 | 검사 시퀀스 수행 — **미구현** |

## 주의

HMI 의 STOP 은 소프트웨어 정지 요청(`move_stop`)일 뿐이다. 물리 비상정지 스위치와 TP 가 최종 권한이다.

## 작업 기록

- **09/17** `cable_pkg` 생성, rclpy · dsr_common2 의존성 추가
- **09/18** `cable_hmi` 패키지 생성
- **09/19 ~ 09/20** `cable_hmi` 구현: PyQt HMI(`.ui`), mock 검사 노드, 실제 로봇 모니터 노드,
  Tool/TCP 자동 설정, 속도 설정, Home 이동, 진행률 보고, 에러 팝업 / `docs/` 정리
- **09/20** 레시피·결과 DB(SQLite), '통합 조회' 탭, 동작 코드 연동(검사 시작 / 일시정지 / 결과 보고 / 포인트 이동)
- **09/21** 설계 문서(CCCIS Sequence v0.2) 흐름 반영: `PAUSE_REQUEST` 상태, HMI 통신 단절 감시(`COMM_LOST` / `COMM_ERROR`),
  Home Return 위임, 작업 단위 기록 `inspection_run`
- **09/21** 검사 조건 이름·의미 정리: `pull_force_n` → `pull_force_limit_n`(Pull 정지 상한, **합격선이 아니다**).
  화면 문구도 `판정 기준 / Pull Force ≥ N` → `검사 조건 / Pull 정지 상한 N` 으로. 합격 기준 힘은 아직 미정
- **09/21** HMI '결과 파일 저장' 버튼: 이번 검사 결과만 `results/runs/` 에 `.db` + `.csv` 로 내보낸다 (공용 DB 는 건드리지 않음)
- **09/21** 파일 정리: 동작 코드 예제를 `examples/` 로, `scripts/init_recipe_db.sql` 추가,
  저장소에 빠져 있던 `sequence_demo.py` · 연동 가이드 · UI mockup · `recipe_prototype/` 포함

### 아직 정해지지 않은 것

- **합격 기준 힘** — 값·비교 방향·판정 시점 미정. 지금 레시피 DB 의 힘 값은 Pull 정지 상한뿐이다
- **레시피의 진입 정보** — `entry_pose`, `entry_direction`, `entry_depth_mm` 이 아직 없어 실제 진입·Pull 시퀀스를 돌릴 수 없다
- **레시피 스키마 정본** — `recipe_prototype/` 이 별도 사본과 갈라져 있다
