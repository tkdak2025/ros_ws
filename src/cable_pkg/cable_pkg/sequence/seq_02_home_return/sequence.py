"""#02 Home Return: 현재 TCP 위치에 맞는 경로로 Home에 복귀한다.
1. Robot 상태와 현재 TCP를 확인한다.
2. 작업영역 안이면 Work Access Safe Pose로 이동한 뒤 전체 관절을 한 번의 MoveJ로 0도 복귀한다.
3. 작업영역 밖이면 전체 관절을 한 번의 MoveJ로 0도 복귀한다.
4. 각 동작 완료점에서 Pause/STOP을 확인한다."""

from cable_pkg.interfaces.sequence_backend import SequenceBackend
from cable_pkg.data_models.sequence_models import SequenceResult


class HomeReturnSequence:
    """현재 TCP의 작업영역 포함 여부에 따라 안전 복귀 경로를 선택한다."""

    # 기능: Home 복귀 장비와 완료점 처리 함수를 준비한다.
    #     backend: 로봇·통신·레시피 확인과 공통 이동을 제공하는 장비 객체.
    #     checkpoint: 완료점 이름을 받아 Pause/STOP을 처리하는 함수. 생략하면 처리하지 않는다.
    def __init__(self, backend: SequenceBackend, checkpoint=lambda _step: None) -> None:
        self.backend = backend
        self.checkpoint = checkpoint



    # 기능: 장비/TCP를 확인하고 작업영역 안/밖에 맞는 Home 복귀를 실행한다.
    #
    #     ------------------------------------------------------------
    #     반환: 복귀 경로·시작 TCP 또는 실패 사유를 담은 SequenceResult.
    def run(self) -> SequenceResult:
        self.backend.phase = "SEQ_02_HOME_RETURN"
        operability = self.backend.check_robot_operability()
        if not operability.success:
            return operability

        tcp = self.backend.current_tcp()
        if len(tcp) < 3:
            return SequenceResult(False, "INVALID_TCP", "현재 TCP 값이 잘못되었습니다.")

        if self.backend.tcp_is_in_work_area(tcp):
            result = self.return_from_work_area()
            route = "WORK_ACCESS_HOME"
        else:
            result = self.return_from_outside()
            route = "SAFE_ROUTE_HOME"
        if not result.success:
            return result

        return SequenceResult(
            True,
            "HOME_RETURN_OK",
            "Home Return을 완료했습니다.",
            {"route": route, "start_tcp": tcp[:6]},
        )



    # 기능: 작업영역 안에서는 Work Access를 경유한 뒤 Home으로 복귀한다.
    #
    #     ------------------------------------------------------------
    #     반환: 마지막 이동 결과 또는 처음 실패한 SequenceResult.
    def return_from_work_area(self):
        result = self.backend.move_work_access_safe_pose()
        if not result.success:
            return result
        self.checkpoint("WORK_ACCESS_REACHED")
        return self.return_from_outside()



    # 기능: 전체 관절을 한 번의 MoveJ로 0도 복귀한다.
    #
    #     ------------------------------------------------------------
    #     반환: 경유 복귀 동작의 SequenceResult.
    def return_from_outside(self):
        result = self.backend.move_home_pose()
        if result.success:
            self.checkpoint("HOME_REACHED")
        return result
