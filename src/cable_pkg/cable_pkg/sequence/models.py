"""공통 시퀀스의 상태와 실행 결과 모델을 정의한다."""

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class SystemState(str, Enum):
    """설계에서 확정한 상위 시스템 상태."""

    SYSTEM_READY = "SYSTEM_READY"
    RUNNING = "RUNNING"
    PAUSE_REQUEST = "PAUSE_REQUEST"
    PAUSED = "PAUSED"
    STOPPED = "STOPPED"
    ERROR = "ERROR"


@dataclass(frozen=True)
class SequenceResult:
    """공통 시퀀스가 호출자에게 반환하는 성공 여부와 근거."""

    success: bool
    code: str
    message: str
    data: dict[str, Any] = field(default_factory=dict)


@dataclass
class JobContext:
    """PAUSE/RESUME 동안에만 보존하는 현재 작업 정보."""

    recipe_id: str
    enabled_point_ids: list[str]
    current_point_index: int = 0
    current_sequence: str = "WORK_INITIALIZE"
    resume_point: str = ""
    execution_state: dict[str, Any] = field(default_factory=dict)

    @property
    def current_point_id(self) -> str:
        """현재 포인트 ID를 반환하고 포인트가 없으면 빈 문자열을 반환한다."""
        if not self.enabled_point_ids:
            return ""
        if self.current_point_index >= len(self.enabled_point_ids):
            return ""
        return self.enabled_point_ids[self.current_point_index]
