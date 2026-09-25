"""입력 경로별 검증 일치, 실패 시 원본 유지, 실행 복사본 격리를 확인한다."""
import json
import subprocess
import sys
from dataclasses import asdict
from pathlib import Path

import pytest
from cable_inspection.recipe.recipe import Recipe
from cable_inspection.recipe.node_recipe import RecipeNode

PACKAGE = Path(__file__).parents[1]
SOURCE = PACKAGE / 'cable_inspection/recipe/inspection/lan_inspection_recipe.json'



@pytest.mark.parametrize('field,value', [
    ('recipe_id', ''), ('recipe_version', ''), ('connector_type', 'x' * 257),
    ('coordinate_frame', 'TOOL'),
])
def test_file_and_message_apply_same_validation(tmp_path, field, value):
    original = Recipe.load_json(SOURCE)
    message = RecipeNode.encode_message(original)
    setattr(message, field, value)
    raw = original
    raw[field] = value
    path = tmp_path / 'recipe.json'
    path.write_text(json.dumps(raw))

    with pytest.raises(ValueError):
        Recipe.load_json(path)

    with pytest.raises(ValueError):
        RecipeNode.decode_message(message)



def test_failed_update_preserves_accepted_recipe():
    source = Recipe.load_json(SOURCE)
    recipes = Recipe()
    recipes.accept(source)
    source['points'][0]['pull_setting']['force_limit_n'] = float('nan')

    with pytest.raises(ValueError):
        recipes.accept(source)

    assert recipes.get(source["recipe_id"])['points'][0]['pull_setting']['force_limit_n'] == 15.0



def test_file_reloaded_without_mutating_existing_execution(tmp_path):
    path = tmp_path / 'recipe.json'
    raw = json.loads(SOURCE.read_text())
    path.write_text(json.dumps(raw))
    recipes = Recipe(recipe_paths=[path])
    running = recipes.get(raw['recipe_id'])
    raw['recipe_version'] = 'next'
    path.write_text(json.dumps(raw))
    assert recipes.get(raw['recipe_id'])['recipe_version'] == 'next'
    assert running["recipe_version"] != 'next'
    raw['recipe_id'] = 'changed_id'
    path.write_text(json.dumps(raw))

    with pytest.raises(ValueError, match='ID'):
        recipes.get(running["recipe_id"])



def test_file_rejects_missing_execution_point_and_nonboolean_enabled(tmp_path):
    raw = json.loads(SOURCE.read_text())
    path = tmp_path / 'recipe.json'
    raw['execution_order'].pop()
    path.write_text(json.dumps(raw))

    with pytest.raises(ValueError):
        Recipe(recipe_paths=[path])

    raw['execution_order'] = list(raw['points'])
    raw['points']['LAN_L2']['enabled'] = 1
    path.write_text(json.dumps(raw))

    with pytest.raises(ValueError):
        Recipe(recipe_paths=[path])



def test_recipe_component_imports_without_ros_environment():
    code = (
        'import sys; '
        f'sys.path.insert(0, {str(PACKAGE)!r}); '
        'from cable_inspection.recipe.recipe import Recipe; '
        'assert "rclpy" not in sys.modules; '
        'assert "cable_interfaces" not in sys.modules'
    )
    subprocess.run([sys.executable, '-I', '-c', code], check=True)



@pytest.mark.parametrize("invalid", ["version", "order", "empty", "enabled"])
def test_recipe_validate_checks_complete_contract_directly(invalid):
    from dataclasses import replace
    recipe = Recipe.load_json(SOURCE)

    if invalid == "version":
        recipe["recipe_version"] = ""

    elif invalid == "order":
        recipe["points"].append(recipe["points"][0])

    elif invalid == "empty":
        recipe["points"].clear()

    else:
        recipe["points"][0]["enabled"] = 1

    with pytest.raises(ValueError):
        Recipe.validate(recipe)
