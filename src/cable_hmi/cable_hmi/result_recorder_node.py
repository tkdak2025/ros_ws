"""
검사 결과를 DB 에 저장하는 노드.

cable_inspection/result 로 오는 결과(PointResult)를 SQLite(result_db.py, 테이블 inspection_result)에
저장하고, 저장에 성공하면 같은 결과를 db_saved=true 로 다시 보낸다. HMI 는 같은 run 의 같은
Point 를 덮어쓰므로 상세 팝업의 '저장 안 됨' 이 '저장 완료' 로 바뀐다.

  - 결과를 누가 보냈는지는 따지지 않는다 (mock_inspection_node, 동작 코드의 ProgressReporter ...).

작업 단위 기록
  status 를 보고 검사 1회(run)의 시작과 끝을 inspection_run 테이블에 남긴다: 시작·종료 시각, 끝난 이유
  (status.end_reason - COMPLETED / STOP / ERROR / COMM_ERROR / INIT_FAIL / ABORTED / LOST), 제품 판정,
  Point 집계. '검사 중' 은 state 가 RUNNING / PAUSE_REQUEST / PAUSED 인 동안이다. 그 밖의 상태로
  바뀌면 끝난 것으로 보고, 끝난 이유가 실려 오지 않았으면 UNKNOWN 으로 적는다.
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


RUN_STATES = (itf.State.RUNNING, itf.State.PAUSE_REQUEST, itf.State.PAUSED)


class ResultRecorderNode(Node):
    """결과 토픽 -> SQLite."""

    def __init__(self):
        super().__init__('result_recorder_node')
        self.declare_parameter('result_db', '')
        path = self.get_parameter('result_db').value
        self._db = result_db.ResultDb(path) if path else None
        self._last_error = ''
        self._open_run = 0              # 지금 '검사 중' 으로 기록해 둔 run_id (0 = 없음)
        self._last_status = None

        self._result_pub = self.create_publisher(
            itf.RESULT_MSG_TYPE, itf.TOPIC_RESULT, itf.QOS_DEPTH)
        self._log_pub = self.create_publisher(itf.LOG_MSG_TYPE, itf.TOPIC_LOG, itf.QOS_DEPTH)
        self.create_subscription(
            itf.RESULT_MSG_TYPE, itf.TOPIC_RESULT, self._on_result, itf.QOS_DEPTH)
        self.create_subscription(
            itf.STATUS_MSG_TYPE, itf.TOPIC_STATUS, self._on_status, itf.QOS_DEPTH)
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

    def _on_status(self, msg):
        """검사 1회의 시작과 끝을 기록한다 (status 는 10 Hz 로 오지만 DB 는 바뀔 때만 쓴다)."""
        try:
            status = itf.decode_status(msg)
        except (ValueError, TypeError):
            return
        if self._db is None:
            return
        running = status.run_id != 0 and status.state in RUN_STATES
        try:
            if self._open_run and (not running or status.run_id != self._open_run):
                # 기록해 둔 검사가 끝났다. 번호가 바뀐 경우에는 마지막으로 본 그 검사의 status 로 닫는다.
                last = status if status.run_id == self._open_run else self._last_status
                reason = last.end_reason if last.run_id == self._open_run else ''
                if not reason and last.state == itf.State.DONE:
                    reason = itf.EndReason.COMPLETED
                self._db.save_run_end(last, reason or 'UNKNOWN')
                self.get_logger().info(f'작업 기록: run {self._open_run} 종료 ({reason or "UNKNOWN"})')
                self._open_run = 0
            if running and not self._open_run:
                self._db.save_run_start(status)
                self._open_run = status.run_id
                self.get_logger().info(f'작업 기록: run {status.run_id} 시작 ({status.recipe_id})')
        except result_db.ResultDbError as e:
            self._warn(f'작업 기록 저장 실패: {e}')
            self._open_run = status.run_id if running else 0     # 같은 실패를 10 Hz 로 되풀이하지 않는다
        if running:
            self._last_status = status

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
