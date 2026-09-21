# M0609 레시피 기반 MoveJ 오차 시험 결과

## 시험 방식

`src/error_validation/pose_range_test.py`는 레시피 JSON의 `sequence`
순서대로 저장된 JOINT에
`MoveJ`하고, 각 도착점의 실제 BASE TASK와 JOINT를 기록한다. 실행 중 TASK 생성,
IK 계산, solution 선택은 하지 않는다.

오차 검증용 레시피는 `src/recipe/error_validation/`에서 일반 예제와 분리해
관리한다.

- Y 시험과 Z 시험은 각각 별도 레시피를 사용한다.
- 첫 포인트는 `REFERENCE_START`이며 모든 오프셋의 기준이다.
- `MoveJ`의 중간 경로는 TCP 직선이나 이동 중 자세 유지를 보장하지 않는다.
- 실행 전 전체 저장 좌표를 출력하며 사용자가 `MOVE`를 입력해야 이동한다.

## 결과 폴더

실행마다 다음 두 파일을 같은 폴더에 저장한다.

```text
measurement_results/
└── {source_point_id}_{axis}_{YYYYMMDD_HHMMSS}/
    ├── pose_errors.csv
    └── run_summary.json
```

- `pose_errors.csv`: 포인트별 목표값, 실제값, 변화량과 오차
- `run_summary.json`: 레시피 원본, 실행 조건, 완료 포인트, 오차 초과와 종료 사유

## CSV 핵심 열

| 열 | 의미 |
| --- | --- |
| `recipe_id`, `recipe_version` | 사용한 레시피 식별 정보 |
| `source_point_id`, `test_axis` | 원본 검사포인트와 시험 축 |
| `point_id`, `point_name` | 실행 포인트 식별 정보 |
| `target_offset_xyz_mm` | 기준점 대비 목표 오프셋 `[dx, dy, dz]` |
| `target_*`, `actual_*` | 목표와 도착 후 실제 TASK·JOINT |
| `error_*` | `실제값 - 목표값` |
| `delta_*` | 기준 포인트 좌표 대비 실제 변화량 |
| `selected_solution_space` | 좌표 생성 단계에서 선택해 레시피에 저장한 자세 해 번호 |
| `actual_solution_space` | 도착 후 제어기가 보고한 자세 해 번호(보통 0~7) |
| `max_command_joint_change_deg` | 직전 명령에서 가장 크게 변한 단일 관절의 각도 |
| `joint_limit_margin` | 관절 가동 한계까지 남은 최소 정규화 여유 |
| `elbow_margin` | J3가 0°에서 떨어진 정도를 나타내는 참고값 |
| `wrist_margin` | J5가 손목 특이점인 0°에서 떨어진 정도를 나타내는 참고값 |
| `freedom_score` | 세 여유 지표 중 가장 작은 값 |
| `position_error_mm` | 목표와 실제 XYZ 사이 거리 |
| `orientation_error_deg` | 목표와 실제 자세 사이 최소 회전각 |
| `within_tolerance` | 위치 1 mm 및 방향 1° 이내 여부 |

좌표·관절·오차는 소수점 3자리, 이동 시간은 소수점 4자리까지 기록한다.

## 자세 여유 지표의 범위와 계산

네 지표는 모두 저장된 **목표 JOINT**에서 계산한다. 범위는 `0.0~1.0`이며
`1.0`에 가까울수록 해당 기준의 여유가 크고 `0.0`에 가까울수록 불리하다.

| 지표 | 계산식 | 해석 |
| --- | --- | --- |
| `joint_limit_margin` | 각 관절의 `(한계-|J|)/한계` 중 최솟값 | 한 관절이라도 한계에 가까우면 낮아진다. 사용 한계는 J1~J6 순서로 `[360, 95, 150, 360, 135, 360]°`다. |
| `elbow_margin` | `min(1, |J3|/30°)` | J3가 0°에 가까울수록 낮다. 30° 이상이면 1이다. |
| `wrist_margin` | `min(1, |J5|/30°)` | J5가 손목 특이점인 0°에 가까울수록 낮다. 30° 이상이면 1이다. |
| `freedom_score` | 위 세 값의 최솟값 | 현재 자세에서 가장 불리한 조건을 한 값으로 표시한다. |

이 값들은 후보 자세와 구간별 변화를 비교하기 위한 휴리스틱이다. Jacobian 기반
manipulability, 충돌 거리 또는 절대적인 안전도를 의미하지 않는다.

`max_command_joint_change_deg`는 0~1 점수가 아니며 단위는 `deg`다. 첫 포인트는
시험 시작 시 읽은 현재 JOINT와 비교하고, 이후 포인트는 직전 목표 JOINT와
비교한다. 코드에서는 90°를 넘는 인접 레시피 경로를 실행 전에 거부한다.

`selected_solution_space`는 실행 중 다시 계산하지 않고 레시피 값을 기록한다.
레시피 생성 당시 번호가 보존되지 않은 포인트는 빈 값이며, 임의로 추정하지
않는다. `actual_solution_space`는 도착 후 제어기 응답이다.

## 분석 시 확인할 값

1. `target_offset_xyz_mm`별 `error_x/y/z_mm`을 비교한다.
2. `orientation_error_deg`로 도착 후 툴 자세 오차를 비교한다.
3. 같은 좌표의 OUT·RETURN 행을 비교해 반복 오차를 확인한다.
4. `actual_j1_deg`부터 `actual_j6_deg`까지 관절 변화를 확인한다.
5. 여유 지표가 이동 범위 끝으로 갈수록 낮아지는지 확인한다.
6. `max_command_joint_change_deg`로 급격한 관절 전환 구간을 찾는다.
7. `run_summary.json`의 `stop_reason`과 `completed_points`로 완주 여부를 확인한다.

CSV는 각 목표에 도착한 뒤 한 행만 기록한다. 이동 중 연속 궤적은 이 결과로
판단할 수 없다.
