"""PAUSE/RESUME 동안에만 보존하는 현재 작업 정보."""

from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime
from cable_inspection.sequence.common.data_models.sequence_status import SequenceStatus



@dataclass
class JobContext:
    """PAUSE/RESUME 동안에만 보존하는 현재 작업 정보."""

    recipe_id: str
    current_sequence: str = "WORK_INITIALIZE"
    resume_point: str = ""
    job_id: str = ""
    state: SequenceStatus = SequenceStatus.IDLE
    start_time: datetime | None = None
    end_time: datetime | None = None
