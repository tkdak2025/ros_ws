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
