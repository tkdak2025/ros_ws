"""검사포인트 한 개의 #03, #04, #05 동작을 조합한다."""

from dataclasses import dataclass

from .adaptive_grip_sequence import AdaptiveGripSequence


@dataclass(frozen=True)
class PointCycleResult:
    transition: dict
    adaptive_grip: object
    pull_inspection: dict


class PointTransitionSequence:
    """#03 Ready Pose와 Entry Pose 이동을 담당한다."""

    def __init__(self, point, hardware):
        self.point = point
        self.hardware = hardware

    def run(self):
        ready = self.hardware.move_joint(self.point.ready_pose)
        entry = self.hardware.move_joint(self.point.entry_pose, allow_incomplete=True)
        return {"ready": ready, "entry": entry}


class PullInspectionSequence:
    """#05 Pull 측정 후 Entry와 Ready로 복귀한다."""

    def __init__(self, point, config, hardware):
        self.point = point
        self.config = config
        self.hardware = hardware

    def run(self, grip_width_hard):
        direction = [-value for value in self.point.normalized_entry_direction()]
        pull = self.hardware.relative(direction, self.config.pull_mm)
        pull["grip_width_hard_mm"] = grip_width_hard
        soft_open = self.hardware.grip(
            self.point.grip_setting["soft_open_width_mm"],
            self.config.soft_force_n,
            opening=True,
        )
        return_entry = self.hardware.move_linear(self.point.entry_pose.task)
        return_ready = self.hardware.move_joint(self.point.ready_pose)
        return {
            "pull": pull,
            "soft_open": soft_open,
            "return_entry": return_entry,
            "return_ready": return_ready,
        }


class InspectionPointSequence:
    """검사포인트 한 개를 문서의 #03 → #04 → #05 순서로 실행한다."""

    def __init__(self, point, config, hardware):
        self.transition = PointTransitionSequence(point, hardware)
        self.adaptive_grip = AdaptiveGripSequence(point, config, hardware)
        self.pull = PullInspectionSequence(point, config, hardware)

    def run(self):
        transition = self.transition.run()
        adaptive = self.adaptive_grip.run()
        pull = self.pull.run(adaptive.grip_width_hard)
        return PointCycleResult(transition, adaptive, pull)


class InspectionRecipeSequence:
    """Recipe의 활성 검사포인트를 저장된 순서대로 반복한다."""

    def __init__(self, recipe, config_for_point, hardware):
        self.recipe = recipe
        self.config_for_point = config_for_point
        self.hardware = hardware

    def run(self):
        results = {}
        for point in self.recipe.points.values():
            if not point.enabled:
                continue
            config = self.config_for_point(point.point_id)
            results[point.point_id] = InspectionPointSequence(
                point, config, self.hardware,
            ).run()
        return results
