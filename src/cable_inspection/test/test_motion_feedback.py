"""실제 공통 모션·검사 시퀀스를 결정적 가상 피드백으로 끝까지 실행한다.

장비 raw API만 대역이며, 파지/이동/감속 계측/판정 요청/복구는 운영 코드다.
"""
import io
import json
import copy
from pathlib import Path
from types import SimpleNamespace as NS

import pytest
from cable_inspection.sequence.common.motion import SequenceMotion
from cable_inspection.sequence.inspection import seq_inspection as new_inspection
from cable_inspection.recipe.recipe import Recipe



class Clock:
    def __init__(self):
        self.t=0.



    def monotonic(self):
        return self.t



    def sleep(self, value):
        self.t+=max(value,0.05)



class Robot:
    def __init__(self, point, case, clock, events):
        self.mode='real'
        self.control_poll=lambda:None
        self.point,self.case,self.clock,self.events=point,case,clock,events
        self.tcp=point['ready_pose']['task'][:]
        self.force=0.
        self.frames=[]
        self.status=0
        self.contact=None
        self.pull_done=False
        self.direction=[0.,0.,1.]
        self.origin=self.tcp[:]



    def verify_mode(self):
        pass



    def get_tcp(self):
        self.clock.t+=0.05

        if self.frames:
            distance,delta_force,self.status=self.frames.pop(0)
            self.force = self.force_baseline + delta_force
            self.tcp=[self.origin[i]+self.direction[i]*distance for i in range(3)]+self.origin[3:]

        return self.tcp[:]



    def get_tool_wrench(self,ref):
        return [0.,0.,self.force,0.,0.,0.]



    def motion_status(self):
        return self.status



    def move_joint(self,joints,speed,acc):
        self.events.append(('movej',tuple(joints),speed,acc))
        self.tcp=(self.point['ready_pose'] if joints==self.point['ready_pose']['joint'] else self.point['entry_pose'])['task'][:]
        self.frames=[]
        self.status=0
        self.force=0.



    def move_linear(self,target,speed,acc):
        self.events.append(('movel',tuple(target),speed,acc))
        self.origin=self.tcp[:]
        self.force_baseline=self.force
        delta=target[2]-self.tcp[2]

        if self.motion.phase == 'GRIP_FAILURE_RECOVERY':
            self.contact=None
            self.tcp=target[:]
            self.frames=[]
            self.status=0

            return

        if delta>0:
            self.contact='ENTRY'
            self.direction=[0.,0.,1.]

        elif not self.pull_done:
            self.contact='PULL'
            self.pull_done=True
            self.direction=[0.,0.,-1.]

        else:
            self.contact=None
            self.tcp=target[:]
            self.frames=[]
            self.status=0

            return

        self.force=0.
        self.status=1

        if self.case=='short':
            self.frames=[(2.,1.,0)]

        elif self.case=='distance':
            self.frames=[(abs(delta),1.,0)]

        elif self.case=='timeout':
            self.frames=[(1.,1.,1)]

        else:
            self.frames=[(2.,16.,1)]



    def stop_motion(self,mode):
        self.events.append(('stop',mode))
        self.frames=[(3.,25.,1),(4.,17.,0)]
        self.status=1



class Gripper:
    def __init__(self,case,clock,events):
        self.mode='real'
        self.control_poll=lambda:None
        self.case,self.clock,self.events=case,clock,events
        self.width=25.
        self.commanded_width_mm=25.
        self.commanded_force_n=10.
        self.gripper_busy=True
        self.hard=False
        self.reads=0



    def set_grip(self,width,force,opening=False):
        self.events.append(('grip',width,force,opening))
        self.commanded_width_mm,self.commanded_force_n=width,force
        self.hard=force==20 and not opening
        self.width=width if opening else (18.8 if self.case=='stable' else 18.4) if self.hard else 22.



    def read_width(self,timeout):
        self.reads+=1
        width=(19.5 if self.reads%2 else 21.) if self.hard and self.case=='grip_timeout' else self.width

        return width,self.clock.monotonic()



recipe=Recipe.load_json(Path(__file__).parents[1]/'cable_inspection/recipe/inspection/lan_inspection_recipe.json')
point=copy.deepcopy(recipe['points'][0])
point['ready_pose']={'task':[0.,0.,100.,0.,0.,0.],'joint':[0.]*6}
point['entry_pose']={'task':[0.,0.,0.,0.,0.,0.],'joint':[1.]*6}
point['grip_setting'].update(soft_close_width_mm=22.,soft_open_width_mm=25.,hard_width_mm=16.,soft_force_n=10.,hard_force_n=20.)
point['entry_setting'].update(max_distance_mm=5.,force_guard_n=5.,timeout_s=.2)
point['pull_setting'].update(max_distance_mm=25.,force_limit_n=15.,timeout_s=.2,speed_mm_s=10.)



