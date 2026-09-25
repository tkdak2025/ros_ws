"""Recipe가 순회와 비동기 결과를 소유하며 Main에는 한 포인트씩 제공하는지 확인한다."""
from copy import deepcopy
from pathlib import Path

import pytest
from cable_inspection.recipe.recipe import Recipe
from cable_inspection.sequence.inspection.data_models.inspection_point_result import InspectionPointResult
from cable_inspection.sequence.common.data_models.sequence_status import SequenceStatus

SOURCE = Path(__file__).parents[1] / 'cable_inspection/recipe/inspection/lan_inspection_recipe.json'



def prepared():
    data = Recipe.load_json(SOURCE)
    skipped = deepcopy(data['points'][0])
    skipped.update(point_id='SKIPPED', enabled=False)
    data['points'].insert(1, skipped)
    recipes = Recipe()
    recipes.accept(data)
    recipes.begin(data['recipe_id'], 42)
    return recipes, data



def motion(point_id):
    return InspectionPointResult(point_id, transition={}, adaptive_grip={'adaptive_grip_done': True})



def judgment(point_id, run_id=42, outcome='PASS'):
    return {point_id: {'run_id': run_id, 'point_id': point_id, 'result': outcome,
        'judgment_status': 'COMPLETED', 'sequence_status': 'SUCCESS', 'reason': outcome}}



def test_array_order_disabled_skip_and_idempotent_next_request():
    recipes, _ = prepared()
    first = recipes.next_point()
    assert first['point_id'] == 'LAN_L2'
    assert recipes.next_point() == first
    first['pull_setting']['force_limit_n'] = 999.
    assert recipes.next_point()['pull_setting']['force_limit_n'] == 15.
    recipes.complete_point(42, motion('LAN_L2'))
    assert recipes.next_point()['point_id'] == 'LAN_L5'
    assert recipes.progress()['execution_index'] == 1
    recipes.complete_point(42, motion('LAN_L5'))
    assert recipes.next_point() is None
    assert recipes.progress()['total_points'] == 2
    assert recipes.progress()['progress_percent'] == 100

    # 모션 완료와 판정 완료는 별개다.
    assert not recipes.completion().success



def test_early_and_late_judgments_are_preserved_and_logs_gate_completion():
    recipes, _ = prepared()
    first = recipes.next_point()['point_id']
    recipes.mark_pending(42, first)
    recipes.apply_judgments(42, judgment(first))
    recipes.complete_point(42, motion(first))
    assert recipes.inspection_results()[first]['result'] == 'PASS'
    recipes.mark_logs_saved(42, [first])
    second = recipes.next_point()['point_id']
    recipes.mark_pending(42, second)
    recipes.complete_point(42, motion(second))
    assert recipes.next_point() is None
    assert recipes.progress()['pending_judgments'] == 1
    recipes.apply_judgments(42, judgment(second, outcome='FAIL'))
    assert not recipes.completion().success
    recipes.mark_logs_saved(42, [second])
    assert recipes.completion().success
    assert recipes.completion().data['counts'] == {'PASS': 1, 'FAIL': 1, 'SYSTEM_ERROR': 0}



def test_stale_unknown_and_duplicate_results_do_not_advance_iteration():
    recipes, _ = prepared()
    key = recipes.next_point()['point_id']
    recipes.mark_pending(42, key)
    recipes.apply_judgments(41, judgment(key, run_id=41))
    recipes.apply_judgments(42, judgment(key, run_id=41))
    recipes.apply_judgments(42, judgment('OTHER'))
    assert recipes.progress()['pending_judgments'] == 1

    for _ in range(2):
        recipes.apply_judgments(42, judgment(key))

    assert recipes.progress()['execution_index'] == 0
    assert recipes.progress()['pending_judgments'] == 0
    recipes.complete_point(42, motion(key))

    with pytest.raises(ValueError):
        recipes.complete_point(42, motion(key))

    assert recipes.progress()['execution_index'] == 1



def test_wrong_point_or_run_never_completes_current_point():
    recipes, _ = prepared()
    key = recipes.next_point()['point_id']

    with pytest.raises(ValueError):
        recipes.complete_point(41, motion(key))

    with pytest.raises(ValueError):
        recipes.complete_point(42, motion('LAN_L5'))

    assert recipes.next_point()['point_id'] == key

    with pytest.raises(ValueError):
        recipes.mark_pending(42, 'LAN_L5')



def test_stop_preserves_last_progress_and_new_run_cannot_take_old_result():
    recipes, data = prepared()
    key = recipes.next_point()['point_id']
    recipes.mark_pending(42, key)
    recipes.end(42)
    assert not recipes.progress()['running']
    assert recipes.progress()['current_point'] == key
    assert recipes._results[key].motion_status == SequenceStatus.INCOMPLETE

    with pytest.raises(RuntimeError):
        recipes.next_point()

    recipes.begin(data['recipe_id'], 43)
    assert recipes.progress(42)['total_points'] == 0
    assert recipes.next_point()['point_id'] == key
    recipes.mark_pending(43, key)
    recipes.apply_judgments(43, judgment(key))
    assert recipes.progress()['pending_judgments'] == 1



def test_received_updates_do_not_change_running_order_or_progress():
    recipes, data = prepared()
    first = recipes.next_point()
    data['points'].reverse()
    data['recipe_version'] = 'updated'
    recipes.accept(data)
    assert recipes.next_point() == first
    assert recipes.snapshot()['recipe_version'] != 'updated'

    with pytest.raises(RuntimeError):
        recipes.begin(data['recipe_id'], 43)

    recipes.end(42)
    recipes.begin(data['recipe_id'], 43)
    assert recipes.next_point()['point_id'] == 'LAN_L5'



def test_completed_progress_remains_available_for_hmi_after_end():
    recipes, _ = prepared()

    while (point := recipes.next_point()) is not None:
        key = point['point_id']
        recipes.mark_pending(42, key)
        recipes.complete_point(42, motion(key))
        recipes.apply_judgments(42, judgment(key))
        recipes.mark_logs_saved(42, [key])

    recipes.end(42)
    assert recipes.progress(42)['progress_percent'] == 100
    assert len(recipes.inspection_results()) == 2
    assert recipes.completion().success
