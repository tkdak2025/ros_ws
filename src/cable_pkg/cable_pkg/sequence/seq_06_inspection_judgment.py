"""Pull 측정 결과를 제품 판정으로 변환한다."""

from dataclasses import dataclass

from cable_pkg.data_models.sequence_models import InspectionResult, JudgmentStatus, PullTermination, SequenceStatus


@dataclass(frozen=True)
class Judgment:
    status: JudgmentStatus
    sequence_status: SequenceStatus
    result: InspectionResult | None
    reason: str


def judge_pull(
    *,
    termination: PullTermination,
    peak_force_n: float,
    displacement_mm: float,
    required_force_n: float,
    normal_displacement_limit_mm: float = 5.0,
    slip_confirmed: bool = False,
) -> Judgment:
    """확정된 #06 규칙으로 판정한다. Slip은 별도 검출 결과를 입력받는다."""
    if slip_confirmed:
        return Judgment(
            JudgmentStatus.COMPLETED,
            SequenceStatus.SUCCESS,
            InspectionResult.MISSING,
            "그리퍼 폭 변화로 케이블 이탈이 확인됐습니다.",
        )

    if termination in {PullTermination.TIMEOUT, PullTermination.MOTION_ERROR}:
        return Judgment(
            JudgmentStatus.ERROR,
            SequenceStatus.INCOMPLETE,
            None,
            f"Pull이 {termination.value}로 끝나 제품 판정을 만들지 않습니다.",
        )

    force_reached = peak_force_n >= required_force_n
    if force_reached and displacement_mm <= normal_displacement_limit_mm:
        result = InspectionResult.PASS
        reason = "요구 힘에 도달했고 허용 변위 이내입니다."
    elif force_reached or termination == PullTermination.MAX_DISTANCE:
        result = InspectionResult.FAIL
        reason = "허용 변위를 초과했거나 최대 Pull 거리에 도달했습니다."
    else:
        return Judgment(
            JudgmentStatus.ERROR,
            SequenceStatus.INCOMPLETE,
            None,
            "정상 종료 근거가 부족해 제품 판정을 만들지 않습니다.",
        )

    return Judgment(JudgmentStatus.COMPLETED, SequenceStatus.SUCCESS, result, reason)
