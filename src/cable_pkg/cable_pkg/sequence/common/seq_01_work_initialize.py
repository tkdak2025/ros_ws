"""Sequence #1 Work Initialize의 확정된 검사 순서를 구현한다."""

from cable_pkg.interfaces.sequence_backend import SequenceBackend
from cable_pkg.data_models.sequence_models import SequenceResult


class WorkInitializeSequence:
    """동작 전 장비·통신·레시피 상태를 매번 다시 확인한다."""

    def __init__(self, backend: SequenceBackend) -> None:
        self.backend = backend

    def run(self, recipe_id: str) -> SequenceResult:
        """확정된 순서로 사전조건을 검사하고 활성 포인트를 반환한다."""
        checks = (
            self.backend.check_robot_operability,
            self.backend.check_hmi_communication,
            self.backend.validate_system_recipe,
            lambda: self.backend.validate_inspection_recipe(recipe_id),
        )
        for check in checks:
            result = check()
            if not result.success:
                return result

        enabled_points = self.backend.enabled_point_ids(recipe_id)
        if not enabled_points:
            return SequenceResult(
                False,
                "NO_ENABLED_POINT",
                "활성화된 검사포인트가 없습니다.",
            )

        return SequenceResult(
            True,
            "WORK_INITIALIZE_OK",
            "Work Initialize 조건을 모두 확인했습니다.",
            {"enabled_point_ids": enabled_points},
        )
