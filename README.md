# ros_ws — M0609 케이블 체결 검사

Doosan M0609 + OnRobot RG2 로 케이블·커넥터 체결 상태를 접촉식 Pull Test 로 검사하는 PoC 워크스페이스 (ROS 2 Jazzy).

## 구성

| 경로 | 내용 |
|---|---|
| [`src/cable_hmi/`](src/cable_hmi/) | **PyQt5 HMI.** 화면, ROS 통신, 실제 로봇 값 모니터 노드, 가상 검사 노드(mock), 진행률 보고 부품. 자세한 설명은 [패키지 README](src/cable_hmi/README.md) |
| [`src/cable_pkg/`](src/cable_pkg/) | **로봇 동작 패키지.** Recipe 기반 검사 시퀀스, 설정, 안전 판단 및 검증 모듈 |
| [`docs/`](docs/) | 문서 (md) |
| [`measurement_results/`](measurement_results/) | 위치 오차 및 Grip/Pull 실험 원본 CSV·JSON |
| [`tools/ccc_inspection/`](tools/ccc_inspection/) | 초기 검증·수동 확인용 보조 스크립트 |

## 로봇 패키지 구조 원칙

`src/cable_pkg/cable_pkg/`는 다음 구조를 기준으로 관리한다.

```text
cable_pkg/
├─ sequence/       # 문서 #00~#07과 같은 번호의 폴더로 관리
│  ├─ seq_00_main_work/ ~ seq_07_work_finish/  # 단계별 클래스·노드
│  └─ inspection/  # InspectionSequence: #03→#04→#05 연결, 검사 단독 실행
├─ data_models/    # Job, Point, 단계 결과용 dataclass와 Enum
├─ interfaces/     # 시퀀스와 Robot·Gripper·HMI·Recipe 구현 사이의 Protocol
├─ hardware/       # DSR M0609·OnRobot RG2 실제 장비 어댑터와 측정
├─ config/         # 실물 Tool/TCP 설정 및 향후 System Recipe
├─ recipe/         # Inspection Recipe 모델과 검사포인트 레시피
├─ safety/         # 작업영역과 안전 복귀 판단
├─ diagnostics/    # 실물 환경과 설정을 확인하는 진단 기능
```

구조 관리 원칙:

- 프로젝트에서 동작하는 시퀀스 코드는 모두 `sequence/`에 둔다.
- 시퀀스 폴더명은 문서 번호에 맞춰 `seq_NN_이름/` 형식을 사용한다.
- 폴더 안에서 동작 클래스는 `sequence.py`, ROS 노드는 `node.py`, 실행부는 `run.py`로 구분한다.
- 전체 흐름은 `SequenceController.run()`, 포인트별 검사 흐름은 `InspectionSequence.run_point()`에서 확인한다.
- dataclass와 Enum 같은 데이터 구조는 `data_models/`에서 관리한다.
- 외부 장비와 시스템의 기능 경계는 `interfaces/`에서 관리한다.
- 실제 ROS 서비스 호출과 센서 측정은 `hardware/`에서 관리한다.
- 테스트를 위해 만든 실행 코드와 프로토타입은 `test_module/`에서 관리한다.
- `config/`는 실물 로봇에 등록된 Tool/TCP와 System Recipe를 관리한다.
- `recipe/`는 검사포인트 순서와 Point별 Grip/Pull 조건을 관리한다.
- 검증 코드는 운영 시퀀스의 설계 근거이므로 기능 이전과 검증 전에는 삭제하지 않는다.

프로젝트 설계 및 검증 체크리스트는
[`docs/ccc_inspection/`](docs/ccc_inspection/)에서 관리한다.

## 문서 (`docs/`)

| 문서 | 내용 |
|---|---|
| [HMI 구현 요약](../docs/concepts/hmi/HMI_구현_요약.md) | HMI 가 어떻게 구현돼 있는지: 구조, 파일별 역할, 통신 규격, 실제 로봇 값 출처, 검증 상태, 실제 장비에서 알게 된 사실, 남은 일 |
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
| 실제 검사 노드 | 실제 | `cable_pkg/sequence`의 Recipe 기반 검사 시퀀스 수행 |

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

# 3) 실제 검사 시퀀스 - Inspection Recipe의 활성 Point를 순서대로 실행
# 별도 터미널에서 판정 노드를 먼저 실행
ros2 run cable_pkg inspection_judgment
# 다른 터미널에서 검사 모션 실행
ros2 run cable_pkg inspection_sequence
```

1)과 2)를 동시에 띄우지 말 것 — 둘 다 `status` 를 publish 해서 값이 섞인다.

## 주의

HMI 의 STOP 은 소프트웨어 정지 요청(`move_stop`)일 뿐이다. 물리 비상정지 스위치와 TP 가 최종 권한이다.

## 작업 기록

- 09/17 11:30 `cable_pkg` 생성, rclpy · dsr_common2 의존성 추가
- 09/18 `cable_hmi` 패키지 생성
- 09/19 ~ 09/20 `cable_hmi` 구현: PyQt HMI(.ui), mock 검사 노드, 실제 로봇 모니터 노드, Tool/TCP 자동 설정, 속도 설정, Home 이동, 진행률 보고, 에러 팝업 / `docs/` 정리
