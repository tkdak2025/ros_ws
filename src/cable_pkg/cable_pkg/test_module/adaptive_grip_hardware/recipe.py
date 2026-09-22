"""레시피 하나에서 공통 조건과 선택한 검사포인트를 읽는다."""

from cable_pkg.test_module.grip_stability.grip_stability_data import GripPullRecipe
from .paths import RECIPE_PATH


def load_recipe(path=RECIPE_PATH):
    """실제 운전에 사용할 Adaptive Grip 레시피 하나를 읽는다."""
    return GripPullRecipe.load_json(path)


def load_trial(path, point_id):
    # 검사포인트별 Entry/Grip/Pull 조건을 한 Recipe에서 읽는다.
    recipe = load_recipe(path)
    point = recipe.get_point(point_id)
    if point.pull_setting is None:
        raise ValueError(f"{point_id}: pull_setting이 필요합니다.")
    return recipe, {
        "search_mm": point.entry_depth_mm,
        "soft_force_n": point.grip_setting["soft_force_n"],
        "hard_force_n": point.grip_setting["hard_force_n"],
        "pull_force_limit_n": point.pull_setting["force_limit_n"],
        "pull_mm": point.pull_setting["max_distance_mm"],
        "pull_timeout_s": point.pull_setting["timeout_s"],
        "linear_speed_mm_s": point.pull_setting["speed_mm_s"],
    }
