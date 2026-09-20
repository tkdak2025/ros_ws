"""케이블 체결 검사 HMI 실행 진입점 (ros2 run cable_hmi hmi)."""

import signal
import sys

from PyQt5.QtWidgets import QApplication
import rclpy
from rclpy.signals import SignalHandlerOptions

from .main_window import MainWindow
from .ros_bridge import RosBridge


def main(args=None):
    """ROS 브리지와 Qt 화면을 띄운다."""
    # SIGINT 는 rclpy 가 아니라 Qt 쪽에서 받아 창을 정상 종료시킨다.
    rclpy.init(args=args, signal_handler_options=SignalHandlerOptions.NO)
    app = QApplication(rclpy.utilities.remove_ros_args(sys.argv))
    signal.signal(signal.SIGINT, lambda *_: app.quit())

    bridge = RosBridge()
    window = MainWindow(bridge)
    bridge.start()
    window.show()
    try:
        code = app.exec_()
    finally:
        bridge.shutdown()
        rclpy.try_shutdown()
    sys.exit(code)


if __name__ == '__main__':
    main()
