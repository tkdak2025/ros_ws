"""
동작 코드에서 HMI 진행률을 보고하는 부품.

사용법 (동작 코드 쪽에는 이 몇 줄만 들어간다):

    progress = ProgressReporter(node, points=3, steps=['접근', '파지', 'Pull', '후퇴'])
    progress.start()
    for i, point in enumerate(points):
        progress.point(i, point.name)
        progress.step('접근');  ...동작...
        progress.step('파지');  ...동작...
    progress.finish()            # 100 %. 중간에 그만둘 때는 progress.abort('사유')

진행률 = (끝난 Point 수 + 현재 Point 안에서의 단계 위치) / 전체 Point 수.
단계 이름이 steps 에 없으면 글자만 바뀌고 퍼센트는 그대로다(예: 시작 전 '홈 이동').

동작 코드는 status 를 직접 보내지 않는다. 진행 상황만 cable_inspection/progress 로 보내면
상태를 보내는 노드(robot_monitor_node)가 로봇 값과 합쳐 HMI 로 보낸다.
나중에 검사 노드가 status 를 직접 보내게 되더라도 이 클래스의 사용법은 그대로 두고
_publish() 안만 바꾸면 된다.
"""

import time

from . import interface as itf

# 두산 예제 노드는 namespace(dsr01) 안에 만들어지므로 절대 이름으로 보낸다.
DEFAULT_TOPIC = '/' + itf.TOPIC_PROGRESS


class ProgressReporter:
    """Point / 단계 단위로 진행률을 계산해 HMI 쪽으로 보낸다."""

    def __init__(self, node, points: int, steps, topic: str = DEFAULT_TOPIC):
        self._points = max(1, int(points))
        self._steps = list(steps)
        self._pub = node.create_publisher(itf.PROGRESS_MSG_TYPE, topic, 10)
        self._point_index = 0
        self._step_index = 0
        self._state = itf.Progress()

    @property
    def percent(self) -> int:
        """현재 진행률(0~100)."""
        return self._state.percent

    def start(self, wait_sec: float = 1.0):
        """0 % 로 시작을 알린다. 받는 쪽이 연결될 때까지 잠깐(최대 wait_sec) 기다린다."""
        deadline = time.monotonic() + wait_sec
        while self._pub.get_subscription_count() == 0 and time.monotonic() < deadline:
            time.sleep(0.05)
        self._point_index = 0
        self._step_index = 0
        self._state = itf.Progress(active=True)
        self._publish()

    def point(self, index: int, name: str = ''):
        """Point 하나를 시작한다. index 는 0 부터 센다."""
        self._point_index = max(0, min(self._points - 1, int(index)))
        self._step_index = 0
        self._state.point = name or f'Point {self._point_index + 1}'
        self._state.step = ''
        self._update_percent()
        self._publish()

    def step(self, name: str):
        """현재 Point 안에서 name 단계를 시작한다."""
        if name in self._steps:
            self._step_index = self._steps.index(name)
        self._state.step = name
        self._update_percent()
        self._publish()

    def finish(self):
        """정상 완료: 100 %."""
        self._state = itf.Progress(active=False, percent=100, point=self._state.point)
        self._publish(settle=True)

    def abort(self, note: str = ''):
        """중단: HMI 진행률을 0 으로 되돌리고 사유를 남긴다. 이미 끝났으면 아무것도 안 한다."""
        if not self._state.active:
            return
        self._state = itf.Progress(active=False, percent=0, aborted=True, note=note)
        self._publish(settle=True)

    def _update_percent(self):
        in_point = self._step_index / len(self._steps) if self._steps else 0.0
        self._state.active = True
        self._state.percent = int(100 * (self._point_index + in_point) / self._points)

    def _publish(self, settle: bool = False):
        self._pub.publish(itf.encode_progress(self._state))
        if settle:
            time.sleep(0.2)     # 프로세스가 바로 끝나도 마지막 메시지가 나가도록
