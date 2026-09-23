"""실제 검사포인트 반복 순서를 검증한다."""

from types import SimpleNamespace

from cable_inspection.data_models.models import (
    InspectionResult,
    JudgmentStatus,
)
from cable_inspection.sequence.main_node import InspectionSequence
from cable_inspection.sequence.inspection_cli import _complete_results


class HardwareDouble:
    def __init__(self):
        self.calls = []
        self.phase = ""

    def configure_point(self, point):
        self.calls.append(("configure", point.point_id))

    def move_joint(self, pose, allow_incomplete=False):
        self.calls.append(("joint", pose.name, allow_incomplete))
        return {"pose": pose.name}

    def wait_gripper_idle(self):
        return {"width_mm": 22.0, "gripper_busy": False}

    def grip(self, width, force, opening=False, wait_for_completion=False):
        self.calls.append(("grip", width, force, opening, wait_for_completion))
        return {"measured": {"width_mm": 16.0, "timestamp": "now"}}

    def relative(self, direction, distance, entry_guard=False, pull_guard=False):
        self.calls.append(("relative", direction, distance, entry_guard, pull_guard))
        if pull_guard:
            return {
                "stop_reason": "PULL_FORCE_LIMIT",
                "peak_pull_force_n": 15.2,
                "pull_displacement_mm": 4.0,
                "pull_width_mm": 16.5,
            }
        return {"stop_reason": "ENTRY_DISTANCE_REACHED",
                "entry_displacement_mm": 5.0}

    def move_linear(self, task):
        self.calls.append(("linear", task))
        return {"task": task}


class Point:
    def __init__(self, point_id):
        self.point_id = point_id
        self.point_name = point_id
        self.enabled = True
        self.ready_pose = SimpleNamespace(name=f"{point_id}_ready")
        self.entry_pose = SimpleNamespace(
            name=f"{point_id}_entry", task=[point_id], joint=[point_id],
        )
        self.grip_setting = {
            "soft_close_width_mm": 22.0, "soft_open_width_mm": 25.0,
            "hard_width_mm": 16.0, "soft_force_n": 10.0,
            "hard_force_n": 20.0,
        }
        self.entry_setting = {"max_distance_mm": 5.0}
        self.pull_setting = {
            "max_distance_mm": 25.0,
            "force_limit_n": 15.0,
            "normal_displacement_limit_mm": 5.0,
        }

    def normalized_entry_direction(self):
        return [0.0, -1.0, 0.0]


def test_recipe_iterates_point_transition_adaptive_pull_and_return():
    hardware = HardwareDouble()
    recipe = SimpleNamespace(
        points={"L5": Point("L5"), "L2": Point("L2")},
        execution_order=["L2", "L5"],
        recipe_id="LAN",
        recipe_version="1.0",
        connector_type="RJ45_LAN",
    )
    requests = []

    results = InspectionSequence(
        hardware, submit_judgment=requests.append, run_id=7,
    ).run(recipe)

    assert list(results) == ["L2", "L5"]
    assert all(result.judgment_status == JudgmentStatus.PENDING
               for result in results.values())
    assert all(result.pull_displacement_mm == 4.0 for result in results.values())
    assert [request.point_id for request in requests] == ["L2", "L5"]
    assert all(request.run_id == 7 for request in requests)
    assert all(request.soft_width_mm == 22.0 for request in requests)
    assert all(request.pull_width_mm == 16.5 for request in requests)
    assert results["L2"].pull_inspection["pull"]["width_delta_mm"] == -5.5

    judgment_results = {
        point_id: {
            "judgment_status": "COMPLETED",
            "sequence_status": "SUCCESS",
            "result": "PASS",
            "reason": "판정 완료",
        }
        for point_id in results
    }
    completed = _complete_results(results, judgment_results)
    assert all(result.result == InspectionResult.PASS
               for result in completed.values())
    assert all(result.reason == "판정 완료" for result in completed.values())
    for point_id in ("L2", "L5"):
        start = 11 * (0 if point_id == "L2" else 1)
        assert hardware.calls[start:start + 10] == [
            ("configure", point_id),
            ("grip", 25.0, 10.0, True, False),
            ("joint", f"{point_id}_ready", False),
            ("joint", f"{point_id}_entry", True),
            ("grip", 22.0, 10.0, False, False),
            ("relative", [0.0, -1.0, 0.0], 5.0, True, False),
            ("grip", 16.0, 20.0, False, True),
            ("relative", [-0.0, 1.0, -0.0], 25.0, False, True),
            ("grip", 25.0, 10.0, True, False),
            ("linear", [point_id]),
        ]
        assert hardware.calls[start + 10][0] == "joint"


