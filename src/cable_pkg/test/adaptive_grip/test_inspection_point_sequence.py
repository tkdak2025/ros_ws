"""실제 검사포인트 반복 순서를 검증한다."""

from types import SimpleNamespace

from cable_pkg.sequence.seq_00_point_cycle import InspectionRecipeCycle


class HardwareDouble:
    def __init__(self):
        self.calls = []

    def move_joint(self, pose, allow_incomplete=False):
        self.calls.append(("joint", pose.name, allow_incomplete))
        return {"pose": pose.name}

    def grip(self, width, force, opening=False, wait_for_completion=False):
        self.calls.append(("grip", width, force, opening, wait_for_completion))
        return {"measured": {"width_mm": 16.0, "timestamp": "now"}}

    def relative(self, direction, distance, entry_guard=False):
        self.calls.append(("relative", direction, distance, entry_guard))
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
            "hard_width_mm": 16.0,
        }

    def normalized_entry_direction(self):
        return [0.0, -1.0, 0.0]


def test_recipe_iterates_point_transition_adaptive_pull_and_return():
    hardware = HardwareDouble()
    recipe = SimpleNamespace(points={"L2": Point("L2"), "L5": Point("L5")})
    config = SimpleNamespace(
        soft_force_n=10.0, hard_force_n=20.0, search_mm=5.0, pull_mm=25.0,
    )

    results = InspectionRecipeCycle(hardware, lambda _: config).run(recipe)

    assert list(results) == ["L2", "L5"]
    for point_id in ("L2", "L5"):
        start = 9 * (0 if point_id == "L2" else 1)
        assert hardware.calls[start:start + 8] == [
            ("joint", f"{point_id}_ready", False),
            ("joint", f"{point_id}_entry", True),
            ("grip", 22.0, 10.0, False, False),
            ("relative", [0.0, -1.0, 0.0], 5.0, True),
            ("grip", 16.0, 20.0, False, True),
            ("relative", [-0.0, 1.0, -0.0], 25.0, False),
            ("grip", 25.0, 10.0, True, False),
            ("linear", [point_id]),
        ]
        assert hardware.calls[start + 8][0] == "joint"
