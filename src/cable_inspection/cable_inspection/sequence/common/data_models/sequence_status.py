"""SequenceStatus 데이터 정의."""

from __future__ import annotations
from enum import Enum



class SequenceStatus(str, Enum):
    IDLE = "IDLE"
    RUNNING = "RUNNING"
    SUCCESS = "SUCCESS"
    FAIL = "FAIL"
    INCOMPLETE = "INCOMPLETE"
