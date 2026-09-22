"""
실제 로봇 값을 HMI 가 구독하는 토픽으로 내보내는 읽기 전용 모니터 노드.

두산 드라이버(dsr_controller2)의 조회 서비스를 주기적으로 읽어
cable_inspection/status 로 publish 한다. 로봇을 움직이는 호출은 하나도 없다.
예외는 넷이다.
  1. HMI 의 STOP 버튼 -> motion/move_stop. 실제 로봇 옆에서 STOP 버튼이 아무 일도
     하지 않는 상황을 만들지 않기 위해서다.
  2. tool_name / tcp_name 파라미터를 준 경우에 한해, 컨트롤러의 Tool/TCP 선택이
     비어 있으면 다시 설정한다(아래 'Tool/TCP 자동 설정').

DSR_ROBOT2 는 쓰지 않는다. 그 함수들은 응답이 올 때까지 멈추는 블로킹 호출이라,
여기서는 rclpy 의 비동기 호출(call_async)로 직접 읽는다. 응답이 늦거나 드라이버가
죽어도 이 노드는 멈추지 않고 'Robot 연결 끊김' 을 내보낸다.

읽는 값
  tool/get_current_tool, tcp/get_current_tcp      -> Tool, TCP 이름
  system/get_robot_state                          -> Robot 연결, 비상정지
  motion/check_motion                             -> 이동 중 여부 (유일한 판단 근거, 아래 참고)
  aux_control/get_tool_force                      -> 현재 힘 (|Fxyz|, 원본은 tool_force 토픽)
  aux_control/get_current_posx                    -> 현재 위치, 변위 (원본은 tcp_pose 토픽)
  /<robot_ns>/error, /<robot_ns>/robot_disconnection 토픽 -> 현재 알람, 연결 끊김
  /onrobot_joint_states 토픽 (OnRobot RG2 드라이버)       -> RG2 연결, 그리퍼 폭

그리퍼 드라이버는 폭(mm)을 직접 내보내지 않고 finger_joint 각도(rad)로 바꿔 보낸다.
같은 RG2 링크 상수로 역산해 폭을 구한다. 이 폭은 드라이버의 relative_width, 즉
핑거팁 오프셋이 반영된 값이다.

Recipe 목록
  recipe_dir 의 레시피 JSON(recipe_catalog 참고)을 읽어 status.available_recipes 로 보낸다.
  HMI 에서 하나를 고르면(SELECT_RECIPE) 그 Recipe 의 id·버전·포인트 수를 status 에 싣고,
  좌표가 전부 0 인(티칭 안 된) 포인트가 있으면 경고한다. 폴더는 5 초마다 다시 확인하므로
  파일을 고치거나 추가하면 노드를 다시 띄우지 않아도 반영된다. 이 노드는 Recipe 로 로봇을
  움직이지 않는다 - 목록과 내용을 보여 줄 뿐이다.

레시피 DB
  recipe_db (SQLite, recipe_db.py 참고)가 있으면 고른 Recipe 의 제품 ID 와 판정 기준을 거기서 읽어
  status 에 채운다. 레시피 JSON 은 위치, DB 는 케이블·판정 기준을 맡고 recipe_id + point_id 로
  묶이므로, 한쪽에만 있는 포인트는 경고한다. 판정 기준은 포인트마다 다를 수 있는데 이 노드에는
  '현재 포인트' 가 없어서, 모든 포인트의 기준이 같을 때만 화면의 판정 기준 칸에 표시한다.
  DB 파일이나 뷰가 아직 없으면 경고만 남기고 DB 없이 동작한다.

진행률
  이 노드는 검사를 하지 않으므로 진행률을 스스로 알 수 없다. 동작 코드가
  cable_inspection/progress 로 보내 주면(cable_hmi.hmi_progress.ProgressReporter) 그 값을
  status 의 진행률과 '현재 단계' 에 넣는다. 완료(100 %)는 다음 실행이 시작될 때까지 남겨 두고,
  중단되면 0 으로 되돌린다.

검사 결과
  이 노드는 판정하지 않는다. 동작 코드가 결과를 cable_inspection/result 로 직접 보내고
  (ProgressReporter.report_result), 이 노드는 동작 코드가 알려 준 run_id · 현재 Point 의 판정 기준 ·
  현재 판정 · 제품 판정을 status 에 옮겨 싣기만 한다. run_id 는 동작 코드가 끝난 뒤에도 마지막 값을
  유지한다(0 으로 되돌리면 HMI 가 결과 표를 비워 버린다).

검사 시작 / 일시정지 / 이어하기
  이 노드는 이 명령들을 실행하지 않는다. HMI 버튼을 받는 동작 코드(ProgressReporter 의
  control=True)가 붙어 있으면, 그 코드가 알려 준 상태(시작 대기 / 검사 중 / 일시정지 / 완료)를
  MONITOR 대신 status 의 상태로 내보내 HMI 버튼이 열리게 할 뿐이다. 명령은 동작 코드가 같은
  command 토픽에서 직접 받는다. 동작 코드의 소식이 PROGRESS_STALE_SEC 넘게 끊기면(프로그램이
  죽음) 다시 MONITOR 로 돌아간다. 동작 코드가 검사 중·일시정지일 때는 Home 이동을 거부한다.

이동 중 판단 (2026-09-19 실제 장비에서 확인)
  get_robot_state 는 '운전 가능한 상태인가' 를 말할 뿐 '움직이는 중인가' 를 말하지 않는다.
  API 로 건 모션(movej/amovel ...) 중에도 계속 STANDBY 이고, 반대로 멈춰 있을 때 move_stop 을
  보내면 모션이 없는데도 잠깐 MOVING 이 된다. 그래서 이동 여부는 check_motion 만 보고,
  get_robot_state 는 서보 OFF·보호정지·비상정지를 알아내는 데만 쓴다.

변위는 기준 자세로부터의 TCP 거리(mm)다. 기준은 노드 시작 시 자세이며,
  ros2 service call /cable_inspection/zero_displacement std_srvs/srv/Trigger
로 현재 자세를 새 기준으로 삼을 수 있다.

  3. HMI 속도 슬라이더 -> motion/change_operation_speed (아래 '속도 설정').

  4. HMI 'Home 이동' 버튼 -> motion/move_joint (아래 'Home 이동'). 이 노드에서 유일하게
     로봇을 움직이는 기능이며 allow_home_move=true 일 때만 동작한다.

Home 이동
  home_joints(관절각 6개, deg)로 비동기 관절 이동(sync_type=ASYNC)을 건다. 드라이버의
  move_home 서비스는 동기 호출이라 이동 중 다른 서비스를 모두 막고, TP 의 사용자 홈 각도를
  읽어 오는 서비스도 없어서, 홈 자세를 파라미터로 직접 받는다.
  받아들이는 조건: 드라이버 연결됨, 로봇 STANDBY, 모션 없음, 다른 Home 이동 없음, 동작 코드가 검사·이동 중이 아님.
  Tool/TCP 설정은 조건이 아니다(관절 이동이라 TCP 와 무관, 툴 무게는 힘 계산에만 영향) - 미설정이면 경고만 남긴다.
  모션이 끝나면 get_current_posj 로 실제 도착했는지 확인한다 - check_motion 은 '도착' 과
  'STOP·보호정지로 중간에 멈춤' 을 구분하지 못하기 때문이다.

속도 설정
  TP 의 속도 슬라이더와 같은 전체 배율(1~100 %)이다. 코드에 적은 vel 과 곱해지므로
  100 % 라도 코드의 속도를 넘지 않는다. 드라이버에는 이 값을 읽는 서비스가 없어서,
  HMI 에는 '이 노드가 마지막으로 설정에 성공한 값' 을 표시한다. 아직 설정한 적이 없거나
  드라이버 연결이 바뀌면(재시작으로 값이 초기화됐을 수 있으므로) 0 = '모름' 을 보낸다.
  노드 시작 시 자동으로 설정하지 않는다 - 슬라이더를 움직이기 전에는 로봇 속도를 건드리지 않는다.
  TP 에서 속도를 바꾸면 HMI 표시와 어긋난다(알 방법이 없음).

Tool/TCP 자동 설정
  두산 드라이버를 재시작하면 컨트롤러의 현재 Tool/TCP 선택이 풀린다. 그러면 툴 무게가
  0 으로 계산되어 힘 값에 툴 무게가 통째로 실리고, TCP 위치도 플랜지 기준이 된다.
  그래서 이름이 비어 있는 것을 볼 때마다(노드 시작 시 한 번이 아니라) 다시 설정한다.
    - 비어 있을 때만 설정한다. TP 에서 다른 툴을 골라 둔 경우는 덮어쓰지 않고 알람만 낸다.
    - 로봇이 STANDBY 이고 모션이 없을 때만 호출한다(중력 보상 모델이 바뀌므로).
    - 실패(success=False: 그 이름이 TP 에 등록되지 않음)하면 알람을 내고 재시도를 멈춘다.
      드라이버가 다시 연결되면 재시도한다.

파라미터
  robot_ns (str, 'dsr01')    : 두산 드라이버 namespace
  fast_rate_hz (float, 10.0) : 힘·자세 읽기 주기
  allow_stop (bool, True)    : HMI STOP -> move_stop 연결 여부
  gripper_topic (str, '/onrobot_joint_states') : RG2 드라이버의 JointState 토픽
  allow_home_move (bool, False): HMI 'Home 이동' 을 허용할지. 기본은 꺼짐(로봇을 움직이지 않음)
  home_joints (float[6])     : 홈 관절각 [deg]. 기본 (0, 0, 90, 0, 90, 0)
  home_vel, home_acc (float) : Home 이동 속도 [deg/s], 가속도 [deg/s^2]. 기본 30, 30
  recipe_dir (str, '')       : 레시피 JSON 폴더. 비우면 Recipe 목록을 보내지 않는다
  recipe_db (str, '')        : 레시피 정보 SQLite 파일. 비우면 쓰지 않는다
  tool_name (str, '')        : 기대하는 Tool 이름. 비우면 Tool 은 건드리지 않고 경고만 한다
  tcp_name (str, '')         : 기대하는 TCP 이름. 비우면 TCP 는 건드리지 않고 경고만 한다
  tool_weight_kg (float, 0.0): TP 에 등록된 tool_name 의 무게. 드라이버에 무게를 읽는
                               서비스가 없어 표시용으로 받는다. 현재 Tool 이 tool_name 일 때만 표시
"""

