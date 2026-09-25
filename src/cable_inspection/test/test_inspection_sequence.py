"""실제 검사포인트 반복 순서를 검증한다."""

from types import SimpleNamespace
from cable_inspection.sequence.inspection.node_inspection import InspectionJudgmentNode

from types import SimpleNamespace

from cable_inspection.sequence.inspection.data_models.inspection_result import InspectionResult
from cable_inspection.sequence.inspection.data_models.judgment_status import JudgmentStatus
from cable_inspection.sequence.inspection.seq_inspection import InspectionSequence



class HardwareDouble:
    def __init__(self):
        self.calls = []
        self.phase = ""
        self.gripper = SimpleNamespace()
        self.robot = SimpleNamespace(safe_abort=lambda: self.calls.append(("abort",)))



    def configure_point(self, point):
        self.point_id = point["point_id"]
        self.calls.append(("configure", self.point_id))



    def move_joint(self, pose, allow_incomplete=False, **kwargs):
        name = f"{self.point_id}_" + ("ready" if pose.task[0] == 0.0 else "entry")
        self.calls.append(("joint", name, allow_incomplete))
        return {"pose": name}



    def open_gripper(self, width, force, sample=None):
        return self.grip(width, force, opening=True)



    def measure_gripper_width(self):
        return {"width_mm": 22.0, "gripper_busy": True}



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



    def move_linear(self, task, **kwargs):
        self.calls.append(("linear", task))
        return {"task": task}



class RecordedInspection(InspectionSequence):
    """순서 테스트에서 검사 계측만 대역으로 처리한다. 실제 계측은 별도 테스트한다."""



    def run_point(self, point):
        self.motion.configure_point(point)
        return super().run_point(point)



    def sample(self):
        return self.motion.measure_gripper_width()



    def close_gripper(self, width, force, wait_for_completion=False):
        return self.motion.grip(width, force, wait_for_completion=wait_for_completion)



    def contact_move(self, point, kind):
        entry = kind == "ENTRY"

        return self.motion.relative(self.axis if entry else [-v for v in self.axis],
            point["entry_setting" if entry else "pull_setting"]["max_distance_mm"],
            entry_guard=entry, pull_guard=not entry)



def Point(point_id):
    return {
        "point_id": point_id, "point_name": point_id, "enabled": True,
        "ready_pose": {"task": [0., 0., 0., 90., -90., 0.], "joint": [0.] * 6},
        "entry_pose": {"task": [1., 0., 0., 90., -90., 0.], "joint": [1.] * 6},
        "grip_setting": {"soft_close_width_mm": 22., "soft_open_width_mm": 25.,
                         "hard_width_mm": 16., "soft_force_n": 10., "hard_force_n": 20.},
        "entry_setting": {"max_distance_mm": 5.},
        "pull_setting": {"speed_mm_s": 10., "max_distance_mm": 25., "force_limit_n": 15., "normal_displacement_limit_mm": 5.},
    }