def test_motion_error_stops_and_submits_system_error_request():
    import pytest
    from cable_inspection.sequence.judgment_node import judge_pull
    class BrokenHardware(HardwareDouble):
        def move_joint(self, pose, allow_incomplete=False):
            raise RuntimeError('motion service failed')

        def safe_abort(self):
            self.calls.append(('abort',))

    hardware = BrokenHardware()
    recipe = SimpleNamespace(points={'L2': Point('L2')}, execution_order=['L2'],
                             recipe_id='LAN', recipe_version='1', connector_type='LAN')
    requests = []
    with pytest.raises(RuntimeError, match='motion service failed'):
        InspectionSequence(hardware, submit_judgment=requests.append).run(recipe)
    assert hardware.calls[-1] == ('abort',)
    assert len(requests) == 1
    request = requests[0]
    assert 'motion service failed' in request.error_reason
    result = judge_pull(soft_width_mm=22.0, pull_width_mm=16.5, termination=request.termination_reason,
                        peak_force_n=request.peak_pull_force_n,
                        displacement_mm=request.pull_displacement_mm,
                        required_force_n=request.required_force_n)
    assert result.result == InspectionResult.SYSTEM_ERROR


def test_hard_grip_waits_until_busy_clears_even_within_width_tolerance():
    from cable_inspection.hardware.robot import HardwareRobot
    samples = iter([
        {'width_mm': 22.0, 'gripper_busy': False},
        {'width_mm': 18.2, 'gripper_busy': True},
        {'width_mm': 17.0, 'gripper_busy': True},
        {'width_mm': 16.2, 'gripper_busy': False},
    ])
    robot = SimpleNamespace(
        sample=lambda: next(samples), _set_gripper=lambda command: None,
        config=SimpleNamespace(width_tolerance_mm=2.5, gripper_timeout_s=1.0,
                               sample_period_s=0.0),
    )
    result = HardwareRobot.grip(robot, 16.0, 20.0, wait_for_completion=True)
    assert result['measured']['gripper_busy'] is False
    assert result['measured']['width_mm'] == 16.2


import pytest


@pytest.mark.parametrize("guard, timeout, expected", [
    ("pull", False, "PULL_FORCE_LIMIT"),
    ("pull", True, "PULL_TIMEOUT"),
    ("entry", False, "ENTRY_FORCE_LIMIT"),
    ("entry", True, "ENTRY_TIMEOUT"),
])
def test_peak_includes_deceleration_samples(guard, timeout, expected):
    from cable_inspection.hardware.robot import HardwareRobot, RobotRuntimeConfig
    from unittest.mock import Mock
    config = RobotRuntimeConfig(sample_period_s=0.0)
    config.pull_force_limit_n = config.entry_force_limit_n = 100.0 if timeout else 15.0
    config.pull_timeout_s = config.entry_timeout_s = 0.0 if timeout else 10.0
    samples = iter([
        {"tcp": [float(i), 0., 0., 0., 0., 0.],
         "wrench_base": [force, 0., 0., 0., 0., 0.], "pull_force_n": force}
        for i, force in enumerate([16., 25., 17.])
    ])
    statuses = iter(([1] if timeout else []) + [1, 0])
    robot = SimpleNamespace(config=config, sample=lambda: next(samples),
                            controlled_stop=Mock(), check_client=object(),
                            _call=lambda *_: SimpleNamespace(status=next(statuses)))
    robot._wait_idle = lambda **kw: HardwareRobot._wait_idle(robot, **kw)
    before = {"tcp": [0.] * 6, "wrench_base": [0.] * 6}
    result = HardwareRobot._monitor(robot, [100., 0., 0., 0., 0., 0.], before,
                                    pull_guard=guard == "pull", entry_guard=guard == "entry")
    assert result["stop_reason"] == expected
    assert result["peak_force_delta_n"] == 25.0
    assert result["peak_pull_force_n"] == (25.0 if guard == "pull" else None)
    robot.controlled_stop.assert_called_once()


@pytest.mark.parametrize("mode", ["real", "virtual"])
def test_connect_validates_mode_and_idle_before_virtual_settings(mode):
    from cable_inspection.hardware.robot import HardwareRobot, RobotRuntimeConfig
    events = []
    config = RobotRuntimeConfig()
    def client(name):
        return SimpleNamespace(srv_name=name, wait_for_service=lambda **_: True)
    def call(service, request):
        if service.srv_name == "motion":
            events.append("idle")
            return SimpleNamespace(status=0)
        events.append("tcp_tool")
        return SimpleNamespace(info=config.tcp_name if "tcp" in service.srv_name else config.tool_name)
    robot = SimpleNamespace(
        mode=mode, config=config, SERVICE_TIMEOUT_S=1., SERVICE_ROOT="/robot",
        system_client=client("system"), check_client=client("motion"),
        node=SimpleNamespace(create_client=lambda _, name: client(name), destroy_client=lambda _: None),
        _check_robot_mode=lambda: events.append("mode"), _call=call,
        wait_for_services=lambda: events.append("settings"), sample=lambda: events.append("sample"))
    HardwareRobot.connect(robot)
    expected = (["mode", "idle", "settings", "tcp_tool", "tcp_tool", "sample"]
                if mode == "virtual" else ["mode", "idle", "tcp_tool", "tcp_tool", "settings", "sample"])
    assert events == expected