def run(case):
    clock=Clock()
    events=[]
    requests=[]
    robot=Robot(point,case,clock,events)
    gripper=Gripper(case,clock,events)
    stream=io.StringIO()
    motion=SequenceMotion(robot,gripper,stream)
    motion.config.gripper_timeout_s=.3 if case=='grip_timeout' else 10.
    motion.config.sample_period_s=0.
    robot.motion=motion
    import cable_inspection.sequence.common.motion as cm
    from unittest.mock import patch
    inspection=new_inspection.InspectionSequence(motion,judgment=NS(submit=requests.append))
    inspection.recipe_id='R'
    inspection.recipe_version='1'
    inspection.connector_type='RJ45_LAN'

    with patch.object(cm, 'time', clock), patch.object(new_inspection, 'time', clock):
        result=inspection.run_point(point)

    logs=[json.loads(line) for line in stream.getvalue().splitlines()]
    metrics=[{k:s.get(k) for k in ('measurement_kind','tcp','width_mm','wrench_base','pull_force_n','entry_displacement_mm','pull_displacement_mm')} for s in logs if s.get('measurement_kind')]

    return events, requests, result, metrics



@pytest.mark.parametrize("case,termination", [
    ("force", "FORCE_LIMIT"), ("short", "STOPPED_SHORT"),
    ("distance", "MAX_DISTANCE"), ("timeout", "TIMEOUT"),
    ("stable", "FORCE_LIMIT"), ("grip_timeout", "TIMEOUT"),
])
def test_real_sequence_with_synthetic_feedback(case, termination):
    events, requests, result, measurements = run(case)
    assert len(requests) == 1
    assert result.termination_reason.value == termination
    assert requests[0].termination_reason == result.termination_reason
    assert all(sample["width_mm"] is not None for sample in measurements)
    assert [event[0] for event in events].count("movej") == 3
    assert events[-1][0:2] == ("movej", tuple(point["ready_pose"]["joint"]))

    if case == "grip_timeout":
        assert result.pull_inspection["skipped"] is True
        assert "HARD_GRIP_TIMEOUT" in requests[0].error_reason
        assert not any(sample["measurement_kind"] == "PULL" for sample in measurements)
        assert events[-3][0] == "grip" and events[-3][-1] is True

    else:
        assert requests[0].soft_width_mm == 22.
        assert requests[0].pull_width_mm == (18.8 if case == "stable" else 18.4)

        if case in ("force", "stable", "timeout"):
            assert requests[0].peak_pull_force_n == 25.  # 감속 중 피크도 포함
            assert requests[0].pull_displacement_mm == 4.

        elif case == "short":
            assert requests[0].pull_displacement_mm == 2.
            assert not any(event[0] == "stop" for event in events)

        else:
            assert requests[0].pull_displacement_mm == 25.



def test_point_speed_does_not_change_common_home_speed():
    from unittest.mock import patch
    from cable_inspection.sequence.common import motion as common
    clock, events = Clock(), []
    selected = copy.deepcopy(point)
    robot = Robot(selected, 'distance', clock, events)
    gripper = Gripper('distance', clock, events)
    motion = SequenceMotion(robot, gripper, io.StringIO())
    robot.motion = motion
    motion.config.linear_speed_mm_s = 7.
    inspection = new_inspection.InspectionSequence(motion, judgment=NS(submit=lambda _:None))

    with patch.object(common, 'time', clock), patch.object(new_inspection, 'time', clock):
        for speed in (3.,12.):
            robot.pull_done = False
            selected['pull_setting']['speed_mm_s'] = speed
            start = len(events)
            inspection.run_point(selected)
            assert [event[2] for event in events[start:] if event[0] == 'movel'] == [speed] * 3
            assert motion.config.linear_speed_mm_s == 7.

        motion.phase = 'HOME'
        motion.move_linear([0.,0.,90.,0.,0.,0.])
        assert events[-1][2] == 7.



