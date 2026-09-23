"""검사포인트의 접근, 파지, Pull, 복귀를 한 흐름으로 실행한다."""

from cable_pkg.data_models.inspection_models import (
    AdaptiveGripResult,
    InspectionPointResult,
    JudgmentRequest,
)
from cable_pkg.data_models.sequence_models import (
    JudgmentStatus,
    PullTermination,
    SequenceStatus,
)


class InspectionSequence:
    """Inspection Recipe 순서대로 각 검사포인트의 전체 Cycle을 수행한다."""

    def __init__(
        self,
        hardware,
        should_run_point=lambda _index, _total, _point: True,
        submit_judgment=lambda _request: None,
        run_id=0,
    ):
        self.hardware = hardware
        self.should_run_point = should_run_point
        self.submit_judgment = submit_judgment
        self.run_id = run_id
        self.recipe = None

    def run(self, recipe):
        """활성 포인트를 execution_order 순서대로 한 번씩 실행한다."""
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
                    raise
        return results

    def run_point(self, point):
        """한 포인트에서 접근부터 Ready 복귀까지 연속 실행한다."""
        self.hardware.configure_point(point)
        transition = self.point_transition(point)
        adaptive = self.adaptive_grip(point)
        pull = self.pull_inspection(point)
        pull_data = pull["pull"]
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

    def point_transition(self, point):
        """#03: Recipe Open 폭 도달을 확인하고 Ready → Entry로 이동한다."""
        self.hardware.phase = "SEQ_03_POINT_TRANSITION"
        opened = self.hardware.grip(
            point.grip_setting["soft_open_width_mm"],
            point.grip_setting["soft_force_n"],
            opening=True,
        )
        ready = self.hardware.move_joint(point.ready_pose)
        entry = self.hardware.move_joint(point.entry_pose, allow_incomplete=True)
        return {"soft_open": opened, "ready": ready, "entry": entry}

    def adaptive_grip(self, point):
        """#04: Soft Grip 상태로 추가 진입한 뒤 Hard Grip한다."""
        self.hardware.phase = "SEQ_04_ADAPTIVE_GRIP"
        self.hardware.grip(
            point.grip_setting["soft_close_width_mm"],
            point.grip_setting["soft_force_n"],
        )
        entry = self.hardware.relative(
            point.normalized_entry_direction(),
            point.entry_setting["max_distance_mm"],
            entry_guard=True,
        )
        # Soft 단계 종료 시점의 실제 폭. Hard 명령을 보내기 전에 확보한다.
        soft = self.hardware.wait_gripper_idle()
        hard = self.hardware.grip(
            point.grip_setting["hard_width_mm"],
            point.grip_setting["hard_force_n"],
            wait_for_completion=True,
        )
        return AdaptiveGripResult(
            entry=entry,
            hard_grip=hard,
            soft_width_mm=soft["width_mm"],
        )

    def pull_inspection(self, point):
        """#05: Pull을 측정하고 Entry Pose와 Ready Pose로 복귀한다."""
        self.hardware.phase = "SEQ_05_PULL_INSPECTION"
        pull_direction = [-value for value in point.normalized_entry_direction()]
        pull = self.hardware.relative(
            pull_direction,
            point.pull_setting["max_distance_mm"],
            pull_guard=True,
        )
        opened = self.hardware.grip(
            point.grip_setting["soft_open_width_mm"],
            point.grip_setting["soft_force_n"],
            opening=True,
        )
        entry = self.hardware.move_linear(point.entry_pose.task)
        ready = self.hardware.move_joint(point.ready_pose)
        return {
            "pull": pull,
            "soft_open": opened,
            "return_entry": entry,
            "return_ready": ready,
        }

    @staticmethod
    def _pull_termination(stop_reason):
        """Hardware 종료 문자열을 시퀀스 공통 Enum으로 변환한다."""
        mapping = {
            "PULL_FORCE_LIMIT": PullTermination.FORCE_LIMIT,
            "PULL_MAX_DISTANCE": PullTermination.MAX_DISTANCE,
            "PULL_TIMEOUT": PullTermination.TIMEOUT,
        }
        return mapping.get(stop_reason, PullTermination.MOTION_ERROR)
