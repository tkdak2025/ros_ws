"""장비 API의 요청 형식, 자체 통신 실패 처리와 준비 중단을 검증한다."""
from concurrent.futures import Future
from types import SimpleNamespace as NS
from unittest.mock import Mock

import pytest
from cable_inspection.robot.node_robot import RobotNode
from cable_inspection.gripper_tool.node_gripper_tool import GripperToolNode
from cable_inspection.gripper_tool.rg2 import RG2Gripper
from cable_inspection.sequence.main.seq_main import MainSequence



def test_robot_move_apis_keep_async_base_requests():
    robot = object.__new__(RobotNode)
    robot.movej_client, robot.movel_client, robot.stop_client = object(), object(), object()
    robot._call = Mock()
    robot.move_joint([1., 2., 3., 4., 5., 6.], 10., 20.)
    client, request = robot._call.call_args.args
    assert client is robot.movej_client
    assert list(request.pos) == [1., 2., 3., 4., 5., 6.]
    assert (request.vel, request.acc, request.sync_type) == (10., 20., 1)
    robot.move_linear([10., 20., 30., 0., 180., 0.], 5., 10.)
    client, request = robot._call.call_args.args
    assert client is robot.movel_client
    assert (request.ref, request.mode, request.sync_type) == (0, 0, 1)
    assert list(request.vel) == [5., -10000.]
    robot.stop_motion(2)
    assert robot._call.call_args.args[1].stop_mode == 2



def test_gripper_initialize_and_open_preserve_force_width_order():
    gripper = object.__new__(GripperToolNode)
    gripper.mode = 'real'
    gripper.initialized = False
    commands = []
    gripper._send_gripper_command = commands.append
    gripper.initialize()
    assert commands == ['i'] * 16
    assert gripper.commanded_force_n == 40.
    gripper.initialize()
    assert commands == ['i'] * 16  # 재검사 시 초기화 명령을 반복하지 않는다.
    commands.clear()
    gripper.gripper_busy = True
    gripper.set_grip(25., 10., opening=True)
    assert commands == ['250'] + ['d'] * 12
    assert (gripper.commanded_width_mm, gripper.commanded_force_n) == (25., 10.)



@pytest.mark.parametrize('success', [True, False])
def test_rg2_handles_its_own_service_response_without_robot(success):
    gripper = object.__new__(RG2Gripper)
    gripper.control_poll = Mock()
    future = Future()
    response = NS(success=success, message='driver error')
    future.set_result(response)
    client = NS(call_async=Mock(return_value=future), srv_name='/onrobot/sendCommand')

    if success:
        assert gripper._call(client, object()) is response

    else:
        with pytest.raises(RuntimeError, match='driver error'):
            gripper._call(client, object())

    assert not hasattr(gripper, '_robot')



def test_rg2_timeout_cancels_only_its_pending_request():
    gripper = object.__new__(RG2Gripper)
    gripper.control_poll = Mock()
    future = Future()
    client = NS(call_async=Mock(return_value=future), srv_name='/onrobot/sendCommand')

    with pytest.raises(TimeoutError):
        gripper._call(client, object(), timeout=0.)

    assert future.cancelled()



def test_rg2_control_interrupt_cancels_pending_request():
    gripper = object.__new__(RG2Gripper)
    gripper.control_poll = Mock(side_effect=[None, RuntimeError('STOP')])
    future = Future()
    client = NS(call_async=Mock(return_value=future), srv_name='/onrobot/sendCommand')

    with pytest.raises(RuntimeError, match='STOP'):
        gripper._call(client, object())

    assert future.cancelled()



def test_rg2_wrong_provider_blocks_command_before_send():
    gripper = object.__new__(RG2Gripper)
    gripper.mode = 'virtual'
    gripper.control_poll = Mock()
    gripper.get_node_names_and_namespaces = lambda: [('OnRobotRGControllerServer', '/dsr01')]
    gripper.get_service_names_and_types_by_node = lambda *_: [(gripper.GRIPPER_SERVICE, [])]
    gripper._call = Mock()

    with pytest.raises(RuntimeError, match='그리퍼 서비스 확인 실패'):
        gripper._send_gripper_command('0.0')

    gripper._call.assert_not_called()



@pytest.mark.parametrize('failed', ['robot', 'gripper'])
def test_prepare_failure_never_configures_or_moves_devices(failed):
    robot = NS(mode="real", check_ready=Mock(), initialize=Mock(), check_operability=Mock())
    gripper = NS(mode="real", check_ready=Mock(), initialize=Mock())
    (robot if failed == 'robot' else gripper).check_ready.side_effect = RuntimeError('not ready')
    sequence = NS(robot=robot, gripper=gripper, config=object(), sample=Mock())

    with pytest.raises(RuntimeError, match='not ready'):
        MainSequence.check_devices(NS(backend=sequence))

    robot.initialize.assert_not_called()
    gripper.initialize.assert_not_called()
    sequence.sample.assert_not_called()
