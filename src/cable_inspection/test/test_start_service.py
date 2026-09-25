from types import SimpleNamespace as NS
from unittest.mock import Mock
import pytest
from pathlib import Path
from cable_interfaces.srv import StartInspection
from cable_inspection.recipe.node_recipe import RecipeNode
from cable_inspection.recipe.recipe import Recipe
from cable_inspection.sequence.main.node_main import MainSequenceNode
from cable_inspection.hmi.interface import HmiInterface
from cable_inspection.sequence.main.data_models.system_state import SystemState



def setup():
    recipe = Recipe.load_json(Path(__file__).parents[1]/"cable_inspection/recipe/inspection/rcp_BMW_LWR_01.json")
    request = StartInspection.Request(request_id="request-1", recipe=RecipeNode.encode_message(recipe))
    main = NS(worker=None, operation="", selected_recipe="", closing=False,
        controller=NS(state=SystemState.SYSTEM_READY, context=None, backend=NS(),
            recipes=NS(decode_message=RecipeNode.decode_message, accept=Mock()),
            run=Mock(), snapshot_notify=Mock(), notify=Mock()), launch_operation=Mock())
    main.is_running = lambda: MainSequenceNode.is_running(main)
    main.start_inspection = lambda recipe, run_id: MainSequenceNode.start_inspection(main, recipe, run_id)
    node = NS(main=main, _start_requests={}, _request_id="", control_mode="hmi",
              is_connected=lambda:True, publish_status=Mock(), publish_log=Mock())

    return node, request



def test_duplicate_start_is_idempotent_and_changed_payload_rejected():
    node, request = setup()
    first = HmiInterface.receive_inspection_start(node, request, StartInspection.Response())
    assert first.accepted
    duplicate = HmiInterface.receive_inspection_start(node, request, StartInspection.Response())
    assert duplicate.accepted and duplicate.run_id == first.run_id
    node.main.launch_operation.assert_called_once()
    request.recipe.recipe_version = "changed"
    conflict = HmiInterface.receive_inspection_start(node, request, StartInspection.Response())
    assert not conflict.accepted
    node.main.launch_operation.assert_called_once()



def test_missing_heartbeat_or_busy_rejects_without_loading_or_launching():
    node, request = setup()
    node.is_connected = lambda: False
    assert not HmiInterface.receive_inspection_start(node, request, StartInspection.Response()).accepted
    node.is_connected = lambda: True
    node.main.controller.state = SystemState.RUNNING
    assert not HmiInterface.receive_inspection_start(node, request, StartInspection.Response()).accepted
    node.main.controller.recipes.accept.assert_not_called()
    node.main.launch_operation.assert_not_called()



def test_terminal_mode_rejects_hmi_start():
    node, request = setup()
    node.control_mode = "terminal"
    assert not HmiInterface.receive_inspection_start(node, request, StartInspection.Response()).accepted
    node.main.launch_operation.assert_not_called()



@pytest.mark.parametrize("case, code", [
    ("empty_id", "INVALID_REQUEST_ID"),
    ("long_id", "INVALID_REQUEST_ID"),
    ("recipe", "INVALID_RECIPE"),
    ("terminal", "CONTROL_MODE_MISMATCH"),
    ("heartbeat", "HEARTBEAT_MISSING"),
    ("context", "BUSY"),
    ("worker", "BUSY"),
    ("state", "NOT_READY"),
    ("disabled", "NO_ENABLED_POINTS"),
])
def test_specific_rejection_code_without_starting(case, code):
    node, request = setup()

    if case == "empty_id":
        request.request_id = "   "

    elif case == "long_id":
        request.request_id = "x" * 129

    elif case == "recipe":
        request.recipe.points[0].pull_setting.force_limit_n = -1.0

    elif case == "terminal":
        node.control_mode = "terminal"

    elif case == "heartbeat":
        node.is_connected = lambda: False

    elif case == "context":
        node.main.controller.context = object()

    elif case == "worker":
        node.main.worker = NS(is_alive=lambda: True)

    elif case == "state":
        node.main.controller.state = SystemState.PAUSED

    elif case == "disabled":
        for point in request.recipe.points:
            point.enabled = False

    response = HmiInterface.receive_inspection_start(node, request, StartInspection.Response())
    assert not response.accepted and response.code == code and response.run_id == 0
    node.main.launch_operation.assert_not_called()
    node.main.controller.recipes.accept.assert_not_called()