from datetime import datetime
import math
import time

from dsr_msgs2.msg import RobotDisconnection, RobotError
from dsr_msgs2.srv import (
    ChangeOperationSpeed, CheckMotion, GetCurrentPosj, GetCurrentPosx, GetCurrentTcp,
    GetCurrentTool, GetRobotState, GetToolForce, MoveJoint, MoveStop, SetCurrentTcp,
    SetCurrentTool,
)
import rclpy
from rclpy.executors import ExternalShutdownException
from rclpy.node import Node
from sensor_msgs.msg import JointState
from std_msgs.msg import Float64MultiArray
from std_srvs.srv import Trigger

from . import interface as itf
from . import recipe_catalog
from . import recipe_db

DR_BASE = 0
DR_QSTOP = 1                 # Quick stop (Stop Category 2)
DR_STATE_IDLE = 0            # check_motion: 0 정지 / 1 모션 계산 중 / 2 모션 수행 중

ROBOT_STATE_NAMES = {
    0: 'INITIALIZING', 1: 'STANDBY', 2: 'MOVING', 3: 'SAFE_OFF', 4: 'TEACHING',
    5: 'SAFE_STOP', 6: 'EMERGENCY_STOP', 7: 'HOMMING', 8: 'RECOVERY', 9: 'SAFE_STOP2',
    10: 'SAFE_OFF2', 15: 'NOT_READY',
}
STATE_STANDBY = 1
STATE_MOVING = 2             # 주의: '움직이는 중' 이 아니다. 위 '이동 중 판단' 참고
STATE_EMERGENCY_STOP = 6
# 로봇이 스스로 멈춘 상태 - HMI '현재 알람' 에 띄운다.
STATE_ALARMS = {
    3: 'Servo Off (SAFE_OFF)', 5: '보호 정지 (SAFE_STOP)', 9: '보호 정지 (SAFE_STOP2)',
    10: 'Servo Off (SAFE_OFF2)', 15: '로봇 준비 안 됨 (NOT_READY)',
}

# OnRobot 드라이버(OnRobotRGControllerServer.py, gtype 'rg2')의 링크 상수 [m, rad].
# 드라이버의 jointValueToWidth() 와 같은 식이어야 한다.
RG2_L1, RG2_L3 = 0.108505, 0.055
RG2_THETA1, RG2_THETA3 = 1.41371, 0.76794
RG2_DY = -0.0144

