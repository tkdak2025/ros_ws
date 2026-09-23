from types import SimpleNamespace as NS
from unittest.mock import Mock
import pytest
from pathlib import Path
from cable_interfaces.srv import StartInspection
from cable_inspection.recipe.inspection_recipe import to_message
from cable_inspection.recipe.inspection_recipe import OperatingInspectionRecipe
from cable_inspection.sequence.main_node import MainSequenceNode
from cable_inspection.data_models.models import SystemState


def setup():
    recipe = OperatingInspectionRecipe.load_json(Path(__file__).parents[1]/"cable_inspection/recipe/inspection/rcp_BMW_LWR_01.json")
    request = StartInspection.Request(request_id="request-1", recipe=to_message(recipe))
    node = NS(_start_requests={}, control_mode="hmi", hmi_available=lambda: True, worker=None,
        controller=NS(state=SystemState.SYSTEM_READY, context=None, backend=NS(accept_inspection_recipe=Mock()), run=Mock()),
        _publish_execution_snapshot=Mock(), _launch=Mock())
    return node, request


def test_duplicate_start_is_idempotent_and_changed_payload_rejected():
    node, request = setup()
    first = MainSequenceNode._start_inspection(node, request, StartInspection.Response())
    assert first.accepted
    duplicate = MainSequenceNode._start_inspection(node, request, StartInspection.Response())
    assert duplicate.accepted and duplicate.run_id == first.run_id
    node._launch.assert_called_once()
    request.recipe.recipe_version = "changed"
    conflict = MainSequenceNode._start_inspection(node, request, StartInspection.Response())
    assert not conflict.accepted
    node._launch.assert_called_once()


def test_missing_heartbeat_or_busy_rejects_without_loading_or_launching():
    node, request = setup()
    node.hmi_available = lambda: False
    assert not MainSequenceNode._start_inspection(node, request, StartInspection.Response()).accepted
    node.hmi_available = lambda: True
    node.controller.state = SystemState.RUNNING
    assert not MainSequenceNode._start_inspection(node, request, StartInspection.Response()).accepted
    node.controller.backend.accept_inspection_recipe.assert_not_called()
    node._launch.assert_not_called()


def test_terminal_mode_rejects_hmi_start():
    node, request = setup()
    node.control_mode = "terminal"
    assert not MainSequenceNode._start_inspection(node, request, StartInspection.Response()).accepted
    node._launch.assert_not_called()


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
    if case == "empty_id": request.request_id = "   "
    elif case == "long_id": request.request_id = "x" * 129
    elif case == "recipe": request.recipe.points[0].pull_setting.force_limit_n = -1.0
    elif case == "terminal": node.control_mode = "terminal"
    elif case == "heartbeat": node.hmi_available = lambda: False
    elif case == "context": node.controller.context = object()
    elif case == "worker": node.worker = NS(is_alive=lambda: True)
    elif case == "state": node.controller.state = SystemState.STOPPED
    elif case == "disabled":
        for point in request.recipe.points: point.enabled = False
    response = MainSequenceNode._start_inspection(node, request, StartInspection.Response())
    assert not response.accepted and response.code == code and response.run_id == 0
    node._launch.assert_not_called()
    node.controller.backend.accept_inspection_recipe.assert_not_called()


def test_duplicate_ack_survives_home_and_does_not_replace_home_status():
    node, request = setup()
    accepted = MainSequenceNode._start_inspection(node, request, StartInspection.Response())
    node._operation, node._request_id = "HOME", ""
    node.hmi_available = lambda: False
    again = MainSequenceNode._start_inspection(node, request, StartInspection.Response())
    assert again.code == "ALREADY_ACCEPTED" and again.run_id == accepted.run_id
    assert node._operation == "HOME" and node._request_id == ""
    request.recipe.recipe_version = "changed"
    assert MainSequenceNode._start_inspection(node, request, StartInspection.Response()).code == "REQUEST_ID_CONFLICT"
    node._launch.assert_called_once()


@pytest.mark.parametrize("operation, busy, expected_id", [
    ("HOME", False, ""), ("HOME", True, "request-1"),
    ("INSPECTION", False, "request-1"),
])
def test_home_clears_only_current_request_when_worker_can_start(operation, busy, expected_id):
    node, _ = setup()
    node._request_id = "request-1"
    node._start_requests = {"request-1": ("recipe", 123)}
    node._log = Mock()
    if busy: node.worker = NS(is_alive=lambda: True)
    action = Mock(return_value=NS(success=True, code="DONE", message=""))
    MainSequenceNode._launch(node, action, operation=operation)
    if not busy: node.worker.join(timeout=1)
    assert node._request_id == expected_id
    assert node._start_requests == {"request-1": ("recipe", 123)}
    assert action.call_count == (0 if busy else 1)
