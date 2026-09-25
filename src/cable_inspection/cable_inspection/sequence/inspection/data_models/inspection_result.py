"""InspectionResult 데이터 정의."""

from __future__ import annotations
from enum import Enum



class InspectionResult(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"
    SYSTEM_ERROR = "SYSTEM_ERROR"
