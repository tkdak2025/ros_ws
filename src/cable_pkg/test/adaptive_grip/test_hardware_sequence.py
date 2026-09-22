"""실물 실행기의 제어 흐름 검증. 이 테스트는 실물 서비스를 호출하지 않는다."""

from dataclasses import replace
import json
from pathlib import Path

import pytest

from cable_pkg.test_module.adaptive_grip.sequence import ValidationStage
from cable_pkg.test_module.adaptive_grip_hardware.sequence import HardwareConfig, HardwareSequence
from cable_pkg.test_module.adaptive_grip_hardware.adaptive_grip_sequence import AdaptiveGripSequence
from cable_pkg.test_module.adaptive_grip_hardware.run import main
from cable_pkg.test_module.adaptive_grip_hardware.run import confirm
from cable_pkg.test_module.adaptive_grip_hardware.run import should_inspect_point
from cable_pkg.test_module.adaptive_grip_hardware.recipe import load_trial
from cable_pkg.test_module.grip_stability.grip_stability_data import GripPullRecipe


PACKAGE = Path(__file__).resolve().parents[2] / "cable_pkg"
RECIPE = PACKAGE / "test_module/adaptive_grip_hardware/recipe.json"


class RobotDouble:
    def __init__(self, contact=True, unstable=False):
        self.calls = []
        self.contact = contact
        self.unstable = unstable
        self.phase = "PREFLIGHT"
        self.tcp = [0.0] * 6

    def sample(self):
        return {"tcp": self.tcp[:], "width_mm": 16.0, "timestamp": "test"}

    def grip(self, width, force, opening=False, wait_for_completion=False):
        self.calls.append(("grip", width, force, opening, wait_for_completion))
        return {"command_width_mm": width, "command_force_n": force,
                "measured": self.sample()}

    def move_joint(self, pose, allow_incomplete=False):
        self.calls.append(("joint", pose.joint, allow_incomplete))
        self.tcp = pose.task[:]
        return self.sample()

    def move_linear(self, target, entry_guard=False):
        self.calls.append(("linear", target[:]))
        self.tcp = target[:]
        return {"peak_force_delta_n": 1.0, "stop_reason": "TARGET_REACHED"}

    def relative(self, axis, distance, entry_guard=False):
        self.calls.append(("relative", axis, distance, entry_guard))
        for i in range(3):
            self.tcp[i] += axis[i] * distance
        reason = "ENTRY_FORCE_LIMIT" if entry_guard and self.contact else "ENTRY_DISTANCE_REACHED"
        if entry_guard:
            return {"stop_reason": reason, "end_width_mm": 16.0}
        return {
            "stop_reason": "PULL_FORCE_LIMIT", "end_width_mm": 16.0,
            "peak_pull_force_n": 15.0, "pull_displacement_mm": 4.0,
        }

    def observe(self, duration):
        self.calls.append(("observe", duration))
        sample = self.sample()
        if self.unstable:
            sample["width_mm"] += 10
        return [sample]


@pytest.fixture
def config():
    return HardwareConfig(**load_trial(RECIPE, "LAN_L2")[1])


def make_sequence(config, robot, confirm=lambda stage, data: True):
    return HardwareSequence(GripPullRecipe.load_json(RECIPE), "LAN_L2", config, robot, confirm)


def test_all_physical_stages_use_lan_recipe_and_pull_direction(config, monkeypatch):
    robot = RobotDouble()
    sequence = make_sequence(config, robot)
    monkeypatch.setattr("builtins.input", lambda _: "0.25")
    results = sequence.run(ValidationStage.GRIP_PULL_LOGGING)
    assert [r.stage for r in results] == list(sequence.STAGES)
    assert all(r.passed for r in results)
    assert robot.calls[:3] == [
        ("grip", 25.0, 10.0, True, False),
        ("joint", sequence.source.ready_pose.joint, False),
        ("joint", sequence.source.entry_pose.joint, True),
    ]
    assert ("grip", 22.0, 10.0, False, False) in robot.calls
    assert robot.calls[4] == ("relative", [0, -1, 0], 5.0, True)
    assert ("grip", 16.0, 20.0, False, True) in robot.calls
    assert robot.calls[-4:] == [
        ("relative", [0, 1, 0], 25.0, False),
        ("grip", 25.0, 10.0, True, False),
        ("linear", sequence.source.entry_pose.task),
        ("joint", sequence.source.ready_pose.joint, False),
    ]


