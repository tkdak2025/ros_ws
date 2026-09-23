"""실물 없이 시퀀스 분기/순서/결과를 확인한다.

장비는 호출 기록만 남기며 ROS 노드를 생성하지 않는다.
가상 측정값은 흐름 확인용으로만 쓰고 실물 성능 검증으로 해석하지 않는다.
운영 코드에서는 이 파일을 참조하지 않는다.
"""

import json
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest
import rclpy

from cable_inspection.data_models.models import (
    InspectionResult, JobContext, JudgmentStatus, PointRuntime,
    SequenceResult, SequenceStatus, SystemState,
)
from cable_inspection.recipe.inspection_recipe import OperatingInspectionRecipe
from cable_inspection.recipe.inspection_recipe import load_system_recipe
from cable_inspection.sequence import main_node as main
from cable_inspection.sequence.main_node import check_work_completion
from cable_inspection.sequence.judgment_node import (
    InspectionJudgmentNode, judge_pull, message_to_ordereddict,
)

PACKAGE = Path(__file__).resolve().parents[1]
RECIPE = PACKAGE / "cable_inspection/recipe/inspection/lan_inspection_recipe.json"


@pytest.fixture(autouse=True)
def no_ros_node(monkeypatch):
    """잘못된 테스트 연결이 있어도 실물 통신 초기화 단계에서 차단한다."""
    def blocked(*args, **kwargs):
        raise AssertionError("오프라인 확인에서는 ROS 초기화를 하지 않습니다.")
    monkeypatch.setattr(rclpy, "init", blocked)


class RecordedRobot:
    """물리 동작 없이 명령 순서를 남기는 장비 대역."""
    def __init__(self, inside=True, failure=None):
        self.calls = []
        self.inside = inside
        self.failure = failure
        self.phase = ""
        self.stream = None
        self.node = None
        self.system = {"max_escape_distance_mm": 30.0,
                       "communication_recovery_timeout_s": 30.0,
                       "judgment_timeout_s": 1.0}
        self.recipe = OperatingInspectionRecipe.load_json(RECIPE)
        self.point = None

    def step(self, name):
        self.calls.append(name)
        return SequenceResult(name != self.failure, name, name)

    def hmi_available(self): return True
    def check_robot_operability(self): return self.step("robot")
    def check_hmi_communication(self): return self.step("hmi")
    def validate_system_recipe(self): return self.step("system_recipe")
    def validate_inspection_recipe(self, recipe_id): return self.step("inspection_recipe")
    def enabled_point_ids(self, recipe_id):
        return [key for key in self.recipe.execution_order if self.recipe.points[key].enabled]
    def current_tcp(self): return [0.0] * 6
    def tcp_is_in_work_area(self, tcp): return self.inside
    def relax_grip(self): return self.step("relax")
    def safe_escape(self, distance): return self.step(f"escape:{distance}")
    def move_work_access_safe_pose(self): return self.step("access")
    def move_home_pose(self): return self.step("home")
    def move_safe_route_home(self): return self.move_home_pose()
    def request_motion_stop(self): return self.step("stop")

    def configure_point(self, point):
        self.point = point
        self.calls.append(point.point_id)

    def move_joint(self, pose, allow_incomplete=False):
        self.calls.append("entry" if pose == self.point.entry_pose else "ready")
        return {"reached": not allow_incomplete}

    def grip(self, width, force, opening=False, wait_for_completion=False):
        self.calls.append("open" if opening else "hard" if wait_for_completion else "soft")
        return {"measured": {"width_mm": width, "gripper_busy": False}}

    def wait_gripper_idle(self):
        self.calls.append("soft_width")
        return {"width_mm": 22.0, "gripper_busy": False}

    def relative(self, direction, distance, entry_guard=False, pull_guard=False):
        self.calls.append("pull" if pull_guard else "additional_entry")
        if pull_guard:
            return {"stop_reason": "PULL_FORCE_LIMIT", "peak_pull_force_n": 15.2,
                    "pull_displacement_mm": 4.0, "pull_width_mm": 16.5}
        return {"stop_reason": "ENTRY_FORCE_LIMIT", "entry_displacement_mm": 2.0}

    def move_linear(self, task):
        self.calls.append("entry" if self.phase == "SEQ_03_POINT_TRANSITION" else "return_entry")
        return {"task": task, "stop_reason": "TARGET_REACHED"}


