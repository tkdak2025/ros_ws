"""
HMI <-> 검사 노드 사이의 ROS 2 인터페이스 정의.

통합 시 수정할 곳은 이 파일 하나다. UI(main_window)와 mock 노드는 아래
dataclass 와 encode_*/decode_* 함수만 사용하고, 토픽 이름·메시지 타입·
직렬화 방식은 전혀 알지 못한다.

현재는 팀 공용 메시지(cable_msgs)가 확정되지 않아 std_msgs/String 에 JSON 을
실어 보낸다. cable_msgs 가 정해지면 *_MSG_TYPE 과 encode_*/decode_* 본문만
바꾸면 된다. JSON 디코딩은 모르는 키를 무시하고 빠진 키는 기본값으로 채우므로
필드가 늘거나 줄어도 HMI 가 죽지 않는다.
"""

from dataclasses import asdict, dataclass, field, fields, is_dataclass
import json
import math
from typing import Any, Dict, List, Optional

from cable_interfaces.msg import InspectionResult as InspectionResultMsg
from cable_interfaces.srv import StartInspection
from rclpy.qos import DurabilityPolicy, HistoryPolicy, QoSProfile, ReliabilityPolicy
from std_msgs.msg import Empty, String

# --------------------------------------------------------------------------
# 토픽 (상대 이름 - launch 에서 namespace 를 주면 그대로 따라간다)
# --------------------------------------------------------------------------
TOPIC_STATUS = 'cable_inspection/status'          # 검사 노드 -> HMI, 10 Hz 권장
# 검사 노드 -> HMI, Point 1개 판정마다. #06 판정 노드(cable_pkg inspection_judgment)가 보낸다.
# 2026-09-23 이전에는 'cable_inspection/result' 에 String+JSON 이었다.
TOPIC_RESULT = 'cable_inspection/judgment_result'
TOPIC_LOG = 'cable_inspection/log'                # 검사 노드 -> HMI, 시스템 로그
TOPIC_COMMAND = 'cable_inspection/command'        # HMI -> 검사 노드
TOPIC_HEARTBEAT = 'cable_inspection/hmi_heartbeat'  # HMI -> 검사 노드, 2 Hz
# 동작 코드 -> 상태를 보내는 노드. 동작 코드는 status 를 직접 보내지 않고(발행자가 둘이 되면
# 값이 섞인다) 진행 상황만 여기로 보낸다. cable_hmi.hmi_progress.ProgressReporter 참고.
TOPIC_PROGRESS = 'cable_inspection/progress'
# HMI 는 쓰지 않는 원본 값 토픽 (rqt_plot, ros2 topic echo, 기록용)
TOPIC_TOOL_FORCE = 'cable_inspection/tool_force'  # Float64MultiArray [Fx Fy Fz Tx Ty Tz]
TOPIC_TCP_POSE = 'cable_inspection/tcp_pose'      # Float64MultiArray [x y z rx ry rz]

STATUS_MSG_TYPE = String
RESULT_MSG_TYPE = InspectionResultMsg      # cable_interfaces/msg/InspectionResult
LOG_MSG_TYPE = String
COMMAND_MSG_TYPE = String
HEARTBEAT_MSG_TYPE = Empty
PROGRESS_MSG_TYPE = String

QOS_DEPTH = 50

# status 가 이 시간(s) 이상 안 오면 HMI 는 'ROS2 통신 끊김' 으로 표시한다.
STATUS_TIMEOUT_SEC = 1.5
HEARTBEAT_PERIOD_SEC = 0.5

# --------------------------------------------------------------------------
# 상태 분리 계약 (2026-09-23, 검사 PC 문서 'HMI 로봇상태 / 작업상태 분리 인터페이스')
#
# 검사 시퀀스(Main)는 위의 status 를 더 이상 보내지 않고 둘로 나눠 보낸다.
#   robot_status : 로봇 상태 전용 노드. 실시간 장비 값. 늘 10 Hz.
#   work_status  : Main. 실행 상태·진행·검사 조건·Pull 측정값.
#                  작업 중 10 Hz, 대기 중에는 바뀔 때와 SYNC 를 받았을 때만 보낸다.
# HMI 는 둘을 합쳐 SystemStatus 하나로 그린다 (merge_split_status). mock 과 robot_monitor_node 는
# 예전 status 하나를 그대로 보내므로 둘 다 받는다.
# --------------------------------------------------------------------------
TOPIC_ROBOT_STATUS = 'cable_inspection/robot_status'
TOPIC_WORK_STATUS = 'cable_inspection/work_status'
ROBOT_STATUS_MSG_TYPE = String
WORK_STATUS_MSG_TYPE = String
ROBOT_STATUS_QOS_DEPTH = 10
# work_status 는 TRANSIENT_LOCAL 로 받는다 - HMI 를 늦게 켜도 Main 의 마지막 상태를 바로 받는다.
WORK_STATUS_QOS = QoSProfile(depth=1, history=HistoryPolicy.KEEP_LAST,
                             reliability=ReliabilityPolicy.RELIABLE,
                             durability=DurabilityPolicy.TRANSIENT_LOCAL)
# robot_status 가 이보다 오래 안 오면 장비 값을 모두 버린다(문서: 데이터 만료 2 s).
ROBOT_STATUS_STALE_SEC = 2.0
# 대기 중 Main 은 조용하므로 HMI 가 SYNC 를 보내 살아 있는지 확인한다(검사 PC 콘솔과 같은 1 s).
WORK_SYNC_PERIOD_SEC = 1.0
# SYNC 응답을 두 번 넘게 놓치면 Main 과 끊긴 것으로 본다.
WORK_STATUS_STALE_SEC = 3.0

