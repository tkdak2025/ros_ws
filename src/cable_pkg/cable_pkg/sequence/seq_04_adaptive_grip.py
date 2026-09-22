"""Sequence #04: Soft Grip, Entry, Hard Grip을 수행한다."""

from cable_pkg.data_models.inspection_models import AdaptiveGripResult


class AdaptiveGripSequence:
    """Entry Pose 도착 후 Pull 직전까지의 파지를 담당한다."""

    def __init__(self, hardware):
        self.hardware = hardware

    def run(self, point, config):
        self.hardware.grip(
            point.grip_setting["soft_close_width_mm"], config.soft_force_n,
        )
        entry = self.hardware.relative(
            point.normalized_entry_direction(), config.search_mm, entry_guard=True,
        )
        hard = self.hardware.grip(
            point.grip_setting["hard_width_mm"], config.hard_force_n,
            wait_for_completion=True,
        )
        measured = hard["measured"]
        hard["grip_width_hard_mm"] = measured["width_mm"]
        hard["grip_width_hard_timestamp"] = measured["timestamp"]
        return AdaptiveGripResult(
            entry, hard, measured["width_mm"], measured["timestamp"],
        )
