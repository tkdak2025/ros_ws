"""
Qt <-> ROS 2 브리지.

ROS 콜백은 별도 스레드의 executor 에서 돌고, 받은 데이터는 Qt signal 로만
GUI 스레드에 넘긴다(스레드 간 signal 은 자동으로 queued connection). 따라서
GUI 가 잠깐 멈춰도 수신이 밀리지 않고, 수신이 몰려도 GUI 가 멈추지 않는다.

이 모듈은 DSR_ROBOT2 등 블로킹 서비스 호출이 있는 모듈을 import 하지 않는다.
HMI 는 publish/subscribe 만 한다. 예외는 검사 시작 서비스 하나이고, 그것도 기다리지 않고
보낸 뒤 응답을 signal 로 받는다(request_start).

상태는 두 가지 계약을 받는다.
  - 예전 status 하나 (mock_inspection_node, robot_monitor_node)
  - 상태 분리 계약: robot_status + work_status (검사 PC 의 Main, 2026-09-23)
두 번째는 여기서 합쳐 status_received 로 똑같이 내보내므로 화면은 차이를 모른다.
새 토픽이 들어오기 시작하면 예전 status 는 무시한다.
"""

import threading
import time

from PyQt5.QtCore import pyqtSignal, QObject, QTimer
import rclpy
from rclpy.executors import ExternalShutdownException, SingleThreadedExecutor
from rclpy.node import Node

from . import interface as itf