# --------------------------------------------------------------------------
# 검사 시작 서비스 (2026-09-23, PR #9 cable_inspection)
#
# hmi 모드의 Main 은 JSON START 를 거절하고, 이 서비스로 검사 레시피 전체를 받는다.
# 레시피 원본은 HMI 쪽이 갖고 있다 (inspection_recipe.py 가 JSON 을 읽어 메시지로 만든다).
# accepted 는 '접수' 일 뿐이다. 실제 진행과 결과는 work_status / log / judgment_result 로 본다.
# --------------------------------------------------------------------------
SERVICE_START = 'cable_inspection/start'
START_SRV_TYPE = StartInspection
# 응답이 이보다 늦으면 경고만 한다. 자동으로 다시 보내지 않는다(문서 3장).
START_TIMEOUT_SEC = 5.0
# inspection_recipe_dir 파라미터가 비었을 때 읽는 곳: 같은 저장소의 검사 레시피 폴더.
DEFAULT_INSPECTION_RECIPE_DIR = '~/ros_ws/src/cable_inspection/cable_inspection/recipe/inspection'


# 파지 실패 기준(확정 사양, 2026-09-22 PR #8): Pull 중 실측 폭이 이보다 작으면 FAIL_GRIP_WIDTH.
# 판정 노드가 고정값으로 쓰고 레시피·상태에는 실려 오지 않아 HMI 도 같은 값을 둔다(표시용).
GRIP_FAILURE_WIDTH_MM = 16.0


class StartCode:
    """StartInspection 응답의 code (cable_inspection/sequence/main_node.py)."""

    ACCEPTED = 'ACCEPTED'
    ALREADY_ACCEPTED = 'ALREADY_ACCEPTED'
    LABELS = {
        ACCEPTED: '접수',
        ALREADY_ACCEPTED: '이미 접수한 요청',
        'INVALID_REQUEST_ID': '요청 ID 오류',
        'INVALID_RECIPE': '레시피 오류',
        'REQUEST_ID_CONFLICT': '같은 요청 ID 에 다른 레시피',
        'CONTROL_MODE_MISMATCH': '검사 PC 가 HMI 모드가 아님',
        'HEARTBEAT_MISSING': 'HMI Heartbeat 미수신',
        'BUSY': '진행 중인 작업 있음',
        'NOT_READY': '시작 가능 상태(SYSTEM_READY) 아님',
        'NO_ENABLED_POINTS': '활성 검사포인트 없음',
    }

    @classmethod
    def label(cls, code: str) -> str:
        return cls.LABELS.get(code, code)


class State:
    """검사 노드의 상위 상태. HMI 버튼 활성화는 전적으로 이 값에 따른다."""

    # 설계 문서(Sequence #00)의 SYSTEM_READY = 여기의 IDLE 과 DONE 이다. 둘 다 START 를 받을 수
    # 있는 정지 대기 상태이고, DONE 은 '직전 검사의 결과가 화면에 남아 있다' 는 것만 다르다.
    # STOPPED 는 START 를 받을 수 없다 - 문서의 SystemState.STOPPED 와 같다.
    IDLE = 'IDLE'          # 대기 - 검사 시작/이동 명령 가능
    RUNNING = 'RUNNING'    # 검사 시퀀스 수행 중
    PAUSE_REQUEST = 'PAUSE_REQUEST'   # 일시정지를 받았고 안전한 정지 지점까지 가는 중 (Common Sequence #1)
    PAUSED = 'PAUSED'      # 일시정지 - 이어하기 가능
    MOVING = 'MOVING'      # Home / Point 이동 중
    DONE = 'DONE'          # 검사 완료 - 검사 시작/이동 명령 가능
    # STOP 으로 Job 이 끝난 상태. 자동 Home Return 이 없으므로 Home 이동을 해야 다시 시작할 수 있다.
    STOPPED = 'STOPPED'    # 정지됨 - Home 이동만 가능
    ESTOP = 'ESTOP'        # 비상정지 작동 중
    ERROR = 'ERROR'        # 장비·제어 오류
    # 읽기 전용 모니터(robot_monitor_node)용. 시작/이동 버튼이 잠긴다.
    MONITOR = 'MONITOR'                  # 로봇 값만 표시 중, 로봇 정지
    MONITOR_MOVING = 'MONITOR_MOVING'    # 로봇 값만 표시 중, 로봇이 움직이는 중

    LABELS = {
        IDLE: '대기',
        RUNNING: '검사 중',
        PAUSE_REQUEST: '일시정지 요청',
        PAUSED: '일시정지',
        MOVING: '이동 중',
        DONE: '검사 완료',
        STOPPED: '정지됨',
        ESTOP: '비상정지',
        ERROR: '오류',
        MONITOR: '모니터링',
        MONITOR_MOVING: '모니터링 · 이동 중',
    }


class ResultCode:
    """
    Point 별 검사 결과 코드 (Concept/Sequence #06 Inspection Judgment, 2026-09-22).

    결과는 PASS / FAIL 두 개다. 상세 원인은 결과와 분리해 PointResult.reason_code 에
    싣는다(ReasonCode). Detach 와 Displacement 를 다른 결과로 나누지 않는다.
    FAIL_DISPLACEMENT / FAIL_DETACHED 는 #06 이전의 코드다 - 지난 DB 기록을 읽기 위해 남겨 두며,
    새 결과에는 쓰지 않는다.
    """

    PASS = 'PASS'
    FAIL = 'FAIL'
    # 제품 결과가 아니다. 판정 노드가 측정값·기준값을 신뢰할 수 없을 때 보낸다.
    # 화면에서는 INCOMPLETE 와 같은 부류로 묶어 회색으로 둔다.
    SYSTEM_ERROR = 'SYSTEM_ERROR'
    # 제품 결과가 아니다. 유효한 판정을 만들지 못한 Point (#06 6.4: TIMEOUT 등).
    # 이 Point 가 있으면 #07 Work Finish 가 Job 종료를 승인하지 않는다.
    INCOMPLETE = 'INCOMPLETE'
    FAIL_DISPLACEMENT = 'FAIL_DISPLACEMENT'   # 옛 코드 (FAIL 로 읽힌다)
    FAIL_DETACHED = 'FAIL_DETACHED'           # 옛 코드 (FAIL 로 읽힌다)

    PRODUCT_CODES = (PASS, FAIL)
    FAIL_CODES = (FAIL, FAIL_DISPLACEMENT, FAIL_DETACHED)

    @staticmethod
    def category(code: str) -> str:
        """결과 코드를 PASS / FAIL / INCOMPLETE 세 부류로 묶는다."""
        if code == ResultCode.PASS:
            return 'PASS'
        if code in ('', ResultCode.INCOMPLETE, ResultCode.SYSTEM_ERROR):
            return 'INCOMPLETE'
        return 'FAIL'


