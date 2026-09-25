"""PullTermination 데이터 정의."""

from __future__ import annotations
from enum import Enum



class PullTermination(str, Enum):
    FORCE_LIMIT = "FORCE_LIMIT"
    MAX_DISTANCE = "MAX_DISTANCE"
    STOPPED_SHORT = "STOPPED_SHORT"
    TIMEOUT = "TIMEOUT"
    MOTION_ERROR = "MOTION_ERROR"
    ROBOT_ERROR = "ROBOT_ERROR"
    TOOL_ERROR = "TOOL_ERROR"
    SAFETY_ERROR = "SAFETY_ERROR"
    INVALID_DATA = "INVALID_DATA"
