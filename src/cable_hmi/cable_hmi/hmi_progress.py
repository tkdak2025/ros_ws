"""
동작 코드에서 HMI 진행률을 보고하고, HMI 의 검사 시작 / 일시정지 / 이어하기를 받는 부품.

1) 진행률만 알릴 때 (동작 코드 쪽에는 이 몇 줄만 들어간다):

    progress = ProgressReporter(node, points=3, steps=['접근', '파지', 'Pull', '후퇴'])
    progress.start()
    for i, point in enumerate(points):
        progress.point(i, point.name)
        progress.step('접근');  ...동작...
        progress.step('파지');  ...동작...
    progress.finish()            # 100 %. 중간에 그만둘 때는 progress.abort('사유')

진행률 = (끝난 Point 수 + 현재 Point 안에서의 단계 위치) / 전체 Point 수.
단계 이름이 steps 에 없으면 글자만 바뀌고 퍼센트는 그대로다(예: 시작 전 '홈 이동').

2) HMI 버튼까지 받을 때 (control=True):

    progress = ProgressReporter(node, points=3, steps=[...], control=True)
    progress.wait_for_start()    # start() 대신. HMI 에서 '검사 시작' 을 누를 때까지 기다린다
    ...
    progress.check_pause()       # 모션을 걸기 전: '일시정지' 가 눌려 있으면 '이어하기' 까지 기다린다
    amovej(...)
    while check_motion() != 0:   # 모션을 기다리는 동안: 로봇을 실제로 멈추고 / 이어 가는 함수를 넘긴다
        progress.check_pause(pause=멈추는_함수, resume=이어가는_함수)
    ...
    progress.finish()
    progress.close()             # 프로그램을 끝내기 전에

  - HMI 버튼은 status 의 상태에 따라 열린다. 이 부품이 '시작 대기 / 검사 중 / 일시정지 / 완료' 를
    0.5 초마다 알려 주면 상태를 보내는 노드(robot_monitor_node)가 그대로 HMI 에 표시한다.
    프로그램이 죽어 소식이 끊기면 노드는 다시 '모니터링' 으로 돌아간다.
  - HMI 의 STOP 을 받으면 wait 중이던 check_pause() 가 HmiStop 을 던진다. 동작 코드는 더 움직이지
    말고 끝내야 한다(로봇을 멈추는 것은 모니터 노드가 move_stop 으로 이미 했다).
  - 일시정지는 비동기 모션(amovej / amovel + check_motion)에서만 된다. 동기 모션(movej, mwait)은
    끝날 때까지 이 코드가 멈춰 있어 check_pause() 를 부를 수 없다.
  - 명령은 별도 스레드가 받아 표시만 해 두고, 로봇을 건드리는 일(pause / resume 함수 호출)은 전부
    check_pause() 를 부른 쪽 스레드에서 한다. 두산 라이브러리는 한 스레드에서만 써야 하기 때문이다.

3) 검사 결과까지 보고할 때 ('현재 검사 결과' 표, 상세 팝업, 제품 판정):

    progress.point(i, point_id, criteria=itf.Criteria(...))   # 검사 조건 칸에 표시된다
    ...
    progress.report_result(itf.PointResult(point_id=..., result=itf.ResultCode.PASS, ...))
    ...
    progress.finish()            # 보고된 결과로 제품 판정(PASS / FAIL / 미검사 있음)을 낸다

  - run_id(검사 1회의 번호)와 시각은 이 부품이 채운다. start() 마다 새 번호가 되고 HMI 는 표를 비운다.
  - HMI 가 늦게 켜져 SYNC 를 보내면 이번 실행의 결과를 다시 보내 준다(control=True 일 때).

4) HMI 의 'FAIL 포인트 이동' / 'MISSING 포인트 이동' 까지 받을 때 (control=True):

    name, args = progress.wait_for_command()     # wait_for_start() 대신. 'START' 또는 'MOVE_TO_POINT'
    if name == itf.CommandName.MOVE_TO_POINT:
        progress.moving(args['point_id'])        # HMI '이동 중'. 일시정지 / STOP 은 검사 중과 똑같이 받는다
        ...그 Point 로 이동 (check_pause 를 부르며 기다릴 것)...
        progress.moved()                         # 이동 전 상태(검사 완료 / 대기)로 돌아간다. 결과 표는 그대로다
    else:
        ...검사...

  wait_for_start() 를 쓰는 코드는 포인트 이동 명령을 받지 않는다(무시하고 그 사실을 HMI 로그에 남긴다).

5) 설계 문서(CCCIS Sequence #0~#2, Common Sequence #1)의 흐름에 맞춰 쓸 때. 전부 선택 사항이고,
   쓰지 않으면 위 1)~4) 의 동작은 그대로다. 예제: ~/ros_ws/main_work_skeleton.py

    progress = ProgressReporter(node, points=N, steps=[...], control=True,
                                watch_heartbeat=True,    # HMI 통신 단절 감시 (아래)
                                handles_home=True)       # HMI 'Home 이동' 을 이 코드가 받는다
    name, args = progress.wait_for_command(auto_start=False)   # START 를 받아도 아직 시작을 알리지 않는다
    if START 를 받을 수 없는 상태:
        progress.reject('사유')              # START VALIDATION - DENY: HMI 팝업, 대기 상태 그대로
    progress.start()                         # ACCEPT: 여기서 새 검사(run)가 시작된다
    progress.sequence('Work Initialize')     # HMI '현재 단계' 앞에 시퀀스 이름이 붙는다
    if 초기화 실패:
        progress.fail('사유')                # INIT FAIL: HMI 팝업, 검사 종료 -> 다시 wait_for_command
    ...
    progress.error('사유')                   # ERROR: HMI 팝업, 검사 종료 (자동 Home Return 없음)

  - 일시정지: '일시정지' 를 누르면 곧바로 HMI 가 '일시정지 요청' 이 되고, 동작 코드가 check_pause() 를
    부르는 지점에서 '일시정지' 가 된다. check_pause() 를 안전한 동작 완료 지점에서만(pause / resume
    함수 없이) 부르면 문서의 Safe Pause Point 방식이고, 모션을 기다리는 루프에서 pause / resume 함수를
    넘겨 부르면 그 자리에서 바로 멈추는 방식이다.
  - HMI 통신 단절(watch_heartbeat=True): 검사·이동 중에 HMI heartbeat 가 heartbeat_lost_sec 넘게 끊기면
    일시정지를 요청한다(사유 COMM_LOST). 통신이 돌아와도 스스로 재개하지 않고 사용자의 '이어하기' 를
    기다린다. comm_timeout_sec 안에 돌아오지 않으면 check_pause() 가 HmiCommError 를 던진다 -
    동작 코드는 HmiStop 과 똑같이 더 움직이지 말고 끝내야 한다.
  - Home 이동(handles_home=True): wait_for_command() 가 'MOVE_HOME' 도 돌려준다. moving('HOME') 으로
    알리고 Home Return 시퀀스를 수행한 뒤 home_done(성공 여부) 로 끝낸다. 이 동작 코드가 떠 있지 않을
    때의 Home 버튼은 지금까지처럼 모니터 노드가 처리한다.

동작 코드는 status 를 직접 보내지 않는다. 진행 상황만 cable_inspection/progress 로 보내면
상태를 보내는 노드(robot_monitor_node)가 로봇 값과 합쳐 HMI 로 보낸다.
나중에 검사 노드가 status 를 직접 보내게 되더라도 이 클래스의 사용법은 그대로 두고
_publish() 안만 바꾸면 된다.
"""

