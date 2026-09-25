"""실물 연결 없이 상태 분리·만료·조회 타임아웃·작업 종료 발행을 검증한다."""
import json
from types import SimpleNamespace as NS
from unittest.mock import Mock

import pytest

from cable_inspection.robot.node_robot import RobotNode
from cable_inspection.robot.m0609 import M0609Robot
from cable_inspection.gripper_tool.node_gripper_tool import GripperToolNode
from cable_inspection.hmi.interface import HmiInterface
from cable_inspection.sequence.main.data_models.system_state import SystemState
from cable_inspection.recipe.recipe import Recipe



def test_robot_snapshot_expiry_and_independent_connections():
    monitor = NS(status_stale_s=2.0, status_channels=dict.fromkeys([
        "task", "joint", "wrench_base", "robot_state_code", "motion_status", "tool_name", "tcp_name"]),
        status_cache={key: {"value": value, "time": 10.0, "error": ""} for key, value in {
            "task": [1.0]*6, "joint": [2.0]*6, "wrench_base": [3.,4.,0.,0.,0.,0.],
            "robot_state_code": 1, "motion_status": 2,
        }.items()})
    gripper = NS(status_stale_s=2.0, width_received_at=None, width_error="", measured_width_mm=None)
    node = NS(main=NS(controller=NS(backend=NS(
        robot=NS(status_snapshot=lambda now: RobotNode.status_snapshot(monitor, now)),
        gripper=NS(status_snapshot=lambda now: GripperToolNode.status_snapshot(gripper, now))))))
    fresh = HmiInterface.robot_status_snapshot(node, 11.0)
    assert fresh["robot_connected"] and not fresh["gripper_connected"]
    assert fresh["robot_motion"] == "MOVING"
    assert fresh["force_norm_n"] == 5.0
    expired = HmiInterface.robot_status_snapshot(node, 13.0)
    assert not expired["robot_connected"]
    assert expired["task"] is None and expired["robot_motion"] == ""
    json.dumps(expired, allow_nan=False)



def test_read_timeout_cancels_pending_request_without_blocking():
    future = Mock()
    future.done.return_value = False
    client = Mock()
    monitor = NS(status_timeout_s=1.0, status_channels={"task": {
        "future": future, "client": client, "started": 0., "next": 10.,
    }}, store_status=Mock())
    RobotNode.poll_status(monitor, 2.0)
    future.cancel.assert_called_once()
    client.remove_pending_request.assert_called_once_with(future)
    assert monitor.status_channels["task"]["future"] is None
    monitor.store_status.assert_called_once_with("task", error="조회 시간 초과")
    client.call_async.assert_not_called()



@pytest.mark.parametrize("values", [[0]*5, [0]*5+[float("nan")], [0]*5+[float("inf")]])
def test_invalid_vectors_are_not_published(values):
    with pytest.raises(ValueError):
        M0609Robot.status_vector(values)



def make_work_node():
    backend = NS(latest_sample=None)
    controller = NS(context=None, backend=backend, state=SystemState.SYSTEM_READY,
                    last_error="", run_id=1, last_summary={}, recipes=Recipe())

    return NS(main=NS(controller=controller, selected_recipe="R", worker=None, operation=""),
              control_mode="hmi", is_connected=lambda:True, _last_status=None, status_pub=Mock())



def test_idle_silent_active_periodic_and_final_state_published():
    node = make_work_node()
    HmiInterface.publish_status(node, force=False)
    HmiInterface.publish_status(node, force=False)
    assert node.status_pub.publish.call_count == 1
    node.main.controller.state = SystemState.RUNNING
    HmiInterface.publish_status(node, force=False)
    HmiInterface.publish_status(node, force=False)
    assert node.status_pub.publish.call_count == 3
    node.main.controller.state = SystemState.STOPPED
    HmiInterface.publish_status(node, force=False)
    HmiInterface.publish_status(node, force=False)
    assert node.status_pub.publish.call_count == 4
    final = json.loads(node.status_pub.publish.call_args.args[0].data)
    assert not final["work_active"] and final["run_state"] == "STOPPED"
    assert "robot_connected" not in final and "task" not in final
    HmiInterface.publish_status(node)  # SYNC는 대기 중에도 응답한다.
    assert node.status_pub.publish.call_count == 5



