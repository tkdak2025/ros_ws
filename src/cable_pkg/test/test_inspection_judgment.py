"""#06 검사 판정 규칙을 검증한다."""

from cable_pkg.sequence.inspection.seq_06_inspection_judgment import judge_pull
from cable_pkg.data_models.sequence_models import (
    InspectionResult, JudgmentStatus, PullTermination, SequenceStatus,
)


def test_force_limit_with_small_displacement_is_pass():
    result = judge_pull(
        termination=PullTermination.FORCE_LIMIT, peak_force_n=15.2,
        displacement_mm=4.9, required_force_n=15.0,
    )
    assert result.result == InspectionResult.PASS
    assert result.status == JudgmentStatus.COMPLETED


def test_force_limit_after_large_displacement_is_fail():
    result = judge_pull(
        termination=PullTermination.FORCE_LIMIT, peak_force_n=15.2,
        displacement_mm=5.1, required_force_n=15.0,
    )
    assert result.result == InspectionResult.FAIL


def test_max_distance_without_slip_is_fail():
    result = judge_pull(
        termination=PullTermination.MAX_DISTANCE, peak_force_n=9.4,
        displacement_mm=25.0, required_force_n=15.0,
    )
    assert result.result == InspectionResult.FAIL


def test_confirmed_slip_is_missing():
    result = judge_pull(
        termination=PullTermination.MAX_DISTANCE, peak_force_n=3.0,
        displacement_mm=25.0, required_force_n=15.0, slip_confirmed=True,
    )
    assert result.result == InspectionResult.MISSING


def test_timeout_is_incomplete_without_product_result():
    result = judge_pull(
        termination=PullTermination.TIMEOUT, peak_force_n=10.0,
        displacement_mm=8.0, required_force_n=15.0,
    )
    assert result.status == JudgmentStatus.ERROR
    assert result.sequence_status == SequenceStatus.INCOMPLETE
    assert result.result is None