def test_recipe_iterates_point_transition_adaptive_pull_and_return():
    hardware = HardwareDouble()
    recipe = {"points": [Point("L2"), Point("L5")], "recipe_id": "LAN",
              "recipe_version": "1.0", "connector_type": "RJ45_LAN"}
    requests = []
    inspection = RecordedInspection(hardware, judgment=SimpleNamespace(submit=requests.append))
    inspection.run_id = 7
    inspection.recipe_id, inspection.recipe_version, inspection.connector_type = "LAN", "1.0", "RJ45_LAN"
    results = {point["point_id"]: inspection.run_point(point) for point in recipe["points"]}

    assert list(results) == ["L2", "L5"]
    assert all(result.judgment_status == JudgmentStatus.PENDING
               for result in results.values())
    assert all(result.pull_displacement_mm == 4.0 for result in results.values())
    assert [request.point_id for request in requests] == ["L2", "L5"]
    assert all(request.run_id == 7 for request in requests)
    assert all(request.soft_width_mm == 22.0 for request in requests)
    assert all(request.pull_width_mm == 16.5 for request in requests)
    assert results["L2"].pull_inspection["pull"]["width_delta_mm"] == -5.5

    for point_id in ("L2", "L5"):
        start = 11 * (0 if point_id == "L2" else 1)
        assert hardware.calls[start:start + 10] == [
            ("configure", point_id),
            ("grip", 25.0, 10.0, True, False),
            ("joint", f"{point_id}_ready", False),
            ("joint", f"{point_id}_entry", False),
            ("grip", 22.0, 10.0, False, False),
            ("relative", [0.0, -1.0, 0.0], 5.0, True, False),
            ("grip", 16.0, 20.0, False, True),
            ("relative", [-0.0, 1.0, -0.0], 25.0, False, True),
            ("grip", 25.0, 10.0, True, False),
            ("linear", [1., 0., 0., 90., -90., 0.]),
        ]
        assert hardware.calls[start + 10][0] == "joint"



def test_motion_error_propagates_to_main_without_advancing_recipe():
    import pytest



    class BrokenHardware(HardwareDouble):
        def move_joint(self, pose, allow_incomplete=False, **kwargs):
            raise RuntimeError('motion service failed')



    hardware = BrokenHardware()
    requests = []
    inspection = RecordedInspection(hardware, judgment=SimpleNamespace(submit=requests.append))
    inspection.recipe_id, inspection.recipe_version, inspection.connector_type = "LAN", "1", "LAN"

    with pytest.raises(RuntimeError, match='motion service failed'):
        inspection.run_point(Point('L2'))

    assert not requests  # 오류 판정과 전체 정지는 Main이 맡는다.



def test_hard_grip_accepts_recorded_normal_width_while_busy_stays_true():
    from cable_inspection.sequence.common.motion import SequenceMotion
    samples = iter([
        {'width_mm': 21.6, 'gripper_busy': True},
        {'width_mm': 18.6, 'gripper_busy': True},
        {'width_mm': 18.4, 'gripper_busy': True},
    ])
    robot = SimpleNamespace(
        sample=lambda: next(samples), robot=SimpleNamespace(verify_mode=lambda: None),
        gripper=SimpleNamespace(set_grip=lambda *args, **kwargs: None),
        config=SimpleNamespace(width_tolerance_mm=2.5, gripper_timeout_s=1.0,
                               sample_period_s=0.0),
    )
    robot.motion = robot
    result = InspectionSequence.close_gripper(robot, 16.0, 20.0, wait_for_completion=True)
    assert result['completion_reason'] == 'TARGET_WIDTH_REACHED'
    assert result['measured'] == {'width_mm': 18.4, 'gripper_busy': True}



import pytest



@pytest.mark.parametrize("guard, timeout, expected", [
    ("pull", False, "PULL_FORCE_LIMIT"),
    ("pull", True, "PULL_TIMEOUT"),
    ("entry", False, "ENTRY_FORCE_LIMIT"),
    ("entry", True, "ENTRY_TIMEOUT"),
])
def test_peak_includes_deceleration_samples(guard, timeout, expected):
    from cable_inspection.sequence.common.motion import SequenceMotion
    from cable_inspection.sequence.common.data_models.robot_runtime_config import RobotRuntimeConfig
    from unittest.mock import Mock
    config = RobotRuntimeConfig(sample_period_s=0.0)
    settings = {"force_guard_n":100.0 if timeout else 15.0,
                "force_limit_n":100.0 if timeout else 15.0, "timeout_s":0.0 if timeout else 10.0}
    samples = iter([
        {"tcp": [float(i), 0., 0., 0., 0., 0.],
         "wrench_base": [force, 0., 0., 0., 0., 0.], "pull_force_n": force}
        for i, force in enumerate([16., 25., 17.])
    ])
    statuses = iter(([1] if timeout else []) + [1, 0])
    robot = SimpleNamespace(config=config, sample=lambda: next(samples),
                            controlled_stop=Mock(), check_client=object(),
                            robot=SimpleNamespace(motion_status=lambda: next(statuses)))
    inspection = contact_inspection(robot, guard)
    before = {"tcp": [0.] * 6, "wrench_base": [0.] * 6}
    result = inspection.monitor_contact([100., 0., 0., 0., 0., 0.], before, guard.upper(), settings)
    assert result["stop_reason"] == expected
    assert result["peak_force_delta_n"] == 25.0
    assert result["peak_pull_force_n"] == (25.0 if guard == "pull" else None)
    robot.controlled_stop.assert_called_once()



