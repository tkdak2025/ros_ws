"""
가상 검사 노드 (로봇 없이 HMI 를 시험하기 위한 mock).

실제 검사 노드(cable_pkg)가 구현해야 할 인터페이스를 그대로 흉내 낸다.
  - command 를 받아 상태머신(IDLE/RUNNING/PAUSED/MOVING/DONE/ESTOP)을 움직이고
  - status 를 10 Hz 로, Point 결과와 시스템 로그를 발생 시점에 publish 한다.
로봇·그리퍼는 전혀 건드리지 않으며 힘/변위/그리퍼 폭은 모두 가짜 값이다.

파라미터
  random_outcomes (bool, 기본 False): True 면 Point 결과를 무작위로 뽑는다.
  require_heartbeat (bool, 기본 True): HMI heartbeat 가 끊기면 자동 일시정지.
  recipe_db (str, 기본 ''): 레시피 정보 SQLite 파일(recipe_db.py 참고). 읽을 수 있으면 Recipe
      목록·케이블·판정 기준을 DB 에서 가져오고, 못 읽으면 경고 후 아래 내장 RECIPES 를 쓴다.
      DB 에는 '결과' 가 없으므로 Point 결과는 MOCK_OUTCOME_CYCLE 을 차례로 쓴다.
"""

from dataclasses import dataclass
from datetime import datetime
import math
import random
import time

import rclpy
from rclpy.executors import ExternalShutdownException
from rclpy.node import Node

from . import interface as itf
from . import recipe_db

Cmd = itf.CommandName
State = itf.State
RC = itf.ResultCode

TICK_SEC = 0.1
HEARTBEAT_TIMEOUT_SEC = 2.0
GRIPPER_OPEN_MM = 60.0
REFERENCE_SPEED = 30        # 이 속도(%)일 때 아래 duration 이 그대로 적용된다
MOVE_DURATION_SEC = 2.0


@dataclass
class MockPoint:
    """Recipe 의 검사 Point 1개 + mock 이 만들어 낼 결과."""

    point_id: str
    cable_id: str
    cable_type: str
    grip_width_mm: float
    pull_force_limit_n: float
    max_displacement_mm: float
    outcome: str
    repeat_count: int = 3


RECIPES = {
    'RECIPE_A': {
        'version': 'v1.2',
        'product_id': 'PANEL-A01',
        'points': [
            MockPoint('Place 1', 'USB-1', 'USB', 12.0, 5.0, 1.5, RC.PASS),
            MockPoint('Place 2', 'LAN-3', 'RJ45', 14.0, 5.0, 1.5, RC.FAIL_DISPLACEMENT),
            MockPoint('Place 3', 'HDMI-4', 'HDMI', 25.0, 5.0, 1.5, RC.MISSING),
        ],
    },
    'RECIPE_B': {
        'version': 'v0.3',
        'product_id': 'PANEL-B07',
        'points': [
            MockPoint('Place 1', 'LAN-1', 'RJ45', 14.0, 6.0, 1.2, RC.PASS),
            MockPoint('Place 2', 'HDMI-2', 'HDMI', 25.0, 6.0, 1.2, RC.FAIL_DETACHED),
            MockPoint('Place 3', 'USB-5', 'USB', 12.0, 4.0, 1.5, RC.PASS),
            MockPoint('Place 4', 'USB-6', 'USB', 12.0, 4.0, 1.5, RC.PASS),
        ],
    },
}

# DB 에서 읽은 Recipe 에는 mock 결과가 없으므로 이 순서를 돌려 쓴다.
MOCK_OUTCOME_CYCLE = (RC.PASS, RC.FAIL_DISPLACEMENT, RC.MISSING, RC.PASS)

OUTCOME_TEXT = {
    RC.PASS: ('유효 검사에서 체결 유지 조건 충족', '결과 기록'),
    RC.FAIL_DISPLACEMENT: ('유효 검사에서 케이블 변위 허용 범위 초과',
                           '불량 결과 기록 · 원본 Force 데이터 보존'),
    RC.FAIL_DETACHED: ('Pull 중 힘 급감과 변위 급증 - 케이블 완전 이탈',
                       '이탈 케이블 안전 회수 · 불량 결과 기록'),
    RC.MISSING: ('그리퍼 폭이 파지 기준 미만 - 대상을 잡지 못함',
                 '사유 기록 · 안전 후퇴 후 다음 Point 진행'),
}


