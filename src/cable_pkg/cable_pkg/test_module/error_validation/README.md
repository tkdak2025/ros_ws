# Y/Z 위치 오차 검증 코드

이 폴더는 실제 검사 시퀀스와 분리된 M0609 위치 오차 검증 도구를 관리한다.

- `pose_range_test.py`: Y 또는 Z 레시피에 저장된 JOINT를 순서대로 MoveJ하고,
  목표·실제 TASK/JOINT와 축별 오차 및 자세 여유 지표를 기록한다.
- `pose_range_observer.py`: 로봇을 움직이지 않고 수동 이동 중 현재 TASK/JOINT와
  최초 위치 대비 변화량을 연속 기록하는 보조 도구다.

시험 좌표는 `cable_pkg/recipe/error_validation/`에 축별 레시피로 보관한다.
결과는 기존과 동일하게 프로젝트의 `measurement_results/`에 저장한다.

## 레시피 기반 Y축 시험

```bash
ros2 run cable_pkg pose_range_test --recipe \
  src/cable_pkg/cable_pkg/recipe/error_validation/y_pose_range_recipe.json
```

## 레시피 기반 Z축 시험

```bash
ros2 run cable_pkg pose_range_test --recipe \
  src/cable_pkg/cable_pkg/recipe/error_validation/z_pose_range_recipe.json
```

## 수동 위치 관찰

```bash
ros2 run cable_pkg pose_range_observer
```

실물 시험 전에는 bringup 모드, TCP/Tool, 전체 MoveJ 경로와 주변 간섭을 확인한다.
