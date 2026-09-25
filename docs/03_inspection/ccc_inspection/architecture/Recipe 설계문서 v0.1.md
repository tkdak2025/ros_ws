> 이 문서는 이전 설계·작업 기록입니다. 현재 기준은 [v4 문서 안내](../../../v4/00_문서안내_v4.md)이며, 이후 변경 내용은 [최종결론](../../../작업내역/18_최종결론_2026-09-25.md)을 참고하세요. 아래 본문은 이력으로 보존합니다.

> 초기 레시피 아키텍처 v0.1 보존본입니다. 현재 실행 레시피의 메시지 필드·검증 조건은 [HMI 검사 측 인터페이스 가이드](../../../작업내역/03_HMI_검사측_인터페이스_가이드_2026-09-23.md)와 `src/cable_inspection/cable_inspection/recipe/inspection_recipe.py`를 기준으로 합니다.

# Recipe / Inspection Architecture v0.1

## 1. 문서 목적

자동차 전장 기판의 케이블 결합 검사에서 검사 레시피, 로봇 접근, 파지 보정,
Grip-Pull 검사, 결과 기록의 책임을 분리한다.

이 문서는 구현 전 구조를 고정하기 위한 v0.1 명세다. 현재의
`src/cable_pkg/cable_pkg/error_validation/pose_range_test.py`와 범위 시험 레시피는 도달 범위
확인용 시험 코드이며
실제 검사 레시피 구조에 포함하지 않는다.

## 2. 핵심 원칙

1. Recipe는 검사 대상의 Nominal 정보와 안전한 진입 조건만 제공한다.
2. 정확한 접촉점, 파지 폭, 최종 파지 위치를 Recipe에 고정하지 않는다.
3. 실제 위치 오차는 Adaptive Search, Pre-Grip, Fine Alignment에서 보정한다.
4. 동일한 검사 알고리즘을 BCM·VCU의 모든 검사포인트에서 재사용한다.
5. Grip-Pull 기록과 PASS/FAIL 판정은 파지 안정화 이후 별도 모듈이 담당한다.
6. 레시피 로더는 데이터를 검증·변환하지만 로봇을 움직이지 않는다.
7. TCP 바운더리와 로봇 전체 충돌 검사는 검사포인트 레시피와 분리한다.

## 3. 도메인 식별 체계

예시 대상 기판은 다음 두 종류다.

- `BCM_MAIN_BOARD`: Body Control Module 메인 기판
- `VCU_INTERFACE_BOARD`: Vehicle Control Unit 인터페이스 기판

검사포인트 ID는 기판 식별자와 포인트 번호를 조합한다.

```text
BCM_P01
BCM_P02
VCU_P01
VCU_P02
```

`inspection_id`는 작업지시와 결과 파일이 공통으로 사용하는 불변 식별자다.
표시 이름은 별도 `inspection_name`으로 관리한다.

## 4. Recipe가 담당하는 정보

### 4.1 Cable Condition

| 필드 | 의미 |
| --- | --- |
| `inspection_id` | 검사포인트 ID |
| `inspection_name` | 사람이 읽는 검사포인트 이름 |
| `board_type` | `BCM_MAIN_BOARD`, `VCU_INTERFACE_BOARD` 등 |
| `connector_type` | `USB_A` 등 커넥터 종류 |
| `cable_type` | 검사 대상 케이블 종류 |
| `inspection_point.position` | 커넥터 Nominal 중심 위치 `[X,Y,Z]` |
| `connection_direction` | 케이블 체결 방향 단위벡터 `[dx,dy,dz]` |

### 4.2 Robot Access Condition

