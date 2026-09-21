# 검사포인트 레시피 예제

`inspection_recipe.example.json`은 JSON 구조와 BCM·VCU 포인트 명명 규칙을
보여주기 위한 예제다.

```text
BCM_P01  BCM 전원 커넥터
BCM_P02  BCM CAN 커넥터
VCU_P01  VCU 전원 커넥터
VCU_P02  VCU 신호 커넥터
```

모든 TASK·JOINT의 `0.0`은 자리표시자이며 실제 로봇 이동에 사용하면 안 된다.
DART에서 같은 자세의 BASE TASK와 JOINT를 확인한 뒤 한 쌍으로 입력한다.

프로젝트 루트가 `PRJT_prototype`일 때 다음처럼 읽을 수 있다.

```python
from cable_pkg.recipe import InspectionRecipe

recipe = InspectionRecipe.load_json(
    "src/recipe/examples/inspection_recipe.example.json"
)

bcm_point = recipe.get_point("BCM_P01")
print(bcm_point.task)
print(bcm_point.joint)
```
