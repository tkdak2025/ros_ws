# CCCIS Test Case #4 - Adaptive Grip Verification

**작성일:** 2026-09-22  
**대상 시스템:** CCCIS (Contact-based Cable Connection Inspection System)  
**Robot / Tool:** Doosan M0609 / OnRobot RG2  
**검사포인트:** `LAN_L2`, `LAN_L5`  
**상태:** 실물 반복검증 진행 중

## 1. 테스트 목적

Inspection Point의 `entry_pose`에서 Soft Grip 상태로 케이블 진입 동작을 수행하고,
Entry Guard에 의해 진입을 정상 종료한 뒤 Hard Grip과 Pull로 전환할 수 있는지 검증한다.

이 테스트에서 Soft/Hard Grip의 케이블 파지 성공 여부나 케이블 체결 정상/불량을
판정하지 않는다. Gripper 명령과 Robot Motion이 정상적으로 수행되는지 확인하고,
유효한 체결 판정은 이후 Pull Inspection과 Inspection Judgment에서 수행한다.

추가로 Entry 접근 중 케이블 간섭 유무에 따른 Force/TCP 데이터를 확보하여,
향후 Tip Contact 감지 또는 케이블 추종 미세조절의 필요성과 가능성을 검토한다.

## 2. 관련 문서와 코드

- 설계 시퀀스: `docs/02_Sequence/Current/Sequence_04_Adaptive_Grip_Sequence_2026-09-21.md`
- 실행 코드: `ros_ws/src/cable_pkg/cable_pkg/adaptive_grip_hardware/`
- 검사 레시피: `adaptive_grip_hardware/recipe.json`
- 측정결과: `adaptive_grip_hardware/measurement_results/<실행시각>/`

## 3. 테스트 대상 Flow

```text
검사포인트 선택 (LAN_L2 / LAN_L5)
        ↓
Recipe Validation
        ↓
Gripper Open
        ↓
Ready MoveJ → Entry Pose MoveJ
        ↓
작업자 접근 Gate
        ├─ 1: 통과
        └─ 2: 실패 및 시험 중단
        ↓
Soft Grip Command
        ↓
Entry MoveL
        ↓
거리 / 힘 / 시간 중 먼저 도달한 Guard로 Entry 종료
        ↓
Hard Grip Command
        ↓
Hard Grip 폭 도달 또는 RG2 Busy 종료 확인
        ↓
Pull 및 측정
        ↓
Entry Pose MoveL → Ready Pose MoveJ 복귀
        ↓
결과 저장
```

Wiggle, Fine Alignment 및 Grip Stability 추론은 기본 정상 Flow에서 제외한다.
이 기능들은 데이터에서 필요성이 확인된 뒤 별도 단위시험으로 검증한다.

## 4. Entry Guard 정의

| 종료 사유 | 조건 | 처리 |
| --- | --- | --- |
| `ENTRY_DISTANCE_REACHED` | Recipe의 `entry_depth_mm` 도달 | 정상 종료 후 Hard Grip 진행 |
| `ENTRY_FORCE_LIMIT` | Entry 시작 대비 힘 변화 5 N 도달 | 즉시 정지 후 Hard Grip 진행 |
| `ENTRY_TIMEOUT` | Entry 시작 후 10초 경과 | 정지 후 Hard Grip 진행 |

세 종료 사유는 Grip 실패 또는 제품 품질 판정값이 아니다. Entry가 더 진행되지 않도록
제한하는 최대조건이며, Robot/Controller 오류가 없다면 모두 정상 Flow로 처리한다.

Hard Grip 20 N은 RG2 Gripper 목표 힘이다. LAN Pull의 Tool Force Limit도 20 N이지만
서로 다른 값이며, Pull 방향 Tool Force가 20 N에 도달하면 Pull Motion을 정지한다.

## 5. 고정 시험조건

| 항목 | 값 | 비고 |
| --- | ---: | --- |
| MoveJ 속도 / 가속도 | 30 deg/s / 30 deg/s² | Ready·Entry Pose 접근 |
| MoveL 속도 / 가속도 | 10 mm/s / 30 mm/s² | Entry·Pull |
| Entry Force Limit | 5 N | 검증 중인 Guard 후보값 |
| Entry Timeout | 10 s | 최대 Entry 대기시간 |
| 시스템 최대 Entry 거리 | 25 mm | Recipe Validation 상한 |
| Soft / Hard Grip 힘 | 10 N / 20 N | Pull 하중 완화를 위해 Hard Grip을 20 N으로 조정 |
| Pull 최대거리 | 25 mm | Force 미도달 시 Motion 보호 상한 |
| Hard Grip 힘 | 20 N | RG2 Gripper 파지 명령 |
| LAN Pull Force Limit | 20 N | Tool Force 기반 Pull 정지조건 |
| Pull Timeout | 10 s | Pull 종료조건 |
| TCP / Tool | `GripperDA_v1` / `ToolWeight` | 제어기 활성 설정 확인 |

