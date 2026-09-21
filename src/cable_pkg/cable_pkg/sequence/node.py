"""확정 시퀀스 Controller를 HMI 명령/상태 토픽에 연결하는 ROS 2 노드."""

import json
import time

import rclpy
from rclpy.node import Node
from std_msgs.msg import Empty, String

from .controller import SequenceController
from .models import SequenceResult, SystemState


class SequenceNode(Node):
    """주입된 Controller를 사용하며 로봇 동작 자체는 구현하지 않는다."""

    TOPIC_COMMAND = "cable_inspection/command"
    TOPIC_HEARTBEAT = "cable_inspection/hmi_heartbeat"
    TOPIC_STATUS = "cable_inspection/status"
    TOPIC_LOG = "cable_inspection/log"

    def __init__(
        self,
        controller: SequenceController,
        *,
        available_recipes: list[str] | None = None,
        heartbeat_timeout_s: float | None = None,
    ) -> None:
        super().__init__("ccc_sequence_node")
        if heartbeat_timeout_s is not None and heartbeat_timeout_s <= 0.0:
            raise ValueError("heartbeat_timeout_s는 0보다 커야 합니다.")

        self.controller = controller
        self.available_recipes = available_recipes or []
        self.heartbeat_timeout_s = heartbeat_timeout_s
        self.last_heartbeat = time.monotonic()
        self.communication_lost_handled = False
        self.run_id = 0

        self.status_pub = self.create_publisher(String, self.TOPIC_STATUS, 50)
        self.log_pub = self.create_publisher(String, self.TOPIC_LOG, 50)
        self.create_subscription(String, self.TOPIC_COMMAND, self._on_command, 50)
        self.create_subscription(Empty, self.TOPIC_HEARTBEAT, self._on_heartbeat, 10)
        self.create_timer(0.1, self._publish_status)
        self.create_timer(0.1, self._check_heartbeat)

    def _on_command(self, message: String) -> None:
        """HMI JSON 명령을 확정된 Controller API로 전달한다."""
        try:
            raw = json.loads(message.data)
            name = str(raw.get("name", "")).upper()
            args = raw.get("args", {})
            if not isinstance(args, dict):
                raise ValueError("args는 JSON 객체여야 합니다.")
        except (json.JSONDecodeError, TypeError, ValueError) as error:
            self._publish_log("ERROR", f"명령 해석 실패: {error}")
            return

        if name == "START":
            result = self.controller.start(str(args.get("recipe_id", "")))
            if result.success:
                self.run_id += 1
        elif name == "PAUSE":
            result = self.controller.pause()
        elif name == "RESUME":
            result = self.controller.resume()
        elif name == "STOP":
            result = self.controller.stop()
        elif name in {"MOVE_HOME", "HOME_RETURN"}:
            result = self.controller.request_home_return()
        elif name == "SELECT_RECIPE":
            recipe_id = str(args.get("recipe_id", ""))
            if recipe_id in self.available_recipes:
                result = SequenceResult(True, "RECIPE_SELECTED", f"레시피 선택: {recipe_id}")
            else:
                result = SequenceResult(False, "RECIPE_NOT_FOUND", f"없는 레시피: {recipe_id}")
        elif name in {"SYNC", "SET_SPEED"}:
            result = SequenceResult(True, f"{name}_ACCEPTED", f"시험 노드가 {name}을 확인했습니다.")
        else:
            result = SequenceResult(False, "UNKNOWN_COMMAND", f"지원하지 않는 명령: {name}")

        self._publish_result_log(result)
        self._publish_status()

    def _on_heartbeat(self, _message: Empty) -> None:
        """통신 복구를 기록하되 자동 RESUME은 수행하지 않는다."""
        was_lost = self.communication_lost_handled
        self.last_heartbeat = time.monotonic()
        self.communication_lost_handled = False
        if was_lost:
            self._publish_result_log(self.controller.communication_recovered())

    def _check_heartbeat(self) -> None:
        """설정된 timeout이 있을 때만 HMI 통신 유실을 처리한다."""
        if self.heartbeat_timeout_s is None or self.communication_lost_handled:
            return
        if time.monotonic() - self.last_heartbeat <= self.heartbeat_timeout_s:
            return
        self.communication_lost_handled = True
        self._publish_result_log(self.controller.communication_lost())

    def _publish_status(self) -> None:
        """내부 상태를 기존 HMI가 읽을 수 있는 상태 문자열로 변환한다."""
        context = self.controller.context
        status = {
            "state": self._hmi_state(self.controller.state),
            "alarm": self.controller.last_error,
            "robot_connected": True,
            "gripper_connected": True,
            "tool": {
                "configured": True,
                "name": "MOCK_TOOL",
                "tcp": "MOCK_TCP",
                "force_zero_done": True,
            },
            "available_recipes": self.available_recipes,
            "run_id": self.run_id,
            "recipe_id": context.recipe_id if context else "",
            "total_points": len(context.enabled_point_ids) if context else 0,
            "current_point": context.current_point_id if context else "",
            "current_step": context.current_sequence if context else "",
            "judgement": self.controller.state.value,
            "progress_percent": self._progress_percent(),
        }
        self.status_pub.publish(String(data=json.dumps(status, ensure_ascii=False)))

    def _progress_percent(self) -> int:
        context = self.controller.context
        if context is None or not context.enabled_point_ids:
            return 0
        completed = min(context.current_point_index, len(context.enabled_point_ids))
        return round(completed / len(context.enabled_point_ids) * 100)

    def _publish_result_log(self, result: SequenceResult) -> None:
        level = "INFO" if result.success else "ERROR"
        self._publish_log(level, f"{result.code}: {result.message}")

    def _publish_log(self, level: str, text: str) -> None:
        payload = {"level": level, "text": text, "popup": not level == "INFO"}
        self.log_pub.publish(String(data=json.dumps(payload, ensure_ascii=False)))

    @staticmethod
    def _hmi_state(state: SystemState) -> str:
        mapping = {
            SystemState.SYSTEM_READY: "IDLE",
            SystemState.RUNNING: "RUNNING",
            SystemState.PAUSE_REQUEST: "RUNNING",
            SystemState.PAUSED: "PAUSED",
            SystemState.STOPPED: "IDLE",
            SystemState.ERROR: "ERROR",
        }
        return mapping[state]


def spin_sequence_node(controller: SequenceController, **kwargs) -> None:
    """실물 Backend가 만든 Controller를 주입받아 노드를 실행한다."""
    rclpy.init()
    node = SequenceNode(controller, **kwargs)
    try:
        rclpy.spin(node)
    finally:
        node.destroy_node()
        rclpy.shutdown()
