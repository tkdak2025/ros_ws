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


def test_result_and_command_roundtrip():
    result = itf.PointResult(run_id=3, point_id='Place 2', cable_id='LAN-3',
                             result=itf.ResultCode.FAIL_DISPLACEMENT, displacement_mm=1.8)
    assert itf.decode_result(itf.encode_result(result)) == result

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
    assert itf.ResultCode.category(itf.ResultCode.MISSING) == 'MISSING'
    assert itf.ResultCode.category(itf.ResultCode.FAIL_DETACHED) == 'FAIL'
    assert itf.ResultCode.category(itf.ResultCode.FAIL_DISPLACEMENT) == 'FAIL'
