"""START의 위치별 준비 경로와 Work Access 미도달 시 검사 차단을 검증한다."""
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import Mock
import pytest
from cable_inspection.recipe.recipe import Recipe
from cable_inspection.sequence.main.seq_main import MainSequence
from cable_inspection.sequence.common.data_models.robot_runtime_config import RobotRuntimeConfig



def setup_route(location, failure=None):
    system = Recipe(system_path=Path(__file__).parents[1]/'config/system_recipe.json').system_recipe()
    access = system['work_Access_safe_pose']['task']
    current = {'tcp': {'home':system['home_pose']['task'], 'access':access,
        'work':[500.,0.,300.,0.,0.,0.]}[location][:]}
    events, checkpoints = [], []



    def open_gripper(width, force):
        events.append('open')

        if failure == 'open':
            raise TimeoutError('open failed')

        return {'measured':{'width_mm':width}}



    def move_linear(target):
        events.append(('escape',target[:]))

        if failure == 'escape':
            raise TimeoutError('escape failed')

        current['tcp'] = target[:]

        return {'stop_reason':'TARGET_REACHED'}



    def move_joint(pose):
        events.append(('access',pose.joint[:]))

        if failure == 'move':
            raise TimeoutError('access failed')

        if failure != 'arrival':
            current['tcp'] = pose.task[:]



    motion = NS(robot=NS(mode='real', get_tcp=lambda:current['tcp'][:]),
        gripper=NS(), config=RobotRuntimeConfig(), open_gripper=open_gripper,
        move_linear=move_linear, move_joint=move_joint)
    main = MainSequence(motion, inspection=NS())
    main.system = system
    main.checkpoint = checkpoints.append

    return main, events, checkpoints



@pytest.mark.parametrize('location,expected', [('home',['access']),('access',[]),('work',['open','escape','access'])])
def test_start_uses_current_pose_to_reach_work_access(location, expected):
    main, events, checkpoints = setup_route(location)
    main.prepare_work_access()
    assert [e if isinstance(e,str) else e[0] for e in events] == expected
    assert checkpoints[-1] == 'WORK_ACCESS_REACHED'
    assert 'HOME_REACHED' not in checkpoints

    if location == 'work':
        assert events[1][1] == [500.,0.,270.,0.,0.,0.]  # Tool −Z 30 mm
        assert checkpoints == ['GRIP_RELAXED','SAFE_ESCAPE_DONE','WORK_ACCESS_REACHED']



@pytest.mark.parametrize('failure,expected', [('open',['open']),('escape',['open','escape']),
                                            ('move',['open','escape','access']),('arrival',['open','escape','access'])])
def test_failed_start_preparation_never_reaches_inspection(failure, expected):
    main, events, checkpoints = setup_route('work', failure)
    inspect = Mock()

    with pytest.raises((TimeoutError,RuntimeError)):
        main.prepare_work_access()
        inspect()

    inspect.assert_not_called()
    assert 'WORK_ACCESS_REACHED' not in checkpoints
    assert [e if isinstance(e,str) else e[0] for e in events] == expected



# 기능: 수동 HOME 명령이 현재 Access를 재확인하고 위치별 복귀 경로를 선택하는지 검증한다.
#     mode: real/virtual 도달 기준. location: Access·작업영역·Home·Access 이탈 상태.
#     command: 실행 노드가 제공하는 두 Home 명령 이름.
#     반환: 없음. 실행권 구분, 명령 순서, Home 완료 상태를 assertion으로 확인한다.
@pytest.mark.parametrize('mode', ['real', 'virtual'])
@pytest.mark.parametrize('location', ['access', 'work', 'home', 'drift'])
@pytest.mark.parametrize('command', ['HOME_RETURN', 'MOVE_HOME'])
def test_manual_home_command_selects_route_from_current_pose(mode, location, command):
    from cable_inspection.sequence.main.node_main import MainSequenceNode
    from cable_inspection.sequence.common.data_models.sequence_result import SequenceResult
    from cable_inspection.sequence.main.data_models.system_state import SystemState

    main, events, checkpoints = setup_route('access' if location == 'drift' else location)
    main.recipes = Recipe(system_path=Path(__file__).parents[1] / 'config/system_recipe.json')
    main.check_devices = Mock(return_value=SequenceResult(True, 'READY', ''))
    main.backend.robot.mode = mode
    joints = main.system['work_Access_safe_pose' if location in {'access', 'drift'} else 'home_pose']['joint'][:]

    if location == 'work':
        joints = [20.0] * 6

    if location == 'drift':
        joints[0] += 1.0
        read_tcp = main.backend.robot.get_tcp
        main.backend.robot.get_tcp = lambda: [read_tcp()[0] + 1.0, *read_tcp()[1:]]

    main.backend.robot.read_joints = lambda: joints[:]
    move_joint = main.backend.move_joint

    # 기능: 기록용 관절 이동과 실제 관절 피드백을 함께 갱신한다.
    #     pose: 명령한 RobotPose. 반환: 없음.
    def record_joint_move(pose):
        move_joint(pose)
        joints[:] = pose.joint

    main.backend.move_joint = record_joint_move
    results = []
    node = NS(controller=main,
              launch_operation=lambda action, operation: results.append((operation, action())))

    # ROS/Worker 생성만 대체하고 실행 노드의 명령 분기와 Main/Home component는 그대로 호출한다.
    MainSequenceNode.execute_command(node, command, {})
    operation, result = results[0]
    labels = [event if isinstance(event, str) else
              'home' if event[0] == 'access' and event[1] == main.system['home_pose']['joint'] else event[0]
              for event in events]

    assert operation == 'HOME'
    assert result.success and main.state == SystemState.SYSTEM_READY
    assert labels == (['home'] if location in {'access', 'home'} else ['open', 'escape', 'access', 'home'])
    assert result.data['route'] == ('VERIFIED_ACCESS_HOME' if location == 'access' else
                                    'SAFE_ROUTE_HOME' if location == 'home' else 'WORK_AREA_ESCAPE')
    assert checkpoints[-1] == 'HOME_REACHED'
    assert joints == main.system['home_pose']['joint']
    main.check_devices.assert_called_once_with()