STATUS_PERIOD_SEC = 0.1
FRESH_SEC = 1.5              # 이 시간 안에 응답이 없으면 그 값은 '끊김' 으로 본다
REQUEST_TIMEOUT_SEC = 2.0    # 응답 없는 요청을 포기하는 시간
ALARM_HOLD_SEC = 30.0        # error 토픽으로 온 알람을 화면에 유지하는 시간
DISCONNECT_HOLD_SEC = 3.0
STARTUP_GRACE_SEC = 5.0      # 시작 후 이 시간까지는 첫 응답 대기로 본다
SYNC_TYPE_ASYNC = 1          # move_joint: 명령만 걸고 바로 반환
HOME_TOLERANCE_DEG = 0.5     # 이 오차 안이면 홈에 도착한 것으로 본다
HOME_START_TIMEOUT_SEC = 2.0  # 이 시간 안에 모션이 안 보이면 '이미 끝남' 으로 보고 도착 확인
NAME_FRESH_SEC = 4.0         # Tool/TCP 이름(1 s 주기)을 '방금 읽은 값' 으로 보는 시간
RECIPE_RESCAN_SEC = 5.0      # 레시피 폴더를 다시 확인하는 주기
PROGRESS_STALE_SEC = 2.0     # HMI 버튼을 받는 동작 코드의 소식(0.5 s 주기)이 끊겼다고 보는 시간
CONTROL_STATES = (itf.State.IDLE, itf.State.RUNNING, itf.State.PAUSE_REQUEST, itf.State.PAUSED,
                  itf.State.DONE,
                  itf.State.MOVING)         # MOVING: 동작 코드가 FAIL / MISSING 포인트나 홈으로 이동 중
BUSY_STATES = (itf.State.RUNNING, itf.State.PAUSE_REQUEST, itf.State.PAUSED, itf.State.MOVING)
CONTROL_COMMANDS = (itf.CommandName.START, itf.CommandName.PAUSE, itf.CommandName.RESUME,
                    itf.CommandName.MOVE_TO_POINT)
SETUP_RETRY_SEC = 3.0        # Tool/TCP 설정 요청 사이의 최소 간격


def rg2_joint_to_width_mm(joint_angle: float) -> float:
    """RG2 finger_joint 각도(rad) -> 그리퍼 폭(mm)."""
    half = math.cos(joint_angle + RG2_THETA3) * RG2_L3 + RG2_DY + RG2_L1 * math.cos(RG2_THETA1)
    return max(0.0, half * 2000.0)


class Poller:
    """
    조회 서비스 하나를 주기적으로 비동기 호출한다.

    이전 요청의 응답이 아직 안 왔으면 새 요청을 보내지 않으므로, 드라이버가 느려져도
    요청이 쌓이지 않는다.
    """

    def __init__(self, node, srv_type, name, period, on_response, make_request=None):
        self.name = name
        self.last_ok = 0.0
        self._node = node
        self._srv_type = srv_type
        self._on_response = on_response
        self._make_request = make_request or srv_type.Request
        self._client = node.create_client(srv_type, name)
        self._pending = None
        self._sent_at = 0.0
        node.create_timer(period, self._tick)

    @property
    def fresh(self) -> bool:
        """최근에 정상 응답을 받았는가."""
        return (time.monotonic() - self.last_ok) < FRESH_SEC

    def fresh_within(self, seconds: float) -> bool:
        """최근 seconds 초 안에 정상 응답을 받았는가."""
        return (time.monotonic() - self.last_ok) < seconds

    def _tick(self):
        now = time.monotonic()
        if self._pending is not None:
            if now - self._sent_at < REQUEST_TIMEOUT_SEC:
                return
            self._pending.cancel()
            self._pending = None
        if not self._client.service_is_ready():
            return
        self._sent_at = now
        self._pending = self._client.call_async(self._make_request())
        self._pending.add_done_callback(self._done)

    def _done(self, future):
        if future is not self._pending:
            return                      # 시간 초과로 버린 요청의 늦은 응답
        self._pending = None
        if future.cancelled() or future.exception() is not None:
            return
        response = future.result()
        if response is None or not getattr(response, 'success', True):
            return
        self.last_ok = time.monotonic()
        self._on_response(response)


class NameSetter:
    """
    컨트롤러의 Tool 또는 TCP 선택 하나를 기대 이름으로 유지한다.

    check() 가 돌려주는 문자열은 HMI '현재 알람' 에 띄울 문제 설명이다(문제 없으면 '').
    """

    def __init__(self, node, label, srv_type, srv_name, expected, log):
        self.label = label
        self.expected = expected
        self._srv_type = srv_type
        self._client = node.create_client(srv_type, srv_name)
        self._log = log
        self._pending = None
        self._last_try = -SETUP_RETRY_SEC
        self._failed = False

    def reset(self):
        """드라이버가 다시 연결됐을 때 - 실패 기록을 지우고 다시 시도하게 한다."""
        self._failed = False

    def check(self, current: str, may_set: bool) -> str:
        """현재 이름을 보고 필요하면 설정 요청을 보낸다. 문제 설명을 돌려준다."""
        if current:
            if not self.expected or current == self.expected:
                self._failed = False
                return ''
            return f'{self.label} 불일치: {current} (기대 {self.expected})'
        if not self.expected:
            return f'{self.label} 미설정 - 힘 값 신뢰 불가'
        if self._failed:
            return f'{self.label} 설정 실패: {self.expected} 가 TP 에 없음?'
        now = time.monotonic()
        ready = (may_set and self._pending is None and self._client.service_is_ready()
                 and now - self._last_try >= SETUP_RETRY_SEC)
        if ready:
            self._last_try = now
            self._pending = self._client.call_async(self._srv_type.Request(name=self.expected))
            self._pending.add_done_callback(self._done)
            self._log('WARN', f'{self.label} 미설정 감지 - {self.expected} 로 설정 요청')
        return f'{self.label} 미설정 - 힘 값 신뢰 불가'

    def _done(self, future):
        self._pending = None
        ok = (not future.cancelled() and future.exception() is None
              and future.result() is not None and future.result().success)
        if ok:
            self._log('INFO', f'{self.label} 설정 완료: {self.expected}')
        else:
            self._failed = True
            self._log('ERROR', f'{self.label} 설정 실패: {self.expected} - TP에 등록되었는지 확인',
                      popup=True)