def test_distance_reached_without_force_limit_continues_to_hard_grip(config):
    robot = RobotDouble(contact=False)
    sequence = make_sequence(config, robot)
    results = sequence.run(ValidationStage.GRIP_PULL_LOGGING)
    entry = next(r for r in results if r.stage == ValidationStage.DEPTH_COMPENSATION)
    assert entry.passed
    assert entry.data["stop_reason"] == "ENTRY_DISTANCE_REACHED"
    assert ("grip", 16.0, 20.0, False, True) in robot.calls


def test_sequence_04_only_runs_soft_entry_hard(config):
    robot = RobotDouble(contact=True)
    point = GripPullRecipe.load_json(RECIPE).get_point("LAN_L2")

    result = AdaptiveGripSequence(point, config, robot).run()

    assert robot.calls == [
        ("grip", 22.0, 10.0, False, False),
        ("relative", [0.0, -1.0, 0.0], 5.0, True),
        ("grip", 16.0, 20.0, False, True),
    ]
    assert result.adaptive_grip_done
    assert result.entry["stop_reason"] == "ENTRY_FORCE_LIMIT"
    assert result.grip_width_hard == 16.0
    assert result.grip_width_hard_timestamp == "test"


def test_sequence_04_does_not_judge_short_entry_or_actual_width(config):
    robot = RobotDouble(contact=True)
    point = GripPullRecipe.load_json(RECIPE).get_point("LAN_L2")

    result = AdaptiveGripSequence(point, config, robot).run()

    assert result.adaptive_grip_done
    assert not hasattr(result, "inspection_result")


def test_normal_flow_excludes_wiggle_and_grip_inference(config):
    robot = RobotDouble(unstable=True)
    sequence = make_sequence(config, robot)
    sequence.run(ValidationStage.GRIP_PULL_LOGGING)
    assert not any(c[0] == "observe" for c in robot.calls)
    linear_calls = [c for c in robot.calls if c[0] == "linear"]
    assert linear_calls == [("linear", sequence.source.entry_pose.task)]


def test_pull_result_is_judged_without_operator_gate(config):
    confirmed = []
    sequence = make_sequence(
        config, RobotDouble(),
        confirm=lambda stage, data: confirmed.append(stage) or True,
    )
    results = sequence.run(ValidationStage.GRIP_PULL_LOGGING)
    pull_result = results[-1]
    assert pull_result.data["judgment"]["result"] == "PASS"
    assert ValidationStage.GRIP_PULL_LOGGING not in confirmed


def test_ready_entry_is_checked_by_code_without_operator_gate(config):
    confirmed = []
    sequence = make_sequence(
        config, RobotDouble(),
        confirm=lambda stage, data: confirmed.append(stage) or False,
    )
    result = sequence.validate_ready_entry()
    assert result.passed
    assert result.message == "Open/Ready 완료, Entry 상태 확인 완료"
    assert confirmed == []


def test_wiggle_returns_to_origin_after_both_directions(config):
    robot = RobotDouble()
    sequence = make_sequence(config, robot)
    sequence.wiggle()
    assert robot.calls == [
        ("linear", [0.5, 0, 0, 0, 0, 0]), ("linear", [0] * 6),
        ("linear", [-0.5, 0, 0, 0, 0, 0]), ("linear", [0] * 6),
    ]


@pytest.mark.parametrize("value", ["nan", "inf", "0.51", "-0.51"])
def test_invalid_alignment_does_not_move(config, monkeypatch, value):
    robot = RobotDouble()
    sequence = make_sequence(config, robot)
    monkeypatch.setattr("builtins.input", lambda _: value)
    with pytest.raises(ValueError):
        sequence.fine_alignment()
    assert robot.calls == []


