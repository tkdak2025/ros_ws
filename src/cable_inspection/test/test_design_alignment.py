"""설계 복원 경로의 실패 차단을 실물 서비스 없이 검증한다."""
from types import SimpleNamespace as NS
from unittest.mock import Mock
from dataclasses import replace
import json
from pathlib import Path

import pytest
from cable_inspection.sequence.common.geometry import reverse_tool_axis
from cable_inspection.sequence.main.seq_main import MainSequence
from cable_inspection.sequence.home_return.seq_home_return import HomeReturnSequence
from cable_inspection.sequence.common.data_models.sequence_result import SequenceResult
from cable_inspection.recipe.recipe import Recipe

ROOT = Path(__file__).parents[1]



def home_for(robot):
    robot.robot = NS(**{name: getattr(robot, name) for name in ("get_tcp", "read_joints", "mode") if hasattr(robot, name)})

    return HomeReturnSequence(robot, checkpoint=lambda _: None, poll_control=lambda: None, system=robot.system)



class RecordedHomeReturnSequence(HomeReturnSequence):
    """Home 순서 테스트에서 장비 호출만 기록한다."""



    def current_tcp(self):
        return self.backend.current_tcp()



    def tcp_is_in_work_area(self, tcp):
        return self.backend.tcp_is_in_work_area(tcp)



    # 기능: 단계별 실패 시험의 시작 위치를 Access 외 작업영역 내부로 고정한다.
    #     tcp: 기록용 현재 TCP. 반환: False.
    def tcp_is_at_work_access(self, tcp):
        return False



    def relax_grip(self):
        return self.backend.relax_grip()



    def safe_escape(self, distance):
        return self.backend.safe_escape(distance)



    def move_safe_route_home(self):
        return self.backend.move_safe_route_home()



@pytest.mark.parametrize("failed", ["robot", "relax", "escape", "access", "home"])
def test_home_stops_at_first_failed_step(failed):
    calls = []



    def step(name):
        calls.append(name)
        return SequenceResult(name != failed, name, name)



    backend = NS(system={"max_escape_distance_mm": 30, "work_Access_safe_pose": {"task": [0.] * 6, "joint": [0.] * 6}},
        check_robot_operability=lambda: step("robot"), current_tcp=lambda: [0.] * 6,
        tcp_is_in_work_area=lambda _: True, relax_grip=lambda: step("relax"),
        safe_escape=lambda _: step("escape"), move_joint=lambda pose: access_step(),
        move_safe_route_home=lambda: step("home"))



    def access_step():
        result = step("access")

        if not result.success:
            raise RuntimeError("access failed")



    controller = MainSequence(backend, inspection=NS(), home_return_sequence=RecordedHomeReturnSequence)
    controller.check_devices = backend.check_robot_operability
    controller.system = backend.system

    if failed == "access":
        with pytest.raises(RuntimeError, match="access failed"):
            controller.home_return()

        assert calls == ["robot", "relax", "escape", "access"]

        return

    result = controller.home_return()
    order = ["robot", "relax", "escape", "access", "home"]
    assert not result.success
    assert calls == order[:order.index(failed)+1]



def test_home_sequence_uses_shared_runtime_without_backend_home_methods():
    """실제 #02가 raw 계측·모션 인터페이스만으로 복귀 순서를 완성한다."""
    events, checkpoints = [], []
    home_pose = {"task": [0.0] * 6, "joint": [0.0] * 6}
    system = {
        "work_area": {"x_min_mm": -10.0, "x_max_mm": 10.0,
                      "y_min_mm": -10.0, "y_max_mm": 10.0,
                      "z_min_mm": 0.0, "z_max_mm": 20.0},
        "relax_width_mm": 25.0, "relax_force_n": 10.0,
        "max_escape_distance_mm": 30.0, "tool_approach_axis": [0.0, 0.0, 1.0],
        "home_pose": home_pose, "safe_home_route": [home_pose],
        "work_Access_safe_pose": home_pose,
        "home_joint_tolerance_deg": 0.1,
    }



    def grip(width, force):
        events.append(("grip", width, True))
        return {"measured": {"width_mm": width}}



    def linear(target):
        events.append(("escape", target))
        return {"stop_reason": "TARGET_REACHED"}



    def access(pose):
        events.append(("access",))
        return SequenceResult(True, "WORK_ACCESS_REACHED", "")



    def joint(pose):
        events.append(("access",) if len(events) == 2 else ("home", pose.joint))



    backend = NS(
        system=system, mode="real", config=NS(width_tolerance_mm=2.5,
            position_tolerance_mm=0.5, orientation_tolerance_deg=1.0), phase="",
        check_robot_operability=lambda: SequenceResult(True, "ROBOT_OPERABLE", ""),
        get_tcp=lambda: [0.0, 0.0, 10.0, 0.0, 0.0, 0.0],
        open_gripper=grip, move_linear=linear,
        move_joint=joint, read_joints=lambda: [0.0] * 6,
    )
    backend.robot = NS(get_tcp=backend.get_tcp, read_joints=backend.read_joints, mode=backend.mode)
    result = HomeReturnSequence(backend, checkpoints.append, lambda: None, backend.system).run()
    assert result.success and result.data["route"] == "WORK_AREA_ESCAPE"
    assert events == [
        ("grip", 25.0, True),
        ("escape", [0.0, 0.0, -20.0, 0.0, 0.0, 0.0]),
        ("access",), ("home", [0.0] * 6),
    ]
    assert checkpoints == ["GRIP_RELAXED", "SAFE_ESCAPE_DONE", "WORK_ACCESS_REACHED", "HOME_REACHED"]