@pytest.mark.parametrize("failure", [None, "robot", "hmi", "system_recipe", "inspection_recipe"])
def test_01_initialize_short_circuits_failed_check(failure):
    robot = RecordedRobot(failure=failure)
    result = main.SequenceController(robot).work_initialize(robot.recipe.recipe_id)
    order = ["robot", "hmi", "system_recipe", "inspection_recipe", "robot"]
    expected = order if failure is None else order[:order.index(failure) + 1]
    assert robot.calls == expected
    assert result.success == (failure is None)


def test_01_no_active_points():
    robot = RecordedRobot()
    robot.recipe.points = {key: replace(point, enabled=False)
                           for key, point in robot.recipe.points.items()}
    assert main.SequenceController(robot).work_initialize(robot.recipe.recipe_id).code == "NO_ENABLED_POINT"


@pytest.mark.parametrize("inside,expected", [
    (True, ["robot", "relax", "escape:30.0", "access", "home"]),
    (False, ["robot", "home"]),
])
def test_02_home_routes(inside, expected):
    robot = RecordedRobot(inside=inside)
    assert main.SequenceController(robot).home_return().success
    assert robot.calls == expected


def test_02_access_failure_prevents_home():
    robot = RecordedRobot(failure="access")
    assert not main.SequenceController(robot).home_return().success
    assert robot.calls == ["robot", "relax", "escape:30.0", "access"]


def test_02_access_and_home_checkpoints():
    robot = RecordedRobot()
    checkpoints = []
    controller = main.SequenceController(robot)
    controller.checkpoint = checkpoints.append
    result = controller.home_return()
    assert result.data["route"] == "WORK_AREA_ESCAPE"
    assert checkpoints == ["GRIP_RELAXED", "SAFE_ESCAPE_DONE", "WORK_ACCESS_REACHED", "HOME_REACHED"]


def completed_context():
    context = JobContext("LAN", ["P1", "P2", "P3"], current_point_index=3)
    context.point_runtime = {
        key: PointRuntime(key, motion_status=SequenceStatus.SUCCESS,
                          adaptive_grip_status=SequenceStatus.SUCCESS, pull_status=SequenceStatus.SUCCESS,
                          result=result, log_saved=True,
                          judgment_status=(JudgmentStatus.ERROR if result == InspectionResult.SYSTEM_ERROR
                                           else JudgmentStatus.COMPLETED))
        for key, result in zip(context.enabled_point_ids, [InspectionResult.PASS, InspectionResult.FAIL, InspectionResult.PASS])
    }
    return context


def test_07_completed_pass_and_fail_can_complete_job():
    result = check_work_completion(completed_context())
    assert result.success
    assert result.data["counts"] == {"PASS": 2, "FAIL": 1, "SYSTEM_ERROR": 0}


@pytest.mark.parametrize("missing", ["point", "motion", "result", "log", "pending", "iteration"])
def test_07_incomplete_conditions(missing):
    context = completed_context()
    if missing == "point":
        del context.point_runtime["P1"]
    elif missing == "motion":
        context.point_runtime["P1"].motion_status = SequenceStatus.INCOMPLETE
    elif missing == "result":
        context.point_runtime["P1"].result = None
    elif missing == "log":
        context.point_runtime["P1"].log_saved = False
    elif missing == "pending":
        context.pending_judgments.add("P1")
    else:
        context.current_point_index = 2
    assert not check_work_completion(context).success


def test_pause_resume_preserves_context_and_rechecks_robot(tmp_path):
    robot = RecordedRobot()
    controller = main.SequenceController(robot, tmp_path)
    controller.context = completed_context()
    original = controller.context
    controller.state = SystemState.RUNNING
    assert controller.pause().success
    assert controller.state == SystemState.PAUSE_REQUEST

    def resume_at_checkpoint():
        assert controller.state == SystemState.PAUSED
        assert controller.context is original
        assert controller.resume().success

    controller.pump = resume_at_checkpoint
    controller.checkpoint("READY_REACHED")
    assert controller.state == SystemState.RUNNING
    assert controller.context.resume_point == "READY_REACHED"
    assert robot.calls == ["robot", "robot"]


def test_communication_recovery_requires_explicit_resume(tmp_path):
    controller = main.SequenceController(RecordedRobot(), tmp_path)
    controller.state = SystemState.RUNNING
    controller.communication_lost()
    controller.state = SystemState.PAUSED
    assert not controller.resume().success
    controller.communication_recovered()
    assert controller.pause_requested.is_set()
    assert controller.resume().success


