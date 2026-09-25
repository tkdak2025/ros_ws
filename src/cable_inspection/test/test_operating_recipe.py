"""운영 LAN Inspection Recipe를 검증한다."""

from pathlib import Path

from cable_inspection.recipe.recipe import Recipe


RECIPE = (Path(__file__).resolve().parents[1]
          / "cable_inspection/recipe/inspection/lan_inspection_recipe.json")



def test_lan_recipe_has_ordered_l2_l5_motion_conditions():
    recipe = Recipe.load_json(RECIPE)

    assert [p["point_id"] for p in recipe["points"]] == ["LAN_L2", "LAN_L5"]
    assert recipe["points"][0]["entry_setting"]["max_distance_mm"] == 5.0
    assert recipe["points"][1]["entry_setting"]["max_distance_mm"] == 6.0

    for point in recipe["points"]:
        assert point["grip_setting"]["soft_force_n"] == 10.0
        assert point["grip_setting"]["hard_force_n"] == 20.0
        assert point["pull_setting"]["force_limit_n"] == 15.0
        assert point["pull_setting"]["max_distance_mm"] == 25.0
