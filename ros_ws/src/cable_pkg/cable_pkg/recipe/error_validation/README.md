# Y/Z축 오차 검증 레시피

이 폴더는 일반 검사포인트 예제와 분리된 로봇 위치 오차 시험 전용 영역이다.
`src/error_validation/pose_range_test.py`가 여기 저장된 TASK·JOINT를
`sequence` 순서로 실행한다.

## 파일 구분

- `y_pose_range_recipe.json`: BASE Y축 100 mm 간격 왕복 시험용.
- `z_pose_range_recipe.json`: BASE Z축 100 mm 간격 왕복 시험용.

Y와 Z 시험은 서로 다른 레시피로 관리한다. 실행 중 좌표 생성이나 IK 계산은
하지 않으며, 새 기준좌표를 사용할 때는 별도 계산·검증 후 해당 레시피를 만든다.

현재 Z 레시피는 기준 TASK
`[700.080, -24.590, 466.450, 177.57, -90.0, -180.0]`를 포함해 Z축
`0 → +300 → 0 → -300 → 0 mm`를 100 mm 간격으로 왕복하는 13개 포인트다.
Y 레시피도 같은 기준 TASK·JOINT에서 Y축을 같은 순서로 왕복한다. Y 레시피의
JOINT와 solution space는 이전에 같은 기준점에서 계산해 저장한 IK 결과를
사용했다.

```python
from recipe import InspectionRecipe

recipe = InspectionRecipe.load_json(
    "src/recipe/error_validation/z_pose_range_recipe.json"
)
```

저장 좌표의 IK·FK 확인은 완료했지만 MoveJ 중간 경로의 링크·그리퍼·케이블
충돌 안전성은 보장하지 않는다. 실행 전 출력되는 전체 경로를 확인해야 한다.

## 가상 모드 관절 시퀀스 시험

실행 중인 M0609 bringup이 `mode:=virtual host:=127.0.0.1`인지 확인한 후:

```bash
source /opt/ros/jazzy/setup.bash
source /home/rokey/ws_cobot_pjt/ws_dsr/install/setup.bash
export ROS_DOMAIN_ID=50 ROS_LOCALHOST_ONLY=1
/usr/bin/python3 src/error_validation/pose_range_test.py \
  --recipe src/recipe/error_validation/y_pose_range_recipe.json \
  --virtual-joint-only --prepare-start --confirm-virtual
```

Z 시험은 레시피 파일명을 `z_pose_range_recipe.json`으로 바꾼다.
`--virtual-joint-only`는 매 이동 전 `get_robot_system=1`을 확인한다.
가상 제어기의 현재 TCP/Tool을 사용하며, 레시피의 TASK와 측정값은 기록하지만
서로 다른 TCP 설정을 비교하지 않도록 TASK 오차·허용오차 판정은 비워 둔다.
관절 도착 오차가 1°를 초과하면 중단한다.
`--prepare-start`는 시작 자세까지 관절 변화가 각 90° 이하인 경유점을 사용한다.
`--confirm-virtual`은 가상 관절 시험에서만 `MOVE` 입력을 생략한다.
결과는 `measurement_results/virtual_*` 폴더에 저장된다.

이 시험은 저장된 JOINT의 실행 및 도착 확인용이며, 실물 위치 정밀도,
그리퍼 접촉력, 중간 경로의 충돌 안전성을 검증하지 않는다.
기존 TCP/Tool 확인을 포함한 위치 오차 시험은 가상 전용 옵션 없이 실행한다.