| 필드 | 의미 |
| --- | --- |
| `ready_pose.joint` | MoveJ로 진입할 안전한 준비 관절 자세 `[J1..J6]` |
| `ready_pose.task` | 준비 자세의 확인용 TASK 값. 선택 항목 |
| `entry_pose.position` | 탐색을 시작할 Nominal TCP 위치 `[X,Y,Z]` |
| `tool_orientation` | 진입 시 TCP 방향 `[A,B,C]` |
| `approach_direction` | 탐색 진입 방향 단위벡터 `[dx,dy,dz]` |
| `approach_range_mm` | 진입 방향으로 탐색할 수 있는 최대 거리 |
| `workspace_boundary_id` | 적용할 별도 작업공간 바운더리 ID |

`entry_pose.position`과 `tool_orientation`을 합치면 DSR `posx`에 사용할
`[X,Y,Z,A,B,C]`가 된다. 방향을 두 곳에 중복 저장하지 않는다.

## 5. Recipe가 담당하지 않는 정보

다음 항목은 v0.1 검사포인트 레시피에 넣지 않는다.

- 정확한 접촉 위치
- 최종 파지 위치
- 그리퍼 파지 폭
- Search 세부 알고리즘
- Fine Alignment 보정 알고리즘
- Grip Stability 계산 알고리즘
- Grip-Pull 동작 구현
- 힘 데이터 필터링과 PASS/FAIL 판정 구현
- 로봇 링크 및 MoveJ 중간 경로 충돌 검사

검사 기준값이 필요해지면 위치 레시피에 섞지 않고 별도의
`inspection_criteria` 구조로 버전을 관리한다.

## 6. YAML 구조 v0.1

```yaml
recipe_id: AUTOMOTIVE_CABLE_INSPECTION
recipe_version: 0.1.0
coordinate_frame: BASE

inspection_points:
  BCM_P01:
    inspection_id: BCM_P01
    inspection_name: BCM_POWER_CONNECTOR

    cable_condition:
      board_type: BCM_MAIN_BOARD
      connector_type: USB_A
      cable_type: STANDARD_USB
      inspection_point:
        position: [TBD, TBD, TBD]
      connection_direction: [TBD, TBD, TBD]

    robot_access:
      ready_pose:
        joint: [TBD, TBD, TBD, TBD, TBD, TBD]
        task: [TBD, TBD, TBD, TBD, TBD, TBD]
      entry_pose:
        position: [TBD, TBD, TBD]
      tool_orientation: [TBD, TBD, TBD]
      approach_direction: [TBD, TBD, TBD]
      approach_range_mm: TBD
      workspace_boundary_id: BCM_WORKSPACE

  VCU_P01:
    inspection_id: VCU_P01
    inspection_name: VCU_POWER_CONNECTOR

    cable_condition:
      board_type: VCU_INTERFACE_BOARD
      connector_type: USB_A
      cable_type: STANDARD_USB
      inspection_point:
        position: [TBD, TBD, TBD]
      connection_direction: [TBD, TBD, TBD]

    robot_access:
      ready_pose:
        joint: [TBD, TBD, TBD, TBD, TBD, TBD]
        task: [TBD, TBD, TBD, TBD, TBD, TBD]
      entry_pose:
        position: [TBD, TBD, TBD]
      tool_orientation: [TBD, TBD, TBD]
      approach_direction: [TBD, TBD, TBD]
      approach_range_mm: TBD
      workspace_boundary_id: VCU_WORKSPACE
```

`TBD`는 실제 좌표 취득 전 자리표시자다. Loader는 `TBD`가 남아 있는 포인트를
실행 가능한 포인트로 반환하면 안 된다.

## 7. Loader의 책임

Recipe Loader는 다음 작업만 수행한다.

1. YAML 또는 dict 읽기
2. `recipe_id`, 버전, 포인트 ID 검증
3. 요청한 `inspection_id` 조회
4. 좌표 길이와 유한값 검증
5. 방향벡터의 크기 및 정규화 여부 검증
6. `entry_pose.position + tool_orientation`을 DSR TASK 6값으로 변환
7. `ready_pose.joint`를 DSR JOINT 6값으로 변환
8. `workspace_boundary_id`로 별도 바운더리 조회
9. 실행부에 불변 데이터 객체 전달

