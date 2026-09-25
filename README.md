# ros_ws — M0609 케이블 체결 검사

Doosan M0609와 OnRobot RG2를 사용하는 ROS 2 Jazzy 워크스페이스입니다. 검사 측은 `cable_inspection`, HMI 측은 `cable_hmi`, 두 측의 메시지·서비스 타입은 `cable_interfaces`가 담당합니다. HMI 화면과 원본 레시피·결과 DB는 검사 패키지에 포함되지 않습니다.

## 실행

로봇/RG2 드라이버를 별도로 기동하고 검사 PC에서 실행합니다.

```bash
source /opt/ros/jazzy/setup.bash
source ~/ws_cobot_pjt/ws_dsr/install/local_setup.bash
colcon build --symlink-install --packages-select cable_interfaces cable_inspection
source install/local_setup.bash
ros2 launch cable_inspection inspection.launch.py control_mode:=hmi robot_mode:=real
```

HMI 운전은 `/cable_inspection/start` 서비스로 전체 검사 레시피를 전달하고 HMI heartbeat를 발행합니다. 실물 연결 없이 가상 드라이버로 모션을 확인할 때는 `robot_mode:=virtual`을 사용합니다. 터미널 운전은 `control_mode:=terminal`로 launch한 뒤 다른 터미널에서 `ros2 run cable_inspection sequence_console`을 실행합니다. 상세한 드라이버 조건과 실행 항목은 [검사 패키지 안내](src/cable_inspection/README.md)를 따릅니다.

## 문서

현재 문서 기준은 [CCCIS v4](docs/v4/00_문서안내_v4.md)입니다.

| 영역 | 내용 |
|---|---|
| [01_commons](docs/v4/01_commons) | BRD·변경 추적·열린 확인 항목 |
| [02_HMI](docs/v4/02_HMI) | 검사측 HMI 통신 계약·레시피 메시지·상태/결과 |
| [03_inspection](docs/v4/03_inspection) | 컨셉·시퀀스 상세 설계·체크리스트·실행/정량검증 |
| [작업내역](docs/작업내역/00_작업내역_목록.md) | 번호 문서 원문과 변경 경위 |

[18 최종결론](docs/작업내역/18_최종결론_2026-09-25.md)에서 마지막 합의를 확인할 수 있습니다. v1~v3와 기존 PDF/DOCX/ZIP는 이전 버전 이력입니다. HMI 화면 구현은 [HMI 패키지 안내](src/cable_hmi/README.md)를 참고합니다.

## 현재 구현과 검증 범위

`inspection.launch.py`는 main_sequence 프로세스 안에서 Main·HMI·Recipe·Judgment·Robot·GripperTool 노드를 구성합니다. Main의 단일 Worker가 모션을 실행하고 판정은 별도 Queue Worker가 처리합니다. 장비 상태는 Robot/RG2에서 비동기로 수집하며 모든 외부 상태·결과는 HmiNode가 발행합니다. HMI의 기존 토픽 `START`는 현재 HMI 운전 시작 수단이 아닙니다.

Ready pose에서 Entry pose까지는 MoveJ **접근**입니다. Entry pose에서 Soft Grip과 함께 Tool +Z 방향으로 움직이는 구간이 **진입**이며 Pull은 반대 방향입니다. 지정 거리는 접촉 이동의 상한이므로 저항으로 미도달해도 실제 이동량과 힘을 기록해 판정합니다. 그리퍼 `busy` 값은 기록만 하며 동작 게이트로 사용하지 않습니다.

작업영역 내부 Home Return은 25 mm Open 폭 확인 → 현재 Tool −Z로 30 mm 후퇴 → Work Access → 전체 관절 0도 Home 순서입니다. Work Finish는 Work Access에서 대기하며 자동 Home으로 가지 않습니다. 수동 HOME은 현재 Access 도달을 확인하면 중복 Escape 없이 직접 Home으로 갑니다. 30 mm 후퇴거리와 실물 경로 간섭, 케이블 해제 여부는 현장 검증이 필요합니다.

수동 HOME 경로(U01)와 접근 미도달 차단(U02)은 반영 완료했으며, 남은 확장 범위(U03)는 [확인 항목](docs/v4/01_commons/02_변경추적_및_확인항목_v4.md)에 남겼습니다. 최신 자동검증 증거와 실물 검증 범위는 [v4 검증 안내](docs/v4/03_inspection/03_verification/02_실행과_정량검증_가이드_v4.md)를 참고합니다.
