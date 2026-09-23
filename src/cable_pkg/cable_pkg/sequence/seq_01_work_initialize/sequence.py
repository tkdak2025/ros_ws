"""#01 Work Initialize: Job 시작 조건을 확인한다.
1. Robot → HMI 통신 → System Recipe → Inspection Recipe 순서로 확인한다.
2. 활성 검사포인트가 있는지 확인하고 Robot 상태를 다시 확인한다.
3. 성공하면 실행할 포인트 목록을 반환하고 실패하면 다음 동작을 막는다."""

from cable_pkg.interfaces.sequence_backend import SequenceBackend
from cable_pkg.data_models.sequence_models import SequenceResult


class WorkInitializeSequence:
    """동작 전 장비·통신·레시피 상태를 매번 다시 확인한다."""

    # 기능: 초기화 검사를 수행할 장비 객체를 연결한다.
    #     backend: 로봇·통신·레시피 확인과 공통 이동을 제공하는 장비 객체.
    def __init__(self, backend: SequenceBackend) -> None:
        self.backend = backend



    # 기능: 사전조건 → 활성 포인트 → Robot 재확인 순서로 시작 가능 여부를 확인한다.
    #     recipe_id: 등록된 Inspection Recipe의 식별자.
    #
    #     ------------------------------------------------------------
    #     반환: 성공 시 활성 point_id 목록, 실패 시 사유를 담은 SequenceResult.
    def run(self, recipe_id: str) -> SequenceResult:
        self.backend.phase = "SEQ_01_WORK_INITIALIZE"
        result = self.check_preconditions(recipe_id)
        if not result.success:
            return result

        enabled_points = self.backend.enabled_point_ids(recipe_id)
        if not enabled_points:
            return SequenceResult(
                False,
                "NO_ENABLED_POINT",
                "활성화된 검사포인트가 없습니다.",
            )

        rechecked = self.backend.check_robot_operability()
        if not rechecked.success:
            return rechecked

        return SequenceResult(
            True,
            "WORK_INITIALIZE_OK",
            "Work Initialize 조건을 모두 확인했습니다.",
            {"enabled_point_ids": enabled_points},
        )



    # 기능: Robot → HMI 통신 → System Recipe → Inspection Recipe 순서로 확인한다.
    #     recipe_id: 등록된 Inspection Recipe의 식별자.
    #
    #     ------------------------------------------------------------
    #     반환: 마지막 확인 결과 또는 처음 실패한 SequenceResult.
    def check_preconditions(self, recipe_id):
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
        return result
