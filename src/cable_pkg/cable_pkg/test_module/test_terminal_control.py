"""터미널/HMI 입력 분리와 숫자 메뉴를 실물 없이 확인한다.
ROS 초기화와 장비 호출은 하지 않는다. 운영 코드에서는 이 파일을 참조하지 않는다."""

import json
import time
from types import SimpleNamespace

import pytest
from rclpy.node import Node
from std_msgs.msg import String

from cable_pkg.data_models.sequence_models import SystemState
from cable_pkg.sequence.seq_00_main_work.console import SequenceConsole
from cable_pkg.sequence.seq_00_main_work.node import SequenceNode
from cable_pkg.sequence.seq_00_main_work.run import main


# 기능: ROS 생성 대신 구독 토픽을 기록해 두 운전 모드의 입력이 분리되는지 확인한다.
@pytest.mark.parametrize('mode,command,heartbeat', [
    ('terminal', 'terminal_command', 'terminal_heartbeat'),
    ('hmi', 'command', 'hmi_heartbeat'),
])
def test_control_source_and_loss(monkeypatch, mode, command, heartbeat):
    subscriptions, lost, started = {}, [], []
    monkeypatch.setattr(Node, '__init__', lambda *a, **k: None)
    monkeypatch.setattr(SequenceNode, 'create_publisher', lambda *a: SimpleNamespace(publish=lambda m: None))
    monkeypatch.setattr(SequenceNode, 'create_subscription', lambda self, kind, topic, callback, qos: subscriptions.update({topic: callback}))
    monkeypatch.setattr(SequenceNode, 'create_timer', lambda *a: None)
    monkeypatch.setattr(SequenceNode, '_publish_status', lambda self: None)
    controller = SimpleNamespace(backend=SimpleNamespace(recipe_paths={'BMW': 'bmw.json'}),
        context=None, state=SystemState.SYSTEM_READY, run=started.append,
        communication_lost=lambda: lost.append(True))
    node = SequenceNode(controller, control_mode=mode)
    assert set(subscriptions) == {f'cable_inspection/{command}', f'cable_inspection/{heartbeat}'}
    node._launch = lambda action: action()
    node._on_command(String(data=json.dumps({'name': 'START', 'args': {}})))
    assert started == ['BMW']
    assert not controller.backend.hmi_available()
    node._on_heartbeat(None)
    assert controller.backend.hmi_available()
    controller.state = SystemState.RUNNING
    node.last_heartbeat = time.monotonic() - 3
    node._tick()
    node._tick()
    assert lost == [True]


# 기능: 숫자 메뉴가 기존 Main 명령과 선택 Recipe ID를 보내는지 확인한다.
def test_console_menu():
    sent = []
    console = SimpleNamespace(recipe_choices=None, status={'available_recipes': ['BMW', 'LAN']},
        send=lambda *args: sent.append(args), show_menu=lambda: None)
    for choice in ('1', '2', '3', '4', '5'):
        assert SequenceConsole.handle_input(console, choice)
    assert [row[0] for row in sent] == ['START', 'PAUSE', 'RESUME', 'STOP', 'HOME_RETURN']
    SequenceConsole.handle_input(console, '6')
    SequenceConsole.handle_input(console, '2')
    assert sent[-1] == ('SELECT_RECIPE', {'recipe_id': 'LAN'})
    assert not SequenceConsole.handle_input(console, 'Q')


# 기능: HMI 모드 또는 오래된 상태에서는 콘솔이 새 모션 명령을 보내지 않는지 확인한다.
@pytest.mark.parametrize('mode,age,allowed', [('terminal', 0, True), ('hmi', 0, False), ('terminal', 3, False)])
def test_console_command_source(mode, age, allowed):
    sent = []
    console = SimpleNamespace(status={'control_mode': mode}, status_received_at=time.monotonic()-age,
                              commands=SimpleNamespace(publish=sent.append))
    SequenceConsole.send(console, 'START')
    assert bool(sent) == allowed
    SequenceConsole.send(console, 'STOP')
    assert json.loads(sent[-1].data)['name'] == 'STOP'


# 기능: launch가 추가하는 ROS 인자가 Main의 argparse 오류를 일으키지 않는지 확인한다.
def test_main_accepts_launch_ros_arguments():
    with pytest.raises(SystemExit) as result:
        main(['--control-mode', 'terminal', '--help', '--ros-args', '--log-level', 'info'])
    assert result.value.code == 0