def test_duplicate_ack_survives_home_and_does_not_replace_home_status():
    node, request = setup()
    accepted = HmiInterface.receive_inspection_start(node, request, StartInspection.Response())
    node.main.operation, node._request_id = "HOME", ""
    node.is_connected = lambda: False
    again = HmiInterface.receive_inspection_start(node, request, StartInspection.Response())
    assert again.code == "ALREADY_ACCEPTED" and again.run_id == accepted.run_id
    assert node.main.operation == "HOME" and node._request_id == ""
    request.recipe.recipe_version = "changed"
    assert HmiInterface.receive_inspection_start(node, request, StartInspection.Response()).code == "REQUEST_ID_CONFLICT"
    node.main.launch_operation.assert_called_once()



@pytest.mark.parametrize("operation, busy, expected_id", [
    ("HOME", False, ""), ("HOME", True, "request-1"),
    ("INSPECTION", False, "request-1"),
])
def test_home_clears_only_current_request_when_worker_can_start(operation, busy, expected_id):
    node, _ = setup()
    node._request_id = "request-1"
    node._start_requests = {"request-1": ("recipe", 123)}
    node._log = Mock()

    if busy:
        node.main.worker = NS(is_alive=lambda: True)

    action = Mock(return_value=NS(success=True, code="DONE", message=""))

    if operation == "HOME":
        node.main.controller.request_home_return = action
        node.main.launch_operation = lambda action, operation="INSPECTION": MainSequenceNode.launch_operation(node.main, action, operation)
        node.main.execute_command = lambda name, args: MainSequenceNode.execute_command(node.main, name, args)
        HmiInterface.receive_command(node, NS(data='{"name":"HOME_RETURN"}'))

    else:
        MainSequenceNode.launch_operation(node.main, action, operation=operation)

    if not busy:
        node.main.worker.join(timeout=1)

    assert node._request_id == expected_id
    assert node._start_requests == {"request-1": ("recipe", 123)}
    assert action.call_count == (0 if busy else 1)



@pytest.mark.parametrize('state', [SystemState.STOPPED, SystemState.ERROR])
def test_terminal_start_accepts_stopped_or_error_without_forced_home(state):
    node, _ = setup()
    main = node.main
    main.controller.state = state
    main.select_recipe = Mock()
    MainSequenceNode.execute_command(main, 'START', {})
    main.select_recipe.assert_called_once()
    main.launch_operation.assert_called_once()
    assert main.controller.state == state  # 준비 절차의 상태 변경은 Worker가 수행한다.



def test_terminal_start_can_launch_from_ready():
    node, _ = setup()
    main = node.main
    main.selected_recipe = 'R'
    main.select_recipe = Mock()
    MainSequenceNode.execute_command(main, 'START', {})
    main.select_recipe.assert_called_once_with('R')
    main.launch_operation.assert_called_once()



def test_terminal_start_does_not_launch_while_previous_worker_is_alive():
    node, _ = setup()
    node.main.worker = NS(is_alive=lambda: True)
    node.main.select_recipe = Mock()

    with pytest.raises(ValueError, match='정리 중'):
        MainSequenceNode.execute_command(node.main, 'START', {})

    node.main.select_recipe.assert_not_called()
    node.main.launch_operation.assert_not_called()



@pytest.mark.parametrize('state', [SystemState.STOPPED, SystemState.ERROR])
def test_hmi_start_accepts_same_idle_states_as_terminal(state):
    node, request = setup()
    node.main.controller.state = state
    response = HmiInterface.receive_inspection_start(node, request, StartInspection.Response())
    assert response.accepted and response.code == 'ACCEPTED'
    node.main.launch_operation.assert_called_once()
