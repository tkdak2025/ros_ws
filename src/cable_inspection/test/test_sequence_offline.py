"""실물 없이 시퀀스 분기/순서/결과를 확인한다.

장비는 호출 기록만 남기며 ROS 노드를 생성하지 않는다.
가상 측정값은 흐름 확인용으로만 쓰고 실물 성능 검증으로 해석하지 않는다.
운영 코드에서는 이 파일을 참조하지 않는다.
"""

from types import SimpleNamespace
from cable_inspection.sequence.inspection.node_inspection import InspectionJudgmentNode

import json
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest
import rclpy

from cable_inspection.sequence.inspection.data_models.inspection_result import InspectionResult
from cable_inspection.sequence.main.data_models.job_context import JobContext
from cable_inspection.sequence.inspection.data_models.judgment_status import JudgmentStatus
from cable_inspection.sequence.inspection.data_models.inspection_point_result import InspectionPointResult
from cable_inspection.sequence.common.data_models.sequence_result import SequenceResult
from cable_inspection.sequence.common.data_models.sequence_status import SequenceStatus
from cable_inspection.sequence.main.data_models.system_state import SystemState
from cable_inspection.recipe.recipe import Recipe, RobotPose
from cable_inspection.sequence.main import node_main as main
from cable_inspection.sequence.inspection.seq_inspection import InspectionSequence
from cable_inspection.sequence.home_return.seq_home_return import HomeReturnSequence
from cable_inspection.sequence.inspection.node_inspection import (
    InspectionJudgmentNode, message_to_ordereddict,
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
        self.at_access = True
        self.failure = failure
        self.phase = ""
        self.stream = None
        self.robot = SimpleNamespace()
        self.gripper = SimpleNamespace()
        self.system = {"max_escape_distance_mm": 30.0,
                       "communication_recovery_timeout_s": 30.0,
                       "judgment_timeout_s": 1.0,
                       "work_Access_safe_pose": {"task": [0.] * 6, "joint": [0.] * 6}}
        self.recipe = Recipe.load_json(RECIPE)
        self.point = None



    def step(self, name):
        self.calls.append(name)
        return SequenceResult(name != self.failure, name, name)



    def hmi_available(self):
        return True



    def check_robot_operability(self):
        return self.step("robot")



    def check_hmi_communication(self):
        return self.step("hmi")



    def validate_system_recipe(self):
        return self.step("system_recipe")



    def validate_inspection_recipe(self, recipe_id):
        return self.step("inspection_recipe")



    def enabled_point_ids(self, recipe_id):
        return [point["point_id"] for point in self.recipe["points"] if point["enabled"]]



    def current_tcp(self):
        return [0.0] * 6



    def tcp_is_in_work_area(self, tcp):
        return self.inside



    def tcp_is_at_work_access(self, tcp):
        return self.at_access



    def relax_grip(self):
        return self.step("relax")



    def safe_escape(self, distance):
        return self.step(f"escape:{distance}")



    def move_work_access_safe_pose(self, pose):
        return self.step("access")



    def move_home_pose(self):
        return self.step("home")



    def move_safe_route_home(self):
        return self.move_home_pose()



    def request_motion_stop(self):
        return self.step("stop")



    def configure_point(self, point):
        self.point = point
        self.calls.append(point["point_id"])



    def move_joint(self, pose, allow_incomplete=False, sample=None):
        if pose == RobotPose(**self.system["work_Access_safe_pose"]):
            result = self.step("access")

            if not result.success:
                raise RuntimeError("access failed")

            return {"stop_reason": "TARGET_REACHED"}

        self.calls.append("entry" if pose == RobotPose(**self.point["entry_pose"]) else "ready")

        # 이 대역의 일반 접근은 도달 성공이며, 미도달 차단은 실제 모션 피드백 시험에서 확인한다.
        return {"reached": not allow_incomplete}



    def grip(self, width, force, opening=False, wait_for_completion=False):
        self.calls.append("open" if opening else "hard" if wait_for_completion else "soft")
        return {"measured": {"width_mm": width, "gripper_busy": False}}



    def measure_gripper_width(self):
        self.calls.append("soft_width")
        return {"width_mm": 22.0, "gripper_busy": True}



    def relative(self, direction, distance, entry_guard=False, pull_guard=False):
        self.calls.append("pull" if pull_guard else "additional_entry")

        if pull_guard:
            return {"stop_reason": "PULL_FORCE_LIMIT", "peak_pull_force_n": 15.2,
                    "pull_displacement_mm": 4.0, "pull_width_mm": 16.5}

        return {"stop_reason": "ENTRY_FORCE_LIMIT", "entry_displacement_mm": 2.0}



    def move_linear(self, task, **kwargs):
        self.calls.append("return_entry")
        return {"task": task}



    def open_gripper(self, width, force, sample=None):
        return self.grip(width, force, opening=True)



class RecordedInspection(InspectionSequence):
    """Main 흐름 검증에서 검사 계측 단계만 대역 처리한다. 실제 모션은 별도 검증한다."""



    def run_point(self, point):
        self.motion.configure_point(point)
        return super().run_point(point)



    def close_gripper(self, width, force, wait_for_completion=False):
        return self.motion.grip(width, force, wait_for_completion=wait_for_completion)



    def sample(self):
        return self.motion.measure_gripper_width()



    def contact_move(self, point, kind):
        entry = kind == "ENTRY"
        settings = point["entry_setting" if entry else "pull_setting"]
        direction = self.axis if entry else [-v for v in self.axis]

        return self.motion.relative(direction, settings["max_distance_mm"],
                                    entry_guard=entry, pull_guard=not entry)



class RecordedHomeReturnSequence(HomeReturnSequence):
    """실행 순서 테스트에서는 기록용 장비 단계만 호출한다."""



    def current_tcp(self):
        return self.backend.current_tcp()



    def tcp_is_in_work_area(self, tcp):
        return self.backend.tcp_is_in_work_area(tcp)



    def tcp_is_at_work_access(self, tcp):
        return self.backend.tcp_is_at_work_access(tcp)



    def relax_grip(self):
        return self.backend.relax_grip()



    def safe_escape(self, distance):
        return self.backend.safe_escape(distance)



    def move_safe_route_home(self):
        return self.backend.move_safe_route_home()



class RecordedController(main.MainSequence):
    """Main 정책 테스트에서 장비/레시피 준비 단계를 순서대로 기록한다."""



    def __init__(self, robot, *args, **kwargs):
        super().__init__(robot, *args, **kwargs)
        self.recipes.accept(robot.recipe)
        self.system = robot.system
        self.hmi_available = robot.hmi_available



    def check_devices(self):
        return self.backend.check_robot_operability()



    def check_hmi_communication(self):
        return self.backend.check_hmi_communication()



    def validate_system_recipe(self):
        return self.backend.validate_system_recipe()



    def validate_inspection_recipe(self, recipe_id):
        result = self.backend.validate_inspection_recipe(recipe_id)

        if result.success:
            self.recipes.begin(recipe_id, self.run_id)

        return result



def controller_for(robot, *args, **kwargs):
    return RecordedController(
        robot, *args, home_return_sequence=RecordedHomeReturnSequence, **kwargs,
    )



def test_main_consumes_recipe_api_without_hardware_recipe_storage():
    source = Recipe.load_json(RECIPE)
    backend = SimpleNamespace(
        config=SimpleNamespace(joint_speed_deg_s=0.0),
        system=None,
    )
    recipes = Recipe(PACKAGE / "config/system_recipe.json", [RECIPE])
    controller = main.MainSequence(backend, recipes=recipes, inspection=SimpleNamespace())
    assert controller.check_hmi_communication().code == "HMI_COMM_LOST"
    controller.hmi_available = lambda: True
    assert controller.check_hmi_communication().success
    assert controller.validate_system_recipe().success
    assert backend.config.joint_speed_deg_s == controller.system["joint_speed_deg_s"]
    recipes.accept(source)
    assert controller.validate_inspection_recipe(source["recipe_id"]).success
    assert controller.recipes.snapshot() is not source
    assert not hasattr(backend, "recipe")
    assert controller.recipes.progress()["total_points"] == 2



@pytest.mark.parametrize("failure", [None, "robot", "hmi", "system_recipe", "inspection_recipe"])
def test_01_initialize_short_circuits_failed_check(failure):
    robot = RecordedRobot(failure=failure)
    result = controller_for(robot).work_initialize(robot.recipe["recipe_id"])
    order = ["robot", "hmi", "system_recipe", "inspection_recipe", "robot"]
    expected = order if failure is None else order[:order.index(failure) + 1]
    assert robot.calls == expected
    assert result.success == (failure is None)



def test_01_no_active_points():
    robot = RecordedRobot()

    for point in robot.recipe["points"]:
        point["enabled"] = False

    assert controller_for(robot).work_initialize(robot.recipe["recipe_id"]).code == "NO_ENABLED_POINT"



@pytest.mark.parametrize("inside,expected", [
    (True, ["robot", "relax", "escape:30.0", "access", "home"]),
    (False, ["robot", "home"]),
])
def test_02_home_routes(inside, expected):
    robot = RecordedRobot(inside=inside)
    robot.at_access = False
    assert controller_for(robot).home_return().success
    assert robot.calls == expected



def test_02_access_failure_prevents_home():
    robot = RecordedRobot(failure="access")
    robot.at_access = False

    with pytest.raises(RuntimeError, match="access failed"):
        controller_for(robot).home_return()

    assert robot.calls == ["robot", "relax", "escape:30.0", "access"]



def test_02_access_and_home_checkpoints():
    robot = RecordedRobot()
    robot.at_access = False
    checkpoints = []
    controller = controller_for(robot)
    controller.checkpoint = checkpoints.append
    result = controller.home_return()
    assert result.data["route"] == "WORK_AREA_ESCAPE"
    assert checkpoints == ["GRIP_RELAXED", "SAFE_ESCAPE_DONE", "WORK_ACCESS_REACHED", "HOME_REACHED"]



def completed_recipe():
    from copy import deepcopy
    data = Recipe.load_json(RECIPE)
    template = data["points"][0]
    data["points"] = [dict(deepcopy(template), point_id=key) for key in ("P1", "P2", "P3")]
    recipes = Recipe()
    recipes.accept(data)
    recipes.begin(data["recipe_id"], 1)

    for result in InspectionResult:
        point = recipes.next_point()
        key = point["point_id"]
        recipes.mark_pending(1, key)
        recipes.complete_point(1, InspectionPointResult(key, transition={}, adaptive_grip={"adaptive_grip_done": True}))
        recipes.apply_judgments(1, {key: {"run_id": 1, "point_id": key, "result": result.value,
            "reason": "", "judgment_status": "ERROR" if result == InspectionResult.SYSTEM_ERROR else "COMPLETED",
            "sequence_status": "SUCCESS"}})
        recipes.mark_logs_saved(1, [key])

    return recipes



def test_07_three_results_can_complete_job():
    result = completed_recipe().completion()
    assert result.success
    assert result.data["counts"] == {"PASS": 1, "FAIL": 1, "SYSTEM_ERROR": 1}



@pytest.mark.parametrize("missing", ["point", "motion", "result", "log", "pending", "iteration"])
def test_07_incomplete_conditions(missing):
    recipes = completed_recipe()

    if missing == "point":
        del recipes._results["P1"]

    elif missing == "motion":
        recipes._results["P1"].motion_status = SequenceStatus.INCOMPLETE

    elif missing == "result":
        recipes._results["P1"].result = None

    elif missing == "log":
        recipes._results["P1"].log_saved = False

    elif missing == "pending":
        recipes._pending.add("P1")

    else:
        recipes._completed = 2

    assert not recipes.completion().success



def test_pause_resume_preserves_context_and_rechecks_robot(tmp_path):
    robot = RecordedRobot()
    controller = controller_for(robot, tmp_path)
    controller.context = JobContext("LAN")
    original = controller.context
    controller.state = SystemState.RUNNING
    assert controller.pause().success
    assert controller.state == SystemState.PAUSE_REQUEST



    def resume_at_checkpoint():
        assert controller.state == SystemState.PAUSED
        assert controller.context is original
        assert controller.resume().success



    controller.pump = resume_at_checkpoint
    controller.collect_results = lambda: None  # 이 검증은 판정 없이 Pause/Resume 상태만 확인한다.
    controller.checkpoint("READY_REACHED")
    assert controller.state == SystemState.RUNNING
    assert controller.context.resume_point == "READY_REACHED"
    assert robot.calls == ["robot"]



def test_communication_recovery_requires_explicit_resume(tmp_path):
    controller = controller_for(RecordedRobot(), tmp_path)
    controller.state = SystemState.RUNNING
    controller.communication_lost()
    controller.state = SystemState.PAUSED
    assert not controller.resume().success
    controller.communication_recovered()
    assert controller.pause_requested.is_set()
    assert controller.resume().success



def test_communication_timeout_requests_stop(monkeypatch, tmp_path):
    controller = controller_for(RecordedRobot(), tmp_path)
    controller.comm_lost_at = 10.0
    monkeypatch.setattr("cable_inspection.sequence.main.seq_main.time.monotonic", lambda: 40.0)
    from cable_inspection.sequence import JobStopped

    with pytest.raises(JobStopped, match="COMM_ERROR"):
        controller.poll_control()



def test_recipe_execution_copy_is_isolated_from_received_input():
    source = Recipe.load_json(RECIPE)
    recipes = Recipe(recipe_paths=[RECIPE])
    recipes.accept(source)
    first = recipes.get(source["recipe_id"])
    source["points"][0]["pull_setting"]["force_limit_n"] = 99.0
    first["points"].reverse()
    first["points"][0]["pull_setting"]["force_limit_n"] = 88.0
    second = recipes.get(source["recipe_id"])
    assert [p["point_id"] for p in second["points"]] == ["LAN_L2", "LAN_L5"]
    assert second["points"][0]["pull_setting"]["force_limit_n"] == 15.0



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
    point = Recipe.load_json(RECIPE)["points"][0]
    from cable_inspection.sequence.common.geometry import reverse_tool_axis
    point["entry_pose"]["task"][3:] = abc
    assert reverse_tool_axis(point["entry_pose"]["task"][3:], [0., 0., -1.]) == pytest.approx(expected, abs=1e-12)



def test_legacy_direction_cannot_override_entry_abc(tmp_path):
    raw = json.loads(RECIPE.read_text())
    raw["points"]["LAN_L2"]["entry_direction"] = [1.0, 0.0, 0.0]
    path = tmp_path / "legacy_recipe.json"
    path.write_text(json.dumps(raw))
    loaded = Recipe.load_json(path)
    assert "entry_direction" not in loaded["points"][0]



def test_system_recipe_without_coordinates_is_rejected(tmp_path):
    data = json.loads((PACKAGE / "config/system_recipe.json").read_text())
    data["home_pose"] = {"task": None, "joint": None}
    path = tmp_path / "missing_home.json"
    path.write_text(json.dumps(data))

    with pytest.raises(ValueError, match="home_pose"):
        Recipe(system_path=path).system_recipe()



@pytest.mark.parametrize("actual,target,expected", [
    ([0, 180, 0], [20, 180, 20], 0.0),
    ([0, 180, 0], [30, 180, 30], 0.0),
    ([0, 180, 0], [20, 180, 30], 10.0),
    ([0, 0, 0], [0, 0, 360], 0.0),
    ([0, 180, 0], [0, 179, 0], 1.0),
    ([0, 0, 0], [0, 180, 0], 180.0),
])
def test_orientation_uses_actual_rotation_difference(actual, target, expected):
    from cable_inspection.sequence.common.geometry import orientation_error_deg
    assert orientation_error_deg(actual, target) == pytest.approx(expected, abs=1e-5)



def test_motion_accepts_equivalent_zyz_pose_without_timeout():
    from cable_inspection.sequence.common.motion import SequenceMotion
    from cable_inspection.sequence.common.data_models.robot_runtime_config import RobotRuntimeConfig
    measured = {"tcp": [589.95, 186.61, 98.98, 0.0, 180.0, 0.0],
                "wrench_base": [0.0] * 6}
    robot = SimpleNamespace(
        config=RobotRuntimeConfig(), check_client=None,
        sample=lambda: measured,
        robot=SimpleNamespace(motion_status=lambda: 0),
    )
    target = [589.95, 186.61, 98.98, 20.0, 180.0, 20.0]
    result = SequenceMotion._monitor(robot, target, measured)
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
            Recipe(system_path=path).system_recipe()

    else:
        assert Recipe(system_path=path).system_recipe() == data



class DelayedJudgment:
    """요청만 모았다가 Work Finish에서 판정을 전달해 비동기 흐름을 확인한다."""



    def __init__(self, robot):
        self.robot = robot
        self.publisher = SimpleNamespace(get_subscription_count=lambda: 1)
        self.requests = []
        self.results = {}
        self.closed = False



    def reset(self, run_id):
        self.requests.clear()
        self.results.clear()



    def is_ready(self):
        return True



    def submit(self, request):
        self.robot.calls.append("judgment_request")
        self.requests.append(request)



    def deliver(self):
        for request in self.requests:
            judgment = InspectionJudgmentNode.judge_request(SimpleNamespace(termination_reason=request.termination_reason, peak_pull_force_n=request.peak_pull_force_n, pull_displacement_mm=request.pull_displacement_mm, required_force_n=request.required_force_n, soft_width_mm=request.soft_width_mm, pull_width_mm=request.pull_width_mm, normal_displacement_limit_mm=5.0))
            message = InspectionJudgmentNode._result_message(request, judgment)
            self.results[request.point_id] = dict(message_to_ordereddict(message))



    def snapshot(self):
        return self.results.copy()



    def record_error(self, request):
        message = InspectionJudgmentNode._result_message(request, InspectionJudgmentNode.judge_request(request))
        self.results[request.point_id] = dict(message_to_ordereddict(message))
        self.requests = [item for item in self.requests if item.point_id != request.point_id]



    def close(self):
        self.closed = True



def test_00_initialization_failure_never_starts_motion(monkeypatch, tmp_path):
    robot = RecordedRobot(failure="system_recipe")
    judgment = DelayedJudgment(robot)
    controller = controller_for(robot, tmp_path, inspection=RecordedInspection(robot, judgment=judgment))
    result = controller.run(robot.recipe["recipe_id"])
    assert result.code == "INIT_FAIL"
    assert controller.state == SystemState.SYSTEM_READY
    assert robot.calls == ["robot", "hmi", "system_recipe"]
    assert not judgment.closed and robot.stream is None



@pytest.mark.parametrize("stop_after_first", [False, True])
def test_00_job_order_delayed_results_and_stop(monkeypatch, tmp_path, stop_after_first):
    robot = RecordedRobot()
    judgment = DelayedJudgment(robot)
    controller = controller_for(robot, tmp_path, inspection=RecordedInspection(robot, judgment=judgment))
    original_configure = robot.configure_point



    def configure(point):
        original_configure(point)

        if stop_after_first and point["point_id"] == "LAN_L5":
            controller.stop()
            controller.poll_control()



    robot.configure_point = configure



    def deliver_at_finish():
        assert controller.recipes.progress()["execution_index"] == 2
        assert robot.calls[-1] == "access"
        assert not judgment.results  # L2 결과를 기다리지 않고 L5까지 진행했다.
        judgment.deliver()



    controller.pump = deliver_at_finish
    result = controller.run(robot.recipe["recipe_id"])
    assert not judgment.closed and robot.stream is None
    assert controller.context is None
    status = json.loads((controller.output / "status.json").read_text())

    if stop_after_first:
        assert result.code == "STOP"
        assert controller.state == SystemState.STOPPED
        assert robot.calls[-2:] == ["LAN_L5", "stop"]
        assert robot.calls.count("home") == 0  # START와 STOP 모두 Home을 자동 실행하지 않는다.
        assert status["completed"] is False

        return

    assert result.success, result.message
    assert controller.state == SystemState.SYSTEM_READY
    cycle = ["open", "ready", "entry", "soft", "additional_entry", "soft_width",
             "hard", "pull", "judgment_request", "open", "return_entry", "ready"]
    assert robot.calls == (
        ["robot", "hmi", "system_recipe", "inspection_recipe", "robot",
         "LAN_L2"] + cycle + ["LAN_L5"] + cycle +
        ["access", "hmi"])
    assert result.data["counts"] == {"PASS": 2, "FAIL": 0, "SYSTEM_ERROR": 0}
    assert status["completed"] is True
    records = json.loads((controller.output / "inspection_results.json").read_text())
    assert list(records) == ["LAN_L2", "LAN_L5"]
    assert all(record["result"] == "PASS" for record in records.values())



@pytest.mark.parametrize("failure", [None, "motion", "joint"])
def test_home_uses_single_move_and_checks_all_joints(failure):
    from cable_inspection.sequence.common.motion import SequenceMotion
    targets = []
    robot = SimpleNamespace(
        system={"home_pose": {"task": [0.0] * 6, "joint": [0.0] * 6},
                "home_joint_tolerance_deg": 0.1},
        robot=SimpleNamespace(read_joints=lambda: [0.0] * 5 + [1.0 if failure == "joint" else 0.0]),
    )



    def move(pose):
        targets.append(pose.joint[:])

        if failure == "motion":
            raise RuntimeError("motion failed")



    robot.move_joint = move

    if failure:
        with pytest.raises(RuntimeError):
            HomeReturnSequence(robot, lambda _: None, lambda: None, robot.system).move_home_pose()

    else:
        assert HomeReturnSequence(robot, lambda _: None, lambda: None, robot.system).move_home_pose().success

    assert targets == [[0.0] * 6]



def test_operating_home_route_matches_confirmed_direct_zero_joint_policy():
    data = Recipe(system_path=PACKAGE / "config/system_recipe.json").system_recipe()
    assert data["safe_home_route"] == [data["home_pose"]]
    assert data["home_pose"]["joint"] == [0.0] * 6
    assert data["tool_approach_axis"] == [0.0, 0.0, 1.0]
    assert data["relax_width_mm"] == 25.0



@pytest.mark.parametrize('stage', ['Soft', 'Hard'])
@pytest.mark.parametrize('recovery_failure', [None, 'open', 'width', 'entry', 'ready', 'stop', 'communication'])
def test_grip_timeout_recovers_to_next_point_or_stops_on_recovery_failure(
        monkeypatch, tmp_path, stage, recovery_failure):
    from cable_inspection.sequence.inspection.data_models.grip_completion_timeout import GripCompletionTimeout
    robot = RecordedRobot()
    robot.config = SimpleNamespace(width_tolerance_mm=2.5)
    first, second = robot.enabled_point_ids(robot.recipe["recipe_id"])
    original_measure, original_grip = robot.measure_gripper_width, robot.grip
    original_linear, original_joint = robot.move_linear, robot.move_joint
    triggered = []



    def fail_grip():
        triggered.append(stage)
        raise GripCompletionTimeout(stage, {'width_mm':24.9, 'gripper_busy':True})



    def measure():
        if stage == 'Soft' and robot.point["point_id"] == first:
            fail_grip()

        return original_measure()



    def grip(*args, **kwargs):
        if robot.phase == 'GRIP_FAILURE_RECOVERY':
            if recovery_failure == 'stop':
                raise main.JobStopped('STOP')

            if recovery_failure in ('open', 'communication'):
                raise TimeoutError(recovery_failure)

        if (stage == 'Hard' and robot.point["point_id"] == first
                and kwargs.get('wait_for_completion')):
            fail_grip()

        result = original_grip(*args, **kwargs)

        if robot.phase == 'GRIP_FAILURE_RECOVERY':
            # Open 폭이 맞으면 기록상 Busy=True여도 복귀를 진행한다.
            result['measured']['gripper_busy'] = True

            if recovery_failure == 'width':
                result['measured']['width_mm'] -= 5

        return result



    def linear(task, **kwargs):
        if robot.phase == 'GRIP_FAILURE_RECOVERY' and recovery_failure == 'entry':
            raise TimeoutError('return entry')

        return original_linear(task)



    def joint(pose, allow_incomplete=False, **kwargs):
        if robot.phase == 'GRIP_FAILURE_RECOVERY' and recovery_failure == 'ready':
            raise TimeoutError('return ready')

        return original_joint(pose, allow_incomplete)



    robot.measure_gripper_width, robot.grip = measure, grip
    robot.move_linear, robot.move_joint = linear, joint
    judgment = DelayedJudgment(robot)
    controller = controller_for(robot, tmp_path, inspection=RecordedInspection(robot, judgment=judgment))
    controller.pump = judgment.deliver
    result = controller.run(robot.recipe["recipe_id"])
    assert triggered == [stage]

    if recovery_failure:
        assert not result.success
        assert second not in robot.calls
        assert 'pull' not in robot.calls
        assert 'stop' in robot.calls

    else:
        assert result.success, result.message
        assert robot.calls.count('pull') == 1  # 다음 포인트에서만 Pull
        assert 'stop' not in robot.calls
        assert result.data['counts'] == {'PASS':1, 'FAIL':0, 'SYSTEM_ERROR':1}
        between = robot.calls[robot.calls.index(first):robot.calls.index(second)]
        assert between[-3:] == ['open', 'return_entry', 'ready']
        records = json.loads((controller.output/'inspection_results.json').read_text())
        assert records[first]['pull_inspection']['skipped']
        assert not records[first]['adaptive_grip']['adaptive_grip_done']
        assert records[first]['result'] == 'SYSTEM_ERROR'
        assert stage.upper() + '_GRIP_TIMEOUT' in records[first]['reason']



def test_02_current_work_access_goes_directly_home():
    robot = RecordedRobot(inside=True)
    result = controller_for(robot).home_return()
    assert result.success and result.data['route'] == 'VERIFIED_ACCESS_HOME'
    assert robot.calls == ['robot', 'home']



def test_02_work_access_drift_uses_escape_route():
    robot = RecordedRobot(inside=True)
    robot.at_access = False
    result = controller_for(robot).home_return()
    assert result.success and result.data['route'] == 'WORK_AREA_ESCAPE'
    assert robot.calls == ['robot', 'relax', 'escape:30.0', 'access', 'home']



def test_work_access_pose_verification_checks_position_and_orientation():
    from cable_inspection.sequence.common.motion import SequenceMotion
    target = [532.25, 34.8, 497.08, 2.23, 117.34, -2.48]
    robot = SimpleNamespace(robot=SimpleNamespace(mode='real'), system={'work_Access_safe_pose':{'task':target}},
        config=SimpleNamespace(position_tolerance_mm=0.5, orientation_tolerance_deg=1.0))
    assert HomeReturnSequence(robot, lambda _: None, lambda: None, robot.system).tcp_is_at_work_access(target)
    assert not HomeReturnSequence(robot, lambda _: None, lambda: None, robot.system).tcp_is_at_work_access([target[0]+1., *target[1:]])
    assert not HomeReturnSequence(robot, lambda _: None, lambda: None, robot.system).tcp_is_at_work_access([*target[:3], target[3]+10., *target[4:]])



def test_virtual_work_access_verifies_joints_despite_emulator_task_offset():
    from cable_inspection.sequence.common.motion import SequenceMotion
    target = [4.12, -15.08, 86.39, -2.35, 46.06, 0.0]
    robot = SimpleNamespace(robot=SimpleNamespace(mode='virtual', read_joints=lambda: target[:]),
        system={'work_Access_safe_pose': {'task': [532.25, 34.8, 497.08, 2.23, 117.34, -2.48],
                                          'joint': target}},
        )
    emulator_tcp = [532.64, 34.89, 498.71, 2.22, 117.33, -2.51]
    assert HomeReturnSequence(robot, lambda _: None, lambda: None, robot.system).tcp_is_at_work_access(emulator_tcp)
    robot.robot.read_joints = lambda: [target[0] + 0.2, *target[1:]]
    assert not HomeReturnSequence(robot, lambda _: None, lambda: None, robot.system).tcp_is_at_work_access(emulator_tcp)



def test_two_jobs_reuse_judgment_connection_and_reset_results(tmp_path):
    """연속 START가 통신을 재생성하지 않고 새 run_id와 결과로 시작하는지 확인한다."""
    robot = RecordedRobot()
    judgment = DelayedJudgment(robot)
    controller = controller_for(robot, tmp_path, inspection=RecordedInspection(robot, judgment=judgment))
    controller.pump = judgment.deliver
    outputs = []

    for run_id in (101, 102):
        result = controller.run(robot.recipe["recipe_id"], run_id=run_id)
        assert result.success, result.message
        assert controller.inspection.judgment is judgment and not judgment.closed
        assert len(judgment.requests) == 2
        assert {value['run_id'] for value in judgment.results.values()} == {run_id}
        assert controller.recipes.progress()['progress_percent'] == 100
        assert robot.stream is None
        outputs.append(controller.output)

    assert outputs[0] != outputs[1]



@pytest.mark.parametrize('state', [SystemState.SYSTEM_READY, SystemState.STOPPED, SystemState.ERROR])
def test_new_job_from_idle_states_does_not_require_initial_home(tmp_path, state):
    robot = RecordedRobot()
    judgment = DelayedJudgment(robot)
    controller = controller_for(robot, tmp_path, inspection=RecordedInspection(robot, judgment=judgment))
    controller.state = state
    controller.stop_requested.set()  # 새 START는 종료한 Job의 STOP 신호를 초기화한다.
    controller.pump = judgment.deliver
    result = controller.run(robot.recipe['recipe_id'])
    assert result.success, result.message
    assert 'home' not in robot.calls[:robot.calls.index('LAN_L2')]
    assert robot.calls.count('home') == 0  # 검사 시작·완료 모두 자동 Home을 실행하지 않는다.
    assert robot.calls[-2:] == ['access', 'hmi']
    assert 'Work Access' in result.message
    assert controller.state == SystemState.SYSTEM_READY



def test_finish_access_failure_does_not_complete_job_or_move_home(tmp_path):
    robot = RecordedRobot(failure='access')
    judgment = DelayedJudgment(robot)
    controller = controller_for(robot, tmp_path, inspection=RecordedInspection(robot, judgment=judgment))
    controller.pump = judgment.deliver
    result = controller.run(robot.recipe['recipe_id'])
    assert not result.success and result.code == 'JOB_ERROR'
    assert controller.state == SystemState.ERROR
    assert robot.calls.count('pull') == 2
    assert 'home' not in robot.calls
    assert 'stop' in robot.calls
    status = json.loads((controller.output/'status.json').read_text())
    assert status['completed'] is False



# 기능: 접근 예외가 Main에서 정지·포인트 오류 기록·Job 오류로 처리되는지 검증한다.
#     tmp_path: 실행 기록을 저장할 시험 전용 폴더.
#     반환: 없음. 후속 파지/다음 포인트 미실행과 오류 기록을 확인한다.
def test_approach_failure_stops_job_and_records_point_error(tmp_path):
    robot = RecordedRobot()
    judgment = DelayedJudgment(robot)
    controller = controller_for(robot, tmp_path, inspection=RecordedInspection(robot, judgment=judgment))
    controller.pump = judgment.deliver
    move_joint = robot.move_joint

    # 기능: 첫 검사포인트의 Entry 접근에만 목표 도달 실패를 전달한다.
    #     pose: 이동 목표. kwargs: 호출부의 sample 등 선택 인자.
    #     반환: 정상 이동 결과. Entry 접근이면 TimeoutError.
    def fail_entry_approach(pose, **kwargs):
        if robot.point is not None and pose == RobotPose(**robot.point['entry_pose']):
            raise TimeoutError('Entry 접근 미도달')

        return move_joint(pose, **kwargs)

    robot.move_joint = fail_entry_approach
    result = controller.run(robot.recipe['recipe_id'])
    first, second = robot.enabled_point_ids(robot.recipe['recipe_id'])[:2]

    assert not result.success and result.code == 'JOB_ERROR'
    assert controller.state == SystemState.ERROR
    assert 'stop' in robot.calls
    assert not any(call in robot.calls for call in ('soft', 'hard', 'pull', second))
    assert controller.context is None
    error = json.loads((controller.output / 'point_error.json').read_text())
    status = json.loads((controller.output / 'status.json').read_text())
    assert error['point_id'] == first and 'Entry 접근 미도달' in error['reason']
    assert not status['completed'] and status['state'] == 'ERROR'
