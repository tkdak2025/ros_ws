"""Sequence #2 Home Return의 확정된 분기와 실행 순서를 구현한다."""

from .backend import SequenceBackend
from .models import SequenceResult


class HomeReturnSequence:
    """현재 TCP의 작업영역 포함 여부에 따라 안전 복귀 경로를 선택한다."""

    def __init__(self, backend: SequenceBackend, max_escape_distance_mm: float) -> None:
        if max_escape_distance_mm <= 0.0:
            raise ValueError("max_escape_distance_mm은 0보다 커야 합니다.")
        self.backend = backend
        self.max_escape_distance_mm = max_escape_distance_mm

    def run(self) -> SequenceResult:
        """작업영역 내부에서는 Grip 완화와 Safe Escape 후 Home으로 복귀한다."""
        operability = self.backend.check_robot_operability()
        if not operability.success:
            return operability

        tcp = self.backend.current_tcp()
        if len(tcp) < 3:
            return SequenceResult(False, "INVALID_TCP", "현재 TCP 값이 잘못되었습니다.")

        if self.backend.tcp_is_in_work_area(tcp):
            steps = (
                self.backend.relax_grip,
                lambda: self.backend.safe_escape(self.max_escape_distance_mm),
                self.backend.move_work_access_safe_pose,
                self.backend.move_home_pose,
            )
            route = "WORK_AREA_ESCAPE"
        else:
            steps = (self.backend.move_safe_route_home,)
            route = "SAFE_ROUTE_HOME"

        for step in steps:
            result = step()
            if not result.success:
                return result

        return SequenceResult(
            True,
            "HOME_RETURN_OK",
            "Home Return을 완료했습니다.",
            {"route": route, "start_tcp": tcp[:6]},
        )
