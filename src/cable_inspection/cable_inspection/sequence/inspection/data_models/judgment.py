"""검사 판정 결과 데이터."""

from dataclasses import dataclass
from cable_inspection.sequence.inspection.data_models.judgment_status import JudgmentStatus
from cable_inspection.sequence.common.data_models.sequence_status import SequenceStatus
from cable_inspection.sequence.inspection.data_models.inspection_result import InspectionResult



@dataclass(frozen=True)
class Judgment:
    """#06이 생성하는 제품 판정과 시퀀스 처리 상태."""

    status: JudgmentStatus
    sequence_status: SequenceStatus
    result: InspectionResult | None
    reason: str
    reason_code: str = ""