class RosBridge(QObject):
    """HMI 가 쓰는 유일한 ROS 접점."""

    status_received = pyqtSignal(object)   # itf.SystemStatus
    result_received = pyqtSignal(object)   # itf.PointResult
    log_received = pyqtSignal(object)      # itf.LogEntry
    start_answered = pyqtSignal(object)    # itf.StartAnswer
    # 상태 분리 계약의 원본 JSON. ROS 스레드에서 GUI 스레드로 넘겨 거기서 합친다
    # (합치는 데 쓰는 값을 두 스레드가 같이 만지지 않게).
    _robot_raw = pyqtSignal(object)
    _work_raw = pyqtSignal(object)

    def __init__(self, node_name: str = 'cable_hmi', parent=None):
        super().__init__(parent)
        self._node = Node(node_name)
        # '통합 조회' 탭이 읽을 위치. 검사 동작과는 무관하다(값은 여전히 status/result 로만 받는다).
        self._node.declare_parameter('recipe_db', '')
        self._node.declare_parameter('recipe_dir', '')
        # 검사 시작 서비스로 보낼 레시피 v0.1 JSON 폴더. 비우면 itf.DEFAULT_INSPECTION_RECIPE_DIR.
        self._node.declare_parameter('inspection_recipe_dir', '')
        # TP 에 등록한 Tool 무게(kg, 표시용). 검사 PC 가 무게를 보내지 않아서 HMI 가 갖고 있다.
        self._node.declare_parameter('tool_weight_kg', '')
        self._start_client = self._node.create_client(itf.START_SRV_TYPE, itf.SERVICE_START)
        self._cmd_pub = self._node.create_publisher(
            itf.COMMAND_MSG_TYPE, itf.TOPIC_COMMAND, itf.QOS_DEPTH)
        self._hb_pub = self._node.create_publisher(
            itf.HEARTBEAT_MSG_TYPE, itf.TOPIC_HEARTBEAT, 1)
        self._node.create_subscription(
            itf.STATUS_MSG_TYPE, itf.TOPIC_STATUS, self._on_status, itf.QOS_DEPTH)
        self._node.create_subscription(
            itf.RESULT_MSG_TYPE, itf.TOPIC_RESULT, self._on_result, itf.QOS_DEPTH)
        self._node.create_subscription(
            itf.LOG_MSG_TYPE, itf.TOPIC_LOG, self._on_log, itf.QOS_DEPTH)
        self._node.create_subscription(
            itf.ROBOT_STATUS_MSG_TYPE, itf.TOPIC_ROBOT_STATUS, self._on_robot_status,
            itf.ROBOT_STATUS_QOS_DEPTH)
        self._node.create_subscription(
            itf.WORK_STATUS_MSG_TYPE, itf.TOPIC_WORK_STATUS, self._on_work_status,
            itf.WORK_STATUS_QOS)

        # 상태 분리 계약의 마지막 값과 받은 시각(GUI 스레드에서만 읽고 쓴다)
        self._robot, self._robot_time = None, 0.0
        self._work, self._work_time = None, 0.0
        self._split_time = 0.0          # ROS 스레드도 읽는다 - float 대입 한 번이라 안전하다
        self._robot_raw.connect(self._take_robot)
        self._work_raw.connect(self._take_work)

        self._executor = SingleThreadedExecutor()
        self._executor.add_node(self._node)
        self._thread = threading.Thread(target=self._spin, name='ros_spin', daemon=True)

        # heartbeat 는 일부러 GUI 스레드의 QTimer 로 보낸다. GUI 가 얼어
        # 작업자가 정지 버튼을 못 누르는 상황이면 heartbeat 도 같이 끊겨야 한다.
        self._hb_timer = QTimer(self)
        self._hb_timer.setInterval(int(itf.HEARTBEAT_PERIOD_SEC * 1000))
        self._hb_timer.timeout.connect(self._publish_heartbeat)
        # 상태 분리 계약: 대기 중 Main 은 조용하므로 SYNC 로 살아 있는지 묻는다. heartbeat 와 같은
        # 이유로 GUI 스레드에서 보낸다. 같은 타이머로 로봇 값 만료도 다시 계산해 화면에 알린다.
        self._split_timer = QTimer(self)
        self._split_timer.setInterval(int(itf.WORK_SYNC_PERIOD_SEC * 1000))
        self._split_timer.timeout.connect(self._split_tick)

    def start(self):
        """수신 스레드와 heartbeat 를 시작한다."""
        self._thread.start()
        self._hb_timer.start()
        self._split_timer.start()

    def shutdown(self):
        """수신 스레드를 멈추고 노드를 정리한다."""
        self._hb_timer.stop()
        self._split_timer.stop()
        self._executor.shutdown()
        if self._thread.is_alive():
            self._thread.join(timeout=2.0)
        self._node.destroy_node()

    def parameter(self, name: str) -> str:
        """HMI 노드의 문자열 파라미터 값."""
        return str(self._node.get_parameter(name).value or '')

    def send_command(self, name: str, _quiet: bool = False, **args):
        """명령을 publish 한다. 블로킹 없음 - 결과는 status 로만 확인한다."""
        self._cmd_pub.publish(itf.encode_command(itf.Command(name=name, args=args)))
        if not _quiet:
            self._node.get_logger().info(f'command -> {name} {args if args else ""}')

    def request_start(self, request_id: str, recipe) -> bool:
        """
        검사 시작 서비스를 부른다. 기다리지 않는다 - 응답은 start_answered 로 온다.

        서비스가 안 보이면 보내지 않고 False. 응답 시간 제한과 경고는 화면 쪽이 맡는다
        (늦게 온 응답도 그대로 알린다. 자동 재전송은 하지 않는다).
        """
        if not self._start_client.service_is_ready():
            return False
        request = itf.START_SRV_TYPE.Request(request_id=request_id, recipe=recipe)
        future = self._start_client.call_async(request)
        future.add_done_callback(lambda f: self._on_start_done(request_id, f))
        self._node.get_logger().info(
            f'start -> {recipe.recipe_id} v{recipe.recipe_version} (request {request_id})')
        return True

    def _on_start_done(self, request_id: str, future):
        try:
            r = future.result()
            answer = itf.StartAnswer(request_id, r.accepted, r.code, r.message, r.run_id)
        except Exception as e:  # noqa: BLE001 - 호출 실패도 화면에 알려야 한다
            answer = itf.StartAnswer(request_id, error=repr(e))
        self.start_answered.emit(answer)

    def _publish_heartbeat(self):
        self._hb_pub.publish(itf.HEARTBEAT_MSG_TYPE())

    def _spin(self):
        try:
            self._executor.spin()
        except ExternalShutdownException:
            pass
        except Exception as e:  # noqa: BLE001 - 수신 스레드가 조용히 죽지 않게 남긴다
            if rclpy.ok():
                self._node.get_logger().error(f'ROS spin 스레드 종료: {e!r}')

    def _emit_decoded(self, decode, signal, msg, what):
        try:
            signal.emit(decode(msg))
        except (ValueError, TypeError) as e:
            self._node.get_logger().warn(
                f'{what} 메시지 해석 실패: {e}', throttle_duration_sec=2.0)

    def _on_status(self, msg):
        if self._split_active():
            return                      # 상태 분리 계약을 받는 중이다 - 예전 status 는 섞지 않는다
        self._emit_decoded(itf.decode_status, self.status_received, msg, 'status')

    # ------------------------------------------------ 상태 분리 계약 (robot_status + work_status)
    def _on_robot_status(self, msg):
        self._split_time = time.monotonic()
        self._emit_decoded(itf.decode_json_object, self._robot_raw, msg, 'robot_status')

    def _on_work_status(self, msg):
        self._split_time = time.monotonic()
        self._emit_decoded(itf.decode_json_object, self._work_raw, msg, 'work_status')

    def _split_active(self) -> bool:
        """최근에 robot_status 나 work_status 를 받았는가."""
        return time.monotonic() - self._split_time < itf.WORK_STATUS_STALE_SEC

    def _take_robot(self, data):
        self._robot, self._robot_time = data, time.monotonic()
        self._emit_split()

    def _take_work(self, data):
        self._work, self._work_time = data, time.monotonic()
        self._emit_split()

    def _emit_split(self):
        now = time.monotonic()
        self.status_received.emit(itf.merge_split_status(
            self._robot, self._work,
            robot_fresh=now - self._robot_time < itf.ROBOT_STATUS_STALE_SEC,
            work_fresh=self._work is not None
            and now - self._work_time < itf.WORK_STATUS_STALE_SEC))

    def _split_tick(self):
        """1 s 마다: Main 에 SYNC 를 묻고, 로봇 값이 오래됐으면 만료된 상태를 화면에 알린다."""
        if not self._split_active():
            return                      # mock·모니터 노드에는 SYNC 를 보내지 않는다(결과를 다시 보낸다)
        self.send_command(itf.CommandName.SYNC, _quiet=True)
        self._emit_split()

    def _on_result(self, msg):
        self._emit_decoded(itf.decode_result, self.result_received, msg, 'result')

    def _on_log(self, msg):
        self._emit_decoded(itf.decode_log, self.log_received, msg, 'log')
