# 로봇 설정 및 검사포인트 위치 레시피

## Tool / TCP 설정

- `tcp.json`: `GripperDA_v1`의 플랜지 기준 TCP 오프셋. XYZ는 mm, ABC는 °.
- `tool.json`: `ToolWeight`의 질량 `1.470 kg`과 플랜지 기준 무게중심
  `XYZ = [1.490, 85.380, 15.620] mm`. 2026-09-21에 제공된 DART 툴 설정
  화면과 대조했다. 관성값은 화면에 없어 `null`이다.

두 파일은 `이슈리스트.md`에 남아 있는 설정 화면의 수치를 정리한 것이다.
`grip_stability_test.py --mode virtual`은 실행 위치와 무관하게 이 두 파일을
자동 로드하고, 가상 시스템·가상 그리퍼 확인 후 등록 및 활성화한다.
이름, 수치, 단위와 좌표 순서를 검사하며 오류가 있으면 설정 적용 전에 중단한다.
관성이 `null`이면 가상 모션 시험에서만 6개 0으로 대체하며, 값이 있으면
6개 수치를 그대로 사용한다. 결과 JSON에는 원본 설정과 적용한 관성을 기록한다.
실물 모드에는 자동 적용하지 않는다.

## 검사포인트 위치 레시피

`InspectionRecipe`는 실제 검사포인트별 위치정보만 관리한다.

```text
InspectionRecipe
└── points
    ├── P01: point_name, TASK, JOINT, coordinate_frame
    ├── P02: point_name, TASK, JOINT, coordinate_frame
    └── ...
```

검사 조건, 힘 기준, 그리퍼 동작, 시험 시퀀스, 속도·가속도, 바운더리는 이
레시피에 넣지 않는다. 각 기능을 담당하는 별도 설정과 클래스에서 관리한다.

레시피 예제는 `src/recipe/examples/inspection_recipe.example.json`에 있다.
예제의 0 좌표는 구조 확인용 자리표시자다. 실제 작업에 사용하기 전에
포인트명과 DART에서 확인한 TASK·JOINT를 입력해야 한다.

```python
from cable_pkg.recipe import InspectionRecipe

recipe = InspectionRecipe.load_json("config/inspection_recipe.json")
point = recipe.get_point("P01")

print(point.task)
print(point.joint)
```

TCP 허용영역과 금지영역은 `safety/workspace_boundary.py`의 `WorkspaceBoundary`가 별도로
담당한다. 이는 목표 TCP만 판정하며 로봇 링크와 MoveJ 중간 경로의 충돌을
확인하지 않는다.
