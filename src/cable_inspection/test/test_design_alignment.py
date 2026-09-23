"""설계 복원 경로의 실패 차단을 실물 서비스 없이 검증한다."""
from types import SimpleNamespace as NS
from unittest.mock import Mock
from dataclasses import replace
import json
from pathlib import Path

import pytest
from cable_inspection.hardware.robot import SequenceRobot, reverse_tool_axis
from cable_inspection.sequence.main_node import SequenceController, InspectionSequence, check_work_completion
from cable_inspection.data_models.models import (
    SequenceResult, SequenceStatus, JudgmentStatus, InspectionResult, PointRuntime, JobContext,
)
from cable_inspection.recipe.inspection_recipe import load_system_recipe, OperatingInspectionRecipe

ROOT = Path(__file__).parents[1]


@pytest.mark.parametrize("failed", ["robot", "relax", "escape", "access", "home"])
def test_home_stops_at_first_failed_step(failed):
    calls = []
    def step(name):
        calls.append(name)
        return SequenceResult(name != failed, name, name)
    backend = NS(system={"max_escape_distance_mm": 30},
        check_robot_operability=lambda: step("robot"), current_tcp=lambda: [0.] * 6,
        tcp_is_in_work_area=lambda _: True, relax_grip=lambda: step("relax"),
        safe_escape=lambda _: step("escape"), move_work_access_safe_pose=lambda: step("access"),
        move_safe_route_home=lambda: step("home"))
    result = SequenceController(backend).home_return()
    order = ["robot", "relax", "escape", "access", "home"]
    assert not result.success
    assert calls == order[:order.index(failed)+1]


@pytest.mark.parametrize("measured,success", [
    ({"width_mm": 25., "gripper_busy": False}, True),
    ({"width_mm": 20., "gripper_busy": False}, False),
    ({"width_mm": 25., "gripper_busy": True}, False),
])
def test_escape_requires_open_width_and_idle(measured, success):
    robot=NS(system={"relax_width_mm":25.,"relax_force_n":10.},
             config=NS(width_tolerance_mm=2.5), grip=Mock(),
             wait_gripper_idle=lambda: measured, ok=SequenceRobot.ok)
    if success:
        assert SequenceRobot.relax_grip(robot).success
    else:
        with pytest.raises(RuntimeError, match="Open"):
            SequenceRobot.relax_grip(robot)
    robot.grip.assert_called_once_with(25., 10., opening=True)


def escape_robot(tcp=None, stop_reason="TARGET_REACHED"):
    # 경계 밖인지 조회할 필요 없이 후퇴 목표 도달로 완료한다.
    return NS(system={"tool_approach_axis":[0.,0.,1.]},
              get_tcp=lambda: tcp or [0.,0.,5.,0.,0.,0.],
              move_linear=Mock(return_value={"stop_reason":stop_reason}),
              ok=SequenceRobot.ok)


@pytest.mark.parametrize("tcp,target", [
    ([0.,0.,5.,0.,0.,0.], [0.,0.,-25.,0.,0.,0.]),
    ([100.,0.,500.,0.,90.,0.], [70.,0.,500.,0.,90.,0.]),
    ([100.,0.,500.,0.,180.,0.], [100.,0.,530.,0.,180.,0.]),
])
def test_escape_moves_30mm_opposite_current_tool_pose(tcp,target):
    robot=escape_robot(tcp)
    result=SequenceRobot.safe_escape(robot,30.)
    assert result.data["distance_mm"] == 30.
    assert robot.move_linear.call_args.args[0] == pytest.approx(target)


@pytest.mark.parametrize("distance", [0.,-1.,30.01,float('nan'),float('inf'),True,None])
def test_invalid_escape_distance_never_moves(distance):
    robot=escape_robot()
    with pytest.raises(ValueError,match="거리"):
        SequenceRobot.safe_escape(robot,distance)
    robot.move_linear.assert_not_called()