def test_interrupted_contact_clears_inspection_measurement_state():
    from unittest.mock import Mock
    robot = NS(move_linear=Mock(side_effect=RuntimeError('service failed')))
    motion = SequenceMotion(robot, NS(), io.StringIO())
    inspection = new_inspection.InspectionSequence(motion)
    inspection.axis = [0.,0.,1.]
    inspection.sample = lambda:{'tcp':[0.] * 6, 'wrench_base':[0.] * 6}

    with pytest.raises(RuntimeError, match='service failed'):
        inspection.contact_move(point, 'ENTRY')

    assert inspection.measurement_kind is None
    assert inspection.measurement_direction is None
    assert inspection.sample_origin is None and inspection.force_origin is None



def test_open_timeout_is_not_treated_as_success():
    from unittest.mock import Mock
    robot = NS(verify_mode=Mock())
    gripper = NS(set_grip=Mock())
    motion = SequenceMotion(robot, gripper, io.StringIO())
    motion.config.gripper_timeout_s = 0.

    with pytest.raises(TimeoutError, match='Open'):
        motion.open_gripper(25.,10.,sample=lambda:{'width_mm':18.,'gripper_busy':False})

    gripper.set_grip.assert_called_once_with(25.,10.,opening=True)



def test_stop_failure_restores_all_control_callbacks():
    from unittest.mock import Mock
    polls = [Mock(side_effect=RuntimeError('STOP')) for _ in range(3)]
    robot, gripper = NS(control_poll=polls[1]), NS(control_poll=polls[2])
    motion = SequenceMotion(robot,gripper,io.StringIO())
    motion.control_poll = polls[0]



    def stopped():
        motion.control_poll()
        robot.control_poll()
        gripper.control_poll()
        raise TimeoutError('stop feedback missing')



    motion.stop_and_wait = stopped

    with pytest.raises(TimeoutError, match='feedback missing'):
        motion.request_motion_stop()

    assert [motion.control_poll,robot.control_poll,gripper.control_poll] == polls
    assert all(poll.call_count == 0 for poll in polls)



# 기능: Ready/Entry 접근 미도달이 실제 공통 모션에서 예외가 되어 후속 파지를 막는지 확인한다.
#     missed_pose: 목표에 도달하지 않을 접근 단계(ready/entry). mode: real/virtual 도달 기준.
#     반환: 없음. 실제 시퀀스의 예외, 체크포인트, 그리퍼·접촉 명령 부재를 확인한다.
@pytest.mark.parametrize('missed_pose', ['ready', 'entry'])
@pytest.mark.parametrize('mode', ['real', 'virtual'])
def test_approach_miss_blocks_grip_and_contact_motion(missed_pose, mode):
    from unittest.mock import patch
    from cable_inspection.sequence.common import motion as common_motion

    clock = Clock()
    events, requests, checkpoints = [], [], []
    robot = Robot(point, 'force', clock, events)
    gripper = Gripper('force', clock, events)
    motion = SequenceMotion(robot, gripper, io.StringIO())
    robot.motion = motion

    if missed_pose == 'ready':
        robot.tcp = [0.0, 0.0, 200.0, 0.0, 0.0, 0.0]

    robot.mode = mode
    joints = [20.0] * 6 if missed_pose == 'ready' else point['ready_pose']['joint'][:]
    robot.read_joints = lambda: joints[:]
    move_joint = robot.move_joint

    # 기능: 지정 접근 명령만 미도달 위치에 정지시키고 나머지는 기존 장비 대역으로 실행한다.
    #     joints: 목표 관절각(deg). speed/acc: 관절 속도·가속도. 반환: 없음.
    def miss_approach(joints, speed, acc):
        if joints == point[f'{missed_pose}_pose']['joint']:
            events.append(('missed_approach', missed_pose))
            robot.status = 0
            return

        move_joint(joints, speed, acc)
        current_joints[:] = joints

    current_joints = joints
    robot.move_joint = miss_approach
    inspection = new_inspection.InspectionSequence(
        motion, judgment=NS(submit=requests.append), checkpoint=checkpoints.append)

    # 가상 시계로 기본 60초 목표 확인을 실행한다. 모션·검사 메서드는 대체하지 않는다.
    with patch.object(common_motion, 'time', clock), patch.object(new_inspection, 'time', clock):
        with pytest.raises(TimeoutError, match='이동 완료/목표 위치'):
            inspection.run_point(point)

    assert clock.t >= motion.config.motion_timeout_s
    assert checkpoints == (['READY_REACHED'] if missed_pose == 'entry' else [])
    assert not requests
    assert all(event[3] is True for event in events if event[0] == 'grip')  # Open만 허용
    assert not any(event[0] == 'movel' for event in events)