Loader는 `movej`, `movel`, 그리퍼 I/O, 힘 측정 서비스를 호출하지 않는다.

## 8. 실행 시퀀스

```text
Load Recipe
    ↓
Select Inspection Point
    ↓
Validate Point and Workspace Boundary
    ↓
movej(Ready Pose)
    ↓
movej / movel(Entry Pose)
    ↓
Gripper Open
    ↓
Adaptive Search
    ↓
Pre-Grip
    ↓
Fine Alignment
    ↓
Final Grip
    ↓
Grip Stability Check
    ↓
Grip-Pull Test
    ↓
Logging and Evaluation
```

각 단계는 성공, 실패 사유, 측정값을 다음 단계에 명시적으로 전달한다. 실패 시
검사 알고리즘은 안전 정지 또는 정의된 복귀 절차를 호출한다.

## 9. 모듈 구조

```text
PRJT_prototype/
├── config/
│   ├── inspection_recipe.yaml
│   └── workspace_boundaries.yaml
├── src/
│   ├── recipe/
│   │   ├── models.py
│   │   └── recipe_loader.py
│   ├── safety/
│   │   └── workspace_boundary.py
│   ├── motion/
│   │   ├── approach.py
│   │   ├── search.py
│   │   └── alignment.py
│   ├── gripper/
│   │   ├── pre_grip.py
│   │   ├── final_grip.py
│   │   └── grip_stability.py
│   ├── inspection/
│   │   ├── grip_pull.py
│   │   └── evaluator.py
│   ├── logging/
│   │   └── inspection_logger.py
│   └── inspection_main.py
└── measurement_results/
```

초기 구현에서는 디렉터리만 과도하게 만들지 않고 `recipe/models.py`와
`recipe/recipe_loader.py`부터 작성한다. 알고리즘 모듈은 호출 시점이 정해질 때
추가한다.

## 10. 미구현 인터페이스

아래 인터페이스는 다음 단계에서 시그니처만 확정하고 내부는 `TODO`로 둔다.

```python
def adaptive_search(point, robot, gripper):
    """Nominal 위치에서 실제 케이블 위치를 탐색한다."""
    raise NotImplementedError


def pre_grip(search_result, gripper):
    """정렬 전 케이블을 약하게 파지한다."""
    raise NotImplementedError


def fine_alignment(pre_grip_result, robot, gripper):
    """최종 파지 전 위치와 자세를 보정한다."""
    raise NotImplementedError


def check_grip_stability(grip_result, robot):
    """Grip-Pull 실행 전 파지 안정성을 확인한다."""
    raise NotImplementedError


def run_grip_pull(stability_result, robot, logger):
    """검증된 파지 상태에서 Pull 시험과 측정을 수행한다."""
    raise NotImplementedError
```

## 11. 바운더리와 충돌 검사의 위치

`workspace_boundary_id`는 검사포인트가 사용할 영역을 참조할 뿐, 영역 좌표를
검사포인트 안에 복제하지 않는다.

```text
Inspection Point
    └── workspace_boundary_id
             ↓
Workspace Boundary Registry
    ├── allowed_workspace
    └── forbidden_regions
```

TCP 바운더리 검사는 목표점의 허용 여부만 판정한다. MoveJ 중간 TCP 경로와
로봇 링크·그리퍼·케이블 충돌은 별도 경로 검사 책임으로 남긴다.

## 12. v0.1 완료 기준

- Recipe와 검사 알고리즘의 책임이 분리돼 있다.
- BCM/VCU 검사포인트를 동일한 구조로 표현할 수 있다.
- 포인트 ID로 Nominal 조건과 Robot Access Condition을 조회할 수 있다.
- 좌표와 방향 데이터가 중복 저장되지 않는다.
- 미확정 알고리즘을 임의로 구현하지 않는다.
- 현재 시험용 `REFERENCE_TASK`와 실제 검사 레시피를 혼용하지 않는다.