@pytest.mark.parametrize("reason", ["TARGET_NOT_REACHED", "ENTRY_TIMEOUT", None])
def test_escape_not_reached_does_not_report_success(reason):
    robot=escape_robot(stop_reason=reason)
    with pytest.raises(RuntimeError,match="도달"):
        SequenceRobot.safe_escape(robot,30.)


def test_escape_motion_exception_propagates():
    robot=escape_robot()
    robot.move_linear.side_effect=TimeoutError("motion timeout")
    with pytest.raises(TimeoutError):
        SequenceRobot.safe_escape(robot,30.)


@pytest.mark.parametrize("bad_result", ["TARGET_NOT_REACHED", "ENTRY_TIMEOUT", None])
def test_entry_not_reached_prevents_soft_grip_and_pull(bad_result):
    hardware=NS(configure_point=Mock(),move_joint=Mock(),grip=Mock(),
                move_linear=Mock(return_value={"stop_reason":bad_result}),relative=Mock())
    point=NS(ready_pose=object(),entry_pose=NS(task=[0.]*6),
             grip_setting={"soft_open_width_mm":25.,"soft_force_n":10.})
    with pytest.raises(RuntimeError,match="Entry"):
        InspectionSequence(hardware).run_point(point)
    assert hardware.grip.call_count == 1  # 접근 전 Open만 실행
    hardware.relative.assert_not_called()


@pytest.mark.parametrize("error_kind", ["system", "judgment", "motion", "adaptive", "pull", "pending"])
def test_error_or_incomplete_point_never_completes_job(error_kind):
    point=PointRuntime("P",motion_status=SequenceStatus.SUCCESS,
        adaptive_grip_status=SequenceStatus.SUCCESS,pull_status=SequenceStatus.SUCCESS,
        result=InspectionResult.PASS,judgment_status=JudgmentStatus.COMPLETED,log_saved=True)
    if error_kind == "system": point.result=InspectionResult.SYSTEM_ERROR
    elif error_kind == "judgment": point.judgment_status=JudgmentStatus.ERROR
    elif error_kind == "pending": point.judgment_status=JudgmentStatus.PENDING
    else: setattr(point, error_kind+('_grip_status' if error_kind=='adaptive' else '_status'), SequenceStatus.INCOMPLETE)
    context=JobContext("R",["P"],current_point_index=1,point_runtime={"P":point})
    assert not check_work_completion(context).success


def test_home_route_uses_only_given_waypoints_and_aborts_on_failure():
    home={"task":[0.]*6,"joint":[0.]*6}
    via={"task":[1.]*6,"joint":[1.]*6}
    robot=NS(system={"home_pose":home,"safe_home_route":[via,home]},
             move_joint=Mock(side_effect=RuntimeError("waypoint failed")),move_home_pose=Mock())
    with pytest.raises(RuntimeError,match="waypoint"):
        SequenceRobot.move_safe_route_home(robot)
    robot.move_home_pose.assert_not_called()


@pytest.mark.parametrize("field", ["tool_approach_axis","safe_home_route"])
def test_missing_escape_configuration_is_rejected(tmp_path,field):
    data=json.loads((ROOT/'config/system_recipe.json').read_text())
    data['safe_home_route']=[data['home_pose']]
    data['tool_approach_axis']=[0.,0.,1.]
    data[field]=None
    path=tmp_path/'system.json'; path.write_text(json.dumps(data))
    with pytest.raises(ValueError,match=field): load_system_recipe(path)


@pytest.mark.parametrize("group,field,value",[
    ("pull_setting","max_distance_mm",25.01),
    ("pull_setting","timeout_s",10.01),
    ("entry_setting","timeout_s",10.01),
])
def test_recipe_rejects_motion_guard_above_design_limit(group,field,value):
    recipe=OperatingInspectionRecipe.load_json(ROOT/'cable_inspection/recipe/inspection/lan_inspection_recipe.json')
    point=next(iter(recipe.points.values()))
    point=replace(point,**{group:{**getattr(point,group),field:value}})
    with pytest.raises(ValueError): point.validate()