import copy
from datetime import datetime
import os
import threading
import time

import rclpy
from rclpy.executors import SingleThreadedExecutor

from . import interface as itf

# 두산 예제 노드는 namespace(dsr01) 안에 만들어지므로 절대 이름으로 보낸다.
DEFAULT_TOPIC = '/' + itf.TOPIC_PROGRESS
DEFAULT_COMMAND_TOPIC = '/' + itf.TOPIC_COMMAND
DEFAULT_RESULT_TOPIC = '/' + itf.TOPIC_RESULT
DEFAULT_LOG_TOPIC = '/' + itf.TOPIC_LOG
DEFAULT_HEARTBEAT_TOPIC = '/' + itf.TOPIC_HEARTBEAT

HEARTBEAT_SEC = 0.5      # control=True 일 때 현재 상태를 다시 알리는 주기
RUN_SETTLE_SEC = 0.3     # 새 run_id 가 status 로 HMI 에 닿을 시간. 그 전에 결과를 보내면 표와 함께 지워진다
WAIT_SLICE_SEC = 0.1     # 기다리는 동안 STOP / Ctrl+C 를 확인하는 간격


class HmiStop(Exception):
    """HMI 에서 STOP 을 눌렀다. 동작 코드는 더 움직이지 말고 끝내야 한다."""


