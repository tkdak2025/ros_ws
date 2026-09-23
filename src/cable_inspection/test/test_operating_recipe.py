"""운영 LAN Inspection Recipe를 검증한다."""

from pathlib import Path

from cable_inspection.recipe.inspection_recipe import OperatingInspectionRecipe


RECIPE = (Path(__file__).resolve().parents[1]
          / "cable_inspection/recipe/inspection/lan_inspection_recipe.json")


def test_lan_recipe_has_ordered_l2_l5_motion_conditions():
    recipe = OperatingInspectionRecipe.load_json(RECIPE)

    assert recipe.execution_order == ["LAN_L2", "LAN_L5"]
    assert recipe.points["LAN_L2"].entry_setting["max_distance_mm"] == 5.0
    assert recipe.points["LAN_L5"].entry_setting["max_distance_mm"] == 6.0
    for point in recipe.points.values():
        assert point.normalized_entry_direction() == [0.0, -1.0, 0.0]
        assert point.grip_setting["soft_force_n"] == 10.0
        assert point.grip_setting["hard_force_n"] == 20.0
        assert point.pull_setting["force_limit_n"] == 15.0
        assert point.pull_setting["max_distance_mm"] == 25.0
