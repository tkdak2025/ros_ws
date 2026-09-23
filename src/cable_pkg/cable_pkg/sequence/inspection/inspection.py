"""Inspection: 포인트별 #03→#04→#05를 연결한다.
1. 레시피 순서로 활성 포인트를 선택하고 장비 조건을 적용한다.
2. Ready/Entry 접근 → Soft 추가진입 → Hard Grip → Pull을 수행한다.
3. Pull 정지 직후 #06을 요청하고 그리퍼 개방 → Entry → Ready로 복귀한다.
4. 단계별 측정 결과를 묶어 반환한다."""

from cable_pkg.data_models.inspection_models import (
    InspectionPointResult,
    JudgmentRequest,
)
from cable_pkg.data_models.sequence_models import (
    JudgmentStatus,
    PullTermination,
    SequenceStatus,
)
from cable_pkg.sequence.seq_03_point_transition.sequence import PointTransitionSequence
from cable_pkg.sequence.seq_04_adaptive_grip.sequence import AdaptiveGripSequence
from cable_pkg.sequence.seq_05_pull_inspection.sequence import PullInspectionSequence


class InspectionSequence:
    """Inspection Recipe 순서대로 각 검사포인트의 전체 Cycle을 수행한다."""

    # 기능: 검사 단계 객체와 포인트 선택·판정 요청 함수를 준비한다.
    #     hardware: 그리퍼 명령, 이동, 실측값 조회를 제공하는 장비 객체.
    #     should_run_point: (현재 순번, 전체 개수, point)를 받아 검사 여부를 반환하는 함수.
    #     submit_judgment: JudgmentRequest를 받아 #06에 비동기 판정을 요청하는 함수.
    #     run_id: 측정과 판정 결과를 연결하는 실행 식별자.
    #     checkpoint: 완료점 이름을 받아 Pause/STOP을 처리하는 함수. 생략하면 처리하지 않는다.
    def __init__(
        self,
        hardware,
        should_run_point=lambda _index, _total, _point: True,
        submit_judgment=lambda _request: None,
        run_id=0,
        checkpoint=lambda _step: None,
    ):
        self.hardware = hardware
        self.should_run_point = should_run_point
        self.submit_judgment = submit_judgment
        self.run_id = run_id
        self.recipe = None
        # 각 단계는 한 클래스. 여기서는 검사 순서와 결과 연결만 관리한다.
        self.point_transition = PointTransitionSequence(hardware, checkpoint)
        self.adaptive_grip = AdaptiveGripSequence(hardware, checkpoint)
        self.pull_inspection = PullInspectionSequence(hardware, checkpoint)



    # 기능: 레시피 순서로 활성 포인트를 선택하여 검사한다. 오류 시 정지·오류 판정을 요청한다.
    #     recipe: 실행 순서와 포인트별 조건을 담은 Inspection Recipe.
    #
    #     ------------------------------------------------------------
    #     반환: point_id별 InspectionPointResult를 담은 dict.
    def run(self, recipe):
        self.recipe = recipe
        points = [
            recipe.points[point_id]
            for point_id in recipe.execution_order
            if recipe.points[point_id].enabled
        ]
        results = {}
        for index, point in enumerate(points, start=1):
            if self.should_run_point(index, len(points), point):
                try:
                    results[point.point_id] = self.run_point(point)
                except Exception as error:
                    self.handle_point_error(point, error)
                    raise
        return results



    # 기능: 한 Point에서 #03 접근 → #04 파지 → #05 Pull/복귀를 수행한다.
    #     point: 현재 검사포인트 레시피. Pose(mm/deg), Grip 폭(mm)·힘(N), 이동 조건을 담는다.
    #
    #     ------------------------------------------------------------
    #     반환: 측정과 단계별 결과를 담은 InspectionPointResult. 판정은 비동기로 처리한다.
    def run_point(self, point):
        self.hardware.configure_point(point)

        # #03 접근 → #04 파지 → #05 Pull/복귀. 측정 직후 #06을 비동기로 요청한다.
        transition = self.point_transition.run(point)
        adaptive = self.adaptive_grip.run(point)
        pull = self.pull_inspection.run(
            point, on_measured=lambda data: self.submit_pull_result(point, adaptive, data),
        )
        return self.make_point_result(point, transition, adaptive, pull)



    # 기능: Pull 정지 직후 폭 차이를 계산해 #06 판정을 요청한다. 복귀와 병행한다.
    #     point: 현재 검사포인트 레시피. Pose(mm/deg), Grip 폭(mm)·힘(N), 이동 조건을 담는다.
    #     adaptive: Soft 기준 폭과 추가진입·Hard Grip 결과를 담은 AdaptiveGripResult.
    #     pull_data: Pull 종료 사유, 최대 힘(N), 실제 변위(mm), 최소 폭(mm)을 담은 dict.
    def submit_pull_result(self, point, adaptive, pull_data):
        pull_data["width_delta_mm"] = pull_data["pull_width_mm"] - adaptive.soft_width_mm
        termination = self._pull_termination(pull_data["stop_reason"])
        self.submit_judgment(JudgmentRequest(
            run_id=self.run_id,
            recipe_id=self.recipe.recipe_id,
            recipe_version=self.recipe.recipe_version,
            point_id=point.point_id,
            point_name=point.point_name,
            soft_width_mm=adaptive.soft_width_mm,
            pull_width_mm=pull_data["pull_width_mm"],
            connector_type=self.recipe.connector_type,
            peak_pull_force_n=float(pull_data["peak_pull_force_n"]),
            pull_displacement_mm=float(pull_data["pull_displacement_mm"]),
            termination_reason=termination,
            required_force_n=point.pull_setting["force_limit_n"],
            normal_displacement_limit_mm=(
                point.pull_setting["normal_displacement_limit_mm"]
            ),
            entry_task=point.entry_pose.task,
            entry_joint=point.entry_pose.joint,
        ))



    # 기능: 장비 종료 문자열을 시퀀스의 Pull 종료 Enum으로 변환한다.
    #     stop_reason: 장비가 반환한 Pull 종료 사유 문자열.
    #
    #     ------------------------------------------------------------
    #     반환: PullTermination. 미등록 종료 사유는 MOTION_ERROR.
    @staticmethod
    def _pull_termination(stop_reason):
        mapping = {
            "PULL_FORCE_LIMIT": PullTermination.FORCE_LIMIT,
            "PULL_MAX_DISTANCE": PullTermination.MAX_DISTANCE,
            "PULL_TIMEOUT": PullTermination.TIMEOUT,
        }
        return mapping.get(stop_reason, PullTermination.MOTION_ERROR)



    # 기능: 검사 모션을 중단하고 포인트 식별자와 오류 사유를 #06에 전달한다.
    #     point: 현재 검사포인트 레시피. Pose(mm/deg), Grip 폭(mm)·힘(N), 이동 조건을 담는다.
    #     error: 작업 중 발생한 예외. 중단 사유와 결과 기록에 사용한다.
    def handle_point_error(self, point, error):
        recipe = self.recipe
        # 하드웨어 오류에서는 후속 모션을 하지 않고 SYSTEM_ERROR를 전달한다.
        self.hardware.safe_abort()
        self.submit_judgment(JudgmentRequest(
            run_id=self.run_id, recipe_id=recipe.recipe_id,
            recipe_version=recipe.recipe_version, point_id=point.point_id,
            point_name=point.point_name, connector_type=recipe.connector_type,
            peak_pull_force_n=0.0, pull_displacement_mm=0.0,
            termination_reason=(PullTermination.TIMEOUT
                if isinstance(error, TimeoutError) else
                PullTermination.INVALID_DATA if isinstance(error, (ValueError, KeyError, TypeError))
                else PullTermination.MOTION_ERROR),
            required_force_n=point.pull_setting["force_limit_n"],
            normal_displacement_limit_mm=point.pull_setting["normal_displacement_limit_mm"],
            entry_task=point.entry_pose.task, entry_joint=point.entry_pose.joint,
            error_reason=f"{type(error).__name__}: {error}",
        ))



    # 기능: 접근·파지·Pull 결과를 한 Point 결과 객체로 묶는다.
    #     point: 현재 검사포인트 레시피. Pose(mm/deg), Grip 폭(mm)·힘(N), 이동 조건을 담는다.
    #     transition: #03의 그리퍼 개방 및 Ready/Entry 접근 결과.
    #     adaptive: Soft 기준 폭과 추가진입·Hard Grip 결과를 담은 AdaptiveGripResult.
    #     pull: #05의 Pull 측정, 그리퍼 개방, Entry/Ready 복귀 결과.
    #
    #     ------------------------------------------------------------
    #     반환: 판정 대기 상태의 InspectionPointResult.
    def make_point_result(self, point, transition, adaptive, pull):
        pull_data = pull["pull"]
        termination = self._pull_termination(pull_data["stop_reason"])
        return InspectionPointResult(
            point_id=point.point_id,
            transition=transition,
            adaptive_grip=adaptive,
            pull_inspection=pull,
            entry_displacement_mm=adaptive.entry.get("entry_displacement_mm"),
            peak_pull_force_n=float(pull_data["peak_pull_force_n"]),
            pull_displacement_mm=float(pull_data["pull_displacement_mm"]),
            termination_reason=termination,
            judgment_status=JudgmentStatus.PENDING,
            sequence_status=SequenceStatus.SUCCESS,
            result=None,
            reason="판정 요청을 등록했습니다.",
        )
