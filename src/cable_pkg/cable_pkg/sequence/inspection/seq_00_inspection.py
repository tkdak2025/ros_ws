"""검사포인트의 접근, 파지, Pull, 복귀를 한 흐름으로 실행한다."""

from cable_pkg.data_models.inspection_models import (
    AdaptiveGripResult,
    PointCycleResult,
)


class InspectionSequence:
    """Inspection Recipe 순서대로 각 검사포인트의 전체 Cycle을 수행한다."""

    def __init__(self, hardware, should_run_point=lambda _index, _total, _point: True):
        self.hardware = hardware
        self.should_run_point = should_run_point

    def run(self, recipe):
        """활성 포인트를 execution_order 순서대로 한 번씩 실행한다."""
        points = [
            recipe.points[point_id]
            for point_id in recipe.execution_order
            if recipe.points[point_id].enabled
        ]
        results = {}
        for index, point in enumerate(points, start=1):
            if self.should_run_point(index, len(points), point):
                results[point.point_id] = self.run_point(point)
        return results

    def run_point(self, point):
        """한 포인트에서 접근부터 Ready 복귀까지 연속 실행한다."""
        self.hardware.configure_point(point)
        transition = self.point_transition(point)
        adaptive = self.adaptive_grip(point)
        pull = self.pull_inspection(point, adaptive.grip_width_hard)
        return PointCycleResult(transition, adaptive, pull)

    def point_transition(self, point):
        """#03: Ready Pose를 거쳐 Entry Pose로 이동한다."""
        self.hardware.phase = "SEQ_03_POINT_TRANSITION"
        ready = self.hardware.move_joint(point.ready_pose)
        entry = self.hardware.move_joint(point.entry_pose, allow_incomplete=True)
        return {"ready": ready, "entry": entry}

    def adaptive_grip(self, point):
        """#04: Soft Grip 상태로 추가 진입한 뒤 Hard Grip한다."""
        self.hardware.phase = "SEQ_04_ADAPTIVE_GRIP"
        self.hardware.grip(
            point.grip_setting["soft_close_width_mm"],
            point.grip_setting["soft_force_n"],
        )
        entry = self.hardware.relative(
            point.normalized_entry_direction(),
            point.entry_setting["max_distance_mm"],
            entry_guard=True,
        )
        hard = self.hardware.grip(
            point.grip_setting["hard_width_mm"],
            point.grip_setting["hard_force_n"],
            wait_for_completion=True,
        )
        measured = hard["measured"]
        return AdaptiveGripResult(
            entry=entry,
            hard_grip=hard,
            grip_width_hard=measured["width_mm"],
            grip_width_hard_timestamp=measured["timestamp"],
        )

    def pull_inspection(self, point, grip_width_hard):
        """#05: Pull을 측정하고 Entry Pose와 Ready Pose로 복귀한다."""
        self.hardware.phase = "SEQ_05_PULL_INSPECTION"
        pull_direction = [-value for value in point.normalized_entry_direction()]
        pull = self.hardware.relative(
            pull_direction,
            point.pull_setting["max_distance_mm"],
            pull_guard=True,
        )
        pull["grip_width_hard_mm"] = grip_width_hard
        opened = self.hardware.grip(
            point.grip_setting["soft_open_width_mm"],
            point.grip_setting["soft_force_n"],
            opening=True,
        )
        entry = self.hardware.move_linear(point.entry_pose.task)
        ready = self.hardware.move_joint(point.ready_pose)
        return {
            "pull": pull,
            "soft_open": opened,
            "return_entry": entry,
            "return_ready": ready,
        }
