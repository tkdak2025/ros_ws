# Adaptive Grip 실물 단계 시험

검사 레시피는 이 폴더의 **`recipe.json` 하나**입니다. 현재 `points` 안에
`LAN_L2`, `LAN_L5` 두 검사포인트를 유지합니다.
기존 LAN Grip 레시피에서 좌표·그립 폭을 가져왔고, 실제 운전에서는 이 폴더의
`recipe.json`만 참조합니다.

## 파일과 읽는 순서

- `recipe.json`: 검사포인트별 좌표·진입축·거리·그립 폭
- `paths.py`: 레시피와 측정결과 폴더의 기준 경로
- `recipe.py`: 선택한 검사포인트와 탐색거리를 읽기
- `run.py`: 설정 확인 → 연결 → 실행 → 기록 저장
- `sequence.py`: V01~V09 시험 순서와 Gate
- `robot.py`: 실제 이동·그리퍼·측정·중단 감시

## 검사포인트 추가

레시피 구조는 다음과 같습니다(구조 설명용이며 값은 실제 파일 참고).

```text
recipe.json
└── points
    ├── LAN_L2                 Ready/Entry, 진입축, 깊이, 그립 폭
    ├── LAN_L5                 Ready/Entry, 진입축, 깊이, 그립 폭
    └── 새 포인트 ID            기존 포인트 블록을 복사해 추가
```

1. `points`의 기존 포인트 블록을 복사합니다.
2. 객체 키와 내부 `point_id`를 같은 새 ID로 바꾸고 `point_name`을 작성합니다.
3. `ready_pose`, `entry_pose`의 TASK와 JOINT를 해당 포인트 값으로 바꿉니다.
4. `entry_direction`, `entry_depth_mm`, `grip_setting`을 입력합니다.
5. 사용할 포인트는 `enabled: true`로 설정합니다.

TASK는 `[X,Y,Z,A,B,C]` mm/deg, JOINT는 6관절 deg, 진입축은 BASE 기준입니다.
**Entry 최대 이동거리는 `entry_depth_mm` 한 곳에서 관리합니다.** L2는 5 mm,
L5는 6 mm이며 시스템 상한은 25 mm입니다.
Wiggle 방향은 진입축과 수직이어야 합니다.

속도·가속도·힘 한계·Wiggle·Pull·허용오차·TCP/Tool 이름은 검사 목적에 맞춰
`sequence.py`의 `HardwareConfig`에 고정했습니다. 검사포인트마다 바꾸지 않습니다.
탐색거리는 항상 해당 포인트의 `entry_depth_mm`을 사용합니다.

## 실행

워크스페이스 루트에서 빌드/source:

```bash
source /opt/ros/jazzy/setup.bash
source /home/rokey/ws_cobot_pjt/ws_dsr/install/setup.bash
cd ros_ws
colcon build --packages-select cable_pkg --symlink-install
source install/setup.bash
```

레시피의 활성 검사포인트를 보고 선택해서 V01~V09 전체 실물 운전:

```bash
ros2 run cable_pkg adaptive_grip_hardware
```

인자 없이 실행하면 START 후 Recipe의 활성 포인트를 Cycle로 순회합니다. 각 포인트의
차례가 됐을 때 `[현재 순번/전체 개수]`와 함께 `1=검사`, `2=건너뛰기`를 묻습니다.
검사를 완료하면 Entry Pose와 Ready Pose로 복귀한 뒤 다음 포인트로 넘어갑니다.

포인트를 명령에서 바로 선택할 수도 있습니다.

```bash
ros2 run cable_pkg adaptive_grip_hardware LAN_L2
```

명령행 인자는 선택 사항이며, 사용한다면 검사포인트 ID 하나뿐입니다.
레시피·결과 경로, V09 종료, 실물 실행은 프로그램 목적에 맞게 고정했습니다.
`START`를 입력하기 전에는 로봇에 연결하거나 명령을 보내지 않습니다.
한 번 실행할 때 활성 포인트를 Recipe 순서대로 순회하며, 각 포인트의 Pull 후
Entry Pose와 Ready Pose로 복귀한 다음 선택한 다음 포인트를 시작합니다.
`--symlink-install` 빌드에서는 소스의 레시피 수정이 반영됩니다.

## 현재 시험조건의 출처

- 좌표, 진입축, 깊이(L2=5/L5=6 mm), Open/Soft/Hard 폭(25/22/16 mm): 기존 LAN 레시피
- Soft/Hard 힘 10/20 N, MoveJ 30 deg/s, MoveL 10 mm/s
- LAN Pull: Tool Force 20 N / 최대거리 25 mm / Timeout 10 s
- Entry Force Limit 5 N: **미검증 Guard 후보값**
- 도달 오차 0.2 mm/1 deg, 안정성 폭/TCP 변화 1 mm/0.2 mm: **미검증 초기 시험값**

실물 검증 완료를 의미하지 않습니다. Entry Force Limit 5 N은 진입을 끝내는 Guard다.
Hard Grip 20 N은 RG2 파지 명령이고, LAN Pull 20 N은 Tool Force 정지값입니다.
숫자는 같지만 센서와 역할이 서로 다릅니다.

