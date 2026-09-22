"""공통 시퀀스의 상태와 실행 결과 모델을 정의한다."""

from dataclasses import dataclass, field
from enum import Enum
from datetime import datetime
from typing import Any


class SystemState(str, Enum):
    """설계에서 확정한 상위 시스템 상태."""

    SYSTEM_READY = "SYSTEM_READY"
    RUNNING = "RUNNING"
    PAUSE_REQUEST = "PAUSE_REQUEST"
    PAUSED = "PAUSED"
    STOPPED = "STOPPED"
    ERROR = "ERROR"


class SequenceStatus(str, Enum):
    IDLE = "IDLE"
    RUNNING = "RUNNING"
    SUCCESS = "SUCCESS"
    FAIL = "FAIL"
    INCOMPLETE = "INCOMPLETE"


class JudgmentStatus(str, Enum):
    PENDING = "PENDING"
    COMPLETED = "COMPLETED"
    ERROR = "ERROR"


class InspectionResult(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"


class PullTermination(str, Enum):
    FORCE_LIMIT = "FORCE_LIMIT"
    MAX_DISTANCE = "MAX_DISTANCE"
    TIMEOUT = "TIMEOUT"
    MOTION_ERROR = "MOTION_ERROR"


@dataclass(frozen=True)
class SequenceResult:
    """공통 시퀀스가 호출자에게 반환하는 성공 여부와 근거."""

    success: bool
    code: str
    message: str
    data: dict[str, Any] = field(default_factory=dict)


@dataclass
class PointRuntime:
    """검사 포인트 한 개의 실행값과 판정값을 보존한다."""

    point_id: str
    motion_status: SequenceStatus = SequenceStatus.IDLE
    adaptive_grip_status: SequenceStatus = SequenceStatus.IDLE
    grip_width_hard: float | None = None
    pull_status: SequenceStatus = SequenceStatus.IDLE
    peak_pull_force: float | None = None
    pull_displacement: float | None = None
    termination_reason: PullTermination | None = None
    grip_width_change: float | None = None
    judgment_status: JudgmentStatus = JudgmentStatus.PENDING
    result: InspectionResult | None = None
    reason: str = ""
    log_saved: bool = False


@dataclass
class JobContext:
    """PAUSE/RESUME 동안에만 보존하는 현재 작업 정보."""

    recipe_id: str
    enabled_point_ids: list[str]
    current_point_index: int = 0
    current_sequence: str = "WORK_INITIALIZE"
    resume_point: str = ""
    execution_state: dict[str, Any] = field(default_factory=dict)
    job_id: str = ""
    recipe_snapshot: dict[str, Any] = field(default_factory=dict)
    state: SequenceStatus = SequenceStatus.IDLE
    start_time: datetime | None = None
    end_time: datetime | None = None
    pending_judgments: set[str] = field(default_factory=set)
    point_runtime: dict[str, PointRuntime] = field(default_factory=dict)

    @property
    def execution_list(self) -> list[str]:
        return self.enabled_point_ids

    @property
    def execution_index(self) -> int:
        return self.current_point_index

    @property
    def current_point_id(self) -> str:
        """현재 포인트 ID를 반환하고 포인트가 없으면 빈 문자열을 반환한다."""
        if not self.enabled_point_ids:
            return ""
        if self.current_point_index >= len(self.enabled_point_ids):
            return ""
        return self.enabled_point_ids[self.current_point_index]