class HmiCommError(HmiStop):
    """
    HMI 통신이 제한 시간 안에 복구되지 않았다 (Common Sequence #1 의 COMM_ERROR).

    HmiStop 의 한 종류다: 'except HmiStop' 으로 함께 잡히고, 처리도 같다(더 움직이지 말고 끝낸다).
    """


class _CommandListener:
    """HMI 명령을 별도 노드·스레드에서 받는다 (동작 코드가 sleep 중이어도 놓치지 않게)."""

    def __init__(self, context, topic, on_command, on_tick, heartbeat_topic='', on_heartbeat=None):
        self._node = rclpy.create_node(f'hmi_control_{os.getpid()}', context=context)
        self._topic = topic
        self._node.create_subscription(itf.COMMAND_MSG_TYPE, topic, on_command, itf.QOS_DEPTH)
        if on_heartbeat is not None:
            self._node.create_subscription(
                itf.HEARTBEAT_MSG_TYPE, heartbeat_topic, on_heartbeat, 10)
        self._node.create_timer(HEARTBEAT_SEC, on_tick)
        self._executor = SingleThreadedExecutor(context=context)
        self._executor.add_node(self._node)
        self._thread = threading.Thread(target=self._spin, daemon=True)
        self._thread.start()

    def _spin(self):
        try:
            self._executor.spin()
        except Exception:  # noqa: BLE001 - rclpy.shutdown() 으로 끝날 때 나는 예외
            pass

    def hears_hmi(self) -> bool:
        """명령을 보내는 쪽(HMI)이 보이는가."""
        return self._node.count_publishers(self._topic) > 0

    def close(self):
        self._executor.shutdown(timeout_sec=1.0)
        self._thread.join(timeout=1.0)
        self._node.destroy_node()