@pytest.mark.parametrize("mode", ["real", "virtual"])
def test_prepare_checks_both_devices_before_settings_and_force_sync(mode):
    from cable_inspection.sequence.common.motion import SequenceMotion
    from cable_inspection.robot.node_robot import RobotNode
    from cable_inspection.gripper_tool.node_gripper_tool import GripperToolNode
    events = []
    robot = SimpleNamespace(
        mode=mode, initialized=False,
        check_operability=lambda config: events.append("operable"),
        check_ready=lambda: events.append("robot_ready"),
        verify_mode=lambda: events.append("robot_mode"),
        _apply_virtual_settings=lambda: events.append("virtual_settings"),
        verify_active_tool_tcp=lambda config: events.append("tcp_tool"),
    )
    robot.initialize = lambda config: RobotNode.initialize(robot, config)
    gripper = SimpleNamespace(mode=mode, initialized=False,
        check_ready=lambda: events.append("gripper_ready"),
        _initialize_rg2_force=lambda: events.append("force_sync"))
    gripper.initialize = lambda: GripperToolNode.initialize(gripper)
    sequence = SimpleNamespace(robot=robot, gripper=gripper, config=object(),
        sample=lambda: events.append("sample"))
    from cable_inspection.sequence.main.seq_main import MainSequence
    MainSequence.check_devices(SimpleNamespace(backend=sequence))
    expected = ["robot_ready", "gripper_ready"]

    if mode == "virtual":
        expected.append("virtual_settings")

    expected.extend(["tcp_tool", "robot_mode"])

    if mode == "real":
        expected.append("force_sync")

    assert events == expected + ["operable", "sample"]



def test_hard_grip_uses_stable_width_without_busy_transition(monkeypatch):
    from cable_inspection.sequence.inspection import seq_inspection as motion_module
    clock = SimpleNamespace(now=0.0)
    widths = iter([21.9, 21.6, *([18.8] * 50)])



    def sample():
        clock.now += 0.05

        return {'width_mm': next(widths), 'gripper_busy': True}



    monkeypatch.setattr(motion_module, 'time', SimpleNamespace(
        monotonic=lambda: clock.now, sleep=lambda _: None))
    robot = SimpleNamespace(sample=sample, robot=SimpleNamespace(verify_mode=lambda: None),
        gripper=SimpleNamespace(set_grip=lambda *args, **kwargs: None),
        config=SimpleNamespace(width_tolerance_mm=2.5,
                               gripper_timeout_s=20.0, sample_period_s=0.0))
    robot.motion = robot
    result = InspectionSequence.close_gripper(robot, 16.0, 20.0, wait_for_completion=True)
    assert result['completion_reason'] == 'WIDTH_STABILIZED'
    assert result['measured']['gripper_busy'] is True
    assert result['measured']['width_mm'] == 18.8



def test_soft_width_snapshot_ignores_busy():
    from cable_inspection.sequence.common.motion import SequenceMotion
    measured = {'width_mm': 24.9, 'gripper_busy': True}
    motion = SimpleNamespace(sample=lambda enrich: measured)
    inspection = SimpleNamespace(motion=motion, measure=lambda sample: None)
    assert InspectionSequence.sample(inspection) is measured



