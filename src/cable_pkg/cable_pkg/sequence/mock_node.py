"""HMI에서 확정 시퀀스 상태 전이를 확인하는 실행 노드."""

import rclpy
from rclpy.executors import ExternalShutdownException

from .backend import UnimplementedPointExecutor
from .controller import SequenceController
from .mock_backend import MockSequenceBackend
from .models import SystemState
from .node import SequenceNode


class MockSequenceNode(SequenceNode):
    """로봇 없이 Point의 닫힌 흐름을 화면 표시용 단계로 진행한다."""

    POINT_STEPS = (
        "READY_POSE",
        "ENTRY_POSE",
        "INSPECTION_PLACEHOLDER",
        "READY_POSE_RETURN",
    )
    STEP_PERIOD_S = 1.0

    def __init__(self) -> None:
        backend = MockSequenceBackend(start_in_work_area=True)
        controller = SequenceController(
            backend,
            UnimplementedPointExecutor(),
            max_escape_distance_mm=30.0,
        )
        super().__init__(controller, available_recipes=backend.recipe_ids)
        self.step_index = 0
        self.create_timer(self.STEP_PERIOD_S, self._advance_test_sequence)
        self._publish_log("INFO", "시퀀스 Mock 노드 시작: 실제 로봇 동작 없음")

    def _advance_test_sequence(self) -> None:
        """RUNNING일 때만 포인트별 표시 단계를 한 단계씩 진행한다."""
        controller = self.controller
        context = controller.context
        if controller.state != SystemState.RUNNING or context is None:
            return
        if context.current_sequence not in {"POINT_LOOP", *self.POINT_STEPS}:
            return

        if self.step_index < len(self.POINT_STEPS):
            context.current_sequence = self.POINT_STEPS[self.step_index]
            self._publish_log(
                "INFO",
                f"{context.current_point_id}: {context.current_sequence}",
            )
            self.step_index += 1
            return

        context.current_point_index += 1
        self.step_index = 0
        if context.current_point_index < len(context.enabled_point_ids):
            context.current_sequence = "POINT_LOOP"
            return

        self._publish_result_log(controller.complete())


def main(args=None) -> None:
    """Mock Sequence Node를 실행한다."""
    rclpy.init(args=args)
    node = MockSequenceNode()
    try:
        rclpy.spin(node)
    except (KeyboardInterrupt, ExternalShutdownException):
        pass
    finally:
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()
