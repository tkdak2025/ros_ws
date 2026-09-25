"""JudgmentStatus 데이터 정의."""

from __future__ import annotations
from enum import Enum



class JudgmentStatus(str, Enum):
    PENDING = "PENDING"
    COMPLETED = "COMPLETED"
    ERROR = "ERROR"