def test_hard_grip_width_timeout_is_distinct_from_feedback_timeout():
    from cable_inspection.sequence.common.motion import SequenceMotion
    from cable_inspection.sequence.inspection.data_models.grip_completion_timeout import GripCompletionTimeout
    measured = {'width_mm':24.9, 'gripper_busy':True}
    robot = SimpleNamespace(sample=lambda: measured, robot=SimpleNamespace(verify_mode=lambda: None),
        gripper=SimpleNamespace(set_grip=lambda *args, **kwargs: None),
        config=SimpleNamespace(gripper_timeout_s=0., sample_period_s=0., width_tolerance_mm=2.5))
    robot.motion = robot



    def invoke():
        return InspectionSequence.close_gripper(robot, 18., 20., wait_for_completion=True)



    with pytest.raises(GripCompletionTimeout) as caught:
        invoke()

    assert caught.value.stage == 'Hard'
    assert caught.value.measured == measured



    def lost_feedback():
        raise TimeoutError('feedback missing')



    robot.sample = lost_feedback

    with pytest.raises(TimeoutError) as caught:
        invoke()

    assert not isinstance(caught.value, GripCompletionTimeout)



@pytest.mark.parametrize('guard,expected', [
    ('entry', 'ENTRY_STOPPED_SHORT'), ('pull', 'PULL_STOPPED_SHORT'),
])
def test_contact_motion_stopped_short_records_actual_distance_without_job_timeout(guard, expected):
    from cable_inspection.sequence.common.motion import SequenceMotion
    from cable_inspection.sequence.common.data_models.robot_runtime_config import RobotRuntimeConfig
    from unittest.mock import Mock
    config = RobotRuntimeConfig(sample_period_s=0.0)
    sample = {'tcp':[2.,0.,0.,0.,0.,0.], 'wrench_base':[1.,0.,0.,0.,0.,0.],
              'pull_force_n':1.}
    robot = SimpleNamespace(config=config, sample=lambda:sample,
        controlled_stop=Mock(), check_client=object(),
        robot=SimpleNamespace(motion_status=lambda: 0),
        measurement_direction=[1.,0.,0.], measurement_kind=guard.upper(),
        sample_origin=[0.]*6, force_origin=[0.]*6)
    before = {'tcp':[0.]*6, 'wrench_base':[0.]*6}
    inspection = contact_inspection(robot, guard)
    result = inspection.monitor_contact([25.,0.,0.,0.,0.,0.], before, guard.upper(),
        {"force_guard_n":15., "force_limit_n":15., "timeout_s":10.})
    assert result['stop_reason'] == expected
    assert result['displacement_mm'] == 2.
    robot.controlled_stop.assert_not_called()  # 로봇은 이미 정지했다.

    if guard == 'pull':
        from cable_inspection.sequence.inspection.seq_inspection import InspectionSequence
        from cable_inspection.sequence.inspection.data_models.pull_termination import PullTermination
        from cable_inspection.sequence.inspection.seq_inspection import InspectionSequence
        termination = InspectionSequence._pull_termination(expected)
        assert termination == PullTermination.STOPPED_SHORT
        judgment = InspectionJudgmentNode.judge_request(SimpleNamespace(termination_reason=termination, peak_pull_force_n=1., pull_displacement_mm=2., required_force_n=15., soft_width_mm=22., pull_width_mm=20., normal_displacement_limit_mm=5.0))
        assert judgment.result == InspectionResult.SYSTEM_ERROR