실물 bringup과 RG2 드라이버가 실행된 상태에서 사용합니다. 설정을 출력한 뒤
`START`를 입력해야 연결/명령을 시작합니다. 프로그램이 요구하는 이 입력은
현장에서 경로와 조건을 확인하기 위한 실행 절차입니다. 기존 연결 코드의 실물 초기화는
RG2 힘 명령을 40 N으로 동기화한 후 V02에서 지정한 Open 폭·힘을 적용합니다.
활성 TCP·Tool 이름이 설정과 다르거나 제어기가 가상 모드이면 중단합니다.

## 단계별 동작

| 단계 | 실제 실행 | Gate |
| --- | --- | --- |
| V01 | 별도 레시피 정적 검증 | 입력 유효성 |
| V02 | Open → Ready MoveJ → Entry MoveJ | 도달 오차 확인 + 간섭/접근 관찰 PASS |
| V04 | Entry Pose에서 Soft Grip 명령 | 명령/Tool 오류가 없으면 다음 단계 |
| V03 | Soft Grip 상태로 BASE 진입축 방향 MoveL | 거리 도달, 5 N 도달 또는 10초 Timeout에서 정상 종료 |
| V07 | Entry 종료 직후 Hard Grip 20 N 명령 | 목표 힘 적용 확인 후 다음 단계 |
| V09 | 진입축 반대 방향 Pull 후 Soft Open→Entry→Ready | 20 N/25 mm/10 s 중 먼저 도달한 사유 기록 |

Entry 종료 사유는 `ENTRY_DISTANCE_REACHED`, `ENTRY_FORCE_LIMIT`, `ENTRY_TIMEOUT`으로
기록한다. 세 사유 모두 Grip 성공/실패 판정이 아니며 Hard Grip으로 진행합니다.
Soft/Hard Grip도 Cable 파지 성공을 추론하지 않고 명령 수행 오류만 확인합니다.
Wiggle, Fine Alignment, Grip Stability 추론은 기본 정상 Flow에서 제외하고 별도
단위시험 메서드로만 유지합니다. 작업자 Gate가 필요한 단계에서는
`1=통과·다음 단계`, `2=실패·시험 중단`을 숫자로 선택합니다.
한 실행은 한 포인트/한 회차이며 반복 실행 시 새 결과 폴더가 생깁니다.

정상 종료 시 해당 지점의 자세와 파지를 유지합니다. 자동 Open/Ready 복귀는
하지 않으므로 시험 종료 후 현장에서 해제·복귀를 수행해야 합니다.
오류·Ctrl+C·Gate 실패 시 기존 `safe_abort()`로 정지를 요청합니다.

## 결과 및 제한

이 테스트 케이스의 코드·레시피와 함께 공유할 수 있도록
`adaptive_grip_hardware/measurement_results/<실행시각>/`에 저장합니다.

- `inputs.json`: 레시피/시험조건/선택 포인트/종료 단계
- `samples.jsonl`: 단계, 시각, TCP, BASE 힘·모멘트, 실제 그리퍼 폭 및 조회 시각,
  진입축 기준 부호 있는 Axial Force/각 이동 시작 대비 Axial Displacement
- `gates.json`: 완료한 단계의 판정과 이동거리·Peak 힘 변화 등
- `status.json`: 전체 완료 여부, 중단 단계와 예외

V03 접촉은 탐색 시작 대비 힘 벡터 변화량으로 감지합니다. V09 Pull도 시작 Force를
기준으로 Pull 방향 Tool Force를 계산하며 20 N에 도달하면 Motion을 정지합니다.
MoveJ 경로 충돌 회피나 작업공간 경계 계산은 하지 않습니다.
위치 오차는 XYZ 거리, 자세 오차는 ABC 각각의 주기 차이로 확인하므로 Euler 표현이
달라지는 경로에서는 확인이 실패할 수 있습니다.

TCP/Force/폭은 순차 ROS 조회이며 하드웨어 동기 샘플이 아닙니다. 조회 시각을 각각
기록하고 `sample_period_s`는 조회 후 대기시간으로 사용합니다. 서비스 지연 때문에
요청 주기의 실시간 보장은 없으며 이 감시 코드는 로봇 제어기 안전 기능을 대체하지 않습니다.
코드 실행 시험은 로봇 없이 대역으로 수행하고 실물 동작 검증 결과와 구분합니다.

## 개발 검증

DSR/RG2 메시지 타입을 포함한 테스트(노드 생성·실물 연결 없음), 워크스페이스 루트에서:

```bash
source /opt/ros/jazzy/setup.bash
source /home/rokey/ws_cobot_pjt/ws_dsr/install/setup.bash
python3 -m pytest -q ros_ws/src/cable_pkg/test/adaptive_grip
```

이 장비에서는 위 드라이버 workspace에 `dsr_msgs2`, `onrobot_rg_msgs`가 설치돼
있습니다. 메시지 패키지가 없는 환경에서는 `test_hardware_robot.py`만 건너뛰고
ROS 독립 테스트를 실행합니다.
