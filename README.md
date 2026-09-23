# ros_ws — M0609 케이블 체결 검사

Doosan M0609 + OnRobot RG2로 케이블·커넥터 체결 상태를 검사하는 ROS 2 Jazzy 워크스페이스입니다.

## 패키지 구성

| 패키지 | 담당 |
|---|---|
| [cable_inspection](src/cable_inspection/README.md) | 실제 로봇 제어, 검사 실행·판정, 로봇/작업 상태 및 결과 발행 |
| [cable_interfaces](src/cable_interfaces/) | 두 PC가 공유하는 ROS 메시지·서비스 정의 |
| [cable_hmi](src/cable_hmi/README.md) | HMI 담당: 화면·검사 레시피 원본 관리·검사 이력 관리 |

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

프로젝트의 ros_ws 디렉터리에서 실행합니다.

```bash
source /opt/ros/jazzy/setup.bash
source ~/ws_cobot_pjt/ws_dsr/install/local_setup.bash
colcon build --symlink-install --packages-select cable_interfaces cable_inspection
source install/local_setup.bash

ros2 launch cable_inspection inspection.launch.py control_mode:=hmi robot_mode:=real
```

로봇/RG2 드라이버는 기존 sodreal 또는 별도 드라이버 launch로 먼저 실행합니다.
검사 launch는 Main·판정·로봇상태 3개 프로세스를 실행하고 HMI의 레시피/START를 기다립니다.
HMI는 별도 PC/프로세스에서 실행하며 검사 실행에 cable_hmi 패키지는 필요하지 않습니다.
토픽·서비스 주소는 기존 `/cable_inspection/...`을 유지합니다.

터미널 운전은 `control_mode:=terminal`로 실행한 뒤 별도 터미널에서 같은 환경을 source하고
`ros2 run cable_inspection sequence_console`을 실행합니다.

## 문서와 검증 자료

- [현재 검사 실행·통신 규격](src/cable_inspection/README.md)
- [설계·검증 문서](docs/ccc_inspection/)
- [초기 수동 검증 도구](tools/ccc_inspection/)

작업일지·과거 설계문서의 이전 패키지명은 당시 기록입니다. 현재 실행 경로는 위 안내를 따릅니다.
