"""실제 검사포인트 반복 순서를 검증한다."""

from types import SimpleNamespace

from cable_pkg.sequence.inspection.seq_00_inspection import InspectionSequence


class HardwareDouble:
    def __init__(self):
        self.calls = []
        self.phase = ""

    def configure_point(self, point):
        self.calls.append(("configure", point.point_id))

    def move_joint(self, pose, allow_incomplete=False):
        self.calls.append(("joint", pose.name, allow_incomplete))
        return {"pose": pose.name}

    def grip(self, width, force, opening=False, wait_for_completion=False):
        self.calls.append(("grip", width, force, opening, wait_for_completion))
        return {"measured": {"width_mm": 16.0, "timestamp": "now"}}

    def relative(self, direction, distance, entry_guard=False, pull_guard=False):
        self.calls.append(("relative", direction, distance, entry_guard, pull_guard))
        return {"stop_reason": "DONE"}

    def move_linear(self, task):
        self.calls.append(("linear", task))
        return {"task": task}


class Point:
    def __init__(self, point_id):
        self.point_id = point_id
        self.enabled = True
        self.ready_pose = SimpleNamespace(name=f"{point_id}_ready")
        self.entry_pose = SimpleNamespace(name=f"{point_id}_entry", task=[point_id])
        self.grip_setting = {
            "soft_close_width_mm": 22.0, "soft_open_width_mm": 25.0,
            "hard_width_mm": 16.0, "soft_force_n": 10.0,
            "hard_force_n": 20.0,
        }
        self.entry_setting = {"max_distance_mm": 5.0}
        self.pull_setting = {"max_distance_mm": 25.0}

    def normalized_entry_direction(self):
        return [0.0, -1.0, 0.0]


def test_recipe_iterates_point_transition_adaptive_pull_and_return():
    hardware = HardwareDouble()
    recipe = SimpleNamespace(
        points={"L5": Point("L5"), "L2": Point("L2")},
        execution_order=["L2", "L5"],
    )

    results = InspectionSequence(hardware).run(recipe)

    assert list(results) == ["L2", "L5"]
    for point_id in ("L2", "L5"):
        start = 10 * (0 if point_id == "L2" else 1)
        assert hardware.calls[start:start + 9] == [
            ("configure", point_id),
            ("joint", f"{point_id}_ready", False),
            ("joint", f"{point_id}_entry", True),
            ("grip", 22.0, 10.0, False, False),
            ("relative", [0.0, -1.0, 0.0], 5.0, True, False),
            ("grip", 16.0, 20.0, False, True),
            ("relative", [-0.0, 1.0, -0.0], 25.0, False, True),
            ("grip", 25.0, 10.0, True, False),
            ("linear", [point_id]),
        ]
        assert hardware.calls[start + 9][0] == "joint"
