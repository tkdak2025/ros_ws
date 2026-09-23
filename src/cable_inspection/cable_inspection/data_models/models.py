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
    SYSTEM_ERROR = "SYSTEM_ERROR"


class PullTermination(str, Enum):
    FORCE_LIMIT = "FORCE_LIMIT"
    MAX_DISTANCE = "MAX_DISTANCE"
    TIMEOUT = "TIMEOUT"
    MOTION_ERROR = "MOTION_ERROR"
    ROBOT_ERROR = "ROBOT_ERROR"
    TOOL_ERROR = "TOOL_ERROR"
    SAFETY_ERROR = "SAFETY_ERROR"
    INVALID_DATA = "INVALID_DATA"


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
    pull_status: SequenceStatus = SequenceStatus.IDLE
    peak_pull_force: float | None = None
    pull_displacement: float | None = None
    termination_reason: PullTermination | None = None
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


@dataclass(frozen=True)
class AdaptiveGripResult:
    entry: dict
    hard_grip: dict
    soft_width_mm: float
    adaptive_grip_done: bool = True


@dataclass(frozen=True)
class InspectionPointResult:
    """검사포인트 한 개의 동작·측정·판정 결과 전체를 보관한다."""

    point_id: str
    transition: dict
    adaptive_grip: AdaptiveGripResult
    pull_inspection: dict
    entry_displacement_mm: float | None
    peak_pull_force_n: float
    pull_displacement_mm: float
    termination_reason: PullTermination
    judgment_status: JudgmentStatus
    sequence_status: SequenceStatus
    result: InspectionResult | None
    reason: str


@dataclass(frozen=True)
class JudgmentRequest:
    """#05가 비동기 #06 Judgment 노드에 전달하는 측정 데이터."""

    run_id: int
    recipe_id: str
    recipe_version: str
    point_id: str
    point_name: str
    connector_type: str
    peak_pull_force_n: float
    pull_displacement_mm: float
    termination_reason: PullTermination
    required_force_n: float
    normal_displacement_limit_mm: float
    entry_task: list[float]
    entry_joint: list[float]
    force_data_id: str = ""
    error_reason: str = ""
    soft_width_mm: float | None = None
    pull_width_mm: float | None = None

    def to_dict(self) -> dict[str, Any]:
        data = self.__dict__.copy()
        data["termination_reason"] = self.termination_reason.value
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "JudgmentRequest":
        # 식별 가능한 요청은 누락/잘못된 측정값도 INVALID_DATA 결과로 남긴다.
        data = dict(data)
        for name in ("peak_pull_force_n", "pull_displacement_mm", "required_force_n",
                     "normal_displacement_limit_mm"):
            data.setdefault(name, None)
        try:
            data["termination_reason"] = PullTermination(data.get("termination_reason"))
        except ValueError:
            data["termination_reason"] = PullTermination.INVALID_DATA
        from dataclasses import fields
        names = {item.name for item in fields(cls)}
        return cls(**{key: value for key, value in data.items() if key in names})
