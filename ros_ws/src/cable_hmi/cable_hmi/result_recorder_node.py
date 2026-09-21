"""
검사 결과를 DB 에 저장하는 노드.

cable_inspection/result 로 오는 결과(PointResult)를 SQLite(result_db.py, 테이블 inspection_result)에
저장하고, 저장에 성공하면 같은 결과를 db_saved=true 로 다시 보낸다. HMI 는 같은 run 의 같은
Point 를 덮어쓰므로 상세 팝업의 '저장 안 됨' 이 '저장 완료' 로 바뀐다.

  - 결과를 누가 보냈는지는 따지지 않는다 (mock_inspection_node, 동작 코드의 ProgressReporter ...).
  - 자기가 다시 보낸 것(db_saved=true)은 건너뛴다.
  - HMI 화면 프로세스가 직접 저장하지 않는 이유: DB 가 잠겨 있어도 화면과 STOP 이 멈추면 안 된다.
  - 저장에 실패하면 시스템 로그에 경고만 남긴다. 검사는 계속된다.
"""

from datetime import datetime

import rclpy
from rclpy.executors import ExternalShutdownException
from rclpy.node import Node

from . import interface as itf
from . import result_db


class ResultRecorderNode(Node):
    """결과 토픽 -> SQLite."""

    def __init__(self):
        super().__init__('result_recorder_node')
        self.declare_parameter('result_db', '')
        path = self.get_parameter('result_db').value
        self._db = result_db.ResultDb(path) if path else None
        self._last_error = ''

        self._result_pub = self.create_publisher(
            itf.RESULT_MSG_TYPE, itf.TOPIC_RESULT, itf.QOS_DEPTH)
        self._log_pub = self.create_publisher(itf.LOG_MSG_TYPE, itf.TOPIC_LOG, itf.QOS_DEPTH)
        self.create_subscription(
            itf.RESULT_MSG_TYPE, itf.TOPIC_RESULT, self._on_result, itf.QOS_DEPTH)
        if self._db is None:
            self.get_logger().warning('result_db 가 지정되지 않음 - 결과를 저장하지 않습니다.')
        else:
            self.get_logger().info(f'검사 결과 저장 위치: {self._db.path}')

    def _on_result(self, msg):
        try:
            result = itf.decode_result(msg)
        except (ValueError, TypeError) as e:
            self._warn(f'결과 메시지 해석 실패: {e}')
            return
        if result.db_saved or self._db is None:
            return
        try:
            self._db.save(result)
        except result_db.ResultDbError as e:
            self._warn(f'검사 결과 저장 실패 ({result.point_id}): {e}')
            return
        self._last_error = ''
        result.db_saved = True
        self._result_pub.publish(itf.encode_result(result))

    def _warn(self, text: str):
        self.get_logger().warning(text)
        if text == self._last_error:        # 같은 이유로 Point 마다 로그가 쌓이지 않게
            return
        self._last_error = text
        stamp = datetime.now().isoformat(timespec='seconds')
        self._log_pub.publish(itf.encode_log(itf.LogEntry(stamp, 'WARN', text)))


def main(args=None):
    rclpy.init(args=args)
    node = ResultRecorderNode()
    try:
        rclpy.spin(node)
    except (KeyboardInterrupt, ExternalShutdownException):
        pass
    finally:
        node.destroy_node()
        rclpy.try_shutdown()


if __name__ == '__main__':
    main()
