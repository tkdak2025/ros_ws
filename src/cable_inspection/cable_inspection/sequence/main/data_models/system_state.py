"""설계에서 확정한 상위 시스템 상태."""

from __future__ import annotations
from enum import Enum



class SystemState(str, Enum):
    """설계에서 확정한 상위 시스템 상태."""

    SYSTEM_READY = "SYSTEM_READY"
    RUNNING = "RUNNING"
    PAUSE_REQUEST = "PAUSE_REQUEST"
    PAUSED = "PAUSED"
    STOPPED = "STOPPED"
    ERROR = "ERROR"
