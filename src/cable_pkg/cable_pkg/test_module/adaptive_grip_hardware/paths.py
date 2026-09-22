"""Adaptive Grip 기능 단위에서 사용하는 파일 경로."""

from pathlib import Path


# --symlink-install로 실행하면 __file__은 build 폴더를 가리킬 수 있다.
# recipe.json 심볼릭 링크의 실제 위치를 기준으로 소스 기능 폴더를 찾는다.
RECIPE_PATH = Path(__file__).with_name("recipe.json").resolve()
UNIT_DIR = RECIPE_PATH.parent
RESULTS_DIR = UNIT_DIR / "measurement_results"

