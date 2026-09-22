"""Sequence #03: 검사포인트의 Ready Pose와 Entry Pose로 이동한다."""


class PointTransitionSequence:
    """Point Transition의 이동 순서만 관리한다."""

    def __init__(self, hardware):
        self.hardware = hardware

    def run(self, point):
        ready = self.hardware.move_joint(point.ready_pose)
        entry = self.hardware.move_joint(point.entry_pose, allow_incomplete=True)
        return {"ready": ready, "entry": entry}
