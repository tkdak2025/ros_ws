"""Sequence #04: Soft Grip, Entry, Hard Grip을 수행한다."""

from dataclasses import dataclass


@dataclass(frozen=True)
class AdaptiveGripResult:
    """#05 Pull Inspection으로 전달할 Adaptive Grip 결과다."""

    entry: dict
    hard_grip: dict
    grip_width_hard: float
    grip_width_hard_timestamp: str
    adaptive_grip_done: bool = True


class AdaptiveGripSequence:
    """Point Transition 완료 후 Pull 직전까지의 파지를 담당한다."""

    def __init__(self, point, config, hardware):
        self.point = point
        self.config = config
        self.hardware = hardware

    def soft_grip(self):
        """Recipe 폭과 힘으로 Soft Grip 명령을 보낸다."""
        return self.hardware.grip(
            self.point.grip_setting["soft_close_width_mm"],
            self.config.soft_force_n,
        )

    def enter(self):
        """Soft Grip 상태로 Entry 방향을 탐색하고 종료 사유를 기록한다."""
        return self.hardware.relative(
            self.point.normalized_entry_direction(),
            self.config.search_mm,
            entry_guard=True,
        )

    def hard_grip(self):
        """Hard Grip 완료 직후 실제 RG2 폭과 시각을 저장한다."""
        result = self.hardware.grip(
            self.point.grip_setting["hard_width_mm"],
            self.config.hard_force_n,
            wait_for_completion=True,
        )
        measured = result["measured"]
        result["grip_width_hard_mm"] = measured["width_mm"]
        result["grip_width_hard_timestamp"] = measured["timestamp"]
        return result

    def run(self):
        """#04의 세 동작을 순서대로 실행하고 #05 전달값을 반환한다."""
        self.soft_grip()
        entry = self.enter()
        hard_grip = self.hard_grip()
        return AdaptiveGripResult(
            entry=entry,
            hard_grip=hard_grip,
            grip_width_hard=hard_grip["grip_width_hard_mm"],
            grip_width_hard_timestamp=hard_grip["grip_width_hard_timestamp"],
        )
