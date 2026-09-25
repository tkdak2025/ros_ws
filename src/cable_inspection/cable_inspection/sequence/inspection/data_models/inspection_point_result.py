"""한 포인트의 실행·판정·기록 상태를 한 곳에 보관한다."""

from __future__ import annotations
from dataclasses import dataclass, asdict
from typing import Any
from cable_inspection.sequence.common.data_models.sequence_status import SequenceStatus
from cable_inspection.sequence.inspection.data_models.inspection_result import InspectionResult
from cable_inspection.sequence.inspection.data_models.judgment_status import JudgmentStatus
from cable_inspection.sequence.inspection.data_models.pull_termination import PullTermination



@dataclass
class InspectionPointResult:
    """한 포인트의 실행·판정·기록 상태를 한 곳에 보관한다."""

    point_id: str
    transition: dict | None = None
    adaptive_grip: dict[str, Any] | None = None
    pull_inspection: dict | None = None
    entry_displacement_mm: float | None = None
    peak_pull_force_n: float | None = None
    pull_displacement_mm: float | None = None
    termination_reason: PullTermination | None = None
    judgment_status: JudgmentStatus = JudgmentStatus.PENDING
    sequence_status: SequenceStatus = SequenceStatus.IDLE
    result: InspectionResult | None = None
    reason: str = ""
    motion_status: SequenceStatus = SequenceStatus.IDLE
    adaptive_grip_status: SequenceStatus = SequenceStatus.IDLE
    pull_status: SequenceStatus = SequenceStatus.IDLE
    log_saved: bool = False



    def inspection_dict(self) -> dict[str, Any]:
        """기존 inspection_results.json 필드만 직렬화한다."""
        data = asdict(self)
        names = (
            "point_id", "transition", "adaptive_grip", "pull_inspection",
            "entry_displacement_mm", "peak_pull_force_n", "pull_displacement_mm",
            "termination_reason", "judgment_status", "sequence_status", "result", "reason",
        )

        return {name: data[name] for name in names}
