"""Recipe의 검사포인트를 #03 → #04 → #05 순서로 반복한다."""

from cable_pkg.data_models.inspection_models import PointCycleResult
from .seq_03_point_transition import PointTransitionSequence
from .seq_04_adaptive_grip import AdaptiveGripSequence
from .seq_05_pull_inspection import PullInspectionSequence

class InspectionPointCycle:
    def __init__(self, hardware):
        self.transition = PointTransitionSequence(hardware)
        self.adaptive = AdaptiveGripSequence(hardware)
        self.pull = PullInspectionSequence(hardware)

    def run(self, point, config):
        transition = self.transition.run(point)
        adaptive = self.adaptive.run(point, config)
        pull = self.pull.run(point, config, adaptive.grip_width_hard)
        return PointCycleResult(transition, adaptive, pull)


class InspectionRecipeCycle:
    def __init__(self, hardware, config_for_point):
        self.point_cycle = InspectionPointCycle(hardware)
        self.config_for_point = config_for_point

    def run(self, recipe):
        results = {}
        for point in recipe.points.values():
            if point.enabled:
                results[point.point_id] = self.point_cycle.run(
                    point, self.config_for_point(point.point_id),
                )
        return results
