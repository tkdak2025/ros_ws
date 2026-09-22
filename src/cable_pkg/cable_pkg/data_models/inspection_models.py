"""검사포인트 실행 단계 사이에 전달하는 결과 구조를 정의한다."""

from dataclasses import dataclass


@dataclass(frozen=True)
class AdaptiveGripResult:
    entry: dict
    hard_grip: dict
    grip_width_hard: float
    grip_width_hard_timestamp: str
    adaptive_grip_done: bool = True


@dataclass(frozen=True)
class PointCycleResult:
    transition: dict
    adaptive_grip: AdaptiveGripResult
    pull_inspection: dict
