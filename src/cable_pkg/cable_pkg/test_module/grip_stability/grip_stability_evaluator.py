"""Pull 힘 곡선으로 케이블 체결 이상 후보를 판정한다."""

from dataclasses import asdict, dataclass
from statistics import median


@dataclass(frozen=True)
class PullSample:
    displacement_mm: float
    force_n: float
    gripper_width_mm: float | None


@dataclass(frozen=True)
class ConnectionEvaluation:
    abnormal: bool
    reason: str
    peak_force_n: float
    peak_displacement_mm: float
    settled_force_n: float
    force_drop_n: float
    settled_to_peak_ratio: float
    gripper_width_range_mm: float | None
    rule_version: str = "force_release_and_slip_v0.2"

    def to_dict(self) -> dict:
        return asdict(self)


class ConnectionEvaluator:
    """힘 상승 후 급락을 커넥터 이탈 또는 체결 이상 신호로 판정한다."""

    MIN_PEAK_FORCE_N = 8.0
    MIN_FORCE_DROP_N = 8.0
    MAX_SETTLED_TO_PEAK_RATIO = 0.45
    MIN_GRIPPER_WIDTH_CHANGE_MM = 2.0
    DISTANCE_LIMIT_RATIO = 0.9
    SETTLED_SAMPLE_COUNT = 5

    def evaluate(
        self,
        samples: list[PullSample],
        pull_distance_limit_mm: float,
        pull_force_limit_n: float,
    ) -> ConnectionEvaluation:
        if len(samples) < self.SETTLED_SAMPLE_COUNT:
            raise ValueError("체결 판정에 필요한 Pull 측정값이 부족합니다.")

        peak_index = max(range(len(samples)), key=lambda i: samples[i].force_n)
        peak = samples[peak_index]
        settled_force = median(
            sample.force_n for sample in samples[-self.SETTLED_SAMPLE_COUNT:]
        )
        force_drop = peak.force_n - settled_force
        ratio = settled_force / peak.force_n if peak.force_n > 0.0 else 1.0

        widths = [
            sample.gripper_width_mm
            for sample in samples
            if sample.gripper_width_mm is not None
        ]
        width_range = max(widths) - min(widths) if widths else None

        force_release = (
            peak.force_n >= self.MIN_PEAK_FORCE_N
            and force_drop >= self.MIN_FORCE_DROP_N
            and ratio <= self.MAX_SETTLED_TO_PEAK_RATIO
        )
        progressive_slip = (
            max(sample.displacement_mm for sample in samples)
            >= pull_distance_limit_mm * self.DISTANCE_LIMIT_RATIO
            and width_range is not None
            and width_range >= self.MIN_GRIPPER_WIDTH_CHANGE_MM
            and peak.force_n < pull_force_limit_n
        )
        abnormal = force_release or progressive_slip
        if force_release:
            reason = "pull_force_peak_then_drop"
        elif progressive_slip:
            reason = "progressive_grip_slip_or_extraction"
        else:
            reason = "no_clear_release_or_slip_pattern"
        return ConnectionEvaluation(
            abnormal=abnormal,
            reason=reason,
            peak_force_n=round(peak.force_n, 4),
            peak_displacement_mm=round(peak.displacement_mm, 4),
            settled_force_n=round(settled_force, 4),
            force_drop_n=round(force_drop, 4),
            settled_to_peak_ratio=round(ratio, 4),
            gripper_width_range_mm=(
                round(width_range, 4) if width_range is not None else None
            ),
        )