class ReasonCode:
    """
    판정의 상세 원인 (Sequence #06). PointResult.reason_code 에 싣는다.

    문서는 "Reason 코드는 HMI Interface 정의에서 최종 확정한다" 고 했다 - 여기가 그 정의다.
    앞부분(PASS_ / FAIL_)이 결과 부류와 같아서 result_of() 로 결과를 얻을 수 있다.
    유효한 판정을 만들지 못한 Point(INCOMPLETE)에는 원인 코드를 붙이지 않는다 - 제품 결과가
    아니기 때문이다. 사유는 reason 문장과 termination_reason 으로 남긴다.
    """

    PASS_FORCE_DISPLACEMENT_OK = 'PASS_FORCE_DISPLACEMENT_OK'   # 기준 힘 도달 + 변위 한계 이내
    FAIL_DISPLACEMENT_LIMIT = 'FAIL_DISPLACEMENT_LIMIT'         # 변위 한계(5 mm) 초과
    FAIL_MAX_DISTANCE = 'FAIL_MAX_DISTANCE'                     # 미끄러짐 없이 최대 거리(25 mm)까지 이동
    FAIL_GRIP_WIDTH = 'FAIL_GRIP_WIDTH'   # Pull 중 실측 폭이 기준(16 mm) 미만 - 파지 실패
    FAIL_GRIP_SLIP = 'FAIL_GRIP_SLIP'     # 옛 코드. FAIL_GRIP_WIDTH 로 바뀌었다
    # 제품 결과가 아니다. 접두사가 PASS_/FAIL_ 이 아니라서 result_of() 가 INCOMPLETE 를 준다.
    SYSTEM_ERROR = 'SYSTEM_ERROR'
    INCOMPLETE_NOT_IMPLEMENTED = 'INCOMPLETE_NOT_IMPLEMENTED'         # 검사 동작 미구현 (개발 중 전용)

    # 통합문서(2026-09-22) 이전 코드. 새 결과에는 쓰지 않고, 지난 기록을 읽을 때만 쓴다.
    FAIL_FORCE_REQUIREMENT = 'FAIL_FORCE_REQUIREMENT'
    INCOMPLETE_INVALID_DATA = 'INCOMPLETE_INVALID_DATA'
    INCOMPLETE_ABNORMAL_TERMINATION = 'INCOMPLETE_ABNORMAL_TERMINATION'

    ALL = (PASS_FORCE_DISPLACEMENT_OK, FAIL_DISPLACEMENT_LIMIT, FAIL_MAX_DISTANCE,
           FAIL_GRIP_WIDTH, SYSTEM_ERROR, INCOMPLETE_NOT_IMPLEMENTED)

    LABELS = {
        PASS_FORCE_DISPLACEMENT_OK: '기준 힘 도달, 변위 허용 범위 이내',
        FAIL_DISPLACEMENT_LIMIT: '변위 허용 한계 초과',
        FAIL_MAX_DISTANCE: '미끄러짐 없이 Pull 최대 거리까지 이동',
        FAIL_GRIP_WIDTH: 'Pull 중 실측 폭이 기준 미만 - 파지 실패',
        SYSTEM_ERROR: '측정값 또는 기준값을 신뢰할 수 없음',
        FAIL_GRIP_SLIP: '파지 미끄러짐으로 불량 (옛 코드)',
        INCOMPLETE_NOT_IMPLEMENTED: '검사 동작 미구현',
        FAIL_FORCE_REQUIREMENT: '기준 힘에 도달하지 못함 (옛 코드)',
        INCOMPLETE_INVALID_DATA: '검사 데이터 누락 또는 비정상 (옛 코드)',
        INCOMPLETE_ABNORMAL_TERMINATION: '검사 비정상 종료 (옛 코드)',
    }

    @staticmethod
    def result_of(reason_code: str) -> str:
        """원인 코드에서 결과(PASS / FAIL)를 얻는다. 코드가 없으면 INCOMPLETE."""
        if reason_code == 'MISSING_GRIP_SLIP':  # 기존 저장 기록 호환
            return ResultCode.FAIL
        for prefix, result in (('PASS_', ResultCode.PASS), ('FAIL_', ResultCode.FAIL)):
            if reason_code.startswith(prefix):
                return result
        return ResultCode.INCOMPLETE


class TerminationReason:
    """
    Pull Motion 이 끝난 이유 (Sequence #05 10장). 판정(#06)의 입력이다.

    실물 시험 코드는 같은 뜻을 `PULL_FORCE_LIMIT` / `PULL_MAX_DISTANCE` 처럼 단계 이름을 붙여
    기록한다(진입 단계는 `ENTRY_FORCE_LIMIT`). 이름을 한쪽으로 강제하지 않고 normalize() 로
    접두어를 벗겨 읽는다 - 보내는 쪽이 어느 형식을 쓰든 화면에는 같은 뜻으로 나온다.
    """

    NONE = ''
    FORCE_LIMIT = 'FORCE_LIMIT'      # 기준 Pull 힘에 도달해 정지 (정상 종료)
    MAX_DISTANCE = 'MAX_DISTANCE'    # Pull 최대 거리(25 mm)까지 이동
    TIMEOUT = 'TIMEOUT'              # 제한 시간 초과. 제품 결과로 바꾸지 않는다 (#06 6.4)
    MOTION_ERROR = 'MOTION_ERROR'    # 모션 오류
    INVALID_DATA = 'INVALID_DATA'    # 판정 요청 자체가 잘못됨 (판정 노드가 붙인다)

    _PREFIXES = ('PULL_', 'ENTRY_')

    LABELS = {
        FORCE_LIMIT: '기준 힘 도달', MAX_DISTANCE: '최대 거리 도달',
        TIMEOUT: '시간 초과', MOTION_ERROR: '모션 오류', INVALID_DATA: '잘못된 판정 요청',
    }

    @staticmethod
    def normalize(code: str) -> str:
        """단계 접두어를 벗긴 코드. 모르는 값은 그대로 돌려준다."""
        for prefix in TerminationReason._PREFIXES:
            if code.startswith(prefix):
                return code[len(prefix):]
        return code

    @staticmethod
    def label(code: str) -> str:
        """한글 설명. 모르는 코드면 빈 문자열."""
        return TerminationReason.LABELS.get(TerminationReason.normalize(code), '')