def test_communication_timeout_requests_stop(monkeypatch, tmp_path):
    controller = main.SequenceController(RecordedRobot(), tmp_path)
    controller.comm_lost_at = 10.0
    monkeypatch.setattr(main.time, "monotonic", lambda: 40.0)
    with pytest.raises(main.JobStopped, match="COMM_ERROR"):
        controller.poll_control()


def test_recipe_add_save_reload_preserves_order(tmp_path):
    recipe = OperatingInspectionRecipe.load_json(RECIPE)
    point = replace(recipe.points["LAN_L2"], point_id="OFFLINE_ONLY", point_name="확인용")
    recipe.add_point(point)
    target = tmp_path / "recipe.json"
    recipe.save_json(target)
    loaded = OperatingInspectionRecipe.load_json(target)
    assert loaded.execution_order == ["LAN_L2", "LAN_L5", "OFFLINE_ONLY"]
    assert loaded.points["OFFLINE_ONLY"] == point
    with pytest.raises(ValueError):
        recipe.add_point(point)


@pytest.mark.parametrize("abc,expected", [
    ([0, 0, 0], [0, 0, 1]),
    ([0, 180, 0], [0, 0, -1]),
    ([20, 180, 20], [0, 0, -1]),
    ([30, 180, 30], [0, 0, -1]),
    ([0, 90, 0], [1, 0, 0]),
    ([90, 90, 0], [0, 1, 0]),
    ([90, -90, 0], [0, -1, 0]),
    ([45, 45, 0], [0.5, 0.5, 2**-0.5]),
    ([45, 45, 70], [0.5, 0.5, 2**-0.5]),
])
def test_entry_direction_comes_from_entry_abc(abc, expected):
    point = OperatingInspectionRecipe.load_json(RECIPE).points["LAN_L2"]
    pose = replace(point.entry_pose, task=point.entry_pose.task[:3] + abc)
    point = replace(point, entry_pose=pose)
    assert point.normalized_entry_direction() == pytest.approx(expected, abs=1e-12)


def test_legacy_direction_cannot_override_entry_abc(tmp_path):
    raw = json.loads(RECIPE.read_text())
    raw["points"]["LAN_L2"]["entry_direction"] = [1.0, 0.0, 0.0]
    path = tmp_path / "legacy_recipe.json"
    path.write_text(json.dumps(raw))
    loaded = OperatingInspectionRecipe.load_json(path)
    assert loaded.points["LAN_L2"].normalized_entry_direction() == [0.0, -1.0, 0.0]


def test_system_recipe_without_coordinates_is_rejected(tmp_path):
    data = json.loads((PACKAGE / "config/system_recipe.json").read_text())
    data["home_pose"] = {"task": None, "joint": None}
    path = tmp_path / "missing_home.json"
    path.write_text(json.dumps(data))
    with pytest.raises(ValueError, match="home_pose"):
        load_system_recipe(path)


@pytest.mark.parametrize("actual,target,expected", [
    ([0, 180, 0], [20, 180, 20], 0.0),
    ([0, 180, 0], [30, 180, 30], 0.0),
    ([0, 180, 0], [20, 180, 30], 10.0),
    ([0, 0, 0], [0, 0, 360], 0.0),
    ([0, 180, 0], [0, 179, 0], 1.0),
    ([0, 0, 0], [0, 180, 0], 180.0),
])
def test_orientation_uses_actual_rotation_difference(actual, target, expected):
    from cable_inspection.hardware.robot import orientation_error_deg
    assert orientation_error_deg(actual, target) == pytest.approx(expected, abs=1e-5)


def test_motion_accepts_equivalent_zyz_pose_without_timeout():
    from cable_inspection.hardware.robot import HardwareRobot, RobotRuntimeConfig
    measured = {"tcp": [589.95, 186.61, 98.98, 0.0, 180.0, 0.0],
                "wrench_base": [0.0] * 6}
    robot = SimpleNamespace(
        config=RobotRuntimeConfig(), check_client=None,
        sample=lambda: measured,
        _call=lambda *_args: SimpleNamespace(status=0),
    )
    target = [589.95, 186.61, 98.98, 20.0, 180.0, 20.0]
    result = HardwareRobot._monitor(robot, target, measured)
    assert result["stop_reason"] == "TARGET_REACHED"