포인트별 좌표, 진입축, Entry 거리와 Grip 폭은 `recipe.json`에서 읽는다.

## 6. 테스트 케이스

### TC-04-01 정상 접근 및 Adaptive Grip

**조건:** Gripper Finger와 이동 경로에 케이블 간섭이 없도록 배치한다.

**절차:**

1. `LAN_L2` 또는 `LAN_L5`를 선택한다.
2. Ready→Entry 접근 중 간섭이 없는지 확인한다.
3. 접근 Gate에서 `1`을 선택한다.
4. Soft Grip 명령과 Entry MoveL을 수행한다.
5. Entry 종료 사유를 기록한다.
6. Hard Grip과 Pull까지 정상 진행되는지 확인한다.

**확인 항목:**

- Entry 종료 사유 및 실제 이동거리
- Entry 중 Peak Force 변화
- Soft/Hard Grip 명령 오류 여부
- Pull 시작 가능 여부
- 측정파일과 단계 상태의 누락 여부

### TC-04-02 Entry 접근 중 케이블 간섭

**조건:** 케이블이 Gripper Tip/Finger 접근 경로에 걸릴 수 있는 상태를 재현한다.

**절차:**

1. 정상 접근과 동일한 Recipe, Point 및 속도를 사용한다.
2. Ready→Entry MoveJ 구간의 TCP와 Wrench를 기록한다.
3. 간섭을 관찰하면 접근 Gate에서 `2`를 선택한다.
4. 후속 Soft Grip 및 Entry가 실행되지 않는지 확인한다.
5. 정상 케이스와 Force/Torque 변화를 비교한다.

**비교 Feature 후보:**

- 접근 시작 대비 최대 Force 변화량
- Force 상승이 시작된 TCP 위치
- 진입축 Force와 측면 Force의 비율
- `Mx, My, Mz` 변화
- Force 지속시간과 적분값 후보
- 목표 Entry Pose까지 남은 거리

케이블은 유연하므로 한 번의 Peak만으로 간섭 판정식을 확정하지 않는다. 반복 데이터에서
정상/간섭 조건이 분리되는지 확인한 뒤 자동 정지 또는 미세조절 적용 여부를 결정한다.

### TC-04-03 Entry Guard 전환

다음 조건을 각각 재현하여 종료 사유가 실패가 아닌 정상 이력으로 저장되고 Hard Grip으로
전환되는지 확인한다.

- 거리 도달: `ENTRY_DISTANCE_REACHED`
- 힘 5 N 도달: `ENTRY_FORCE_LIMIT`
- 10초 도달: `ENTRY_TIMEOUT`

Robot Motion 오류, Service Timeout과 E-STOP은 Entry Guard 정상 종료와 구분하여
System Error로 처리해야 한다.

### TC-04-04 HMI 통합 환경구조

HMI와 연결할 때 다음 정보가 동일한 Recipe/Point/Run ID를 기준으로 교환되는지 확인한다.

| 구분 | HMI 표시·입력 항목 |
| --- | --- |
| Recipe | Recipe ID, Version |
| Inspection Point | `LAN_L2`, `LAN_L5` |
| 실행 상태 | Ready 접근, Soft Grip, Entry, Hard Grip, Pull |
| Entry 상태 | 이동거리, Force, 종료 사유 |
| 작업자 Gate | `1=통과`, `2=실패·중단` |
| 결과 상태 | Running, Completed, Error, Interrupted Phase |
| 결과 위치 | Run ID와 측정결과 폴더 |

통신 단절, Pause/Resume 및 Stop 처리는 공통 Sequence 정책을 따르며 Adaptive Grip의
Entry Guard 판정과 혼용하지 않는다.

## 7. 측정 데이터

각 회차 결과는 다음 구조로 저장한다.

```text
adaptive_grip_hardware/measurement_results/<실행시각>/
├── inputs.json
├── samples.jsonl
├── gates.json
└── status.json
```

| 파일 | 내용 |
| --- | --- |
| `inputs.json` | Recipe 원본, 고정 운전조건, 선택 포인트 |
| `samples.jsonl` | Timestamp, Phase, TCP, Wrench, Gripper Width, 축방향 Force, Entry/Pull 이동량 |
| `gates.json` | 단계별 수행 결과, Entry 종료 사유와 Entry/Pull 최종 이동량 |
| `status.json` | 전체 완료 여부, 중단 단계와 오류 |