class RobotMotion:
    """
    로봇이 지금 무엇을 하고 있는가. 두산 제어기에서 읽은 값이다.

    **이동 여부는 check_motion 으로만 판단한다.** get_robot_state 는 API 로 건 모션 중에도
    STANDBY 를 유지하고, 멈춰 있을 때 move_stop 을 보내면 잠깐 MOVING 이 된다(2026-09-19 실기 확인).
    그래서 보내는 쪽 규칙은: check_motion 이 정지가 아니면 MOVING, 아니면 get_robot_state 의 이름.
    """

    NONE = ''
    MOVING = 'MOVING'                  # 실제로 움직이는 중 (check_motion)
    STANDBY = 'STANDBY'                # 정지, 운전 가능
    INITIALIZING = 'INITIALIZING'
    SAFE_OFF = 'SAFE_OFF'              # 서보 OFF
    TEACHING = 'TEACHING'
    SAFE_STOP = 'SAFE_STOP'            # 보호 정지
    EMERGENCY_STOP = 'EMERGENCY_STOP'
    HOMMING = 'HOMMING'
    RECOVERY = 'RECOVERY'
    SAFE_STOP2 = 'SAFE_STOP2'
    SAFE_OFF2 = 'SAFE_OFF2'
    NOT_READY = 'NOT_READY'

    # get_robot_state 응답 숫자 -> 이름
    CODES = {
        0: INITIALIZING, 1: STANDBY, 2: MOVING, 3: SAFE_OFF, 4: TEACHING, 5: SAFE_STOP,
        6: EMERGENCY_STOP, 7: HOMMING, 8: RECOVERY, 9: SAFE_STOP2, 10: SAFE_OFF2, 15: NOT_READY,
    }

    LABELS = {
        MOVING: '이동 중', STANDBY: '대기', INITIALIZING: '초기화 중', SAFE_OFF: '서보 OFF',
        TEACHING: '교시 중', SAFE_STOP: '보호 정지', EMERGENCY_STOP: '비상정지',
        HOMMING: '원점 복귀 중', RECOVERY: '복구 중', SAFE_STOP2: '보호 정지 2',
        SAFE_OFF2: '서보 OFF 2', NOT_READY: '준비 안 됨',
    }

    @staticmethod
    def of(robot_state: int, moving: bool) -> str:
        """check_motion 결과(moving)를 먼저 보고, 아니면 get_robot_state 이름을 쓴다."""
        if moving:
            return RobotMotion.MOVING
        return RobotMotion.CODES.get(robot_state, '')

    @staticmethod
    def label(code: str) -> str:
        return RobotMotion.LABELS.get(code, '')


class Servo:
    """
    서보(모터) 전원 상태.

    두산 드라이버에는 서보 상태를 묻는 서비스가 없다(servo_off 는 끄는 명령뿐이다). 그래서
    get_robot_state 값에서 끌어낸다 - 모터가 꺼져 있다고 보는 상태는 아래 OFF_STATES 다.
    값을 읽지 못했으면 NONE(빈 문자열)으로 두고 화면에는 '—' 로 나온다.
    """

    NONE = ''
    ON = 'ON'
    OFF = 'OFF'

    # 모터가 꺼져 있다고 보는 제어기 상태
    OFF_STATES = (RobotMotion.INITIALIZING, RobotMotion.SAFE_OFF, RobotMotion.SAFE_OFF2,
                  RobotMotion.NOT_READY, RobotMotion.EMERGENCY_STOP)

    LABELS = {ON: 'ON', OFF: 'OFF'}

    @staticmethod
    def of(robot_state: int) -> str:
        """get_robot_state 응답 숫자에서 서보 상태를 얻는다. 모르는 값이면 NONE."""
        name = RobotMotion.CODES.get(robot_state)
        if name is None:
            return Servo.NONE
        return Servo.OFF if name in Servo.OFF_STATES else Servo.ON


class JudgmentStatus:
    """Point 별 판정 진행 상태 (Sequence #06 10장). 판정은 로봇 이동과 비동기로 돈다."""

    NONE = ''
    PENDING = 'PENDING'        # 측정은 끝났고 판정 대기 중
    COMPLETED = 'COMPLETED'    # 판정 완료
    ERROR = 'ERROR'            # 판정을 만들 수 없음 -> Job 종료 보류 (#07)

    LABELS = {PENDING: '판정 대기', COMPLETED: '판정 완료', ERROR: '판정 오류'}


class SequenceStatus:
    """
    Point 하나의 시퀀스 처리 상태 (#06 판정 노드가 결과에 함께 싣는다).

    제품 판정(ResultCode)과 다른 축이다: 제품이 FAIL 이어도 시퀀스는 SUCCESS 일 수 있다.
    INCOMPLETE 는 #07 Work Finish 가 종료를 승인할지 판단할 때 쓴다.
    """

    NONE = ''
    IDLE = 'IDLE'
    RUNNING = 'RUNNING'
    SUCCESS = 'SUCCESS'
    FAIL = 'FAIL'
    INCOMPLETE = 'INCOMPLETE'

    LABELS = {IDLE: '대기', RUNNING: '수행 중', SUCCESS: '정상 처리',
              FAIL: '처리 실패', INCOMPLETE: '미완료'}

    @staticmethod
    def label(code: str) -> str:
        return SequenceStatus.LABELS.get(code, '')


