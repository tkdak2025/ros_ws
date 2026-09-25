"""새 피드백은 있으나 Soft/Hard 파지 완료를 확인하지 못한 포인트 실패."""

from __future__ import annotations



class GripCompletionTimeout(TimeoutError):
    """새 피드백은 있으나 Soft/Hard 파지 완료를 확인하지 못한 포인트 실패."""



    def __init__(self, stage, measured):
        self.stage = stage
        self.measured = measured
        super().__init__(f"{stage} Grip 동작 완료 확인 실패")
