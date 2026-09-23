# ros_ws — M0609 케이블 체결 검사

Doosan M0609 + OnRobot RG2로 케이블·커넥터 체결 상태를 검사하는 ROS 2 Jazzy 워크스페이스입니다.

## 패키지 구성

| 패키지 | 담당 |
|---|---|
| [`src/cable_hmi/`](src/cable_hmi/) | **PyQt5 HMI.** 화면, ROS 통신, 실제 로봇 값 모니터 노드, 가상 검사 노드(mock), 진행률 보고 부품. 자세한 설명은 [패키지 README](src/cable_hmi/README.md) |
| [`src/cable_pkg/`](src/cable_pkg/) | **로봇 동작 패키지.** Recipe 기반 검사 시퀀스, 설정, 안전 판단 및 검증 모듈 |
| [`src/cable_interfaces/`](src/cable_interfaces/) | **팀 공용 ROS 메시지.** `msg/InspectionResult.msg` — 판정 노드가 HMI로 보내는 Point 검사 결과 |
| [`docs/`](docs/) | 문서 (md) |
| [`measurement_results/`](measurement_results/) | 위치 오차 및 Grip/Pull 실험 원본 CSV·JSON |
| [`tools/ccc_inspection/`](tools/ccc_inspection/) | 초기 검증·수동 확인용 보조 스크립트 |

이전 cable_pkg와 cable_management는 cable_inspection으로 대체했습니다.
HMI와 검사 구현은 분리하며 cable_interfaces와 ROS 통신으로 연결합니다.
HMI 화면과 레시피/결과 DB 서비스는 검사 패키지에 포함하지 않습니다.

## 검사 소스 구성

```text
src/cable_inspection/cable_inspection/
├── sequence/       # Main·판정·터미널 운전
├── hardware/       # 실제 로봇·그리퍼 제어
├── diagnostics/    # 상시·수동 로봇상태 조회
├── recipe/         # 레시피 모델·검증·변환과 교시 JSON
├── data_models/    # 공통 상태·결과 모델
└── safety/         # 작업영역 검사
```

노드 내부 구현은 파일 단위로 묶고 기능별 폴더로 관리합니다.
세부 실행 항목·인자는 [검사 패키지 README](src/cable_inspection/README.md)를 따릅니다.

## 빌드·실행

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
- 통신 규격은 `src/cable_hmi/cable_hmi/interface.py` **한 파일**에 있다.
  - 검사 결과: `cable_interfaces/msg/InspectionResult` (`cable_inspection/judgment_result`)
  - 나머지(status · progress · log · command): `std_msgs/String` + JSON
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
source ~/ws_cobot_pjt/ws_dsr/install/local_setup.bash
colcon build --symlink-install --packages-select cable_interfaces cable_inspection
source install/local_setup.bash

# 3) 실제 검사 - 판정 노드를 먼저 띄운 뒤 시퀀스를 실행한다 (터미널 2개)
ros2 run cable_pkg inspection_judgment     # 판정 전담. 로봇을 쓰지 않는다
ros2 run cable_pkg inspection_sequence     # Recipe의 활성 Point를 순서대로 실행
```

`inspection_sequence`는 판정 노드가 떠 있지 않으면 5초 뒤 오류로 멈춘다(로봇을 움직이기 전에 걸린다).

1)과 2)를 동시에 띄우지 말 것 — 둘 다 `status` 를 publish 해서 값이 섞인다.

터미널 운전은 `control_mode:=terminal`로 실행한 뒤 별도 터미널에서 같은 환경을 source하고
`ros2 run cable_inspection sequence_console`을 실행합니다.

## 문서와 검증 자료

## 진행 현황 (2026-09-23 기준)

| 구간 | 상태 |
|---|---|
| #03 Point Transition · #04 Adaptive Grip · #05 Pull Inspection | **동작함** — 실물에서 힘·변위·그리퍼 폭까지 측정 |
| #06 Judgment | **동작함** — `inspection_judgment` 노드가 PASS / FAIL / SYSTEM_ERROR 생성 |
| 판정 결과 → HMI | **연결됨** — `cable_interfaces/msg/InspectionResult` |
| 로봇 상태 → HMI | **연결됨** — `robot_monitor_node`가 드라이버에서 직접 읽음 |
| 진행 상황 → HMI | **없음** — 동작코드가 `cable_inspection/progress`를 보내지 않는다 |
| #00 Main · #01 Initialize · #02 Home Return · Common #01 | 코드는 있으나 `SequenceBackend` 구현체가 없어 미동작 |
| #07 Work Finish | 미구현 |

검사를 돌리면 **결과 표와 로봇 상태는 채워지지만** 진행률·현재 단계·검사 조건 칸은 비어 있다.
동작코드가 `ProgressReporter`로 진행 상황을 보내면 채워진다.

확정된 판정 기준

| 항목 | 값 |
|---|---|
| 기준 Pull 힘 | 15 N (도달 시 Pull 정지) |
| 허용 변위 | 5 mm 이하 → PASS, 초과 → FAIL |
| Pull 최대 거리 | 25 mm (도달 시 FAIL) |
| 파지 실패 | Pull 중 실측 폭 16 mm 미만 → FAIL (`FAIL_GRIP_WIDTH`) |
| 결과 코드 | PASS / FAIL / SYSTEM_ERROR (MISSING은 09/22 폐지) |

남은 일과 담당자 요청 사항은
[`docs/ccc_inspection/tracking/`](docs/ccc_inspection/tracking/)에 정리한다.

## 작업 기록

- 09/17 11:30 `cable_pkg` 생성, rclpy · dsr_common2 의존성 추가
- 09/18 `cable_hmi` 패키지 생성
- 09/19 ~ 09/20 `cable_hmi` 구현: PyQt HMI(.ui), mock 검사 노드, 실제 로봇 모니터 노드, Tool/TCP 자동 설정, 속도 설정, Home 이동, 진행률 보고, 에러 팝업 / `docs/` 정리
- 09/21 실물 Grip/Pull 시험. 정상·파지불량 샘플 측정. 기준 Pull 힘 **15 N** 확정
- 09/22 통합 시퀀스 문서(#00~#07, Common #01) 반영. `cable_pkg`에 검사 시퀀스·판정 규칙 작성.
  **MISSING 결과 폐지** — Grip Slip은 FAIL로 처리 (PR #7)
- 09/23 결과 전달을 **팀 공용 메시지로 확정** (PR #8): `cable_interfaces` 신설,
  판정을 별도 노드(`inspection_judgment`)로 분리, 파지 실패 기준 **Pull 최소 폭 16 mm** 확정.
  HMI를 그 형식에 맞춤
