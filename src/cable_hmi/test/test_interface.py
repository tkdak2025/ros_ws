"""interface.py 의 인코딩/디코딩 왕복과 전방 호환성 시험."""

from cable_hmi import interface as itf
import pytest
from std_msgs.msg import String


def test_status_roundtrip_keeps_nested_dataclasses():
    status = itf.SystemStatus(
        state=itf.State.RUNNING,
        tool=itf.ToolInfo(True, 'RG2_CABLE_JAW', 1.35, 'RG2_TCP_01', True),
        criteria=itf.Criteria(1.5, 5.0, 3, 25.0),
        available_recipes=['RECIPE_A', 'RECIPE_B'],
        current_point='Place 2',
        force_n=12.0,
    )
    decoded = itf.decode_status(itf.encode_status(status))
    assert decoded == status
    assert isinstance(decoded.tool, itf.ToolInfo)
    assert isinstance(decoded.criteria, itf.Criteria)


def test_result_roundtrip_keeps_message_fields():
    """결과는 cable_interfaces 메시지로 오간다. 메시지에 있는 필드만 왕복한다."""
    result = itf.PointResult(
        run_id=3, point_id='Place 2', result=itf.ResultCode.FAIL,
        reason_code=itf.ReasonCode.FAIL_GRIP_WIDTH, judgment_status='COMPLETED',
        sequence_status=itf.SequenceStatus.SUCCESS, displacement_mm=1.8,
        pull_width_mm=15.2, grip_failure_width_mm=16.0, width_delta_mm=-1.4,
        task=[1.0, 2.0, 3.0], joint=[0.0] * 6, db_saved=True)
    decoded = itf.decode_result(itf.encode_result(result))
    assert decoded == result
    assert isinstance(decoded.task, list)        # float64[] 는 array 로 오므로 list 로 바꾼다


def test_result_drops_fields_the_message_lacks():
    """cable_id 처럼 메시지에 없는 필드는 왕복에서 기본값으로 돌아온다."""
    result = itf.PointResult(run_id=3, point_id='Place 2', cable_id='LAN-3',
                             product_id='PANEL-A', action='재검사')
    decoded = itf.decode_result(itf.encode_result(result))
    assert decoded.point_id == 'Place 2'
    assert (decoded.cable_id, decoded.product_id, decoded.action) == ('', '', '')


def test_decode_result_rejects_wrong_message():
    with pytest.raises(ValueError):
        itf.decode_result(String(data='{}'))


def test_command_roundtrip():
    cmd = itf.Command(itf.CommandName.MOVE_TO_POINT, {'point_id': 'Place 2', 'reason': 'FAIL'})
    assert itf.decode_command(itf.encode_command(cmd)) == cmd


def test_decode_ignores_unknown_keys_and_fills_defaults():
    msg = String(data='{"state": "PAUSED", "new_field": 1, "tool": {"name": "X", "extra": 2}}')
    status = itf.decode_status(msg)
    assert status.state == itf.State.PAUSED
    assert status.tool.name == 'X'
    assert status.speed_percent == 0


@pytest.mark.parametrize('payload', ['not json', '[1, 2]', '{"tool": 5}'])
def test_decode_rejects_malformed_payload(payload):
    with pytest.raises(ValueError):
        itf.decode_status(String(data=payload))


def test_result_category():
    assert itf.ResultCode.category(itf.ResultCode.PASS) == 'PASS'
    assert itf.ResultCode.category('MISSING') == 'FAIL'
    assert itf.ResultCode.category(itf.ResultCode.FAIL_DETACHED) == 'FAIL'
    assert itf.ResultCode.category(itf.ResultCode.FAIL_DISPLACEMENT) == 'FAIL'


def test_product_results_exclude_missing_and_slip_is_fail():
    assert itf.ResultCode.PRODUCT_CODES == ('PASS', 'FAIL')
    assert itf.ReasonCode.result_of(itf.ReasonCode.FAIL_GRIP_SLIP) == 'FAIL'
    assert itf.ReasonCode.result_of('MISSING_GRIP_SLIP') == 'FAIL'
    assert itf.ReasonCode.result_of(itf.ReasonCode.INCOMPLETE_INVALID_DATA) == 'INCOMPLETE'


def test_system_error_is_not_a_product_result():
    """판정 노드의 SYSTEM_ERROR 는 제품 결과가 아니라 판정 미완으로 묶인다."""
    assert itf.ResultCode.SYSTEM_ERROR not in itf.ResultCode.PRODUCT_CODES
    assert itf.ResultCode.category(itf.ResultCode.SYSTEM_ERROR) == 'INCOMPLETE'
    assert itf.ReasonCode.result_of(itf.ReasonCode.SYSTEM_ERROR) == itf.ResultCode.INCOMPLETE


