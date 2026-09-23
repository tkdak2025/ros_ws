"""실물 연결 없이 상태 분리·만료·조회 타임아웃·작업 종료 발행을 검증한다."""
import json
from types import SimpleNamespace as NS
from unittest.mock import Mock

import pytest

from cable_inspection.diagnostics.robot_state_node import RobotStateNode, vector
from cable_inspection.sequence.main_node import MainSequenceNode
from cable_inspection.data_models.models import SystemState


def test_robot_snapshot_expiry_and_independent_connections():
    monitor = NS(stale=2.0, channels=dict.fromkeys([
        "task", "joint", "wrench_base", "robot_state_code", "motion_status", "tool_name", "tcp_name"]),
        cache={key: {"value": value, "time": 10.0, "error": ""} for key, value in {
            "task": [1.0]*6, "joint": [2.0]*6, "wrench_base": [3.,4.,0.,0.,0.,0.],
            "robot_state_code": 1, "motion_status": 2,
        }.items()})
    fresh = RobotStateNode._snapshot(monitor, 11.0)
    assert fresh["robot_connected"] and not fresh["gripper_connected"]
    assert fresh["robot_motion"] == "MOVING"
    assert fresh["force_norm_n"] == 5.0
    expired = RobotStateNode._snapshot(monitor, 13.0)
    assert not expired["robot_connected"]
    assert expired["task"] is None and expired["robot_motion"] == ""
    json.dumps(expired, allow_nan=False)


def test_read_timeout_cancels_pending_request_without_blocking():
    future = Mock()
    future.done.return_value = False
    client = Mock()
    monitor = NS(timeout=1.0, channels={"task": {
        "future": future, "client": client, "started": 0., "next": 10.,
    }}, _store=Mock())
    RobotStateNode._poll(monitor, 2.0)
    future.cancel.assert_called_once()
    client.remove_pending_request.assert_called_once_with(future)
    assert monitor.channels["task"]["future"] is None
    monitor._store.assert_called_once_with("task", error="조회 시간 초과")
    client.call_async.assert_not_called()


@pytest.mark.parametrize("values", [[0]*5, [0]*5+[float("nan")], [0]*5+[float("inf")]])
def test_invalid_vectors_are_not_published(values):
    with pytest.raises(ValueError):
        vector(values)


def make_work_node():
    backend = NS(recipe_paths={"R": "unused"}, latest_sample=None)
    controller = NS(context=None, backend=backend, state=SystemState.SYSTEM_READY,
                    last_error="", run_id=1, last_summary={})
    return NS(controller=controller, control_mode="hmi", hmi_available=lambda: True,
              selected_recipe="R", worker=None, _last_status=None, status_pub=Mock())


def test_idle_silent_active_periodic_and_final_state_published():
    node = make_work_node()
    MainSequenceNode._publish_status(node, force=False)
    MainSequenceNode._publish_status(node, force=False)
    assert node.status_pub.publish.call_count == 1
    node.controller.state = SystemState.RUNNING
    MainSequenceNode._publish_status(node, force=False)
    MainSequenceNode._publish_status(node, force=False)
    assert node.status_pub.publish.call_count == 3
    node.controller.state = SystemState.STOPPED
    MainSequenceNode._publish_status(node, force=False)
    MainSequenceNode._publish_status(node, force=False)
    assert node.status_pub.publish.call_count == 4
    final = json.loads(node.status_pub.publish.call_args.args[0].data)
    assert not final["work_active"] and final["run_state"] == "STOPPED"
    assert "robot_connected" not in final and "task" not in final
    MainSequenceNode._publish_status(node)  # SYNC는 대기 중에도 응답한다.
    assert node.status_pub.publish.call_count == 5


def test_work_uses_matching_point_sample_and_snapshot_criteria(monkeypatch):
    node = make_work_node()
    node.controller.state = SystemState.RUNNING
    node.controller.context = NS(enabled_point_ids=["P"], recipe_id="R", job_id="1",
        recipe_snapshot={"points": {"P": {
            "pull_setting": {"force_limit_n": 15., "normal_displacement_limit_mm": 5., "max_distance_mm": 25.},
            "grip_setting": {"hard_width_mm": 21.}}}},
        current_point_index=0, resume_point="", current_point_id="P", current_sequence="PULL",
        pending_judgments=[])
    node.controller.backend.latest_sample = {
        "point_id": "OLD", "monotonic_s": 99., "timestamp": "sample-time", "phase": "PULL",
        "measurement_kind": "PULL", "pull_force_n": 15.2, "pull_displacement_mm": 3.}
    monkeypatch.setattr("cable_inspection.sequence.main_node.time.monotonic", lambda: 100.)
    MainSequenceNode._publish_status(node)
    payload = json.loads(node.status_pub.publish.call_args.args[0].data)
    assert payload["measurement"] is None
    assert payload["criteria"]["required_pull_force_n"] == 15.
    node.controller.backend.latest_sample["point_id"] = "P"
    MainSequenceNode._publish_status(node)
    payload = json.loads(node.status_pub.publish.call_args.args[0].data)
    assert payload["measurement"]["pull_force_n"] == 15.2
    assert payload["measurement"]["valid"]