def test_sequence_uses_separate_device_objects_and_propagates_control_poll():
    import io
    from unittest.mock import Mock
    from cable_inspection.sequence.common.motion import SequenceMotion
    robot = SimpleNamespace(mode="virtual", stop_motion=Mock())
    gripper = SimpleNamespace(mode="virtual")
    sequence = SequenceMotion(robot, gripper, io.StringIO())
    poll = lambda: None
    sequence.control_poll = robot.control_poll = gripper.control_poll = poll
    assert robot.control_poll is poll and gripper.control_poll is poll
    robot.motion_status = lambda: 0
    sequence.sample = lambda: {}
    sequence.request_motion_stop()
    assert sequence.control_poll is poll and robot.control_poll is poll and gripper.control_poll is poll
    robot.stop_motion.assert_called_once_with(2)
    assert not hasattr(robot, "gripper")
    assert not hasattr(gripper, "robot")



def test_open_updates_rg2_width_before_reducing_force():
    from cable_inspection.gripper_tool.rg2 import RG2Gripper
    robot = object.__new__(RG2Gripper)
    robot.mode = 'real'
    robot.commanded_width_mm = 18.0
    robot.commanded_force_n = 20.0
    commands = []
    robot._send_gripper_command = commands.append
    robot._set_gripper(25.0, 10.0, opening=True)
    assert commands == ['250', 'd', 'd', 'd', 'd']
    assert robot.commanded_width_mm == 25.0
    assert robot.commanded_force_n == 10.0



def test_robot_preparation_runs_once_across_operability_checks():
    """다음 Job/Home 재확인은 기존 장비 연결을 사용하고 초기 힘 설정을 반복하지 않는다."""
    from unittest.mock import Mock
    from cable_inspection.sequence.common.motion import SequenceMotion

    from cable_inspection.robot.node_robot import RobotNode
    from cable_inspection.gripper_tool.node_gripper_tool import GripperToolNode
    from cable_inspection.sequence.main.seq_main import MainSequence
    device = SimpleNamespace(mode="virtual", initialized=False, check_ready=Mock(),
        _apply_virtual_settings=Mock(), robot_state=lambda:1, verify_mode=Mock(),
        verify_active_tool_tcp=Mock(), read_joints=lambda:[0.] * 6)
    device.initialize = lambda config: RobotNode.initialize(device, config)
    device.check_operability = lambda config: RobotNode.check_operability(device, config)
    gripper = SimpleNamespace(mode="virtual", initialized=False, check_ready=Mock())
    gripper.initialize = lambda: GripperToolNode.initialize(gripper)
    sequence = SimpleNamespace(robot=device, gripper=gripper,
        config=SimpleNamespace(tcp_name="tcp", tool_name="tool"), sample=Mock())
    main = SimpleNamespace(backend=sequence)
    assert MainSequence.check_devices(main).success
    assert MainSequence.check_devices(main).success
    device._apply_virtual_settings.assert_called_once()
    assert device.initialized and gripper.initialized

    # 최초 설정 확인과 두 차례 운전 전 재확인은 읽기만 수행한다.
    assert device.verify_active_tool_tcp.call_count == 3
    device.verify_active_tool_tcp.assert_called_with(sequence.config)



def contact_inspection(motion, guard):
    """측정 입력만 대체하고 축 투영·감속 중 누적은 실제 검사 코드로 확인한다."""
    from cable_inspection.sequence.common.motion import SequenceMotion
    motion.gripper = SimpleNamespace()
    motion.robot.stop_motion = lambda mode: motion.controlled_stop()
    motion.stop_and_wait = lambda sample: SequenceMotion.stop_and_wait(motion, sample=sample)
    inspection = InspectionSequence(motion)
    inspection.point = {'point_id':'P1'}
    inspection.axis = inspection.measurement_direction = [1.,0.,0.]
    inspection.measurement_kind = guard.upper()
    inspection.sample_origin = inspection.force_origin = [0.] * 6
    inspection.peak_force_delta = inspection.peak_pull_force = 0.
    inspection.pull_min_width = float('inf')
    raw_sample = motion.sample



    def sample():
        measured = dict(raw_sample(), width_mm=18.4)
        inspection.measure(measured)
        return measured



    inspection.sample = sample

    return inspection
