"""ProgressReporter 의 진행률 계산 시험 (ROS 통신 없이 가짜 publisher 사용)."""

from cable_hmi import interface as itf
from cable_hmi.hmi_progress import ProgressReporter


class _FakePublisher:

    def __init__(self):
        self.sent = []

    def publish(self, msg):
        self.sent.append(itf.decode_progress(msg))

    def get_subscription_count(self):
        return 1


class _FakeNode:

    def __init__(self):
        self.pub = _FakePublisher()

    def create_publisher(self, _msg_type, _topic, _depth):
        return self.pub


def _reporter(points, steps):
    node = _FakeNode()
    return ProgressReporter(node, points=points, steps=steps), node.pub.sent


def test_percent_follows_point_and_step():
    progress, sent = _reporter(3, ['a', 'b', 'c', 'd'])
    progress.start()
    assert (sent[-1].active, sent[-1].percent) == (True, 0)
    progress.point(0, 'P1')
    progress.step('c')                      # (0 + 2/4) / 3
    assert sent[-1].percent == 16 and sent[-1].point == 'P1' and sent[-1].step == 'c'
    progress.point(1, 'P2')                 # (1 + 0) / 3
    assert sent[-1].percent == 33 and sent[-1].step == ''
    progress.point(2)
    progress.step('d')                      # (2 + 3/4) / 3
    assert sent[-1].percent == 91 and sent[-1].point == 'Point 3'
    progress.finish()
    assert (sent[-1].active, sent[-1].percent, sent[-1].aborted) == (False, 100, False)


def test_unknown_step_changes_text_only():
    progress, sent = _reporter(2, ['a', 'b'])
    progress.start()
    progress.point(1)
    progress.step('b')
    before = sent[-1].percent
    progress.step('여기에 없는 단계')
    assert sent[-1].percent == before and sent[-1].step == '여기에 없는 단계'


def test_abort_resets_to_zero_and_is_ignored_after_finish():
    progress, sent = _reporter(2, ['a'])
    progress.start()
    progress.point(1)
    progress.abort('(Ctrl+C)')
    assert (sent[-1].percent, sent[-1].aborted, sent[-1].note) == (0, True, '(Ctrl+C)')

    progress, sent = _reporter(2, ['a'])
    progress.start()
    progress.finish()
    count = len(sent)
    progress.abort('late')                  # finally 에서 불려도 100 % 를 지우지 않는다
    assert len(sent) == count and sent[-1].percent == 100
