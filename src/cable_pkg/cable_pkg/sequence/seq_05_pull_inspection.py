"""Sequence #05: Pull을 측정하고 Entry와 Ready로 복귀한다."""


class PullInspectionSequence:
    """Pull Motion과 검사포인트 복귀 순서를 관리한다."""

    def __init__(self, hardware):
        self.hardware = hardware

    def run(self, point, config, grip_width_hard):
        direction = [-value for value in point.normalized_entry_direction()]
        pull = self.hardware.relative(direction, config.pull_mm)
        pull["grip_width_hard_mm"] = grip_width_hard
        opened = self.hardware.grip(
            point.grip_setting["soft_open_width_mm"], config.soft_force_n,
            opening=True,
        )
        entry = self.hardware.move_linear(point.entry_pose.task)
        ready = self.hardware.move_joint(point.ready_pose)
        return {"pull": pull, "soft_open": opened,
                "return_entry": entry, "return_ready": ready}
