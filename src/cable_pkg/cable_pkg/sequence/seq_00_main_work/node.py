"""Main Work 명령 수신부: ROS Callback과 장비 Worker를 분리한다.
1. START/Home은 Worker에서 실행하고 Pause/Resume/STOP은 제어 객체에 전달한다.
2. Heartbeat를 감시하고 유실/복구를 알린다.
3. 진행 상태와 로그를 발행한다."""

import json
import threading
import time

import rclpy
from rclpy.node import Node
from std_msgs.msg import Empty, String

from cable_pkg.data_models.sequence_models import SystemState


class SequenceNode(Node):
    """Callback은 짧게 유지한다. Worker만 장비 서비스를 호출한다."""

    # 기능: 명령 수신·상태 발행과 Heartbeat 감시를 준비한다.
    #     controller: 현재 Job 상태, 결과 저장, 제어 명령을 관리하는 SequenceController.
    #     heartbeat_timeout_s: Heartbeat를 기다릴 최대 시간(s).
    def __init__(self, controller, heartbeat_timeout_s=2.0):
        super().__init__("ccc_sequence_node")
        self.controller = controller
        self.heartbeat_timeout_s = heartbeat_timeout_s
        self.last_heartbeat = None
        self.communication_lost_handled = False
        self.worker = None
        self.selected_recipe = ""
        self.status_pub = self.create_publisher(String, "cable_inspection/status", 50)
        self.log_pub = self.create_publisher(String, "cable_inspection/log", 50)
        self.create_subscription(String, "cable_inspection/command", self._on_command, 50)
        self.create_subscription(Empty, "cable_inspection/hmi_heartbeat", self._on_heartbeat, 10)
        self.create_timer(0.1, self._tick)
        controller.notify = self._log
        controller.backend.hmi_available = self.hmi_available



    # 기능: 최근 Heartbeat가 통신 제한시간 안에 도착했는지 확인한다.
    #
    #     ------------------------------------------------------------
    #     반환: 통신이 유효하면 True, 아니면 False.
    def hmi_available(self):
        return (self.last_heartbeat is not None
                and time.monotonic() - self.last_heartbeat <= self.heartbeat_timeout_s)



    # 기능: 실행 중인 Worker가 없을 때만 별도 스레드에서 Job 또는 Home 동작을 시작한다.
    #     action: 장비 Worker에서 실행할 인자 없는 함수.
    def _launch(self, action):
        if self.worker is not None and self.worker.is_alive():
            self._log("WARN", "이전 시퀀스가 실행/정지 처리 중입니다.")
            return
        def work():
            try:
                result = action()
                self._log("INFO" if result.success else "ERROR", f"{result.code}: {result.message}")
            except Exception as error:
                self.controller._abort_motion()
                self.controller.last_error = str(error)
                self.controller.state = SystemState.ERROR
                self._log("ERROR", str(error))
        self.worker = threading.Thread(target=work, name="sequence-worker", daemon=False)
        self.worker.start()



    # 기능: 수신한 명령을 START/Home/Pause/Resume/STOP 등 해당 제어 기능에 전달한다.
    #     message: name과 args를 담은 JSON 형식의 std_msgs/String.
    def _on_command(self, message):
        try:
            raw = json.loads(message.data)
            if not isinstance(raw, dict) or not isinstance(raw.get("args", {}), dict):
                raise ValueError("명령은 name과 args를 가진 JSON 객체여야 합니다.")
            name, args = str(raw.get("name", "")).upper(), raw.get("args", {})
            if name == "START":
                recipe_id = str(args.get("recipe_id", self.selected_recipe))
                self._launch(lambda: self.controller.run(recipe_id))
            elif name in {"HOME_RETURN", "MOVE_HOME"}:
                self._launch(self.controller.request_home_return)
            elif name == "PAUSE":
                self._report(self.controller.pause())
            elif name == "RESUME":
                self._report(self.controller.resume())
            elif name == "STOP":
                if self.worker is not None and self.worker.is_alive():
                    self._report(self.controller.stop())
                else:
                    self.controller.context = None
                    self.controller.state = SystemState.STOPPED
                    self._log("INFO", "STOPPED: 진행 중인 Job이 없습니다.")
            elif name == "SELECT_RECIPE":
                recipe_id = str(args.get("recipe_id", ""))
                if recipe_id not in self.controller.backend.recipe_paths:
                    raise ValueError(f"등록되지 않은 Recipe: {recipe_id}")
                if self.controller.state != SystemState.SYSTEM_READY:
                    raise ValueError("실행 중 Recipe를 변경할 수 없습니다.")
                self.selected_recipe = recipe_id
                self._log("INFO", f"RECIPE_SELECTED: {recipe_id}")
            elif name == "SYNC":
                self._publish_status()
            else:
                raise ValueError(f"지원하지 않는 명령: {name}")
        except (ValueError, TypeError, KeyError) as error:
            self._log("ERROR", str(error))



    # 기능: Heartbeat 수신 시각을 갱신하고 유실 상태였다면 통신 복구를 알린다.
    #     _message: Heartbeat 수신 메시지. 내용 대신 수신 시각을 사용한다.
    def _on_heartbeat(self, _message):
        self.last_heartbeat = time.monotonic()
        if self.communication_lost_handled:
            self.controller.communication_recovered()
            self._log("INFO", "통신 복구. 상태를 다시 전달하며 RESUME을 기다립니다.")
        self.communication_lost_handled = False



    # 기능: 실행 중 통신 유실을 감시하고 현재 상태를 발행한다.
    def _tick(self):
        active = self.controller.state in {SystemState.RUNNING, SystemState.PAUSE_REQUEST, SystemState.PAUSED}
        if active and not self.hmi_available() and not self.communication_lost_handled:
            self.communication_lost_handled = True
            self.controller.communication_lost()
            self._log("WARN", "HMI COMM LOST: Safe Pause 요청")
        self._publish_status()



    # 기능: 현재 Job, Point, 진행률과 통신 상태를 상태 토픽에 발행한다.
    def _publish_status(self):
        context, backend = self.controller.context, self.controller.backend
        total = len(context.enabled_point_ids) if context else 0
        state = self.controller.state.value
        status = {
            "state": "IDLE" if state == "SYSTEM_READY" else state,
            "run_state": state, "alarm": self.controller.last_error,
            "robot_connected": backend.connected, "gripper_connected": backend.connected,
            "tool": {"configured": backend.connected, "name": backend.config.tool_name,
                     "tcp": backend.config.tcp_name, "force_zero_done": False},
            "available_recipes": list(backend.recipe_paths), "run_id": self.controller.run_id,
            "recipe_id": context.recipe_id if context else self.selected_recipe,
            "job_id": context.job_id if context else "",
            "recipe_version": context.recipe_snapshot.get("recipe_version", "") if context else "",
            "execution_index": context.current_point_index if context else 0,
            "resume_point": context.resume_point if context else "",
            "total_points": total, "current_point": context.current_point_id if context else "",
            "current_step": context.current_sequence if context else "",
            "pending_judgments": len(context.pending_judgments) if context else 0,
            "progress_percent": round(100 * context.current_point_index / total) if total else 0,
            "job_summary": self.controller.last_summary,
        }
        self.status_pub.publish(String(data=json.dumps(status, ensure_ascii=False)))



    # 기능: 제어 요청의 성공 여부에 맞는 수준으로 결과를 로그에 남긴다.
    #     result: 성공 여부, 사유 코드, 부가 정보를 담은 SequenceResult.
    def _report(self, result):
        self._log("INFO" if result.success else "WARN", f"{result.code}: {result.message}")



    # 기능: 동일한 로그 내용을 터미널과 ROS 토픽에 전달한다.
    #     level: 로그 수준(INFO/WARN/ERROR).
    #     text: 터미널과 로그 토픽에 전달할 문자열.
    def _log(self, level, text):
        print(f"[{level}] {text}", flush=True)
        self.log_pub.publish(String(data=json.dumps({"level": level, "text": text,
                                                    "popup": level == "ERROR"}, ensure_ascii=False)))



    # 기능: 실행 중인 Worker에 STOP을 요청하고 장비 동작 처리가 끝날 때까지 기다린다.
    def close(self):
        if self.worker is not None and self.worker.is_alive():
            self.controller.stop()
            self.worker.join()  # 장비 서비스를 사용하는 Worker 종료 후 노드를 파괴한다.
