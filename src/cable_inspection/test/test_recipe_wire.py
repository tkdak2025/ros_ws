from copy import deepcopy
from pathlib import Path
import pytest
from cable_inspection.recipe.inspection_recipe import OperatingInspectionRecipe
from cable_inspection.recipe.inspection_recipe import to_message, from_message, validate_recipe


def recipe():
    return OperatingInspectionRecipe.load_json(Path(__file__).parents[1]/"cable_inspection/recipe/inspection/rcp_BMW_LWR_01.json")


def test_structured_roundtrip_preserves_order_and_disabled_points():
    from dataclasses import replace
    original = recipe()
    original.execution_order.reverse()
    key = original.execution_order[0]
    original.points[key] = replace(original.points[key], enabled=False)
    decoded = from_message(to_message(original))
    assert decoded == original
    assert not decoded.points[key].enabled


def test_duplicate_wire_point_is_rejected():
    message = to_message(recipe())
    message.points.append(deepcopy(message.points[0]))
    with pytest.raises(ValueError, match="중복"):
        from_message(message)


def test_nonfinite_recipe_is_rejected():
    message = to_message(recipe())
    message.points[0].pull_setting.force_limit_n = float("nan")
    with pytest.raises(ValueError): from_message(message)