def test_work_uses_matching_point_sample_and_snapshot_criteria(monkeypatch):
    node = make_work_node()
    node.main.controller.state = SystemState.RUNNING
    node.main.controller.context = NS(recipe_id="R", job_id="1", resume_point="", current_sequence="PULL")
    node.main.controller.recipes.progress = lambda *args: {
        "total_points": 1, "recipe_version": "1", "execution_index": 0,
        "current_point": "P", "pending_judgments": 0, "progress_percent": 0,
        "point": {"pull_setting": {"force_limit_n": 15., "normal_displacement_limit_mm": 5., "max_distance_mm": 25.},
                  "grip_setting": {"hard_width_mm": 21.}},
    }
    node.main.controller.backend.latest_sample = {
        "point_id": "OLD", "monotonic_s": 99., "timestamp": "sample-time", "phase": "PULL",
        "measurement_kind": "PULL", "pull_force_n": 15.2, "pull_displacement_mm": 3.}
    monkeypatch.setattr("cable_inspection.hmi.interface.time.monotonic", lambda: 100.)
    HmiInterface.publish_status(node)
    payload = json.loads(node.status_pub.publish.call_args.args[0].data)
    assert payload["measurement"] is None
    assert payload["criteria"]["required_pull_force_n"] == 15.
    node.main.controller.backend.latest_sample["point_id"] = "P"
    HmiInterface.publish_status(node)
    payload = json.loads(node.status_pub.publish.call_args.args[0].data)
    assert payload["measurement"]["pull_force_n"] == 15.2
    assert payload["measurement"]["valid"]



def test_gripper_feedback_validity_and_expiry_do_not_depend_on_busy():
    from cable_inspection.gripper_tool.rg2 import RG2Gripper
    gripper = NS(status_stale_s=2.)
    RG2Gripper._gripper_state_callback(gripper, NS(position=[0.], effort=[1.]))
    stamp = gripper.width_received_at
    fresh = GripperToolNode.status_snapshot(gripper, stamp)['gripper_width_mm']
    assert fresh['valid'] and fresh['value'] > 0 and gripper.gripper_busy
    assert not GripperToolNode.status_snapshot(gripper, stamp+3.)['gripper_width_mm']['valid']
    RG2Gripper._gripper_state_callback(gripper, NS(position=[float('nan')], effort=[]))
    invalid = GripperToolNode.status_snapshot(gripper)['gripper_width_mm']
    assert not invalid['valid'] and invalid['value'] is None and invalid['error']
    RG2Gripper._gripper_state_callback(gripper, NS(position=[0.], effort=[]))
    assert GripperToolNode.status_snapshot(gripper)['gripper_width_mm']['valid']
    assert not gripper.gripper_busy



def test_robot_monitor_keeps_one_pending_request_and_runs_during_stop():
    future = Mock()
    future.done.return_value = False
    client = Mock()
    client.call_async.return_value = future
    channel = dict(client=client, future=None, request=object(), started=0., next=0., period=.2)
    monitor = NS(status_timeout_s=1., status_channels={'task':channel}, store_status=Mock(),
                 control_poll=Mock(side_effect=RuntimeError('STOP')))
    RobotNode.poll_status(monitor, 0.)
    RobotNode.poll_status(monitor, .5)
    assert client.call_async.call_count == 1
    monitor.control_poll.assert_not_called()
    future.done.return_value = True
    future.result.return_value = NS(success=False)
    RobotNode.poll_status(monitor, .6)
    monitor.store_status.assert_called_once_with('task', error='조회 실패')