@dataclass
class Step:
    """검사 시퀀스의 한 단계."""

    name: str
    duration: float
    kind: str = 'move'   # move | grip | pull | check | recover | retreat | home


def build_steps(point: MockPoint):
    """Point 의 mock 결과에 맞는 단계 목록 (02_Inspection_Sequence_Concept 기준)."""
    steps = [
        Step('InspectionPointApproach', 1.5),
        Step('ToolPosAlign', 1.0),
        Step('Cable Approach', 0.8),
        Step('Contact Search', 1.2),
        Step('Cable Grip', 0.8, 'grip'),
    ]
    if point.outcome != RC.MISSING:
        steps += [Step('Pull Test', 3.0, 'pull'), Step('Force Check', 0.5, 'check')]
    if point.outcome == RC.FAIL_DETACHED:
        steps.append(Step('이탈 케이블 회수', 1.5, 'recover'))
    steps.append(Step('Retreat', 0.8, 'retreat'))
    return steps


class MockInspectionNode(Node):
    """HMI 통합 시험용 가상 검사 노드."""

    def __init__(self):
        super().__init__('mock_inspection_node')
        self.declare_parameter('random_outcomes', False)
        self.declare_parameter('require_heartbeat', True)
        self.declare_parameter('recipe_db', '')

        self._status_pub = self.create_publisher(
            itf.STATUS_MSG_TYPE, itf.TOPIC_STATUS, itf.QOS_DEPTH)
        self._result_pub = self.create_publisher(
            itf.RESULT_MSG_TYPE, itf.TOPIC_RESULT, itf.QOS_DEPTH)
        self._log_pub = self.create_publisher(itf.LOG_MSG_TYPE, itf.TOPIC_LOG, itf.QOS_DEPTH)
        self.create_subscription(
            itf.COMMAND_MSG_TYPE, itf.TOPIC_COMMAND, self._on_command, itf.QOS_DEPTH)
        self.create_subscription(
            itf.HEARTBEAT_MSG_TYPE, itf.TOPIC_HEARTBEAT, self._on_heartbeat, 1)

        self._st = itf.SystemStatus(
            robot_connected=True,
            gripper_connected=True,
            tool=itf.ToolInfo(True, 'RG2_CABLE_JAW', 1.35, 'RG2_TCP_01', True),
            available_recipes=self._load_recipes(),
            current_point='HOME',
            judgement='대기',
            speed_percent=REFERENCE_SPEED,
            gripper_width_mm=GRIPPER_OPEN_MM,
        )
        self._points = []
        self._point_idx = 0
        self._steps = []
        self._step_idx = 0
        self._elapsed = 0.0
        self._results = []
        self._max_force = 0.0
        self._resume_state = State.IDLE
        self._move_target = ''
        self._last_heartbeat = time.monotonic()

        self.create_timer(TICK_SEC, self._tick)
        self._log('INFO', 'mock 검사 노드 시작 (로봇 미연결 · 모든 값은 가상)')

    # ---------------------------------------------------------------- 명령
    def _on_heartbeat(self, _msg):
        self._last_heartbeat = time.monotonic()

    def _on_command(self, msg):
        try:
            cmd = itf.decode_command(msg)
        except (ValueError, TypeError) as e:
            self._log('ERROR', f'명령 해석 실패: {e}')
            return
        handler = {
            Cmd.START: self._cmd_start,
            Cmd.PAUSE: self._cmd_pause,
            Cmd.RESUME: self._cmd_resume,
            Cmd.ESTOP: self._cmd_estop,
            Cmd.ESTOP_RESET: self._cmd_estop_reset,
            Cmd.MOVE_HOME: self._cmd_move_home,
            Cmd.MOVE_TO_POINT: self._cmd_move_to_point,
            Cmd.SET_SPEED: self._cmd_set_speed,
            Cmd.SYNC: self._cmd_sync,
        }.get(cmd.name)
        if handler is None:
            self._log('WARN', f'알 수 없는 명령: {cmd.name}')
            return
        handler(cmd.args)

    def _ready(self, what: str) -> bool:
        """대기/완료 상태에서만 허용되는 명령의 공통 검사."""
        if self._st.state in (State.IDLE, State.DONE) and not self._st.estop:
            return True
        self._log('WARN', f'{what} 거부 - 현재 상태 {self._st.state}')
        return False

    def _load_recipes(self):
        """Recipe 표를 만든다: DB 를 읽을 수 있으면 DB, 아니면 내장 RECIPES. id 목록을 돌려준다."""
        self._recipes = dict(RECIPES)
        path = self.get_parameter('recipe_db').value
        if not path:
            return list(self._recipes)
        try:
            db = recipe_db.RecipeDb(path)
            loaded = {rid: db.load_recipe(rid) for rid in db.list_recipes()}
        except recipe_db.RecipeDbError as e:
            self.get_logger().warn(f'레시피 DB 를 쓰지 못함 - 내장 예제 레시피 사용: {e}')
            return list(self._recipes)
        if not loaded:
            self.get_logger().warn('레시피 DB 에 Recipe 가 없음 - 내장 예제 레시피 사용')
            return list(self._recipes)
        self._recipes = {
            rid: {
                'version': info.recipe_version,
                'product_id': info.product_id,
                'points': [
                    MockPoint(p.point_id, p.cable_id, p.cable_type, p.grip_width_mm,
                              p.pull_force_limit_n, p.max_displacement_mm,
                              MOCK_OUTCOME_CYCLE[i % len(MOCK_OUTCOME_CYCLE)],
                              p.repeat_count or 3)
                    for i, p in enumerate(info.points.values())],
            } for rid, info in loaded.items()}
        self.get_logger().info(f'레시피 DB 에서 {len(self._recipes)}개 읽음: {path}')
        return list(self._recipes)

    def _cmd_start(self, args):
        if not self._ready('검사 시작'):
            return
        recipe_id = args.get('recipe_id', '')
        recipe = self._recipes.get(recipe_id)
        if recipe is None:
            self._log('ERROR', f'검사 시작 거부 - 없는 Recipe: {recipe_id!r}')
            return
        st = self._st
        st.run_id += 1
        st.recipe_id = recipe_id
        st.recipe_version = recipe['version']
        st.product_id = recipe['product_id']
        st.product_result = itf.ProductResult.NONE
        st.end_reason = itf.EndReason.NONE
        st.progress_percent = 0
        self._points = list(recipe['points'])
        st.total_points = len(self._points)
        self._results = []
        self._point_idx = 0
        st.state = State.RUNNING
        self._begin_point()
        self._log('INFO', f'검사 시작: {recipe_id} {st.recipe_version} '
                          f'/ {st.product_id} / Point {st.total_points}개')

    def _cmd_pause(self, _args):
        if self._st.state not in (State.RUNNING, State.MOVING):
            self._log('WARN', f'일시정지 거부 - 현재 상태 {self._st.state}')
            return
        self._resume_state = self._st.state
        self._st.state = State.PAUSED
        self._log('INFO', f'일시정지 ({self._st.current_point} · {self._st.current_step})')

    def _cmd_resume(self, _args):
        if self._st.state != State.PAUSED:
            self._log('WARN', f'이어하기 거부 - 현재 상태 {self._st.state}')
            return
        self._st.state = self._resume_state
        self._last_heartbeat = time.monotonic()
        self._log('INFO', '이어하기')

    def _cmd_estop(self, _args):
        st = self._st
        if st.estop:
            return
        st.estop = True
        st.state = State.ESTOP
        st.alarm = '비상정지 작동'
        st.force_n = 0.0
        st.judgement = '중단'
        st.end_reason = itf.EndReason.STOP
        self._log('ERROR', f'비상정지! 모든 동작 중단 ({st.current_point} · {st.current_step})')

    def _cmd_estop_reset(self, _args):
        st = self._st
        if not st.estop:
            return
        st.estop = False
        st.alarm = ''
        st.state = State.IDLE
        st.current_step = ''
        st.judgement = '대기'
        st.gripper_width_mm = GRIPPER_OPEN_MM
        st.displacement_mm = 0.0
        self._log('WARN', '비상정지 해제 - 진행 중이던 검사는 중단됨. 다시 시작하세요.')

    def _cmd_move_home(self, _args):
        if self._ready('Home 이동'):
            self._begin_move('HOME', 'Home 이동')

    def _cmd_move_to_point(self, args):
        if not self._ready('Point 이동'):
            return
        point_id = args.get('point_id', '')
        if point_id not in [p.point_id for p in self._points]:
            self._log('ERROR', f'Point 이동 거부 - 현재 Recipe 에 없는 Point: {point_id!r}')
            return
        reason = args.get('reason', '')
        self._begin_move(point_id, f'{reason} Point 이동'.strip())

    def _cmd_set_speed(self, args):
        try:
            percent = max(1, min(100, int(args.get('percent'))))
        except (TypeError, ValueError):
            self._log('WARN', f'속도 설정 거부 - 잘못된 값: {args}')
            return
        self._st.speed_percent = percent
        self._log('INFO', f'속도 설정 {percent}%')

    def _cmd_sync(self, _args):
        for result in self._results:
            self._result_pub.publish(itf.encode_result(result))

    # -------------------------------------------------------------- 시뮬레이션
    def _tick(self):
        st = self._st
        hb_lost = (time.monotonic() - self._last_heartbeat) > HEARTBEAT_TIMEOUT_SEC
        if (hb_lost and st.state in (State.RUNNING, State.MOVING)
                and self.get_parameter('require_heartbeat').value):
            self._resume_state = st.state
            st.state = State.PAUSED
            self._log('WARN', 'HMI heartbeat 끊김 - 안전을 위해 자동 일시정지')

        if st.state in (State.RUNNING, State.MOVING):
            self._elapsed += TICK_SEC * st.speed_percent / REFERENCE_SPEED
            if st.state == State.MOVING:
                self._tick_move()
            else:
                self._tick_step()
        self._status_pub.publish(itf.encode_status(st))

    def _begin_move(self, target: str, step_name: str):
        self._move_target = target
        self._elapsed = 0.0
        self._st.state = State.MOVING
        self._st.current_step = step_name
        self._st.judgement = '대기'
        self._log('INFO', f'{step_name} 시작 -> {target}')

    def _tick_move(self):
        if self._elapsed < MOVE_DURATION_SEC:
            return
        st = self._st
        st.current_point = self._move_target
        st.current_step = ''
        st.state = State.IDLE
        self._log('INFO', f'{self._move_target} 도착')

    def _begin_point(self):
        point = self._points[self._point_idx]
        if self.get_parameter('random_outcomes').value:
            point.outcome = random.choices(
                [RC.PASS, RC.FAIL_DISPLACEMENT, RC.FAIL_DETACHED, RC.MISSING],
                weights=[6, 2, 1, 1])[0]
        self._steps = build_steps(point)
        self._step_idx = 0
        self._elapsed = 0.0
        self._max_force = 0.0
        st = self._st
        st.current_point = point.point_id
        st.current_step = self._steps[0].name
        st.judgement = '검사 중'
        st.displacement_mm = 0.0
        st.force_n = 0.0
        st.gripper_width_mm = GRIPPER_OPEN_MM
        st.criteria = itf.Criteria(
            point.max_displacement_mm, point.pull_force_limit_n, point.repeat_count,
            point.grip_width_mm)
        self._log('INFO', f'{point.point_id} ({point.cable_id}) 검사 시작')

    def _tick_step(self):
        st = self._st
        step = self._steps[self._step_idx]
        ratio = min(1.0, self._elapsed / step.duration)

        if step.kind == 'home':
            st.current_step = step.name
            st.force_n = 0.0
        else:
            self._simulate(step, self._points[self._point_idx], ratio)
            done = self._point_idx + (self._step_idx + ratio) / len(self._steps)
            st.progress_percent = int(100 * done / len(self._points))

        if ratio < 1.0:
            return
        if step.kind == 'grip' and self._points[self._point_idx].outcome == RC.MISSING:
            self._finish_point()
        elif step.kind == 'check':
            self._finish_point()

        self._step_idx += 1
        self._elapsed = 0.0
        if self._step_idx < len(self._steps):
            return
        if step.kind == 'home':
            self._finish_run()
            return
        self._point_idx += 1
        if self._point_idx < len(self._points):
            self._begin_point()
        else:
            self._steps = [Step('Home 복귀', 1.5, 'home')]
            self._step_idx = 0
            st.progress_percent = 100

    def _simulate(self, step: Step, point: MockPoint, ratio: float):
        """단계 종류에 맞는 가짜 센서값을 status 에 채운다."""
        st = self._st
        st.current_step = step.name
        noise = random.gauss(0.0, 0.12)
        if step.kind == 'grip':
            closed = 0.0 if point.outcome == RC.MISSING else point.grip_width_mm
            st.gripper_width_mm = GRIPPER_OPEN_MM + (closed - GRIPPER_OPEN_MM) * ratio
            st.force_n = abs(noise)
        elif step.kind == 'pull':
            cycle = min(point.repeat_count, int(ratio * point.repeat_count) + 1)
            st.current_step = f'{step.name} ({cycle}/{point.repeat_count})'
            wave = math.sin(math.pi * ((ratio * point.repeat_count) % 1.0))
            final_disp = {RC.PASS: 0.4, RC.FAIL_DISPLACEMENT: 1.8}.get(point.outcome, 0.6)
            detached = point.outcome == RC.FAIL_DETACHED and ratio > 0.45
            if detached:
                st.force_n = abs(0.4 + noise)
                st.displacement_mm = 8.5
            else:
                st.force_n = max(0.0, (point.pull_force_limit_n + 0.8) * wave + noise)
                st.displacement_mm = round(final_disp * max(wave, ratio), 2)
            self._max_force = max(self._max_force, st.force_n)
        elif step.kind in ('retreat', 'recover'):
            st.force_n = abs(noise)
            if step.kind == 'retreat':
                st.gripper_width_mm += (GRIPPER_OPEN_MM - st.gripper_width_mm) * ratio
        else:
            st.force_n = abs(noise)

    def _finish_point(self):
        point = self._points[self._point_idx]
        st = self._st
        reason, action = OUTCOME_TEXT[point.outcome]
        missing = point.outcome == RC.MISSING
        result = itf.PointResult(
            run_id=st.run_id,
            stamp=datetime.now().isoformat(timespec='seconds'),
            recipe_id=st.recipe_id,
            recipe_version=st.recipe_version,
            product_id=st.product_id,
            point_id=point.point_id,
            cable_id=point.cable_id,
            cable_type=point.cable_type,
            result=point.outcome,
            max_force_n=0.0 if missing else round(self._max_force, 2),
            pull_force_limit_n=point.pull_force_limit_n,
            displacement_mm=0.0 if missing else round(st.displacement_mm, 2),
            displacement_limit_mm=point.max_displacement_mm,
            reason=reason,
            action=action,
            force_data_id='' if missing else f'FORCE-{st.run_id:05d}-P{self._point_idx + 1}',
            repeat_count=point.repeat_count,
            grip_width_mm=point.grip_width_mm,
            # db_saved 는 채우지 않는다: result_recorder_node 가 저장한 뒤 True 로 다시 보낸다.
        )
        self._results.append(result)
        self._result_pub.publish(itf.encode_result(result))
        st.judgement = point.outcome
        level = 'INFO' if point.outcome == RC.PASS else 'WARN'
        self._log(level, f'{point.point_id} ({point.cable_id}) 결과 {point.outcome} - {reason}')

    def _finish_run(self):
        st = self._st
        codes = [r.result for r in self._results]
        if any(c in RC.FAIL_CODES for c in codes):
            st.product_result = itf.ProductResult.FAIL
        elif RC.MISSING in codes:
            st.product_result = itf.ProductResult.INCOMPLETE
        else:
            st.product_result = itf.ProductResult.PASS
        st.state = State.DONE
        st.end_reason = itf.EndReason.COMPLETED
        st.current_point = 'HOME'
        st.current_step = ''
        st.judgement = st.product_result
        self._log('INFO', f'검사 완료 - 제품 판정 {st.product_result} '
                          f'(PASS {codes.count(RC.PASS)} / 전체 {len(codes)})')

    def _log(self, level: str, text: str):
        stamp = datetime.now().isoformat(timespec='seconds')
        self._log_pub.publish(itf.encode_log(itf.LogEntry(stamp, level, text)))
        # rclpy 로거는 같은 호출 위치에서 severity 가 바뀌면 예외를 던지므로 줄을 나눈다.
        if level == 'ERROR':
            self.get_logger().error(text)
        elif level == 'WARN':
            self.get_logger().warn(text)
        else:
            self.get_logger().info(text)


def main(args=None):
    """Mock 검사 노드를 실행한다."""
    rclpy.init(args=args)
    node = MockInspectionNode()
    try:
        rclpy.spin(node)
    except (KeyboardInterrupt, ExternalShutdownException):
        pass
    finally:
        # launch 는 Ctrl+C 때 SIGINT 를 두 번 보낼 수 있다. 종료 구간을 짧게 둔다.
        rclpy.try_shutdown()


if __name__ == '__main__':
    main()