class Step:
    """
    현재 단계(work_status.current_step)의 화면 이름. 값은 검사 PC 가 보낸 코드 그대로다.

    Main 은 '방금 끝낸 완료점' 이름을 보낸다(cable_inspection main_node.checkpoint).
    예: HARD_GRIP_DONE 이면 파지를 마치고 Pull 을 하는 중이다. 표에 없는 코드는 그대로 보인다.
    """

    LABELS = {
        'WORK_INITIALIZE': '작업 초기화',
        'INITIALIZE_DONE': '초기화 완료',
        'HOME_REACHED': 'Home 도착',
        'WORK_ACCESS_REACHED': '작업 진입 위치 도착',
        'POINT_START': 'Point 시작',
        'READY_REACHED': '준비 위치 도착',
        'ENTRY_REACHED': '진입 완료',
        'HARD_GRIP_DONE': '파지 완료',
        'POINT_READY_RETURNED': '준비 위치 복귀',
        'WORK_ACCESS_FINISH': '작업 진입 위치 복귀',
        'WORK_FINISH': '작업 종료 확인',
        'WORK_FINISH_WAIT': '판정 대기',
        'WORK_FINISH_RETRY': '종료 재확인',
    }

    @classmethod
    def label(cls, code: str) -> str:
        return cls.LABELS.get(code, code)


class ControlMode:
    """
    status.control_mode - 어떤 노드가 status 를 보내는가, 그 노드가 HMI 명령을 받는가.

    검사 시퀀스(Main)만 이 값을 채운다. 비어 있으면 모니터·mock 노드다.
    Main 은 STOP / START / PAUSE / RESUME / Home / SELECT_RECIPE / SYNC 만 받고
    MOVE_TO_POINT, SET_SPEED, ESTOP, ESTOP_RESET 은 받지 않는다.
    """

    NONE = ''              # 모니터·mock 노드 (모든 명령을 받는다)
    HMI = 'hmi'            # Main, HMI 명령을 받는다
    TERMINAL = 'terminal'  # Main, 터미널 콘솔로 운전 중 - HMI 명령은 버린다

    @staticmethod
    def is_main(mode: str) -> bool:
        """검사 시퀀스(Main)가 보낸 상태인가."""
        return mode in (ControlMode.HMI, ControlMode.TERMINAL)


class ProductResult:
    """
    제품 단위 최종 판정. 판정 미완료가 남으면 PASS 가 될 수 없다.

    Job 을 종료해도 되는가(#07 Work Finish)와는 다른 이야기다: FAIL 이 있어도
    모든 Point 판정이 정상 완료됐다면 Job 은 정상 종료된다.
    """

    NONE = ''
    PASS = 'PASS'
    FAIL = 'FAIL'
    INCOMPLETE = 'INCOMPLETE'   # FAIL 은 없지만 판정 미완료 Point 존재


class PauseReason:
    """왜 일시정지했는가 (Common Sequence #1)."""

    NONE = ''
    USER = 'USER'                # 사용자가 일시정지를 눌렀다
    COMM_LOST = 'COMM_LOST'      # HMI heartbeat 가 끊겼다. 복구돼도 사용자가 이어하기를 눌러야 재개한다


class EndReason:
    """검사(run) 1회가 어떻게 끝났는가. 작업 단위 기록(result_db 의 inspection_run)에 남는다."""

    NONE = ''
    COMPLETED = 'COMPLETED'      # 마지막 Point 까지 검사하고 정상 완료
    STOP = 'STOP'                # HMI STOP
    ERROR = 'ERROR'              # 로봇·시퀀스 오류
    COMM_ERROR = 'COMM_ERROR'    # HMI 통신이 제한 시간 안에 복구되지 않음
    INIT_FAIL = 'INIT_FAIL'      # Work Initialize 에서 시작 조건 불만족
    # Work Finish(#07) 가 종료 조건 불충족으로 Job 종료를 승인하지 않았다. 검사 결과가 나쁘다는
    # 뜻이 아니라 판정 대기·결과 누락·Point 오류가 남아 있다는 뜻이다. 로봇은 안전 위치에 머문다.
    NOT_COMPLETE = 'NOT_COMPLETE'
    ABORTED = 'ABORTED'          # 동작 코드가 스스로 중단 (Ctrl+C, 예외 ...)
    LOST = 'LOST'                # 동작 코드가 검사 도중에 소식이 끊김 (프로그램이 죽음)


class CommandName:
    """HMI 가 보내는 명령. args 는 Command.args 참고."""

    START = 'START'                  # args: recipe_id
    PAUSE = 'PAUSE'
    RESUME = 'RESUME'
    # 작업 정지. 빨간 버튼이 보낸다. 검사 시퀀스(Main)는 Job 을 끝내고 Context 를 버린다 -
    # 자동 Home 은 없고, Home 이동으로 복구한 뒤 새로 START 한다 (#00 8장).
    # 하드웨어 비상정지가 아니다. 물리 비상정지 스위치와 TP 가 최종 권한이다.
    STOP = 'STOP'
    # 옛 명령. 모니터·mock 노드는 아직 받지만 검사 시퀀스(Main)는 받지 않는다 (2026-09-23).
    ESTOP = 'ESTOP'
    ESTOP_RESET = 'ESTOP_RESET'
    MOVE_HOME = 'MOVE_HOME'
    MOVE_TO_POINT = 'MOVE_TO_POINT'  # args: point_id, reason('FAIL')
    SET_SPEED = 'SET_SPEED'          # args: percent(1~100)
    SELECT_RECIPE = 'SELECT_RECIPE'  # args: recipe_id. 목록에서 Recipe 를 고름(검사 시작 아님)
    SYNC = 'SYNC'                    # 현재 run 의 결과를 다시 보내 달라는 요청(선택 구현)


@dataclass
class ToolInfo:
    """좌측 'Tool 설정' 패널."""

    configured: bool = False
    name: str = ''
    weight_kg: float = 0.0
    tcp: str = ''
    force_zero_done: Optional[bool] = False   # None = 알 수 없음 (상태 분리 계약은 보내지 않는다)


