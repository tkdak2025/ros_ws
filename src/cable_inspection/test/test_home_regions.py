"""영역별 HOME 복귀: 실물 없이 경계, 실패 차단, 이동 순서를 검증한다."""
import copy
import json
from pathlib import Path
from types import SimpleNamespace as NS
import pytest
from cable_inspection.sequence.home_return.seq_home_return import HomeReturnSequence
from cable_inspection.sequence.common.data_models.robot_runtime_config import RobotRuntimeConfig
from cable_inspection.recipe.recipe import Recipe

CONFIG = Path(__file__).parents[1] / 'config/system_recipe.json'


def make_route(tcp, joints=None, failure=None):
    system = json.loads(CONFIG.read_text())
    state = {'tcp': tcp[:], 'joint': list(joints or [20.] * 6)}
    events = []
    def open_gripper(width, force):
        events.append('open')
        if failure == 'open':
            raise TimeoutError('open')
        return {'measured': {'width_mm': width}}
    def move_joint(pose, **kwargs):
        events.append(pose.joint[:])
        if failure == 'move':
            raise TimeoutError('move')
        if failure != 'arrival':
            state.update(tcp=pose.task[:], joint=pose.joint[:])
    backend = NS(robot=NS(mode='real', get_tcp=lambda:state['tcp'][:],
                          read_joints=lambda:state['joint'][:], motion_status=lambda:0),
                 config=RobotRuntimeConfig(), open_gripper=open_gripper,
                 move_joint=move_joint)
    route = HomeReturnSequence(backend, lambda x:None, lambda:None, system)
    return route, events


@pytest.mark.parametrize('x,key', [(-330.,'upper'),(-298.07,'upper'),(100.,'upper'),
                                   (100.01,'midlower'),(924.84,'midlower')])
def test_region_boundary_and_joint_route(x,key):
    route,events=make_route([x,0.,700.,0.,0.,0.])
    assert route.run().success
    assert events == ['open',route.system['safe_escape_region_'+key]['joint'],
                      route.system['home_pose']['joint']]


@pytest.mark.parametrize('tcp', [[-330.01,0,700,0,0,0],[924.85,0,700,0,0,0],
                                [0,266,700,0,0,0],[0,0,801,0,0,0]])
def test_outside_no_commands(tcp):
    route,events=make_route(tcp)
    assert route.run().code == 'HOME_OUTSIDE_REGIONS'
    assert events == []


@pytest.mark.parametrize('key',['upper','midlower'])
def test_reached_escape_skips_duplicate_move(key):
    pose=json.loads(CONFIG.read_text())['safe_escape_region_'+key]
    route,events=make_route(pose['task'],pose['joint'])
    assert route.run().success
    assert events == ['open',route.system['home_pose']['joint']]


def test_home_no_commands():
    pose=json.loads(CONFIG.read_text())['home_pose']
    route,events=make_route(pose['task'],pose['joint'])
    assert route.run().data['route']=='ALREADY_HOME'
    assert not events


@pytest.mark.parametrize('failure',['open','move','arrival'])
def test_failure_never_moves_home(failure):
    route,events=make_route([-200,0,700,0,0,0],failure=failure)
    with pytest.raises((TimeoutError,RuntimeError)):
        route.run()
    assert route.system['home_pose']['joint'] not in events


def test_same_tcp_different_joint_does_not_skip():
    pose=json.loads(CONFIG.read_text())['safe_escape_region_upper']
    route,events=make_route(pose['task'])
    assert route.run().success
    assert events[1] == pose['joint']


def test_config_validation(tmp_path):
    data=json.loads(CONFIG.read_text())
    assert Recipe(system_path=CONFIG).system_recipe()
    for change in ('missing','outside'):
        bad=copy.deepcopy(data)
        if change=='missing': del bad['safe_escape_region_upper']
        else: bad['safe_escape_region_upper']['task'][0]=-999
        p=tmp_path/'system.json';p.write_text(json.dumps(bad))
        with pytest.raises(ValueError): Recipe(system_path=p).system_recipe()


def test_ready_joint_reached_with_different_tcp_skips_escape():
    pose=json.loads(CONFIG.read_text())['safe_escape_region_upper']
    route,events=make_route([-146.209,164.665,701.991,148.778,2.681,-75.217],pose['joint'])
    assert route.run().success
    assert events == ['open',route.system['home_pose']['joint']]


@pytest.mark.parametrize('status,joint_offset,success',[(0,0,True),(1,0,False),(0,360,False)])
def test_real_home_movej_checks_stopped_absolute_joints(status,joint_offset,success):
    from cable_inspection.sequence.common.motion import SequenceMotion
    from cable_inspection.recipe.recipe import RobotPose
    target=RobotPose(**json.loads(CONFIG.read_text())['safe_escape_region_upper'])
    robot=NS(mode='real',move_joint=lambda *args:None,motion_status=lambda:status,
             read_joints=lambda:[target.joint[0]+joint_offset,*target.joint[1:]])
    motion=SequenceMotion(robot,None,None)
    motion.config.motion_timeout_s=0
    sample=lambda:{'tcp':[-146.209,164.665,701.991,148.778,2.681,-75.217]}
    if success:
        result=motion.move_joint(target,sample=sample,joint_tolerance_deg=0.1)
        assert result['stop_reason']=='TARGET_REACHED'
    else:
        with pytest.raises(TimeoutError):
            motion.move_joint(target,sample=sample,joint_tolerance_deg=0.1)
