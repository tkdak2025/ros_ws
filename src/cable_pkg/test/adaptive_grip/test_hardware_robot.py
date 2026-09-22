"""설치된 ROS 메시지 타입으로 감시 로직 검증. ROS 노드는 생성하지 않는다."""

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

pytest.importorskip("dsr_msgs2")
pytest.importorskip("onrobot_rg_msgs")

from cable_pkg.test_module.adaptive_grip_hardware.robot import HardwareRobot
from cable_pkg.test_module.adaptive_grip_hardware.sequence import HardwareConfig
from cable_pkg.test_module.adaptive_grip_hardware.recipe import load_trial


@pytest.fixture
def hardware():
    path = (Path(__file__).resolve().parents[2]
            / "cable_pkg/test_module/adaptive_grip_hardware/recipe.json")
    robot = HardwareRobot.__new__(HardwareRobot)
    robot.config = HardwareConfig(**load_trial(path, "LAN_L2")[1])
    robot.check_client = object()
    robot._call = Mock(return_value=SimpleNamespace(status=0))
    robot.safe_abort = Mock()
    robot.controlled_stop = Mock()
    robot._wait_idle = Mock()
    return robot


def sample(x=0, force=0):
    return {"tcp": [x, 0, 0, 0, 0, 0], "wrench_base": [force, 0, 0, 0, 0, 0],
            "width_mm": 16.0, "pull_force_n": abs(force)}


def test_idle_alone_does_not_count_as_arrival(hardware, monkeypatch):
    monkeypatch.setattr("cable_pkg.test_module.adaptive_grip_hardware.robot.time.sleep", lambda _: None)
    hardware.sample = Mock(side_effect=[sample(), sample(1)])
    result = hardware._monitor([1, 0, 0, 0, 0, 0], sample())
    assert hardware.sample.call_count == 2
    assert result["displacement_mm"] == 1


def test_contact_stops_and_waits_for_idle(hardware):
    hardware.sample = Mock(side_effect=[sample(0.3, 6), sample(0.4, 6)])
    result = hardware._monitor([5, 0, 0, 0, 0, 0], sample(), entry_guard=True)
    hardware.controlled_stop.assert_called_once()
    hardware._wait_idle.assert_called_once()
    assert result["stop_reason"] == "ENTRY_FORCE_LIMIT"
    assert result["end_tcp"][0] == 0.4


def test_reaching_entry_distance_is_normal_end(hardware):
    hardware.measurement_kind = "ENTRY"
    hardware.measurement_direction = [1, 0, 0]
    hardware.sample = Mock(return_value=sample(5, 1))
    result = hardware._monitor([5, 0, 0, 0, 0, 0], sample(), True)
    assert result["stop_reason"] == "ENTRY_DISTANCE_REACHED"
    assert result["entry_displacement_mm"] == 5
    assert result["pull_displacement_mm"] is None
    hardware.controlled_stop.assert_not_called()


def test_pull_displacement_is_positive_in_pull_direction(hardware):
    hardware.measurement_kind = "PULL"
    hardware.measurement_direction = [-1, 0, 0]
    hardware.sample = Mock(return_value=sample(-12, 1))
    result = hardware._monitor([-12, 0, 0, 0, 0, 0], sample())
    assert result["entry_displacement_mm"] is None
    assert result["pull_displacement_mm"] == 12


def test_pull_stops_at_recipe_force_limit(hardware):
    hardware.measurement_kind = "PULL"
    hardware.measurement_direction = [1, 0, 0]
    hardware.sample = Mock(side_effect=[sample(3, 21), sample(3.1, 21)])
    result = hardware._monitor([25, 0, 0, 0, 0, 0], sample(), pull_guard=True)
    hardware.controlled_stop.assert_called_once()
    hardware._wait_idle.assert_called_once()
    assert result["stop_reason"] == "PULL_FORCE_LIMIT"
    assert result["peak_pull_force_n"] == 21


def test_motion_timeout_is_not_success(hardware, monkeypatch):
    hardware.sample = Mock(return_value=sample())
    monkeypatch.setattr("cable_pkg.test_module.adaptive_grip_hardware.robot.time.monotonic", Mock(side_effect=[0, 21]))
    with pytest.raises(TimeoutError):
        hardware._monitor([5, 0, 0, 0, 0, 0], sample())


def test_entry_target_timeout_is_recorded_and_continues(hardware, monkeypatch):
    hardware.sample = Mock(side_effect=[sample(), sample(0.2)])
    monkeypatch.setattr(
        "cable_pkg.test_module.adaptive_grip_hardware.robot.time.monotonic",
        Mock(side_effect=[0, 21]),
    )
    result = hardware._monitor(
        [5, 0, 0, 0, 0, 0], sample(), allow_incomplete=True,
    )
    assert result["stop_reason"] == "TARGET_NOT_REACHED"
    hardware.controlled_stop.assert_called_once()
    hardware._wait_idle.assert_called_once()