class RobotMonitorNode(Node):
    """두산 드라이버 조회 서비스 -> cable_inspection/status."""

    def __init__(self):
        super().__init__('robot_monitor_node')
        self.declare_parameter('robot_ns', 'dsr01')
        self.declare_parameter('fast_rate_hz', 10.0)
        self.declare_parameter('allow_stop', True)
        self.declare_parameter('gripper_topic', '/onrobot_joint_states')
        self.declare_parameter('allow_home_move', False)
        self.declare_parameter('home_joints', [0.0, 0.0, 90.0, 0.0, 90.0, 0.0])
        self.declare_parameter('home_vel', 30.0)
        self.declare_parameter('home_acc', 30.0)
        self.declare_parameter('recipe_dir', '')
        self.declare_parameter('recipe_db', '')
        self.declare_parameter('tool_name', '')
        self.declare_parameter('tcp_name', '')
        self.declare_parameter('tool_weight_kg', 0.0)
        robot_ns = self.get_parameter('robot_ns').value.strip('/')
        fast = 1.0 / max(1.0, float(self.get_parameter('fast_rate_hz').value))
        srv = f'/{robot_ns}/dsr_controller2/'

        self._tool_name = ''
        self._tcp_name = ''
        self._robot_state = -1
        self._joint = None            # 현재 관절각 [deg x 6]
        self._motion = 0
        self._force = [0.0] * 6
        self._pose = None
        self._ref_pose = None
        self._alarm = ''
        self._alarm_at = 0.0
        self._disconnected_at = -DISCONNECT_HOLD_SEC
        self._was_connected = None
        self._started_at = time.monotonic()
        self._gripper_width = 0.0
        self._gripper_at = 0.0
        self._gripper_was_connected = False
        self._setup_alarm = ''
        self._speed_percent = 0        # 0 = 모름 (아직 설정한 적 없음)
        self._speed_wanted = None      # 응답 대기 중에 새로 들어온 요청 (마지막 것만 유지)
        self._speed_pending = None
        self._recipes = {}             # recipe_id -> recipe_catalog.RecipeInfo
        self._recipe = None            # HMI 에서 고른 Recipe
        self._recipe_signature = None
        self._recipe_problems = []
        self._recipe_db_info = None    # 고른 Recipe 의 DB 정보 (없으면 None)
        self._progress = itf.Progress()  # 동작 코드가 마지막으로 알려 준 진행 상황
        self._progress_at = 0.0          # 그것을 받은 시각
        self._run_id = 0                 # 동작 코드가 마지막으로 알려 준 검사 번호
        self._end_reason = ''            # 그 검사가 끝난 이유 (다음 검사가 시작될 때까지 유지)
        self._home_active = False      # Home 이동을 걸었고 아직 끝을 확인하지 않음
        self._home_seen_motion = False
        self._home_started = 0.0

        self._status_pub = self.create_publisher(
            itf.STATUS_MSG_TYPE, itf.TOPIC_STATUS, itf.QOS_DEPTH)
        self._log_pub = self.create_publisher(itf.LOG_MSG_TYPE, itf.TOPIC_LOG, itf.QOS_DEPTH)
        self._force_pub = self.create_publisher(Float64MultiArray, itf.TOPIC_TOOL_FORCE, 10)
        self._pose_pub = self.create_publisher(Float64MultiArray, itf.TOPIC_TCP_POSE, 10)

        self._state_poll = Poller(
            self, GetRobotState, srv + 'system/get_robot_state', 0.2, self._on_robot_state)
        self._force_poll = Poller(
            self, GetToolForce, srv + 'aux_control/get_tool_force', fast, self._on_force,
            lambda: GetToolForce.Request(ref=DR_BASE))
        self._pose_poll = Poller(
            self, GetCurrentPosx, srv + 'aux_control/get_current_posx', fast, self._on_pose,
            lambda: GetCurrentPosx.Request(ref=DR_BASE))
        self._motion_poll = Poller(
            self, CheckMotion, srv + 'motion/check_motion', 0.2, self._on_motion)
        self._tool_poll = Poller(
            self, GetCurrentTool, srv + 'tool/get_current_tool', 1.0, self._on_tool)
        self._tcp_poll = Poller(
            self, GetCurrentTcp, srv + 'tcp/get_current_tcp', 1.0, self._on_tcp)
        self._tool_setter = NameSetter(
            self, 'Tool', SetCurrentTool, srv + 'tool/set_current_tool',
            self.get_parameter('tool_name').value, self._log)
        self._tcp_setter = NameSetter(
            self, 'TCP', SetCurrentTcp, srv + 'tcp/set_current_tcp',
            self.get_parameter('tcp_name').value, self._log)
        self._tool_weight = float(self.get_parameter('tool_weight_kg').value)
        self._stop_client = self.create_client(MoveStop, srv + 'motion/move_stop')
        self._movej_client = self.create_client(MoveJoint, srv + 'motion/move_joint')
        self._posj_client = self.create_client(
            GetCurrentPosj, srv + 'aux_control/get_current_posj')
        self._speed_client = self.create_client(
            ChangeOperationSpeed, srv + 'motion/change_operation_speed')

        self.create_subscription(RobotError, f'/{robot_ns}/error', self._on_error, 10)
        self.create_subscription(
            RobotDisconnection, f'/{robot_ns}/robot_disconnection', self._on_disconnection, 10)
        self.create_subscription(
            JointState, self.get_parameter('gripper_topic').value, self._on_gripper, 10)
        # 관절각은 서비스 대신 토픽에서 받는다 (약 100 Hz, 서비스 호출이 늘지 않는다).
        self.create_subscription(
            JointState, f'/{robot_ns}/joint_states', self._on_joint_states, 10)
        self.create_subscription(
            itf.PROGRESS_MSG_TYPE, itf.TOPIC_PROGRESS, self._on_progress, itf.QOS_DEPTH)
        self.create_subscription(
            itf.COMMAND_MSG_TYPE, itf.TOPIC_COMMAND, self._on_command, itf.QOS_DEPTH)
        self.create_service(Trigger, 'cable_inspection/zero_displacement', self._on_zero)

        self.create_timer(STATUS_PERIOD_SEC, self._publish_status)
        self.create_timer(1.0, self._check_tool_setup)
        if self.get_parameter('recipe_dir').value:
            self._scan_recipes()
            self.create_timer(RECIPE_RESCAN_SEC, self._scan_recipes)
        self._log('INFO', f'로봇 모니터 시작 (읽기 전용) - 드라이버 {srv}')

    # ------------------------------------------------------------ 로봇 -> 값
    def _on_joint_states(self, msg: JointState):
        """드라이버의 관절각(rad)을 deg 로 바꿔 둔다. 앞 6개가 J1~J6 이다."""
        if len(msg.position) >= 6:
            self._joint = [math.degrees(v) for v in msg.position[:6]]

    def _on_robot_state(self, response):
        self._robot_state = int(response.robot_state)

    def _on_motion(self, response):
        self._motion = int(response.status)

    def _on_tool(self, response):
        self._tool_name = response.info

    def _on_tcp(self, response):
        self._tcp_name = response.info

    def _on_force(self, response):
        self._force = [float(v) for v in response.tool_force]
        self._force_pub.publish(Float64MultiArray(data=self._force))

    def _on_pose(self, response):
        if not response.task_pos_info or len(response.task_pos_info[0].data) < 6:
            return
        self._pose = [float(v) for v in response.task_pos_info[0].data[:6]]
        if self._ref_pose is None:
            self._ref_pose = list(self._pose)
        self._pose_pub.publish(Float64MultiArray(data=self._pose))

    def _on_gripper(self, msg):
        if not msg.position:
            return
        self._gripper_width = rg2_joint_to_width_mm(float(msg.position[0]))
        self._gripper_at = time.monotonic()

    def _on_error(self, msg):
        text = ' '.join(t for t in (msg.msg1, msg.msg2, msg.msg3) if t)
        self._alarm = f'[{msg.group}-{msg.code}] {text}'.strip()
        self._alarm_at = time.monotonic()
        if msg.level >= 3:
            self._log('ERROR', f'로봇 알람 {self._alarm}')
        else:
            self._log('WARN', f'로봇 알림 {self._alarm}')

    def _on_disconnection(self, _msg):
        self._disconnected_at = time.monotonic()
        self._log('ERROR', '로봇 컨트롤러 연결 끊김 (robot_disconnection)')

    def _on_zero(self, _request, response):
        if self._pose is None:
            response.success = False
            response.message = '아직 TCP 자세를 읽지 못했습니다.'
            return response
        self._ref_pose = list(self._pose)
        response.success = True
        response.message = '현재 자세를 변위 기준으로 설정'
        self._log('INFO', '변위 기준을 현재 자세로 재설정')
        return response

    # ------------------------------------------------------------ 동작 코드 -> 노드
    def _on_progress(self, msg):
        try:
            progress = itf.decode_progress(msg)
        except (ValueError, TypeError) as e:
            self._log('WARN', f'진행률 메시지 해석 실패: {e}')
            return
        old = self._progress
        was_active = old.active
        self._progress = progress
        self._progress_at = time.monotonic()
        if progress.run_id:
            if int(progress.run_id) != self._run_id:
                self._end_reason = ''               # 새 검사가 시작됐다
            self._run_id = int(progress.run_id)
        if progress.end_reason:
            self._end_reason = progress.end_reason
        if progress.active and not was_active:
            self._log('INFO', '동작 코드 시작 - 진행률 수신')
        elif progress.aborted:
            if not old.aborted:         # 같은 메시지가 다시 와도 한 번만 남긴다
                self._log('WARN', f'동작 코드 중단 {progress.note}'.rstrip())
        elif was_active and not progress.active:
            self._log('INFO', '동작 코드 완료 (100 %)')
        elif progress.note and progress.note != old.note:
            self._log('WARN', f'동작 코드: {progress.note}')
        if progress.run_state != old.run_state:
            if progress.run_state == itf.State.IDLE:
                self._log('INFO', "동작 코드 연결 - '검사 시작' 을 기다리는 중")
            elif progress.run_state == itf.State.PAUSE_REQUEST:
                why = ('HMI 통신 단절' if progress.pause_reason == itf.PauseReason.COMM_LOST
                       else '사용자 요청')
                self._log('WARN', f'일시정지 요청 ({why}) - 안전한 지점에서 멈춥니다')
            elif progress.run_state == itf.State.PAUSED:
                self._log('WARN', '동작 코드 일시정지')
            elif old.run_state == itf.State.PAUSED:
                self._log('INFO', '동작 코드 이어하기')
            elif progress.run_state == itf.State.MOVING:
                self._log('INFO', f'포인트 이동 시작 - {progress.step}')
            elif old.run_state == itf.State.MOVING and progress.run_state in CONTROL_STATES:
                self._log('INFO', '포인트 이동 완료')

    def _control_state(self) -> str:
        """HMI 버튼을 받는 동작 코드가 살아 있으면 그 상태, 아니면 ''."""
        if self._progress.run_state not in CONTROL_STATES:
            return ''
        if time.monotonic() - self._progress_at < PROGRESS_STALE_SEC:
            return self._progress.run_state
        old = self._progress
        if old.run_state == itf.State.DONE:
            # 검사를 끝내고 프로그램을 닫았다. 완료 표시(100 %, 제품 판정)는 남겨 둔다.
            self._progress = itf.Progress(percent=100, point=old.point, judgement=old.judgement,
                                          product_result=old.product_result)
            self._log('INFO', '동작 코드 종료 - 모니터링으로 돌아갑니다.')
        else:
            # 프로그램이 죽었다. 마지막 진행 상황(단계 이름, 퍼센트)도 더는 사실이 아니므로 지운다.
            if old.active:
                self._end_reason = itf.EndReason.LOST       # 검사 도중이었다 -> 작업 기록에 남는다
            self._progress = itf.Progress()
            self._log('WARN', '동작 코드 응답 없음 - 모니터링으로 돌아갑니다.')
        return ''

    # ------------------------------------------------------------ HMI -> 노드
    def _on_command(self, msg):
        try:
            cmd = itf.decode_command(msg)
        except (ValueError, TypeError) as e:
            self._log('ERROR', f'명령 해석 실패: {e}')
            return
        if cmd.name == itf.CommandName.SYNC:
            # HMI 가 방금 연결됐다. 노드 시작 때 남긴 레시피 경고는 그때 HMI 가 없어 못 받았을 수
            # 있으므로 다시 알려 준다.
            self._announce_recipes()
            return
        if cmd.name == itf.CommandName.ESTOP:
            self._stop_robot()
            return
        if cmd.name == itf.CommandName.SELECT_RECIPE:
            self._select_recipe(str(cmd.args.get('recipe_id', '')))
            return
        if cmd.name == itf.CommandName.MOVE_HOME:
            if self._control_state() and self._progress.handles_home:
                # 동작 코드가 Home Return 시퀀스(작업영역 확인, Safe Escape ...)로 처리한다.
                self._log('INFO', 'MOVE_HOME - 동작 코드가 처리합니다.')
                return
            self._move_home()
            return
        if cmd.name == itf.CommandName.SET_SPEED:
            self._set_speed(cmd.args.get('percent'))
            return
        if cmd.name in CONTROL_COMMANDS and self._control_state():
            self._log('INFO', f'{cmd.name} - 동작 코드가 처리합니다.')
            return
        self._log('WARN', f'읽기 전용 모니터 - {cmd.name} 명령은 무시합니다.')

    def _stop_robot(self):
        if not self.get_parameter('allow_stop').value:
            self._log('WARN', 'STOP 수신 - allow_stop=false 라 move_stop 을 보내지 않음')
            return
        if not self._stop_client.service_is_ready():
            self._log('ERROR', 'STOP 수신 - move_stop 서비스 없음! 물리 비상정지를 사용하세요.')
            return
        future = self._stop_client.call_async(MoveStop.Request(stop_mode=DR_QSTOP))
        future.add_done_callback(self._on_stop_done)
        self._log('ERROR', 'STOP 수신 - move_stop(Quick stop) 전송')

    def _on_stop_done(self, future):
        ok = (not future.cancelled() and future.exception() is None
              and future.result() is not None and future.result().success)
        if ok:
            self._log('WARN', 'move_stop 완료. 힘 제어·DRL 프로그램은 이 명령으로 해제되지 않습니다.')
        else:
            self._log('ERROR', 'move_stop 실패! 물리 비상정지를 사용하세요.')

    # ------------------------------------------------------------ Recipe 목록
    def _scan_recipes(self):
        folder = self.get_parameter('recipe_dir').value
        current = recipe_catalog.signature(folder)
        if current == self._recipe_signature:
            return                      # 파일이 바뀌지 않았다
        self._recipe_signature = current
        self._recipes, self._recipe_problems = recipe_catalog.scan(folder)
        self._announce_recipes()
        if self._recipe is not None:    # 고른 Recipe 의 파일이 바뀌었거나 없어졌을 수 있다
            self._select_recipe(self._recipe.recipe_id, announce=False)

    def _announce_recipes(self):
        if not self.get_parameter('recipe_dir').value:
            return
        for problem in self._recipe_problems:
            self._log('WARN', f'레시피 {problem}')
        names = ', '.join(sorted(self._recipes)) or '없음'
        self._log('INFO', f'레시피 {len(self._recipes)}개 읽음: {names}')

    def _select_recipe(self, recipe_id: str, announce: bool = True):
        info = self._recipes.get(recipe_id)
        if info is None:
            self._recipe = None
            self._log('WARN', f'Recipe 선택 실패 - 목록에 없음: {recipe_id!r}')
            return
        self._recipe = info
        self._load_recipe_db(info, announce)
        if not announce:
            return
        ids = ', '.join(p.point_id for p in info.points)
        self._log('INFO', f'Recipe 선택: {info.recipe_id} {info.recipe_version} '
                          f'- 포인트 {len(info.points)}개 ({ids})')
        if info.untaught_points:
            self._log('WARN', '티칭 안 된 포인트(좌표가 전부 0): '
                              + ', '.join(info.untaught_points) + ' - 이동에 쓰면 안 됩니다')

    def _load_recipe_db(self, info, announce: bool):
        """고른 Recipe 의 케이블·판정 기준을 DB 에서 읽는다. 못 읽으면 경고만 남긴다."""
        self._recipe_db_info = None
        path = self.get_parameter('recipe_db').value
        if not path:
            return
        try:
            db_info = recipe_db.RecipeDb(path).load_recipe(info.recipe_id)
        except recipe_db.RecipeDbError as e:
            if announce:
                self._log('WARN', f'레시피 DB: {e}')
            return
        self._recipe_db_info = db_info
        if not announce:
            return
        json_ids = [p.point_id for p in info.points]
        only_json = [i for i in json_ids if i not in db_info.points]
        only_db = [i for i in db_info.points if i not in json_ids]
        if only_json:
            self._log('WARN', '레시피 DB 에 없는 포인트(위치만 있음): ' + ', '.join(only_json))
        if only_db:
            self._log('WARN', '레시피 JSON 에 없는 포인트(위치 없음): ' + ', '.join(only_db))
        for p in db_info.points.values():
            self._log('INFO', f'  {p.point_id}: {p.cable_id or "-"} ({p.cable_type or "-"}) '
                              f'변위≤{p.max_displacement_mm} mm, 기준 힘≥{p.required_pull_force_n} N, '
                              f'Pull 정지 {p.pull_force_limit_n} N, '
                              f'{p.repeat_count}회, 파지 {p.grip_width_mm} mm')

    def _uniform_criteria(self):
        """모든 포인트의 검사 조건이 같으면 그 조건, 아니면 None."""
        if self._recipe_db_info is None:
            return None
        found = {(p.max_displacement_mm, p.required_pull_force_n, p.pull_force_limit_n,
                  p.repeat_count, p.grip_width_mm)
                 for p in self._recipe_db_info.points.values()}
        if len(found) != 1:
            return None
        limit, required, force, repeat, grip = found.pop()
        return itf.Criteria(max_displacement_mm=limit, required_pull_force_n=required,
                            pull_force_limit_n=force, repeat_count=repeat, grip_width_mm=grip)

    # ------------------------------------------------------------ Home 이동
    def _home_joints(self):
        joints = [float(v) for v in self.get_parameter('home_joints').value]
        return joints if len(joints) == 6 else None

    def _home_blocked_reason(self) -> str:
        """Home 이동을 받아들일 수 없는 이유. 받아들일 수 있으면 ''."""
        if not self.get_parameter('allow_home_move').value:
            return 'allow_home_move=false (이 노드는 로봇을 움직이지 않도록 설정됨)'
        if self._home_joints() is None:
            return 'home_joints 는 관절각 6개여야 함'
        if not self._state_poll.fresh:
            return '로봇 드라이버 응답 없음'
        if self._robot_state != STATE_STANDBY:
            name = ROBOT_STATE_NAMES.get(self._robot_state, str(self._robot_state))
            return f'로봇이 대기 상태가 아님 ({name})'
        if not self._motion_poll.fresh or self._motion != DR_STATE_IDLE:
            return '로봇이 이미 움직이는 중'
        if self._home_active:
            return '이전 Home 이동을 확인하는 중'
        if self._control_state() in BUSY_STATES:
            return '동작 코드가 검사 중 / 이동 중 / 일시정지 중'
        # Tool/TCP 설정은 조건이 아니다. 홈 이동은 고정된 관절각으로 가는 관절 이동이라 TCP 와 무관하고,
        # 툴 무게는 도착 자세가 아니라 힘 계산(힘 값, 충돌 감지)에만 영향을 준다. 설정 이상은
        # '현재 알람' 과 팝업으로 계속 알리고, 그 상태로 이동하면 _move_home 이 로그에 남긴다.
        return ''

    def _move_home(self):
        reason = self._home_blocked_reason()
        if reason:
            self._log('WARN', f'Home 이동 거부 - {reason}')
            return
        if not self._movej_client.service_is_ready():
            self._log('ERROR', 'Home 이동 실패 - move_joint 서비스 없음')
            return
        joints = self._home_joints()
        request = MoveJoint.Request(
            pos=joints, vel=float(self.get_parameter('home_vel').value),
            acc=float(self.get_parameter('home_acc').value), sync_type=SYNC_TYPE_ASYNC)
        self._home_active = True
        self._home_seen_motion = False
        self._home_started = time.monotonic()
        self._movej_client.call_async(request).add_done_callback(self._on_home_sent)
        self._log('INFO', f'Home 이동 시작 -> {[round(v, 1) for v in joints]} deg')
        if self._setup_alarm or not (self._tool_name and self._tcp_name):
            self._log('WARN', 'Tool/TCP 미설정 상태로 Home 이동 - 힘 값과 충돌 감지 기준이 '
                              f'어긋나 있습니다 ({self._setup_alarm or "미설정"})')

    def _on_home_sent(self, future):
        ok = (not future.cancelled() and future.exception() is None
              and future.result() is not None and future.result().success)
        if not ok:
            self._home_active = False
            self._log('ERROR', 'Home 이동 명령을 드라이버가 거부함')

    def _track_home(self):
        """Home 이동이 끝났는지 본다. 끝났으면 실제로 도착했는지 확인을 요청한다."""
        if not self._home_active or not self._motion_poll.fresh:
            return
        if self._motion != DR_STATE_IDLE:
            self._home_seen_motion = True
            return
        waited = time.monotonic() - self._home_started
        if not self._home_seen_motion and waited < HOME_START_TIMEOUT_SEC:
            return                      # 아직 모션이 시작되지 않았을 수 있다
        self._home_active = False
        if self._posj_client.service_is_ready():
            self._posj_client.call_async(
                GetCurrentPosj.Request()).add_done_callback(self._on_home_arrival)
        else:
            self._log('WARN', 'Home 이동 종료 - 도착 여부를 확인하지 못함 (get_current_posj 없음)')

    def _on_home_arrival(self, future):
        ok = (not future.cancelled() and future.exception() is None
              and future.result() is not None and future.result().success)
        joints = self._home_joints()
        if not ok or joints is None:
            self._log('WARN', 'Home 이동 종료 - 도착 여부를 확인하지 못함')
            return
        error = max(abs(a - b) for a, b in zip(future.result().pos, joints))
        if error <= HOME_TOLERANCE_DEG:
            self._log('INFO', 'Home 도착')
        else:
            self._log('WARN', f'Home 에 도착하지 못하고 멈춤 (최대 오차 {error:.1f} deg) '
                              '- STOP 또는 보호정지로 중단됐을 수 있음')

    # ------------------------------------------------------------ 속도 설정
    def _set_speed(self, percent):
        try:
            percent = max(1, min(100, int(percent)))
        except (TypeError, ValueError):
            self._log('WARN', f'속도 설정 거부 - 잘못된 값: {percent!r}')
            return
        if self._speed_pending is not None:
            self._speed_wanted = percent        # 응답이 오면 마지막 요청만 보낸다
            return
        if not self._speed_client.service_is_ready():
            self._log('ERROR', '속도 설정 실패 - change_operation_speed 서비스 없음 (드라이버 확인)')
            return
        self._speed_pending = self._speed_client.call_async(
            ChangeOperationSpeed.Request(speed=percent))
        self._speed_pending.add_done_callback(
            lambda future, value=percent: self._on_speed_done(future, value))

    def _on_speed_done(self, future, percent):
        self._speed_pending = None
        ok = (not future.cancelled() and future.exception() is None
              and future.result() is not None and future.result().success)
        if ok:
            self._speed_percent = percent
            self._log('INFO', f'속도 설정 {percent} ')
        else:
            self._log('ERROR', f'속도 설정 {percent} % 실패 - 로봇 속도는 바뀌지 않았습니다.')
        wanted, self._speed_wanted = self._speed_wanted, None
        if wanted is not None and wanted != percent:
            self._set_speed(wanted)

    # ------------------------------------------------------------ Tool/TCP 유지
    def _check_tool_setup(self):
        names_known = (self._state_poll.fresh and self._tool_poll.fresh_within(NAME_FRESH_SEC)
                       and self._tcp_poll.fresh_within(NAME_FRESH_SEC))
        if not names_known:
            return                      # 이름을 모르는 동안은 판단하지 않는다
        may_set = (self._robot_state == STATE_STANDBY
                   and self._motion_poll.fresh and self._motion == DR_STATE_IDLE)
        problems = [
            self._tool_setter.check(self._tool_name, may_set),
            self._tcp_setter.check(self._tcp_name, may_set),
        ]
        alarm = ' / '.join(text for text in problems if text)
        if alarm != self._setup_alarm:
            self._setup_alarm = alarm
            if alarm:
                self._log('WARN', alarm)
            else:
                self._log('INFO', 'Tool/TCP 설정 정상')

    # ------------------------------------------------------------ status
    def _publish_status(self):
        now = time.monotonic()
        self._track_home()
        connected = (self._state_poll.fresh
                     and now - self._disconnected_at > DISCONNECT_HOLD_SEC)
        # 시작 직후에는 첫 응답을 기다리는 중일 뿐이므로 '응답 없음' 으로 기록하지 않는다.
        starting = self._was_connected is None and now - self._started_at < STARTUP_GRACE_SEC
        if connected != self._was_connected and not (starting and not connected):
            self._was_connected = connected
            self._speed_percent = 0     # 드라이버 재시작으로 초기화됐을 수 있다 -> 모름
            if connected:
                self._tool_setter.reset()
                self._tcp_setter.reset()
                self._log('INFO', '로봇 드라이버 응답 확인')
            else:
                self._log('ERROR', '로봇 드라이버 응답 없음 (get_robot_state)')

        gripper = now - self._gripper_at < FRESH_SEC
        if gripper != self._gripper_was_connected:
            self._gripper_was_connected = gripper
            if gripper:
                self._log('INFO', 'RG2 그리퍼 드라이버 수신 시작')
            else:
                self._log('ERROR', 'RG2 그리퍼 드라이버 수신 끊김')

        # 먼저 판단한다: 동작 코드가 죽은 것을 여기서 알아채면 끝난 이유(LOST)가 같은 status 에 실린다.
        control_state = self._control_state()
        st = itf.SystemStatus(robot_connected=connected, gripper_connected=gripper)
        st.speed_percent = self._speed_percent
        st.available_recipes = sorted(self._recipes)
        if self._recipe is not None:
            st.recipe_id = self._recipe.recipe_id
            st.recipe_version = self._recipe.recipe_version
            st.total_points = len(self._recipe.points)
            if self._recipe_db_info is not None:
                st.product_id = self._recipe_db_info.product_id
                st.criteria = self._uniform_criteria() or itf.Criteria()
        st.progress_percent = max(0, min(100, int(self._progress.percent)))
        st.run_id = self._run_id
        st.end_reason = self._end_reason
        st.pause_reason = self._progress.pause_reason
        st.judgement = self._progress.judgement
        st.product_result = self._progress.product_result
        if self._progress.active and self._progress.criteria != itf.Criteria():
            st.criteria = self._progress.criteria       # 동작 코드가 알려 준 현재 Point 의 기준
        if gripper:
            st.gripper_width_mm = round(self._gripper_width, 1)
        tool_name = self._tool_name if connected else ''
        tcp_name = self._tcp_name if connected else ''
        expected_tool = self._tool_setter.expected
        weight_known = self._tool_weight > 0 and bool(tool_name) and tool_name == expected_tool
        st.tool = itf.ToolInfo(
            configured=bool(tool_name and tcp_name) and not self._setup_alarm,
            name=tool_name, tcp=tcp_name,
            weight_kg=self._tool_weight if weight_known else 0.0)

        estop = connected and self._robot_state == STATE_EMERGENCY_STOP
        moving = connected and self._motion_poll.fresh and self._motion != DR_STATE_IDLE
        st.estop = estop
        if estop:
            st.state = itf.State.ESTOP
        elif control_state and connected:
            # 동작 코드가 HMI 버튼을 받는다 -> 그 상태를 내보내 버튼이 열리게 한다. 단, 시작 대기 중에
            # 로봇이 움직이고 있으면(Home 이동 등) 끝날 때까지 '검사 시작' 을 잠가 모션이 겹치지 않게 한다.
            waiting = control_state in (itf.State.IDLE, itf.State.DONE)
            busy = moving or self._home_active
            st.state = itf.State.MONITOR_MOVING if waiting and busy else control_state
        elif moving:
            st.state = itf.State.MONITOR_MOVING
        else:
            st.state = itf.State.MONITOR

        if estop:
            st.alarm = '비상정지 (EMERGENCY_STOP)'
        elif connected and self._robot_state in STATE_ALARMS:
            st.alarm = STATE_ALARMS[self._robot_state]
        elif now - self._alarm_at < ALARM_HOLD_SEC:
            st.alarm = self._alarm
        elif connected:
            st.alarm = self._setup_alarm

        if connected:
            reported = ' · '.join(t for t in (self._progress.sequence, self._progress.point,
                                              self._progress.step) if t)
            if control_state == itf.State.MOVING and self._progress.step:
                st.current_step = self._progress.step       # 예: 'VT_P02 (으)로 이동'
            elif self._progress.active and reported and not self._home_active:
                st.current_step = reported          # 동작 코드가 알려 준 Point · 단계
            elif moving:
                st.current_step = 'Home 이동 중' if self._home_active else '로봇 이동 중'
            elif self._robot_state in (STATE_STANDBY, STATE_MOVING):
                # 모션이 없는데 MOVING 인 것은 move_stop 직후의 순간적인 값이다.
                st.current_step = '로봇 대기 (STANDBY)'
            else:
                name = ROBOT_STATE_NAMES.get(self._robot_state, str(self._robot_state))
                st.current_step = f'로봇 {name}'
        # 이동 여부는 check_motion 만 보고 판단한다 (위 '이동 중 판단' 참고).
        if connected:
            st.robot_motion = itf.RobotMotion.of(self._robot_state, moving)
            st.servo = itf.Servo.of(self._robot_state)
        if self._force_poll.fresh:
            st.force_n = round(math.sqrt(sum(v * v for v in self._force[:3])), 2)
        if self._pose_poll.fresh and self._pose is not None:
            x, y, z = self._pose[:3]
            st.current_point = f'X{x:.0f} Y{y:.0f} Z{z:.0f}'
            st.task = [float(v) for v in self._pose[:6]]
        if self._joint is not None:
            st.joint = [round(v, 2) for v in self._joint]
            st.displacement_mm = round(math.dist(self._pose[:3], self._ref_pose[:3]), 2)
        self._status_pub.publish(itf.encode_status(st))

    def _log(self, level: str, text: str, popup: bool = False):
        """시스템 로그를 남긴다. popup=True 면 HMI 가 팝업으로도 띄운다(작업자가 놓치면 안 되는 것만)."""
        stamp = datetime.now().isoformat(timespec='seconds')
        self._log_pub.publish(itf.encode_log(itf.LogEntry(stamp, level, text, popup)))
        # rclpy 로거는 같은 호출 위치에서 severity 가 바뀌면 예외를 던지므로 줄을 나눈다.
        if level == 'ERROR':
            self.get_logger().error(text)
        elif level == 'WARN':
            self.get_logger().warn(text)
        else:
            self.get_logger().info(text)


def main(args=None):
    """로봇 모니터 노드를 실행한다."""
    rclpy.init(args=args)
    node = RobotMonitorNode()
    try:
        rclpy.spin(node)
    except (KeyboardInterrupt, ExternalShutdownException):
        pass
    finally:
        rclpy.try_shutdown()


if __name__ == '__main__':
    main()