@dataclass
class Criteria:
    """
    현재 Point 에 적용 중인 검사 조건 (우측 패널 상단). 판정 규칙은 Sequence #06 이다.

        PASS    = 기준 힘(required_pull_force_n)에 도달 AND 변위 <= max_displacement_mm
        FAIL    = 유효한 검사인데 위 조건을 못 채움 (변위 초과, 최대 거리까지 이동)
        FAIL = Grip Slip을 포함한 불량

    기준 Pull 힘(required_pull_force_n)은 합격선이면서 **Pull 정지 조건**이다 - 이 힘에 도달하면
    Pull 을 멈춘다(#05). 허용 변위 5 mm 는 판정 기준일 뿐 정지 조건이 아니며, 5 mm 를 넘어도
    기준 힘 / 최대 거리 25 mm / 시간 초과까지 계속 당긴다.
    표준값: 기준 힘 LAN 20 N / USB 12 N, 허용 변위 5 mm, 최대 거리 25 mm.
    """

    max_displacement_mm: float = 0.0   # 허용 변위 5 mm. 넘으면 FAIL. Pull 정지 조건이 아니다
    required_pull_force_n: float = 0.0  # 기준 Pull 힘. 도달하면 Pull 을 멈춘다 (LAN 20 / USB 12)
    pull_max_distance_mm: float = 0.0  # Pull 최대 거리 25 mm. 모션 보호 상한
    pull_force_limit_n: float = 0.0    # 옛 필드. 기준 힘과 정지 힘을 따로 두던 때의 값
    repeat_count: int = 0              # 옛 필드. 현재 Pull 은 1회다
    grip_width_mm: float = 0.0


@dataclass
class SystemStatus:
    """검사 노드가 주기적으로 내보내는 전체 상태. HMI 는 이것만 그린다."""

    state: str = State.IDLE
    estop: bool = False
    robot_connected: bool = False
    gripper_connected: bool = False
    alarm: str = ''
    tool: ToolInfo = field(default_factory=ToolInfo)
    criteria: Criteria = field(default_factory=Criteria)

    available_recipes: List[str] = field(default_factory=list)
    # 검사 시퀀스(Main)만 보내는 값 (2026-09-23 HMI_ROS2_연동 5장). 모니터·mock 노드는 비워 둔다.
    control_mode: str = ''          # ControlMode. 'hmi' 여야 Main 이 HMI 명령을 받는다
    control_connected: bool = False  # Main 이 HMI heartbeat 를 받고 있는가
    selected_recipe_id: str = ''     # Main 에서 현재 선택된 Recipe
    run_id: int = 0
    recipe_id: str = ''
    recipe_version: str = ''
    product_id: str = ''
    total_points: int = 0
    product_result: str = ProductResult.NONE
    pending_judgments: int = 0   # 아직 판정이 끝나지 않은 Point 수 (#06 비동기 판정)
    end_reason: str = EndReason.NONE       # 이번 run 이 끝난 이유. 다음 run 이 시작될 때까지 남는다

    pause_reason: str = PauseReason.NONE   # state 가 PAUSE_REQUEST / PAUSED 일 때
    current_point: str = ''      # 예: 'Place 2', 'HOME'
    current_step: str = ''       # 예: 'Pull Test (2/3)'
    judgement: str = ''          # 예: '검사 중', 'PASS'
    speed_percent: int = 0
    gripper_width_mm: float = 0.0
    force_n: float = 0.0
    # 현재 TCP 위치 [x, y, z, rx, ry, rz] (BASE, mm/deg). 비어 있으면 값을 못 읽은 것이다.
    task: List[float] = field(default_factory=list)
    joint: List[float] = field(default_factory=list)   # 현재 관절각 [J1..J6] (deg)
    robot_motion: str = RobotMotion.NONE   # 지금 로봇이 무엇을 하고 있는가
    servo: str = Servo.NONE                # 서보 전원 ON / OFF
    displacement_mm: float = 0.0
    progress_percent: int = 0
    # 아래는 상태 분리 계약에서 합친 값일 때만 쓴다 (merge_split_status).
    # 합친 값에서는 모르는 수치를 0.0 이 아니라 None 으로 둔다 - 화면은 '—' 로 그린다.
    raw_force_n: Optional[float] = None   # robot_status.force_norm_n. 원시 힘 크기, Pull 정지 기준이 아님
    split_contract: bool = False          # robot_status + work_status 를 합친 값인가
    work_fresh: bool = True               # 작업상태(Main)가 최근에 왔는가. 예전 status 는 늘 True