def test_sensor_failure_propagates_without_success(hardware):
    hardware.sample = Mock(side_effect=RuntimeError("Force 상한 초과"))
    with pytest.raises(RuntimeError, match="Force 상한"):
        hardware._monitor([5, 0, 0, 0, 0, 0], sample())


def test_hard_grip_waits_until_busy_motion_finishes(hardware, monkeypatch):
    monkeypatch.setattr("cable_pkg.test_module.adaptive_grip_hardware.robot.time.sleep", lambda _: None)
    hardware._set_gripper = Mock()
    hardware.sample = Mock(side_effect=[
        {"width_mm": 24.0, "gripper_busy": False},
        {"width_mm": 22.0, "gripper_busy": True},
        {"width_mm": 21.0, "gripper_busy": False},
    ])
    result = hardware.grip(16.0, 20.0, wait_for_completion=True)
    assert result["completion_reason"] == "GRIPPER_MOTION_COMPLETED"
    assert result["measured"]["width_mm"] == 21.0


def test_hard_grip_can_complete_at_target_width(hardware):
    hardware._set_gripper = Mock()
    hardware.sample = Mock(side_effect=[
        {"width_mm": 24.0, "gripper_busy": False},
        {"width_mm": 16.1, "gripper_busy": False},
    ])
    result = hardware.grip(16.0, 20.0, wait_for_completion=True)
    assert result["completion_reason"] == "TARGET_WIDTH_REACHED"


def test_missing_system_service_blocks_requests_and_gripper_setup(hardware):
    hardware.system_client = SimpleNamespace(
        wait_for_service=Mock(return_value=False), srv_name="/dsr01/system/get_robot_system")
    hardware._check_robot_mode = Mock()
    hardware.wait_for_services = Mock()
    with pytest.raises(RuntimeError, match="ROS_DOMAIN_ID="):
        hardware.connect()
    hardware._check_robot_mode.assert_not_called()
    hardware.wait_for_services.assert_not_called()


def test_system_service_discovery_precedes_first_query(hardware):
    calls = []
    hardware.system_client = SimpleNamespace(
        wait_for_service=lambda **kwargs: calls.append("discovered") or True)

    def query():
        calls.append("query")
        raise RuntimeError("조회까지 도달")

    hardware._check_robot_mode = query
    with pytest.raises(RuntimeError, match="조회까지 도달"):
        hardware.connect()
    assert calls == ["discovered", "query"]


@pytest.mark.parametrize("sensor_error", [False, True])
def test_runner_stops_and_saves_failed_run(monkeypatch, tmp_path, sensor_error):
    from cable_pkg.test_module.adaptive_grip_hardware import run, robot
    import rclpy

    package = Path(__file__).resolve().parents[2] / "cable_pkg"
    fake_recipe = tmp_path / "a/b/c/d/recipe.json"
    fake_recipe.parent.mkdir(parents=True)
    fake_recipe.write_text(
        (package / "test_module/adaptive_grip_hardware/recipe.json").read_text())
    device = SimpleNamespace(
        phase="PREFLIGHT", connect=Mock(), close=Mock(), safe_abort=Mock(),
        grip=Mock(return_value={}), move_joint=Mock(return_value={}),
        relative=Mock(side_effect=RuntimeError("Entry 측정 실패")),
    )
    if sensor_error:
        device.move_joint.side_effect = RuntimeError("센서 통신 실패")
    monkeypatch.setattr(robot, "HardwareRobot", lambda config, stream: device)
    monkeypatch.setattr(rclpy, "init", Mock())
    monkeypatch.setattr(rclpy, "ok", lambda: False)
    monkeypatch.setattr(run, "RECIPE_PATH", fake_recipe)
    monkeypatch.setattr(run, "RESULTS_DIR", fake_recipe.parent / "measurement_results")
    monkeypatch.setattr("builtins.input", lambda _: "START")
    monkeypatch.setattr(run, "confirm", lambda stage, data: False)
    code = run.main(["LAN_L2"])
    assert code == 1
    device.safe_abort.assert_called_once()
    device.close.assert_called_once()
    output_root = fake_recipe.parent / "measurement_results"
    result_dir, = output_root.iterdir()
    status = json.loads((result_dir / "status.json").read_text())
    assert not status["completed"]
    expected_phase = "V02_READY_ENTRY" if sensor_error else "V03_DEPTH_COMPENSATION"
    assert status["interrupted_phase"] == expected_phase
    assert (result_dir / "inputs.json").is_file()
    gates = json.loads((result_dir / "gates.json").read_text())["results"]
    assert len(gates) == (1 if sensor_error else 3)
