"""
Qt <-> ROS 2 브리지.

ROS 콜백은 별도 스레드의 executor 에서 돌고, 받은 데이터는 Qt signal 로만
GUI 스레드에 넘긴다(스레드 간 signal 은 자동으로 queued connection). 따라서
GUI 가 잠깐 멈춰도 수신이 밀리지 않고, 수신이 몰려도 GUI 가 멈추지 않는다.

이 모듈은 DSR_ROBOT2 등 블로킹 서비스 호출이 있는 모듈을 import 하지 않는다.
HMI 는 publish/subscribe 만 한다.
"""

import threading

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

    def __init__(self, node_name: str = 'cable_hmi', parent=None):
        super().__init__(parent)
        self._node = Node(node_name)
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

        self._executor = SingleThreadedExecutor()
        self._executor.add_node(self._node)
        self._thread = threading.Thread(target=self._spin, name='ros_spin', daemon=True)

        # heartbeat 는 일부러 GUI 스레드의 QTimer 로 보낸다. GUI 가 얼어
        # 작업자가 정지 버튼을 못 누르는 상황이면 heartbeat 도 같이 끊겨야 한다.
        self._hb_timer = QTimer(self)
        self._hb_timer.setInterval(int(itf.HEARTBEAT_PERIOD_SEC * 1000))
        self._hb_timer.timeout.connect(self._publish_heartbeat)

    def start(self):
        """수신 스레드와 heartbeat 를 시작한다."""
        self._thread.start()
        self._hb_timer.start()

    def shutdown(self):
        """수신 스레드를 멈추고 노드를 정리한다."""
        self._hb_timer.stop()
        self._executor.shutdown()
        if self._thread.is_alive():
            self._thread.join(timeout=2.0)
        self._node.destroy_node()

    def send_command(self, name: str, **args):
        """명령을 publish 한다. 블로킹 없음 - 결과는 status 로만 확인한다."""
        self._cmd_pub.publish(itf.encode_command(itf.Command(name=name, args=args)))
        self._node.get_logger().info(f'command -> {name} {args if args else ""}')

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
        self._emit_decoded(itf.decode_status, self.status_received, msg, 'status')

    def _on_result(self, msg):
        self._emit_decoded(itf.decode_result, self.result_received, msg, 'result')

    def _on_log(self, msg):
        self._emit_decoded(itf.decode_log, self.log_received, msg, 'log')