@dataclass
class PointResult:
    """Point 1개의 검사 결과 (결과 테이블 1행 + 상세 팝업)."""

    run_id: int = 0
    stamp: str = ''              # ISO 8601
    recipe_id: str = ''
    recipe_version: str = ''
    product_id: str = ''
    point_id: str = ''           # 예: 'Place 2'
    cable_id: str = ''           # 예: 'LAN-3'
    cable_type: str = ''         # 예: 'RJ45'
    result: str = ''             # ResultCode: PASS / FAIL / INCOMPLETE(제품 결과 아님)
    reason_code: str = ''        # ReasonCode: 상세 원인 (결과와 분리, #06)
    judgment_status: str = ''    # JudgmentStatus: PENDING / COMPLETED / ERROR
    sequence_status: str = ''    # SequenceStatus: 시퀀스 처리 상태 (제품 판정과 다른 축)
    # 판정 입력(#06 9장)과 그때 쓴 조건을 짝지어 싣는다:
    #   max_force_n ↔ required_pull_force_n (합격 기준) / pull_force_limit_n (정지 상한)
    #   displacement_mm ↔ displacement_limit_mm
    # 측정: 이번 Pull 의 최대 힘 (peak_pull_force).
    # **Pull 을 멈출지 판단할 때 비교한 그 값을 그대로 싣는다.** 실물 기록에는 축방향 원값
    # (peak_pull_force_n)과 시작 기준값을 뺀 변화량(peak_force_delta_n)이 함께 남는데, 둘은
    # 샘플에 따라 대소가 뒤집힌다(실측: 정상 20.31 vs 18.50, 파지불량 9.43 vs 10.12).
    # 다른 값을 실으면 "기준 15 N 인데 왜 이 판정인가" 를 화면에서 설명할 수 없다.
    max_force_n: float = 0.0
    required_pull_force_n: float = 0.0  # 조건: 기준 Pull 힘 (= Pull 정지 조건)
    pull_force_limit_n: float = 0.0    # 조건: Pull 정지 상한 (합격 기준이 아니다)
    displacement_mm: float = 0.0       # 측정: Pull 방향 변위 (pull_displacement)
    displacement_limit_mm: float = 0.0  # 조건: 허용 변위 (5 mm)
    pull_max_distance_mm: float = 0.0  # 조건: Pull 최대 거리 (25 mm)
    # TerminationReason: FORCE_LIMIT / MAX_DISTANCE / TIMEOUT / MOTION_ERROR
    termination_reason: str = ''
    # 2026-09-23 판정 노드가 보내는 그리퍼 폭. 절대 폭으로 파지 실패를 가린다.
    soft_width_mm: float = 0.0          # 측정: Soft 종료 기준 폭
    pull_width_mm: float = 0.0          # 측정: Pull 전체(정지 대기 포함) 최소 실측 폭
    width_delta_mm: float = 0.0         # pull_width_mm - soft_width_mm (부호 있음, 기록용)
    grip_failure_width_mm: float = 0.0  # 조건: 이 폭 미만이면 파지 실패 (현재 16.0)
    # 옛 필드. 폭 변화량으로 미끄러짐을 보던 때의 값이라 새 결과에는 오지 않는다.
    grip_width_hard_mm: float = 0.0
    grip_width_change_mm: float = 0.0
    reason: str = ''             # 판정 사유 / 미수행 사유 (사람이 읽는 문장)
    action: str = ''             # 처리 내용
    force_data_id: str = ''      # 원본 Force 데이터(CSV 등) 식별자
    db_saved: bool = False       # result_recorder_node 가 DB 에 저장한 뒤 True 로 다시 보낸다
    # 검사 당시의 나머지 레시피 정보 (상세 팝업용). 보내는 쪽이 모르면 비워 둔다.
    point_name: str = ''         # 예: 'BCM_POWER_CONNECTOR'
    repeat_count: int = 0
    grip_width_mm: float = 0.0
    task: List[float] = field(default_factory=list)    # 검사에 쓴 위치 [mm x3, deg x3] (BASE, ZYZ)
    joint: List[float] = field(default_factory=list)   # 검사에 쓴 위치 [deg x6]


@dataclass
class LogEntry:
    """시스템 로그 1줄."""

    stamp: str = ''
    level: str = 'INFO'          # INFO | WARN | ERROR
    text: str = ''
    popup: bool = False          # True 면 HMI 가 시스템 로그에 더해 팝업으로도 띄운다


@dataclass
class Progress:
    """동작 코드가 알려 주는 진행 상황. 메시지 하나가 전체 상태를 담는다(앞 메시지를 놓쳐도 됨)."""

    active: bool = False         # 동작 코드가 실행 중인가
    percent: int = 0             # 0~100
    point: str = ''              # 예: 'Place 2', 'Cycle 2'
    step: str = ''               # 예: 'Pull Test', '직선 이동 1'
    aborted: bool = False        # 끝까지 못 가고 중단됨
    note: str = ''               # 중단 사유 등
    # HMI 의 검사 시작 / 일시정지 / 이어하기를 받는 동작 코드만 채운다: State.IDLE(시작 대기) /
    # RUNNING / PAUSED / DONE. 비어 있으면 진행률만 알리는 코드다(HMI 버튼은 잠긴 채로 둔다).
    run_state: str = ''
    sequence: str = ''           # 현재 시퀀스. 예: 'Work Initialize', 'Home Return', 'Pull Inspection'
    pause_reason: str = PauseReason.NONE
    end_reason: str = EndReason.NONE
    # True 면 HMI 의 Home 이동(MOVE_HOME)을 이 동작 코드가 받아 처리한다(Home Return 시퀀스).
    # False 면 지금까지처럼 모니터 노드가 홈 관절각으로 바로 이동시킨다.
    handles_home: bool = False
    # 검사 결과를 보고하는 동작 코드만 채운다 (ProgressReporter.report_result 참고).
    run_id: int = 0              # 검사 1회의 번호. 바뀌면 HMI 가 결과 표를 비운다. 0 = 알리지 않음
    criteria: Criteria = field(default_factory=Criteria)   # 현재 Point 의 판정 기준
    judgement: str = ''          # 예: '검사 중', 'PASS'
    product_result: str = ''     # ProductResult. 검사가 끝났을 때


@dataclass
class Command:
    """HMI -> 검사 노드 명령."""

    name: str = ''
    args: Dict[str, Any] = field(default_factory=dict)


@dataclass
class StartAnswer:
    """검사 시작 서비스의 응답. 서비스 호출 자체가 실패하면 error 에 이유가 들어간다."""

    request_id: str = ''
    accepted: bool = False
    code: str = ''               # StartCode
    message: str = ''
    run_id: int = 0
    error: str = ''


def _from_dict(cls, data: Dict[str, Any]):
    """모르는 키는 버리고 빠진 키는 기본값으로 두어 dataclass 를 만든다."""
    if not isinstance(data, dict):
        raise ValueError(f'{cls.__name__}: JSON object 가 아님')
    obj = cls()
    for f in fields(cls):
        if f.name not in data:
            continue
        value = data[f.name]
        current = getattr(obj, f.name)
        if is_dataclass(current):
            value = _from_dict(type(current), value)
        setattr(obj, f.name, value)
    return obj


def _encode(obj) -> String:
    return String(data=json.dumps(asdict(obj), ensure_ascii=False))


def _decode(cls, msg: String):
    return _from_dict(cls, json.loads(msg.data))


def encode_status(status: SystemStatus) -> String:
    """상태(SystemStatus)를 ROS 메시지로 바꾼다."""
    return _encode(status)


def decode_status(msg: String) -> SystemStatus:
    """ROS 메시지 -> SystemStatus. 형식이 틀리면 ValueError."""
    return _decode(SystemStatus, msg)