@pytest.mark.parametrize("invalid", [None, "route", "escape", "axis", "missing_axis", "tolerance"])
def test_system_recipe_entered_values(tmp_path, invalid):
    # 가상 좌표는 임시 파일에만 저장한다. 운영 레시피의 미정 좌표는 유지한다.
    data = json.loads((PACKAGE / "config/system_recipe.json").read_text())
    data.update(
        home_pose={"task": [50.0, 0, 0, 0, 0, 0], "joint": [0.0] * 6},
        work_Access_safe_pose={"task": [0.0] * 6, "joint": [0.0] * 6},
        work_area={f"{axis}_{side}_mm": value for axis in "xyz"
                   for side, value in (("min", -10.0), ("max", 10.0))},
        tool_approach_axis=[0.0, 0.0, 1.0],
    )
    data["safe_home_route"] = [data["home_pose"]]
    if invalid == "route":
        data["safe_home_route"] = []
    elif invalid == "missing_axis":
        data["tool_approach_axis"] = None
    elif invalid == "tolerance":
        data["home_joint_tolerance_deg"] = 0.0
    elif invalid == "escape":
        data["max_escape_distance_mm"] = 31.0
    elif invalid == "axis":
        data["tool_approach_axis"] = [0.0] * 3
    path = tmp_path / "system.json"
    path.write_text(json.dumps(data))
    if invalid:
        with pytest.raises(ValueError):
            load_system_recipe(path)
    else:
        assert load_system_recipe(path) == data


class DelayedJudgment:
    """요청만 모았다가 Work Finish에서 판정을 전달해 비동기 흐름을 확인한다."""
    def __init__(self, robot):
        self.robot = robot
        self.publisher = SimpleNamespace(get_subscription_count=lambda: 1)
        self.requests = []
        self.results = {}
        self.closed = False

    def submit(self, request):
        self.robot.calls.append("judgment_request")
        self.requests.append(request)

    def deliver(self):
        for request in self.requests:
            judgment = judge_pull(
                termination=request.termination_reason,
                peak_force_n=request.peak_pull_force_n,
                displacement_mm=request.pull_displacement_mm,
                required_force_n=request.required_force_n,
                soft_width_mm=request.soft_width_mm, pull_width_mm=request.pull_width_mm)
            message = InspectionJudgmentNode._result_message(request, judgment)
            self.results[request.point_id] = dict(message_to_ordereddict(message))

    def close(self):
        self.closed = True


def test_00_initialization_failure_never_starts_motion(monkeypatch, tmp_path):
    robot = RecordedRobot(failure="system_recipe")
    judgment = DelayedJudgment(robot)
    monkeypatch.setattr(main, "JudgmentClient", lambda node: judgment)
    controller = main.SequenceController(robot, tmp_path)
    result = controller.run(robot.recipe.recipe_id)
    assert result.code == "INIT_FAIL"
    assert controller.state == SystemState.SYSTEM_READY
    assert robot.calls == ["robot", "hmi", "system_recipe"]
    assert judgment.closed and robot.stream is None


@pytest.mark.parametrize("stop_after_first", [False, True])
def test_00_job_order_delayed_results_and_stop(monkeypatch, tmp_path, stop_after_first):
    robot = RecordedRobot()
    judgment = DelayedJudgment(robot)
    monkeypatch.setattr(main, "JudgmentClient", lambda node: judgment)
    controller = main.SequenceController(robot, tmp_path)
    original_configure = robot.configure_point

    def configure(point):
        original_configure(point)
        if stop_after_first and point.point_id == "LAN_L5":
            controller.stop()
            controller.poll_control()

    robot.configure_point = configure

    def deliver_at_finish():
        assert controller.context.current_point_index == 2
        assert robot.calls[-1] == "access"
        assert not judgment.results  # L2 결과를 기다리지 않고 L5까지 진행했다.
        judgment.deliver()

    controller.pump = deliver_at_finish
    result = controller.run(robot.recipe.recipe_id)
    assert judgment.closed and robot.stream is None
    assert controller.context is None
    status = json.loads((controller.output / "status.json").read_text())

    if stop_after_first:
        assert result.code == "STOP"
        assert controller.state == SystemState.STOPPED
        assert robot.calls[-2:] == ["LAN_L5", "stop"]
        assert robot.calls.count("home") == 1  # 초기 Home만 수행, STOP 후 Home 없음.
        assert status["completed"] is False
        assert status["context"]["recipe_id"] == robot.recipe.recipe_id
        return

    assert result.success, result.message
    assert controller.state == SystemState.SYSTEM_READY
    cycle = ["open", "ready", "entry", "soft", "additional_entry", "soft_width",
             "hard", "pull", "judgment_request", "open", "return_entry", "ready"]
    assert robot.calls == (
        ["robot", "hmi", "system_recipe", "inspection_recipe", "robot",
         "robot", "relax", "escape:30.0", "access", "home", "access",
         "LAN_L2"] + cycle + ["LAN_L5"] + cycle +
        ["access", "hmi", "robot", "relax", "escape:30.0", "access", "home"])
    assert result.data["counts"] == {"PASS": 2, "FAIL": 0, "SYSTEM_ERROR": 0}
    assert status["completed"] is True
    records = json.loads((controller.output / "inspection_results.json").read_text())
    assert list(records) == ["LAN_L2", "LAN_L5"]
    assert all(record["result"] == "PASS" for record in records.values())
    assert all(request.force_data_id == str((controller.output / "samples.jsonl").resolve())
               for request in judgment.requests)


