"""확정 시퀀스가 요구하는 장비·레시피 기능의 경계를 정의한다."""

from typing import Any, Protocol

from cable_pkg.data_models.sequence_models import JobContext, SequenceResult


class SequenceBackend(Protocol):
    """실물 또는 가상 장비 구현체가 제공해야 하는 공통 기능."""

    def check_robot_operability(self) -> SequenceResult: ...

    def check_hmi_communication(self) -> SequenceResult: ...

    def validate_system_recipe(self) -> SequenceResult: ...

    def validate_inspection_recipe(self, recipe_id: str) -> SequenceResult: ...

    def enabled_point_ids(self, recipe_id: str) -> list[str]: ...

    def current_tcp(self) -> list[float]: ...

    def tcp_is_in_work_area(self, tcp: list[float]) -> bool: ...

    def relax_grip(self) -> SequenceResult: ...

    def safe_escape(self, max_distance_mm: float) -> SequenceResult: ...

    def move_work_access_safe_pose(self) -> SequenceResult: ...

    def move_home_pose(self) -> SequenceResult: ...

    def move_safe_route_home(self) -> SequenceResult: ...

    def request_pause_safe(self, context: JobContext) -> SequenceResult: ...

    def resume_from(self, context: JobContext) -> SequenceResult: ...

    def request_motion_stop(self) -> SequenceResult: ...


class InspectionPointExecutor(Protocol):
    """상세설계 후 연결할 Point 단위 검사 실행 인터페이스."""

    def execute(self, context: JobContext) -> SequenceResult: ...


class InspectionHardware(Protocol):
    """#03~#05가 실제 Robot·Gripper 어댑터에 요구하는 기능."""

    phase: str

    def configure_point(self, point: Any) -> None: ...

    def move_joint(self, pose: Any, allow_incomplete: bool = False) -> dict: ...

    def move_linear(self, target: list[float]) -> dict: ...

    def relative(
        self,
        direction: list[float],
        distance: float,
        entry_guard: bool = False,
        pull_guard: bool = False,
    ) -> dict: ...

    def grip(
        self,
        width: float,
        force: float,
        opening: bool = False,
        wait_for_completion: bool = False,
    ) -> dict: ...


class UnimplementedPointExecutor:
    """미확정 Point 시퀀스가 실행되는 것을 명시적으로 차단한다."""

    def execute(self, context: JobContext) -> SequenceResult:
        """Point Transition 상세설계 미확정을 오류 결과로 반환한다."""
        return SequenceResult(
            False,
            "POINT_SEQUENCE_NOT_IMPLEMENTED",
            "Point Transition/Adaptive Grip/Pull 상세 시퀀스가 확정되지 않았습니다.",
            {"point_id": context.current_point_id},
        )