def decode_json_object(msg: String) -> Dict[str, Any]:
    """robot_status / work_status 의 JSON 객체. 형식이 틀리면 ValueError."""
    data = json.loads(msg.data)
    if not isinstance(data, dict):
        raise ValueError('JSON object 가 아님')
    return data


def _number(value) -> Optional[float]:
    """유한한 숫자면 float, 아니면(null, 문자열, NaN) None. 0.0 으로 바꾸지 않는다."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value) if math.isfinite(value) else None


def _pose(value) -> List[float]:
    """좌표 6개면 list, 아니면(null, 개수 틀림) 빈 list - 화면은 빈 list 를 '—' 로 그린다."""
    if not isinstance(value, list) or len(value) != 6:
        return []
    numbers = [_number(v) for v in value]
    return [] if None in numbers else numbers


def merge_split_status(robot: Optional[Dict[str, Any]], work: Optional[Dict[str, Any]],
                       robot_fresh: bool, work_fresh: bool) -> SystemStatus:
    """
    robot_status 와 work_status 를 화면이 그리는 SystemStatus 하나로 합친다.

    - 실행 상태·진행·레시피·검사 조건은 work_status, 장비 값은 robot_status 에서 온다.
    - 모르는 수치는 None, 모르는 좌표는 [] 로 둔다(문서: null 을 0 으로 바꾸지 않는다).
    - robot_fresh=False 면 robot_status 가 끊긴 것이다 - 장비 값을 모두 버리고 연결 끊김으로 둔다.
    - 현재 힘·변위는 work_status.measurement 가 valid 일 때만 쓴다. 그 값이 Pull 을 멈출지
      비교하는 힘이다. robot_status.force_norm_n 은 원시 힘이라 raw_force_n 에 따로 둔다.
    - work 가 아직 없으면 상태를 모른다. work_fresh=False 이므로 화면은 연결 전으로 그린다.
    """
    status = _from_dict(SystemStatus, work) if work else SystemStatus()
    status.split_contract = True
    status.work_fresh = work_fresh

    measurement = work.get('measurement') if work else None
    valid = isinstance(measurement, dict) and measurement.get('valid') is True
    status.force_n = _number(measurement.get('pull_force_n')) if valid else None
    status.displacement_mm = _number(measurement.get('pull_displacement_mm')) if valid else None

    r = robot if (robot and robot_fresh) else {}
    status.robot_connected = r.get('robot_connected') is True
    status.gripper_connected = r.get('gripper_connected') is True
    status.task = _pose(r.get('task'))
    status.joint = _pose(r.get('joint'))
    status.gripper_width_mm = _number(r.get('gripper_width_mm'))
    status.raw_force_n = _number(r.get('force_norm_n'))
    status.robot_motion = str(r.get('robot_motion') or '')
    status.servo = str(r.get('servo') or '')
    tool = r.get('tool') if isinstance(r.get('tool'), dict) else {}
    name, tcp = str(tool.get('name') or ''), str(tool.get('tcp') or '')
    # 무게와 Force Zero 는 이 계약이 보내지 않는다 - 모름으로 둔다.
    status.tool = ToolInfo(configured=bool(name and tcp), name=name, tcp=tcp,
                           weight_kg=0.0, force_zero_done=None)
    return status


# 결과만 팀 공용 메시지(cable_interfaces/msg/InspectionResult)를 쓴다. 이름이 같은 필드만
# 주고받고, 메시지에 없는 HMI 필드(cable_id, product_id, action ...)는 기본값으로 남는다.
# JSON 과 달리 메시지는 타입을 강제하므로 넣기 전에 dataclass 타입으로 맞춘다.
_RESULT_FIELDS = tuple(f for f in fields(PointResult)
                       if f.name in InspectionResultMsg.get_fields_and_field_types())


def encode_result(result: PointResult) -> InspectionResultMsg:
    """결과(PointResult)를 ROS 메시지로 바꾼다. 값이 맞지 않으면 ValueError."""
    msg = InspectionResultMsg()
    for f in _RESULT_FIELDS:
        value = getattr(result, f.name)
        try:
            if f.type == List[float]:
                value = [float(v) for v in value]
            elif f.type is bool:
                value = bool(value)
            elif f.type in (int, float, str):
                value = f.type(value)
            setattr(msg, f.name, value)
        except (AttributeError, TypeError, ValueError) as e:
            raise ValueError(f'{f.name} 값을 메시지에 넣을 수 없습니다: {value!r} ({e})') from None
    return msg


def decode_result(msg: InspectionResultMsg) -> PointResult:
    """ROS 메시지 -> PointResult. 형식이 틀리면 ValueError."""
    result = PointResult()
    try:
        for f in _RESULT_FIELDS:
            value = getattr(msg, f.name)
            # float64[] 는 array.array 로 온다. 화면과 DB 는 list 를 기대한다.
            setattr(result, f.name, [float(v) for v in value]
                    if f.type == List[float] else value)
    except (AttributeError, TypeError) as e:
        raise ValueError(f'결과 메시지 형식이 다릅니다: {e}') from None
    return result


def encode_log(entry: LogEntry) -> String:
    """로그(LogEntry)를 ROS 메시지로 바꾼다."""
    return _encode(entry)


def decode_log(msg: String) -> LogEntry:
    """ROS 메시지 -> LogEntry. 형식이 틀리면 ValueError."""
    return _decode(LogEntry, msg)


def encode_command(command: Command) -> String:
    """명령(Command)을 ROS 메시지로 바꾼다."""
    return _encode(command)


def decode_command(msg: String) -> Command:
    """ROS 메시지 -> Command. 형식이 틀리면 ValueError."""
    return _decode(Command, msg)


def encode_progress(progress: Progress) -> String:
    """진행 상황(Progress)을 ROS 메시지로 바꾼다."""
    return _encode(progress)


def decode_progress(msg: String) -> Progress:
    """ROS 메시지 -> Progress. 형식이 틀리면 ValueError."""
    return _decode(Progress, msg)
