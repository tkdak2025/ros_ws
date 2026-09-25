from copy import deepcopy
from pathlib import Path
import pytest
from cable_inspection.recipe.recipe import Recipe
from cable_inspection.recipe.node_recipe import RecipeNode



def recipe():
    return Recipe.load_json(Path(__file__).parents[1]/"cable_inspection/recipe/inspection/rcp_BMW_LWR_01.json")



def test_structured_roundtrip_preserves_order_and_disabled_points():
    original = recipe()
    original["points"].reverse()
    original["points"][0]["enabled"] = False
    decoded = RecipeNode.decode_message(RecipeNode.encode_message(original))
    assert decoded == original
    assert not decoded["points"][0]["enabled"]



def test_duplicate_wire_point_is_rejected():
    message = RecipeNode.encode_message(recipe())
    message.points.append(deepcopy(message.points[0]))

    with pytest.raises(ValueError, match="중복"):
        RecipeNode.decode_message(message)



def test_nonfinite_recipe_is_rejected():
    message = RecipeNode.encode_message(recipe())
    message.points[0].pull_setting.force_limit_n = float("nan")

    with pytest.raises(ValueError):
        RecipeNode.decode_message(message)