@pytest.mark.parametrize("failure", [None, "motion", "joint"])
def test_home_uses_single_move_and_checks_all_joints(failure):
    from cable_inspection.hardware.robot import SequenceRobot
    targets = []
    robot = SimpleNamespace(
        system={"home_pose": {"task": [0.0] * 6, "joint": [0.0] * 6},
                "home_joint_tolerance_deg": 0.1},
        current_joints=lambda: [0.0] * 5 + [1.0 if failure == "joint" else 0.0],
        ok=SequenceRobot.ok,
    )
    def move(pose):
        targets.append(pose.joint[:])
        if failure == "motion":
            raise RuntimeError("motion failed")
    robot.move_joint = move
    if failure:
        with pytest.raises(RuntimeError):
            SequenceRobot.move_home_pose(robot)
    else:
        assert SequenceRobot.move_home_pose(robot).success
    assert targets == [[0.0] * 6]


def test_operating_home_route_matches_confirmed_direct_zero_joint_policy():
    data = load_system_recipe(PACKAGE / "config/system_recipe.json")
    assert data["safe_home_route"] == [data["home_pose"]]
    assert data["home_pose"]["joint"] == [0.0] * 6
    assert data["tool_approach_axis"] == [0.0, 0.0, 1.0]
    assert data["relax_width_mm"] == 25.0


@pytest.mark.parametrize("result,judgment", [
    (InspectionResult.PASS, JudgmentStatus.PENDING),
    (InspectionResult.FAIL, JudgmentStatus.ERROR),
    (InspectionResult.SYSTEM_ERROR, JudgmentStatus.COMPLETED),
])
def test_finish_rejects_unfinished_or_inconsistent_judgment(result, judgment):
    context = completed_context()
    context.point_runtime["P1"].result = result
    context.point_runtime["P1"].judgment_status = judgment
    outcome = check_work_completion(context)
    assert not outcome.success
    assert "P1" in outcome.data["missing_points"]


def test_recording_directory_failure_does_not_leave_running_state(tmp_path):
    target = tmp_path / "not_a_directory"
    target.write_text("occupied")
    robot = RecordedRobot()
    controller = main.SequenceController(robot, target)
    result = controller.run(robot.recipe.recipe_id)
    assert not result.success
    assert controller.state != SystemState.RUNNING
    assert controller.context is None and robot.stream is None
    assert robot.calls == []


def test_judgment_creation_failure_closes_stream(monkeypatch, tmp_path):
    robot = RecordedRobot()
    previous = object()
    robot.stream = previous
    opened = []
    def fail_client(node):
        opened.append(robot.stream)
        raise RuntimeError("cannot create judgment client")
    monkeypatch.setattr(main, "JudgmentClient", fail_client)
    controller = main.SequenceController(robot, tmp_path)
    result = controller.run(robot.recipe.recipe_id)
    assert not result.success
    assert opened[0].closed and robot.stream is previous
    assert controller.state == SystemState.SYSTEM_READY
    assert robot.calls == []


