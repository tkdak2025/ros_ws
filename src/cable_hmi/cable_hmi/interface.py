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
from typing import Any, Dict, List

from std_msgs.msg import Empty, String

# --------------------------------------------------------------------------
# 토픽 (상대 이름 - launch 에서 namespace 를 주면 그대로 따라간다)
# --------------------------------------------------------------------------
TOPIC_STATUS = 'cable_inspection/status'          # 검사 노드 -> HMI, 10 Hz 권장
TOPIC_RESULT = 'cable_inspection/result'          # 검사 노드 -> HMI, Point 1개 완료마다
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
RESULT_MSG_TYPE = String
LOG_MSG_TYPE = String
COMMAND_MSG_TYPE = String
HEARTBEAT_MSG_TYPE = Empty
PROGRESS_MSG_TYPE = String

QOS_DEPTH = 50

# status 가 이 시간(s) 이상 안 오면 HMI 는 'ROS2 통신 끊김' 으로 표시한다.
STATUS_TIMEOUT_SEC = 1.5
HEARTBEAT_PERIOD_SEC = 0.5


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
        if code in ('', ResultCode.INCOMPLETE):
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
    FAIL_GRIP_SLIP = 'FAIL_GRIP_SLIP'                     # 파지 미끄러짐 - 검사 무효
    INCOMPLETE_NOT_IMPLEMENTED = 'INCOMPLETE_NOT_IMPLEMENTED'         # 검사 동작 미구현 (개발 중 전용)

    # 통합문서(2026-09-22) 이전 코드. 새 결과에는 쓰지 않고, 지난 기록을 읽을 때만 쓴다.
    FAIL_FORCE_REQUIREMENT = 'FAIL_FORCE_REQUIREMENT'
    INCOMPLETE_INVALID_DATA = 'INCOMPLETE_INVALID_DATA'
    INCOMPLETE_ABNORMAL_TERMINATION = 'INCOMPLETE_ABNORMAL_TERMINATION'

    ALL = (PASS_FORCE_DISPLACEMENT_OK, FAIL_DISPLACEMENT_LIMIT, FAIL_MAX_DISTANCE,
           FAIL_GRIP_SLIP, INCOMPLETE_NOT_IMPLEMENTED)

    LABELS = {
        PASS_FORCE_DISPLACEMENT_OK: '기준 힘 도달, 변위 허용 범위 이내',
        FAIL_DISPLACEMENT_LIMIT: '변위 허용 한계 초과',
        FAIL_MAX_DISTANCE: '미끄러짐 없이 Pull 최대 거리까지 이동',
        FAIL_GRIP_SLIP: '파지 미끄러짐으로 불량',
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

    _PREFIXES = ('PULL_', 'ENTRY_')

    LABELS = {
        FORCE_LIMIT: '기준 힘 도달', MAX_DISTANCE: '최대 거리 도달',
        TIMEOUT: '시간 초과', MOTION_ERROR: '모션 오류',
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
    force_zero_done: bool = False


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
    # 측정: Hard Grip 직후 RG2 실제 폭 (#04 grip_width_hard). 지시한 파지 폭(grip_width_mm)과
    # 다르다 - 실측 예: 지시 16.0 mm 에 실제 18.4 mm. Pull 중 폭 변화의 기준값이다.
    grip_width_hard_mm: float = 0.0
    grip_width_change_mm: float = 0.0  # Hard Grip 뒤 Pull 중 RG2 폭 변화 (미끄러짐 보조 판별)
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


def encode_result(result: PointResult) -> String:
    """결과(PointResult)를 ROS 메시지로 바꾼다."""
    return _encode(result)


def decode_result(msg: String) -> PointResult:
    """ROS 메시지 -> PointResult. 형식이 틀리면 ValueError."""
    return _decode(PointResult, msg)


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