class ProgressReporter:
    """Point / 단계 단위로 진행률을 계산해 HMI 쪽으로 보낸다. control=True 면 HMI 버튼도 받는다."""

    def __init__(self, node, points: int, steps, topic: str = DEFAULT_TOPIC,
                 control: bool = False, command_topic: str = DEFAULT_COMMAND_TOPIC,
                 result_topic: str = DEFAULT_RESULT_TOPIC,
                 watch_heartbeat: bool = False, heartbeat_lost_sec: float = 3.0,
                 comm_timeout_sec: float = 30.0, handles_home: bool = False,
                 log_topic: str = DEFAULT_LOG_TOPIC,
                 heartbeat_topic: str = DEFAULT_HEARTBEAT_TOPIC):
        self._points = max(1, int(points))
        self._steps = list(steps)
        self._pub = node.create_publisher(itf.PROGRESS_MSG_TYPE, topic, 10)
        self._result_pub = node.create_publisher(itf.RESULT_MSG_TYPE, result_topic, itf.QOS_DEPTH)
        self._log_pub = node.create_publisher(itf.LOG_MSG_TYPE, log_topic, itf.QOS_DEPTH)
        self._run_id = 0
        self._results = []                  # 이번 실행에서 보고한 결과 (SYNC 재전송, 제품 판정용)
        self._point_index = 0
        self._step_index = 0
        self._state = itf.Progress()
        self._lock = threading.RLock()      # _state 는 명령 스레드(주기 보고)도 읽는다

        self._start = threading.Event()
        self._pause = threading.Event()
        self._resume = threading.Event()
        self._stop = threading.Event()
        self._pending = ('', {})            # 기다리는 동안 받은 명령 (이름, args)
        self._before_move = None            # moving() 직전의 상태. moved() 가 되돌린다
        # 받은 명령을 확인하는 동안(wait_for_command 가 돌아온 뒤 ~ start / 다음 대기)에는 새 START / 이동
        # 명령을 받지 않는다. 대기·완료 상태라도 그 사이에 또 눌린 버튼이 쌓이면 안 되기 때문이다.
        # 완료(finish)나 이동 완료(moved)를 알린 직후에 눌린 버튼은 받는다 - 다음 대기에서 처리된다.
        self._deciding = False
        self._pre_pause_state = ''          # 일시정지 요청 직전의 상태 (RUNNING / MOVING). 재개 때 되돌린다
        self._handles_home = bool(handles_home) and control
        # HMI 통신 단절 감시 (watch_heartbeat=True 일 때만)
        self._watch_heartbeat = bool(watch_heartbeat) and control
        self._heartbeat_lost_sec = float(heartbeat_lost_sec)
        self._comm_timeout_sec = float(comm_timeout_sec)
        self._last_heartbeat = time.monotonic()
        self._comm_lost_at = None           # 끊긴 것을 알아챈 시각. None = 정상
        self._listener = None
        if control:
            self._listener = _CommandListener(
                node.context, command_topic, self._on_command, self._on_tick,
                heartbeat_topic, self._on_heartbeat if self._watch_heartbeat else None)

    @property
    def percent(self) -> int:
        """현재 진행률(0~100)."""
        return self._state.percent

    def start(self, wait_sec: float = 1.0):
        """0 % 로 시작을 알린다. 받는 쪽이 연결될 때까지 잠깐(최대 wait_sec) 기다린다."""
        deadline = time.monotonic() + wait_sec
        while self._pub.get_subscription_count() == 0 and time.monotonic() < deadline:
            time.sleep(0.05)
        with self._lock:
            self._deciding = True               # 검사 중에는 어차피 상태 때문에 안 받는다
            self._point_index = 0
            self._step_index = 0
            self._run_id = max(self._run_id + 1, int(time.time()))   # 프로그램을 다시 켜도 안 겹친다
            self._results = []
            self._state = itf.Progress(active=True, run_state=self._run(itf.State.RUNNING),
                                       run_id=self._run_id)
            self._publish()
        time.sleep(RUN_SETTLE_SEC)

    def set_points(self, points: int):
        """전체 Point 수를 바꾼다 (Recipe 를 '검사 시작' 뒤에야 알 수 있을 때)."""
        self._points = max(1, int(points))

    def point(self, index: int, name: str = '', criteria: itf.Criteria = None):
        """Point 하나를 시작한다. index 는 0 부터 센다. criteria 를 주면 HMI 검사 조건 칸에 표시된다."""
        with self._lock:
            self._point_index = max(0, min(self._points - 1, int(index)))
            self._step_index = 0
            self._state.point = name or f'Point {self._point_index + 1}'
            self._state.step = ''
            self._state.criteria = criteria or itf.Criteria()
            self._state.judgement = '검사 중'
            self._update_percent()
            self._publish()

    def report_result(self, result: itf.PointResult):
        """Point 1개의 검사 결과를 HMI 로 보낸다. run_id 와 (비어 있으면) 시각은 여기서 채운다."""
        with self._lock:
            result.run_id = self._run_id
            if not result.stamp:
                result.stamp = datetime.now().isoformat(timespec='seconds')
            self._results.append(result)
            self._result_pub.publish(itf.encode_result(result))
            self._state.judgement = result.result
            self._publish()

    def step(self, name: str):
        """현재 Point 안에서 name 단계를 시작한다."""
        with self._lock:
            self._state.step = name
            if self._before_move is None:       # 이동(moving ~ moved) 중에는 검사 진행률을 건드리지 않는다
                if name in self._steps:
                    self._step_index = self._steps.index(name)
                self._update_percent()
            self._publish()

    def finish(self):
        """정상 완료: 100 %."""
        with self._lock:
            product = self._product_result()
            self._deciding = False
            self._state = itf.Progress(active=False, percent=100, point=self._state.point,
                                       run_state=self._run(itf.State.DONE), run_id=self._run_id,
                                       judgement=product, product_result=product,
                                       end_reason=itf.EndReason.COMPLETED)
            self._publish()
        time.sleep(0.2)         # 프로세스가 바로 끝나도 마지막 메시지가 나가도록

    def abort(self, note: str = '', end_reason: str = ''):
        """
        중단: HMI 진행률을 0 으로 되돌리고 사유를 남긴다. 이미 끝났으면 아무것도 안 한다.

        end_reason(itf.EndReason)은 작업 단위 기록에 남는다. 따로 주지 않으면 HMI STOP 을 받은
        뒤에는 STOP, 아니면 ABORTED 다.
        """
        if not end_reason:
            end_reason = itf.EndReason.STOP if self._stop.is_set() else itf.EndReason.ABORTED
        with self._lock:
            if not self._state.active and self._state.run_state != itf.State.MOVING:
                return
            self._before_move = None
            # run_state 를 비운다 = 더는 HMI 버튼을 받지 않는다(HMI 는 '모니터링' 으로 돌아간다).
            self._state = itf.Progress(active=False, percent=0, aborted=True, note=note,
                                       run_id=self._run_id, judgement='중단',
                                       end_reason=end_reason)
            self._publish()
        time.sleep(0.2)

    # ------------------------------------------------------------ 설계 문서의 흐름 (선택 사항)
    def sequence(self, name: str):
        """현재 시퀀스 이름을 알린다 (예: 'Work Initialize'). HMI '현재 단계' 앞에 붙는다."""
        with self._lock:
            self._state.sequence = name
            self._state.step = ''
            self._publish()

    def reject(self, reason: str):
        """START VALIDATION - DENY: 시작하지 않는다. 사유를 HMI 팝업으로 알리고 대기 상태로 남는다."""
        self._popup('WARN', f'검사 시작 거부 - {reason}')

    def fail(self, reason: str):
        """INIT FAIL: 시작 조건을 만족하지 못해 검사를 끝낸다. 사유를 HMI 팝업으로 알린다."""
        self._popup('WARN', f'작업 초기화 실패 - {reason}')
        self.abort(f'(INIT FAIL: {reason})', itf.EndReason.INIT_FAIL)

    def error(self, reason: str):
        """ERROR: 검사를 끝낸다 (자동 Home Return 없음). 원인을 HMI 팝업으로 알린다."""
        self._popup('ERROR', f'작업 오류로 종료 - {reason}')
        self.abort(f'(ERROR: {reason})', itf.EndReason.ERROR)

    def home_done(self, success: bool, reason: str = ''):
        """Home Return 시퀀스의 결과(SUCCESS / FAIL)를 알리고 이동 전 상태로 돌아간다."""
        if not success:
            self._popup('ERROR', f'Home Return 실패 - {reason or "원인 미상"}')
        self.moved()

    def _popup(self, level: str, text: str):
        stamp = datetime.now().isoformat(timespec='seconds')
        self._log_pub.publish(itf.encode_log(itf.LogEntry(stamp, level, text, popup=True)))

    # ------------------------------------------------------------ HMI 버튼 (control=True)
    def wait_for_start(self) -> dict:
        """
        HMI 에서 '검사 시작' 을 누를 때까지 기다린 뒤 0 % 로 시작을 알린다.

        START 명령의 args(예: {'recipe_id': ...})를 돌려준다. control=False 면 기다리지 않는다.
        포인트 이동 명령은 받지 않는다(받으려면 wait_for_command).
        """
        while True:
            name, args = self.wait_for_command()
            if name == itf.CommandName.START:
                return args
            self._note('이 동작 코드는 포인트 이동을 지원하지 않음')

    def wait_for_command(self, auto_start: bool = True):
        """
        HMI 의 '검사 시작' 또는 'FAIL / MISSING 포인트 이동' 을 기다린다. (명령 이름, args) 를 돌려준다.

        START 면 0 % 로 시작을 알린 뒤에 돌아온다(args 예: {'recipe_id': ...}). auto_start=False 면
        알리지 않고 돌아온다 - 시작해도 되는지 확인한 뒤 start() 또는 reject() 를 직접 부를 것.
        MOVE_TO_POINT 면 상태를 바꾸지 않고 돌아온다(args: {'point_id': ..., 'reason': 'FAIL'|'MISSING'}).
        이동하기 전에 moving(), 끝나고 moved() 를 부를 것. handles_home=True 면 MOVE_HOME 도 돌려준다
        (moving('HOME') ... home_done()). control=False 면 기다리지 않고 START 를 돌려준다.
        """
        if self._listener is None:
            self.start()
            return itf.CommandName.START, {}
        with self._lock:
            # 완료 표시(100 %)는 남겨 둔다. 완료를 알린 직후에 눌린 버튼도 버리지 않는다.
            if self._state.run_state != itf.State.DONE:
                self._state = itf.Progress(run_state=itf.State.IDLE)
                self._start.clear()
            self._deciding = False
        # '시작 대기' 는 여기서 바로 알리지 않고 주기 보고(_on_tick)에 맡긴다. HMI 가 보일 때만 알린다.
        while not self._start.wait(WAIT_SLICE_SEC):
            pass
        with self._lock:
            self._deciding = True
            name, args = self._pending
            for flag in (self._start, self._pause, self._resume, self._stop):
                flag.clear()            # 기다리는 동안 눌린 것은 이번 실행과 무관하다
            self._comm_lost_at = None
            self._last_heartbeat = time.monotonic()
        if name == itf.CommandName.START and auto_start:
            self.start()
        return name, dict(args)

    def moving(self, point_id: str):
        """이동(포인트 이동, Home Return)을 시작한다고 알린다 (HMI '이동 중'). 결과 표시는 그대로 둔다."""
        with self._lock:
            # 이동 전 표시(진행률, 단계, 시퀀스, 판정)를 통째로 보관한다. 이동 중에 step() / sequence() 로
            # 글자를 바꿔도 moved() 가 그대로 되돌린다.
            self._before_move = copy.copy(self._state)
            self._last_heartbeat = time.monotonic()
            self._state.run_state = itf.State.MOVING
            self._state.step = f'{point_id} (으)로 이동'
            self._state.note = ''
            self._publish()

    def moved(self):
        """포인트 이동이 끝났다: moving() 직전의 상태(검사 완료 / 대기)로 돌아간다."""
        with self._lock:
            if self._before_move is None:
                return
            self._state = self._before_move
            self._state.note = ''
            self._state.pause_reason = itf.PauseReason.NONE
            self._before_move = None
            self._deciding = False
            self._publish()

    def check_pause(self, pause=None, resume=None) -> bool:
        """
        '일시정지' 가 눌려 있으면 '이어하기' 까지 여기서 기다린다. 기다렸으면 True.

        pause / resume: 로봇을 실제로 멈추고 이어 가는 함수(성공하면 True 를 돌려줄 것). 모션을
        기다리는 중에 부를 때만 넘긴다. 모션을 걸기 전에 부를 때는 생략한다(기다리기만 한다).
        pause 가 실패하면 일시정지하지 않고 False 를 돌려준다. resume 이 실패하면 일시정지 상태로
        남아 '이어하기' 를 다시 기다린다. STOP 을 받았으면 HmiStop 을 던진다.
        """
        if self._listener is None:
            return False
        if self._stop.is_set():
            raise HmiStop()
        if not self._pause.is_set():
            return False
        self._pause.clear()
        resumed_state = self._pre_pause_state or itf.State.RUNNING      # RUNNING 또는 MOVING
        if pause is not None and not pause():
            self._note('일시정지 실패 - 계속 진행')
            self._set_run_state(resumed_state)
            return False
        self._set_run_state(itf.State.PAUSED, keep_pause_reason=True)
        while True:
            while not self._resume.wait(WAIT_SLICE_SEC):
                if self._stop.is_set():
                    raise HmiStop()
                lost_at = self._comm_lost_at
                if lost_at is not None and time.monotonic() - lost_at > self._comm_timeout_sec:
                    self._popup('ERROR', 'HMI 통신이 제한 시간 안에 복구되지 않아 작업을 종료합니다 '
                                         '(COMM_ERROR)')
                    raise HmiCommError()
            self._resume.clear()
            if self._stop.is_set():
                raise HmiStop()
            if resume is None or resume():
                break
            self._note('이어하기 실패 - 일시정지 유지')
        self._set_run_state(resumed_state)
        return True

    def note(self, text: str):
        """HMI 시스템 로그에 남길 짧은 알림 (모니터 노드가 WARN 으로 옮겨 적는다)."""
        self._note(text)

    def close(self):
        """명령 수신을 끝낸다. 프로그램을 끝내기 전(rclpy.shutdown() 전)에 부른다."""
        if self._listener is not None:
            self._listener.close()
            self._listener = None

    def _on_command(self, msg):
        """명령 스레드에서 불린다. 표시만 해 두고 로봇은 건드리지 않는다."""
        try:
            cmd = itf.decode_command(msg)
        except (ValueError, TypeError):
            return
        run_state = self._state.run_state
        if cmd.name == itf.CommandName.ESTOP:
            self._stop.set()
        elif cmd.name in (itf.CommandName.START, itf.CommandName.MOVE_TO_POINT,
                          itf.CommandName.MOVE_HOME):
            if cmd.name == itf.CommandName.MOVE_HOME and not self._handles_home:
                return                      # 모니터 노드가 처리한다
            with self._lock:
                waiting = self._state.run_state in (itf.State.IDLE, itf.State.DONE)
                if waiting and not self._deciding and not self._start.is_set():
                    self._pending = (cmd.name, dict(cmd.args))
                    self._start.set()
        elif cmd.name == itf.CommandName.PAUSE:
            self._request_pause(itf.PauseReason.USER)
        elif cmd.name == itf.CommandName.RESUME:
            # 통신이 끊긴 채로는 재개하지 않는다(끊긴 HMI 에서 RESUME 이 올 수도 없다).
            if run_state == itf.State.PAUSED and self._comm_lost_at is None:
                self._resume.set()
        elif cmd.name == itf.CommandName.SYNC:
            with self._lock:                # HMI 가 방금 켜졌다: 이번 실행의 결과를 다시 보낸다
                for result in self._results:
                    self._result_pub.publish(itf.encode_result(result))

    def _request_pause(self, reason: str):
        """일시정지를 요청한다: HMI 에는 곧바로 '일시정지 요청', 실제 정지는 check_pause() 에서."""
        with self._lock:
            if self._state.run_state not in (itf.State.RUNNING, itf.State.MOVING):
                return
            self._pre_pause_state = self._state.run_state
            self._state.run_state = itf.State.PAUSE_REQUEST
            self._state.pause_reason = reason
            self._pause.set()
            self._publish()

    def _on_heartbeat(self, _msg):
        """명령 스레드에서 불린다 (watch_heartbeat=True 일 때만)."""
        self._last_heartbeat = time.monotonic()
        if self._comm_lost_at is not None:
            self._comm_lost_at = None
            # 통신이 돌아왔다고 스스로 재개하지 않는다. 사용자가 상태를 확인하고 이어하기를 눌러야 한다.
            self._popup('WARN', "HMI 통신 복구됨 - 현재 상태를 확인한 뒤 '이어하기' 를 눌러 재개하세요")

    def _check_heartbeat(self):
        # 사용자가 이미 일시정지해 둔 상태(PAUSED)에서 HMI 가 꺼진 것은 따지지 않는다: 로봇은 멈춰 있고,
        # 제한 시간으로 작업을 끝내 버리면 보존해 둔 작업 Context 만 잃는다.
        busy = (itf.State.RUNNING, itf.State.MOVING, itf.State.PAUSE_REQUEST)
        if not self._watch_heartbeat or self._state.run_state not in busy:
            return
        if self._comm_lost_at is not None:
            return
        if time.monotonic() - self._last_heartbeat <= self._heartbeat_lost_sec:
            return
        self._comm_lost_at = time.monotonic()
        with self._lock:
            self._state.pause_reason = itf.PauseReason.COMM_LOST
        self._request_pause(itf.PauseReason.COMM_LOST)      # 이미 멈춰 있으면 아무것도 하지 않는다

    def _on_tick(self):
        """명령 스레드에서 불린다. 살아 있다는 표시로 현재 상태를 다시 보낸다."""
        listener = self._listener
        if listener is None:                # close() 와 겹친 마지막 호출
            return
        self._check_heartbeat()
        with self._lock:
            run_state = self._state.run_state
            # '검사 시작' 을 받을 수 있을 때만 시작 대기를 알린다. HMI 의 명령이 아직 이쪽에 닿지 않는데
            # 버튼부터 열리면, 눌러도 아무 일도 일어나지 않는다.
            waiting = run_state in (itf.State.IDLE, itf.State.DONE)
            if run_state and (not waiting or listener.hears_hmi()):
                self._publish()

    def _product_result(self) -> str:
        """보고된 결과로 제품 판정을 낸다. MISSING 이 남으면 PASS 가 될 수 없다."""
        categories = {itf.ResultCode.category(r.result) for r in self._results}
        if not categories:
            return itf.ProductResult.NONE
        if 'FAIL' in categories:
            return itf.ProductResult.FAIL
        if 'MISSING' in categories:
            return itf.ProductResult.INCOMPLETE
        return itf.ProductResult.PASS

    def _run(self, run_state: str) -> str:
        return run_state if self._listener is not None else ''

    def _set_run_state(self, run_state: str, keep_pause_reason: bool = False):
        with self._lock:
            self._state.run_state = run_state
            self._state.note = ''
            if not keep_pause_reason:
                self._state.pause_reason = itf.PauseReason.NONE
            self._publish()

    def _note(self, text: str):
        with self._lock:
            self._state.note = text
            self._publish()

    def _update_percent(self):
        in_point = self._step_index / len(self._steps) if self._steps else 0.0
        self._state.active = True
        self._state.percent = int(100 * (self._point_index + in_point) / self._points)

    def _publish(self):
        self._state.handles_home = self._handles_home
        self._pub.publish(itf.encode_progress(self._state))