def test_recording_cleanup_restores_stream_even_if_client_close_fails(tmp_path):
    robot = RecordedRobot()
    controller = main.SequenceController(robot, tmp_path)
    controller.output = tmp_path
    def fail_close():
        raise RuntimeError("close failed")
    controller.judgment = SimpleNamespace(results={}, close=fail_close)
    stream = (tmp_path / "samples.jsonl").open("w")
    robot.stream = stream
    previous = object()
    with pytest.raises(RuntimeError, match="close failed"):
        controller.close_recording(stream, previous)
    assert stream.closed and robot.stream is previous


def test_result_save_failure_closes_resources_and_blocks_success(monkeypatch, tmp_path):
    robot = RecordedRobot()
    judgment = DelayedJudgment(robot)
    monkeypatch.setattr(main, "JudgmentClient", lambda _: judgment)
    controller = main.SequenceController(robot, tmp_path)
    controller.pump = judgment.deliver
    original_save = controller.save
    def fail_save(name, data):
        if name == "judgment_results.json":
            raise OSError("disk full")
        return original_save(name, data)
    controller.save = fail_save
    result = controller.run(robot.recipe.recipe_id)
    assert not result.success and result.code == "RECORDING_ERROR"
    assert controller.state == SystemState.ERROR
    assert judgment.closed and robot.stream is None
    assert controller.context is None


@pytest.mark.parametrize("final_home_fails", [False, True])
def test_final_summary_reflects_home_outcome(monkeypatch, tmp_path, final_home_fails):
    robot = RecordedRobot()
    original_home = robot.move_home_pose
    homes = []
    def home():
        homes.append(True)
        if final_home_fails and len(homes) == 2:
            return SequenceResult(False, "HOME_FAILED", "home failed")
        return original_home()
    robot.move_home_pose = home
    judgment = DelayedJudgment(robot)
    monkeypatch.setattr(main, "JudgmentClient", lambda _: judgment)
    controller = main.SequenceController(robot, tmp_path)
    controller.pump = judgment.deliver
    result = controller.run(robot.recipe.recipe_id)
    summary = json.loads((controller.output / "job_summary.json").read_text())
    status = json.loads((controller.output / "status.json").read_text())
    assert result.success == (not final_home_fails)
    assert summary["job_status"] == ("ERROR" if final_home_fails else "COMPLETED")
    assert summary["completed"] == status["completed"] == result.success
    assert summary["end_time"] >= summary["inspection_end_time"]


def test_system_error_waits_at_access_without_final_home(monkeypatch, tmp_path):
    robot = RecordedRobot()
    robot.system["judgment_timeout_s"] = 0.01
    judgment = DelayedJudgment(robot)
    monkeypatch.setattr(main, "JudgmentClient", lambda _: judgment)
    controller = main.SequenceController(robot, tmp_path)
    paused = []
    def pump():
        if controller.pause_requested.is_set():
            paused.append(controller.state)
            assert robot.calls.count("home") == 1  # 최초 위치 정규화만 완료
            controller.stop()
            controller.poll_control()
        judgment.deliver()
        for result in judgment.results.values():
            result.update(result="SYSTEM_ERROR", judgment_status="ERROR", sequence_status="INCOMPLETE")
    controller.pump = pump
    result = controller.run(robot.recipe.recipe_id)
    assert result.code == "STOP"
    assert paused == [SystemState.PAUSED]
    assert robot.calls.count("home") == 1
    status = json.loads((controller.output / "status.json").read_text())
    assert not status["completed"]
    assert all(point["pull_status"] == "INCOMPLETE"
               for point in status["context"]["point_runtime"].values())


def test_paused_robot_fault_is_reported_without_waiting_for_resume(monkeypatch, tmp_path):
    robot = RecordedRobot()
    judgment = DelayedJudgment(robot)
    monkeypatch.setattr(main, "JudgmentClient", lambda _: judgment)
    controller = main.SequenceController(robot, tmp_path)
    original_operability = robot.check_robot_operability
    def operability():
        if controller.state == SystemState.PAUSED:
            return SequenceResult(False, "ROBOT_ERROR", "fault during pause")
        return original_operability()
    robot.check_robot_operability = operability
    original_access = controller.move_work_access
    def pause_at_access(checkpoint_name):
        controller.pause()
        original_access(checkpoint_name)
    controller.move_work_access = pause_at_access
    result = controller.run(robot.recipe.recipe_id)
    assert not result.success and result.code == "JOB_ERROR"
    assert controller.state == SystemState.ERROR
    assert "fault during pause" in result.message
    assert robot.calls.count("home") == 1
    assert "LAN_L2" not in robot.calls