def test_grip_width_failure_is_fail():
    assert itf.ReasonCode.result_of(itf.ReasonCode.FAIL_GRIP_WIDTH) == 'FAIL'
    assert itf.ReasonCode.LABELS[itf.ReasonCode.FAIL_GRIP_WIDTH]
    assert itf.TerminationReason.label('INVALID_DATA') == '잘못된 판정 요청'


def test_status_keeps_main_sequence_fields():
    """검사 시퀀스(Main)가 보내는 제어 모드 필드를 버리지 않는다 (HMI_ROS2_연동 5장)."""
    msg = String(data='{"state": "IDLE", "run_state": "SYSTEM_READY", "control_mode": "hmi", '
                      '"control_connected": true, "selected_recipe_id": "rcp_BMW_LWR_01", '
                      '"job_summary": {}}')
    status = itf.decode_status(msg)
    assert status.control_mode == itf.ControlMode.HMI
    assert status.control_connected is True
    assert status.selected_recipe_id == 'rcp_BMW_LWR_01'


def test_control_mode_tells_main_from_monitor():
    assert itf.ControlMode.is_main(itf.ControlMode.HMI)
    assert itf.ControlMode.is_main(itf.ControlMode.TERMINAL)
    assert not itf.ControlMode.is_main(itf.ControlMode.NONE)      # 모니터·mock 노드
    assert itf.CommandName.STOP == 'STOP'


# ------------------------------------------------ 상태 분리 계약 (robot_status + work_status)
ROBOT = {'robot_connected': True, 'gripper_connected': True,
         'task': [548.1, 183.7, 319.9, 0.0, 180.0, 0.0],
         'joint': [17.9, 42.6, 12.4, -180.0, -125.0, -162.1],
         'force_norm_n': 4.4, 'gripper_width_mm': 26.2, 'robot_motion': 'STANDBY', 'servo': 'ON',
         'tool': {'name': 'ToolWeight', 'tcp': 'GripperDA_v1'}}
WORK = {'state': 'RUNNING', 'run_state': 'RUNNING', 'control_mode': 'hmi', 'run_id': 7,
        'available_recipes': ['rcp_BMW_LWR_01'], 'current_point': 'HARNESS_02',
        'criteria': {'required_pull_force_n': 15.0, 'max_displacement_mm': 5.0},
        'measurement': {'valid': True, 'pull_force_n': 11.2, 'pull_displacement_mm': 2.1}}


def test_merge_takes_work_fields_and_robot_values():
    s = itf.merge_split_status(ROBOT, WORK, robot_fresh=True, work_fresh=True)
    assert (s.state, s.run_id, s.current_point) == ('RUNNING', 7, 'HARNESS_02')
    assert s.criteria.required_pull_force_n == 15.0
    assert (s.force_n, s.displacement_mm) == (11.2, 2.1)    # Pull 정지 기준 힘 = measurement
    assert s.raw_force_n == 4.4                              # 원시 힘은 따로
    assert s.task[0] == 548.1 and len(s.joint) == 6
    assert (s.gripper_width_mm, s.robot_motion, s.servo) == (26.2, 'STANDBY', 'ON')
    assert s.tool.configured and s.tool.force_zero_done is None
    assert s.split_contract and s.work_fresh


def test_merge_keeps_unknown_as_none_not_zero():
    """문서: null·만료 값을 0 으로 바꾸지 않는다."""
    robot = dict(ROBOT, task=None, gripper_width_mm=None, force_norm_n=float('nan'))
    work = dict(WORK, measurement={'valid': False, 'pull_force_n': 11.2})
    s = itf.merge_split_status(robot, work, robot_fresh=True, work_fresh=True)
    assert s.task == [] and s.gripper_width_mm is None and s.raw_force_n is None
    assert s.force_n is None and s.displacement_mm is None   # valid=false 면 버린다


def test_merge_expires_stale_robot_status():
    s = itf.merge_split_status(ROBOT, WORK, robot_fresh=False, work_fresh=True)
    assert not s.robot_connected and not s.gripper_connected
    assert s.task == [] and s.gripper_width_mm is None
    assert s.state == 'RUNNING'                              # 작업상태는 그대로


def test_merge_without_work_is_not_linked():
    """작업상태를 아직 못 받았으면 화면은 연결 전으로 그린다(검사 시작을 열지 않는다)."""
    s = itf.merge_split_status(ROBOT, None, robot_fresh=True, work_fresh=False)
    assert not s.work_fresh and s.robot_connected


def test_old_status_is_not_split():
    s = itf.decode_status(String(data='{"state": "MONITOR", "force_n": 3.0}'))
    assert not s.split_contract and s.work_fresh and s.force_n == 3.0
