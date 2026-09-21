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

    # 설계 문서(CCCIS Sequence #0)의 SYSTEM_READY = 여기의 IDLE 과 DONE 이다. 둘 다 START 를 받을 수
    # 있는 정지 대기 상태이고, DONE 은 '직전 검사의 결과가 화면에 남아 있다' 는 것만 다르다.
    IDLE = 'IDLE'          # 대기 - 검사 시작/이동 명령 가능
    RUNNING = 'RUNNING'    # 검사 시퀀스 수행 중
    PAUSE_REQUEST = 'PAUSE_REQUEST'   # 일시정지를 받았고 안전한 정지 지점까지 가는 중 (Common Sequence #1)
    PAUSED = 'PAUSED'      # 일시정지 - 이어하기 가능
    MOVING = 'MOVING'      # Home / Point 이동 중
    DONE = 'DONE'          # 검사 완료 - 검사 시작/이동 명령 가능
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
        ESTOP: '비상정지',
        ERROR: '오류',
        MONITOR: '모니터링',
        MONITOR_MOVING: '모니터링 · 이동 중',
    }


class ResultCode:
    """Point 별 검사 결과 코드 (BRD 합의사항 5장)."""

    PASS = 'PASS'
    FAIL_DISPLACEMENT = 'FAIL_DISPLACEMENT'
    FAIL_DETACHED = 'FAIL_DETACHED'
    MISSING = 'MISSING'

    FAIL_CODES = (FAIL_DISPLACEMENT, FAIL_DETACHED)

    @staticmethod
    def category(code: str) -> str:
        """결과 코드를 PASS / FAIL / MISSING 세 부류로 묶는다."""
        if code == ResultCode.PASS:
            return 'PASS'
        if code == ResultCode.MISSING:
            return 'MISSING'
        return 'FAIL'


class ProductResult:
    """제품 단위 최종 판정. MISSING 이 남으면 PASS 가 될 수 없다."""

    NONE = ''
    PASS = 'PASS'
    FAIL = 'FAIL'
    INCOMPLETE = 'INCOMPLETE'   # FAIL 은 없지만 미검사(MISSING) Point 존재


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
    MOVE_TO_POINT = 'MOVE_TO_POINT'  # args: point_id, reason('FAIL'|'MISSING')
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
    현재 Point 에 적용 중인 검사 조건 (우측 패널 상단).

    합격 여부를 가르는 것은 max_displacement_mm 이다. pull_force_limit_n 은 Pull 을 멈추는
    힘(안전 상한)이지 합격선이 아니다 - '이 힘까지만 당긴다' 는 뜻이고, 도달해도 그 자체로는
    합격도 불합격도 아니다. 합격 기준 힘은 아직 정해지지 않았다. 정해지면 이 상한과 헷갈리지
    않는 별도 필드로 추가할 것.
    """

    max_displacement_mm: float = 0.0   # 허용 변위. 이 값을 넘으면 FAIL_DISPLACEMENT
    pull_force_limit_n: float = 0.0    # Pull 정지 상한. 판정 기준이 아니다
    repeat_count: int = 0
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
    end_reason: str = EndReason.NONE       # 이번 run 이 끝난 이유. 다음 run 이 시작될 때까지 남는다

    pause_reason: str = PauseReason.NONE   # state 가 PAUSE_REQUEST / PAUSED 일 때
    current_point: str = ''      # 예: 'Place 2', 'HOME'
    current_step: str = ''       # 예: 'Pull Test (2/3)'
    judgement: str = ''          # 예: '검사 중', 'PASS'
    speed_percent: int = 0
    gripper_width_mm: float = 0.0
    force_n: float = 0.0
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
    result: str = ''             # ResultCode
    # 측정값과 그때 쓴 조건을 짝지어 싣는다 (max_force_n ↔ pull_force_limit_n,
    # displacement_mm ↔ displacement_limit_mm). 합격 여부는 변위로 가른다.
    max_force_n: float = 0.0           # 측정: 이번 Pull 의 최대 힘
    pull_force_limit_n: float = 0.0    # 조건: Pull 정지 상한 (합격 기준이 아니다)
    displacement_mm: float = 0.0       # 측정: Pull 방향 변위
    displacement_limit_mm: float = 0.0  # 조건: 허용 변위 (이 값을 넘으면 FAIL_DISPLACEMENT)
    reason: str = ''             # 판정 사유 / 미수행 사유
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