`samples.jsonl`의 `width_mm`은 RG2 실측 폭이고, `commanded_width_mm`과
`commanded_force_n`은 드라이버에 마지막으로 전달한 목표값이다. 현재 RG2 JointState에는
실제 파지력 측정값이 없으므로 `commanded_force_n`을 실측 힘으로 해석하지 않는다.
`gripper_busy`는 드라이버가 동작 중이라고 표시한 상태다.

정상/간섭 비교시험에는 작업자가 별도로 다음 정보를 시험 기록에 남긴다.

이동량 필드는 동작 시작 TCP를 0 mm로 사용한다. `entry_displacement_mm`은 Entry
진입방향, `pull_displacement_mm`은 Pull 방향을 각각 양수로 기록한다. 적용되지 않는
단계는 `null`이다. 기존 `axial_displacement_mm`은 진입축 기준 부호 있는 값이므로
Pull 중에는 음수가 될 수 있다.

- Test Case ID (`TC-04-01` 또는 `TC-04-02`)
- 간섭 관찰 여부와 접촉 위치
- Cable 배치 상태
- Point ID와 반복 회차
- 수동 중단 여부 및 사유

## 8. 예비 측정 기록

| 실행시각 | Point | 조건 | 관찰 및 데이터 | 처리 |
| --- | --- | --- | --- | --- |
| 2026-09-22 10:03 | LAN_L2 | Entry 접근 중 선 간섭 | Ready 최대 변화 약 1.63 N, Entry 최대 변화 약 19.37 N, 목표 부근에서 증가 | V02 작업자 Gate 실패로 후속 단계 차단 |
| 2026-09-22 10:32 | LAN_L5 | Entry 6 mm 진행 | Entry 최대 변화 약 4.08 N으로 기존 5 N 미도달 | 당시 구현은 V03 실패였으나 설계문서에 맞춰 거리 도달 정상 종료로 코드 수정 |

위 두 회차는 코드 정정 전 예비 데이터다. 정상/간섭 판정 Threshold 근거로 바로 사용하지
않고 후속 반복시험 설계의 참고값으로만 사용한다.

## 9. 합격 기준

- `LAN_L2`, `LAN_L5` Recipe가 변경 없이 로드된다.
- Ready→Entry 접근 Gate 실패 시 후속 Grip/Entry가 실행되지 않는다.
- Soft Grip 명령 후 Entry MoveL이 실행된다.
- 거리·5 N·10초 종료가 모두 정상 종료 사유로 기록되고 Hard Grip으로 전환된다.
- Soft/Hard Grip 폭이나 실제 파지 상태를 근거로 임의의 Grip 실패를 만들지 않는다.
- Robot/Tool 명령 오류는 정상 Guard 종료와 구분되어 Error로 기록된다.
- 모든 측정결과가 동일 Run 폴더에 저장된다.
- HMI 표시 상태와 저장된 Phase/Status가 일치한다.

## 10. 실행 방법

```bash
cd /home/rokey/Desktop/ROKEY9/ROKEY_3/PRJT_CCCIS/ros_ws
source /opt/ros/jazzy/setup.bash
source /home/rokey/ws_cobot_pjt/ws_dsr/install/setup.bash
source install/setup.bash
ros2 run cable_pkg adaptive_grip_hardware
```

실행 후 `LAN_L2` 또는 `LAN_L5`를 선택하고, 실제 Motion 시작 전 `START`를 입력한다.

## 11. 결과 기록표

| Test Case | Point | 반복 | Entry 종료 사유 | Peak Force 변화 | 간섭 관찰 | 결과 폴더 | 판정 |
| --- | --- | ---: | --- | ---: | --- | --- | --- |
| TC-04-01 | TBD | TBD | TBD | TBD N | 없음 | TBD | TBD |
| TC-04-02 | TBD | TBD | 해당 없음 또는 접근 중단 | TBD N | 있음 | TBD | TBD |
| TC-04-03 | TBD | TBD | 거리 / 힘 / 시간 | TBD N | TBD | TBD | TBD |
| TC-04-04 | TBD | TBD | TBD | TBD N | TBD | TBD | TBD |

## 12. 후속 판단

정상·간섭 반복데이터가 분리되면 다음 순서로 기능 확장을 검토한다.

1. V02 접근 중 Force 변화 기반 조기 정지
2. Tip Contact와 유연 케이블 접촉의 구분 가능성 평가
3. 접촉 방향이 반복적으로 식별될 경우 제한된 거리의 미세조절 단위시험
4. 단위시험 통과 후에만 기본 Adaptive Grip Flow 반영 여부 결정