@pytest.mark.parametrize("measured,success", [
    ({"width_mm": 25., "gripper_busy": False}, True),
    ({"width_mm": 20., "gripper_busy": False}, False),
    ({"width_mm": 25., "gripper_busy": True}, True),
])
def test_escape_requires_open_width_without_busy_gate(measured, success):
    robot=NS(system={"relax_width_mm":25.,"relax_force_n":10.},
             config=NS(width_tolerance_mm=2.5), open_gripper=Mock(return_value={"measured":measured}),
)

    if success:
        assert home_for(robot).relax_grip().success

    else:
        with pytest.raises(RuntimeError, match="Open"):
            home_for(robot).relax_grip()

    robot.open_gripper.assert_called_once_with(25., 10.)



def escape_robot(tcp=None, stop_reason="TARGET_REACHED"):
    # 경계 밖인지 조회할 필요 없이 후퇴 목표 도달로 완료한다.
    return NS(system={"tool_approach_axis":[0.,0.,1.]},
              get_tcp=lambda: tcp or [0.,0.,5.,0.,0.,0.],
              move_linear=Mock(return_value={"stop_reason":stop_reason}),
 )



@pytest.mark.parametrize("tcp,target", [
    ([0.,0.,5.,0.,0.,0.], [0.,0.,-25.,0.,0.,0.]),
    ([100.,0.,500.,0.,90.,0.], [70.,0.,500.,0.,90.,0.]),
    ([100.,0.,500.,0.,180.,0.], [100.,0.,530.,0.,180.,0.]),
])
def test_escape_moves_30mm_opposite_current_tool_pose(tcp,target):
    robot=escape_robot(tcp)
    result=home_for(robot).safe_escape(30.)
    assert result.data["distance_mm"] == 30.
    assert robot.move_linear.call_args.args[0] == pytest.approx(target)



@pytest.mark.parametrize("distance", [0.,-1.,30.01,float('nan'),float('inf'),True,None])
def test_invalid_escape_distance_never_moves(distance):
    robot=escape_robot()

    with pytest.raises(ValueError,match="거리"):
        home_for(robot).safe_escape(distance)

    robot.move_linear.assert_not_called()



@pytest.mark.parametrize("reason", ["TARGET_NOT_REACHED", "ENTRY_TIMEOUT", None])
def test_escape_not_reached_does_not_report_success(reason):
    robot=escape_robot(stop_reason=reason)

    with pytest.raises(RuntimeError,match="도달"):
        home_for(robot).safe_escape(30.)



def test_escape_motion_exception_propagates():
    robot=escape_robot()
    robot.move_linear.side_effect=TimeoutError("motion timeout")

    with pytest.raises(TimeoutError):
        home_for(robot).safe_escape(30.)






def test_home_route_uses_only_given_waypoints_and_aborts_on_failure():
    home={"task":[0.]*6,"joint":[0.]*6}
    via={"task":[1.]*6,"joint":[1.]*6}
    robot=NS(system={"home_pose":home,"safe_home_route":[via,home]},
             move_joint=Mock(side_effect=RuntimeError("waypoint failed")),move_home_pose=Mock())

    with pytest.raises(RuntimeError,match="waypoint"):
        home_for(robot).move_safe_route_home()

    robot.move_joint.assert_called_once()



@pytest.mark.parametrize("field", ["tool_approach_axis","safe_home_route"])
def test_missing_escape_configuration_is_rejected(tmp_path,field):
    data=json.loads((ROOT/'config/system_recipe.json').read_text())
    data['safe_home_route']=[data['home_pose']]
    data['tool_approach_axis']=[0.,0.,1.]
    data[field]=None
    path=tmp_path/'system.json'
    path.write_text(json.dumps(data))

    with pytest.raises(ValueError,match=field):
        Recipe(system_path=path).system_recipe()



@pytest.mark.parametrize("group,field,value",[
    ("pull_setting","max_distance_mm",25.01),
    ("pull_setting","timeout_s",10.01),
    ("entry_setting","timeout_s",10.01),
])
def test_recipe_accepts_pr9_motion_guard_values(group,field,value):
    recipe=Recipe.load_json(ROOT/'cable_inspection/recipe/inspection/lan_inspection_recipe.json')
    recipe["points"][0][group][field] = value
    Recipe.validate(recipe)