@pytest.mark.parametrize("change", [
    {"entry_force_limit_n": None}, {"pull_mm": float("nan")},
    {"wiggle_axis": [0, 0, 0]}, {"soft_force_n": 11}, {"hard_force_n": 5},
    {"sample_period_s": 30}, {"position_tolerance_mm": 0.5}, {"search_mm": 25.1},
])
def test_invalid_conditions_block_construction(config, change):
    with pytest.raises(ValueError):
        make_sequence(replace(config, **change), RobotDouble())


def test_nonperpendicular_wiggle_is_rejected(config):
    with pytest.raises(ValueError, match="수직"):
        make_sequence(replace(config, wiggle_axis=[0, 1, 0]), RobotDouble())


def test_cancel_after_preview_does_not_connect(monkeypatch):
    monkeypatch.setattr("builtins.input", lambda _: "CANCEL")
    assert main(["LAN_L2"]) == 0


def test_point_cycle_choice_repeats_until_numeric(monkeypatch):
    answers = iter(["LAN_L2", "", "1"])
    monkeypatch.setattr("builtins.input", lambda _: next(answers))
    assert should_inspect_point(1, 2, "LAN_L2") is True


def test_recipe_points_are_asked_inside_cycle(monkeypatch):
    from cable_pkg.test_module.adaptive_grip_hardware import run
    import rclpy

    answers = iter(["START", "2", "1"])
    monkeypatch.setattr("builtins.input", lambda _: next(answers))
    monkeypatch.setattr(rclpy, "init", lambda **kwargs: None)
    monkeypatch.setattr(rclpy, "ok", lambda: False)
    executed = []
    monkeypatch.setattr(run, "execute_trial",
                        lambda sequence, config, point_id, hardware: executed.append(point_id) or 0)
    assert main([]) == 0
    assert executed == ["LAN_L5"]


@pytest.mark.parametrize("answer,expected", [("1", True), ("2", False)])
def test_gate_uses_numeric_selection(monkeypatch, answer, expected):
    monkeypatch.setattr("builtins.input", lambda _: answer)
    assert confirm(ValidationStage.READY_ENTRY, {}) is expected


def test_gate_repeats_until_numeric_selection(monkeypatch):
    answers = iter(["PASS", "", "1"])
    monkeypatch.setattr("builtins.input", lambda _: next(answers))
    assert confirm(ValidationStage.READY_ENTRY, {}) is True


def test_invalid_recipe_is_rejected_before_ros_connection(tmp_path):
    data = json.loads(RECIPE.read_text())
    data["points"]["LAN_L2"]["entry_depth_mm"] = None
    path = tmp_path / "invalid.json"
    path.write_text(json.dumps(data))
    with pytest.raises((TypeError, ValueError)):
        load_trial(path, "LAN_L2")


def test_one_recipe_contains_both_points_with_distinct_depths():
    recipe, l2 = load_trial(RECIPE, "LAN_L2")
    _, l5 = load_trial(RECIPE, "LAN_L5")
    assert set(recipe.points) == {"LAN_L2", "LAN_L5"}
    assert l2["search_mm"] == 5.0
    assert l5["search_mm"] == 6.0


def test_added_point_uses_own_pose_and_depth(tmp_path):
    data = json.loads(RECIPE.read_text())
    point = json.loads(json.dumps(data["points"]["LAN_L2"]))
    point.update(point_id="LAN_NEW", point_name="새 포인트", entry_depth_mm=3.0)
    point["entry_pose"]["joint"][0] = 2.0
    data["points"]["LAN_NEW"] = point
    path = tmp_path / "recipe.json"
    path.write_text(json.dumps(data))
    recipe, conditions = load_trial(path, "LAN_NEW")
    assert recipe.get_point("LAN_NEW").entry_pose.joint[0] == 2.0
    assert conditions["search_mm"] == 3.0
