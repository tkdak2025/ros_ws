"""#06 검사 판정 규칙을 검증한다."""

from cable_pkg.sequence.inspection.seq_06_inspection_judgment_node import judge_pull
from cable_pkg.data_models.sequence_models import (
    InspectionResult, JudgmentStatus, PullTermination, SequenceStatus,
)


def test_force_limit_with_small_displacement_is_pass():
    result = judge_pull(soft_width_mm=22.0, pull_width_mm=16.5,
        termination=PullTermination.FORCE_LIMIT, peak_force_n=15.2,
        displacement_mm=4.9, required_force_n=15.0,
    )
    assert result.result == InspectionResult.PASS
    assert result.status == JudgmentStatus.COMPLETED


def test_force_limit_after_large_displacement_is_fail():
    result = judge_pull(soft_width_mm=22.0, pull_width_mm=16.5,
        termination=PullTermination.FORCE_LIMIT, peak_force_n=15.2,
        displacement_mm=5.1, required_force_n=15.0,
    )
    assert result.result == InspectionResult.FAIL


def test_max_distance_without_slip_is_fail():
    result = judge_pull(soft_width_mm=22.0, pull_width_mm=16.5,
        termination=PullTermination.MAX_DISTANCE, peak_force_n=9.4,
        displacement_mm=25.0, required_force_n=15.0,
    )
    assert result.result == InspectionResult.FAIL


def test_timeout_is_incomplete_without_product_result():
    result = judge_pull(soft_width_mm=22.0, pull_width_mm=16.5,
        termination=PullTermination.TIMEOUT, peak_force_n=10.0,
        displacement_mm=8.0, required_force_n=15.0,
    )
    assert result.status == JudgmentStatus.ERROR
    assert result.sequence_status == SequenceStatus.INCOMPLETE
    assert result.result == InspectionResult.SYSTEM_ERROR


def test_worker_publishes_queued_results_and_client_tracks_only_terminal_results(monkeypatch, capsys):
    """ROS 통신/로봇 없이 실제 Worker Thread와 요청·결과 직렬화를 검증한다."""
    import json
    import queue
    import threading
    from types import SimpleNamespace
    from cable_pkg.data_models.inspection_models import JudgmentRequest
    from cable_pkg.sequence.inspection import seq_06_inspection_judgment_node as module

    monkeypatch.setattr(module, "String", SimpleNamespace)
    published = queue.Queue()
    worker_node = SimpleNamespace(
        tasks=queue.Queue(),
        result_pub=SimpleNamespace(publish=published.put),
        _result_message=module.InspectionJudgmentNode._result_message,
        _publish_log=lambda *args: None,
    )
    request = JudgmentRequest(
        run_id=7, recipe_id="LAN", recipe_version="1", point_id="L2",
        point_name="LAN_L2", connector_type="RJ45_LAN", peak_pull_force_n=15.2,
        pull_displacement_mm=4.0,
        termination_reason=PullTermination.FORCE_LIMIT, required_force_n=15.0,
        normal_displacement_limit_mm=5.0,
        entry_task=[0.0] * 6, entry_joint=[0.0] * 6,
        soft_width_mm=22.0, pull_width_mm=16.5,
    )
    module.InspectionJudgmentNode._receive(
        worker_node, SimpleNamespace(data=json.dumps(request.to_dict())),
    )
    assert worker_node.tasks.qsize() == 1
    thread = threading.Thread(target=module.InspectionJudgmentNode._work,
                              args=(worker_node,), daemon=True)
    thread.start()
    try:
        message = published.get(timeout=2.0)
        result = dict(module.message_to_ordereddict(message))
        assert result["result"] == "PASS"
        assert result["reason_code"] == "PASS_FORCE_DISPLACEMENT_OK"
        assert result["required_pull_force_n"] == 15.0
        assert "grip_width_hard_mm" not in result
        assert "grip_width_change_mm" not in result
        client = SimpleNamespace(pending={(7, "L2")}, results={})
        for altered in ({**result, "run_id": 8},
                        {**result, "judgment_status": "PENDING"}):
            module.JudgmentClient._receive_result(
                client, module.InspectionResultMessage(**altered),
            )
            assert client.pending == {(7, "L2")}
        module.JudgmentClient._receive_result(client, message)
        assert not client.pending
        assert client.results["L2"] == result
    finally:
        worker_node.tasks.put(None)
        thread.join(timeout=2.0)
    assert not thread.is_alive()
    terminal = capsys.readouterr().out
    assert "[PASS] L2 | Run 7" in terminal
    assert "최대 Pull 힘: 15.2 N / 기준: 15.0 N" in terminal
    assert "실제 Pull 변위: 4.0 mm / 허용: 5.0 mm 이하" in terminal
    assert "종료 조건: FORCE_LIMIT" in terminal


import pytest


@pytest.mark.parametrize("termination,force,displacement,expected", [
    (PullTermination.FORCE_LIMIT, 15.0, 5.0, InspectionResult.PASS),
    (PullTermination.MAX_DISTANCE, 20.0, 4.0, InspectionResult.FAIL),
    (PullTermination.FORCE_LIMIT, 14.0, 4.0, InspectionResult.SYSTEM_ERROR),
    (PullTermination.MOTION_ERROR, 20.0, 4.0, InspectionResult.SYSTEM_ERROR),
    (PullTermination.ROBOT_ERROR, 20.0, 4.0, InspectionResult.SYSTEM_ERROR),
    (PullTermination.TOOL_ERROR, 20.0, 4.0, InspectionResult.SYSTEM_ERROR),
    (PullTermination.SAFETY_ERROR, 20.0, 4.0, InspectionResult.SYSTEM_ERROR),
    (PullTermination.INVALID_DATA, 20.0, 4.0, InspectionResult.SYSTEM_ERROR),
    (PullTermination.FORCE_LIMIT, float("nan"), 4.0, InspectionResult.SYSTEM_ERROR),
    (PullTermination.FORCE_LIMIT, 20.0, -1.0, InspectionResult.SYSTEM_ERROR),
    (PullTermination.FORCE_LIMIT, None, 4.0, InspectionResult.SYSTEM_ERROR),
])
def test_v03_policy(termination, force, displacement, expected):
    assert judge_pull(soft_width_mm=22.0, pull_width_mm=16.5, termination=termination, peak_force_n=force,
                      displacement_mm=displacement, required_force_n=15.0).result == expected


def test_identifiable_invalid_request_returns_system_error(monkeypatch):
    import json
    from types import SimpleNamespace
    from cable_pkg.sequence.inspection import seq_06_inspection_judgment_node as module
    monkeypatch.setattr(module, 'String', SimpleNamespace)
    published = []
    node = SimpleNamespace(tasks=__import__('queue').Queue(),
                           result_pub=SimpleNamespace(publish=published.append),
                           _publish_log=lambda *args: None)
    module.InspectionJudgmentNode._receive(
        node, SimpleNamespace(data=json.dumps({'run_id': 1, 'point_id': 'L2'})))
    result = dict(module.message_to_ordereddict(published[0]))
    assert result['result'] == 'SYSTEM_ERROR'
    assert result['termination_reason'] == 'INVALID_DATA'
    assert result['point_id'] == 'L2'


@pytest.mark.parametrize("termination,force,distance,expected", [
    (PullTermination.FORCE_LIMIT, 15.0, 5.0, "PASS"),
    (PullTermination.MAX_DISTANCE, 8.0, 25.0, "FAIL"),
    (PullTermination.TIMEOUT, 8.0, 3.0, "SYSTEM_ERROR"),
])
def test_custom_result_serialization(termination, force, distance, expected):
    from cable_pkg.data_models.inspection_models import JudgmentRequest
    from cable_pkg.sequence.inspection import seq_06_inspection_judgment_node as module
    from rclpy.serialization import serialize_message, deserialize_message
    request = JudgmentRequest(
        run_id=21, recipe_id="LAN", recipe_version="1", point_id="LAN_L2",
        point_name="L2", connector_type="LAN", peak_pull_force_n=force,
        pull_displacement_mm=distance, termination_reason=termination,
        required_force_n=15.0, normal_displacement_limit_mm=5.0,
        entry_task=[1.0] * 6, entry_joint=[2.0] * 6,
        soft_width_mm=22.0, pull_width_mm=16.5,
    )
    judgment = judge_pull(soft_width_mm=22.0, pull_width_mm=16.5, termination=termination, peak_force_n=force,
                          displacement_mm=distance, required_force_n=15.0)
    message = module.InspectionJudgmentNode._result_message(request, judgment)
    decoded = deserialize_message(serialize_message(message), module.InspectionResultMessage)
    assert decoded == message
    assert decoded.result == expected
    assert decoded.run_id == 21
    assert decoded.max_force_n == force
    assert decoded.displacement_mm == distance
    import json
    recorded = json.loads(json.dumps(module.message_to_ordereddict(decoded)))
    assert recorded['task'] == [1.0] * 6
    assert recorded['result'] == expected


@pytest.mark.parametrize("width,expected", [
    (15.99, InspectionResult.FAIL), (16.0, InspectionResult.PASS),
    (18.0, InspectionResult.PASS), (None, InspectionResult.SYSTEM_ERROR),
])
def test_pull_width_failure_threshold(width, expected):
    result = judge_pull(termination=PullTermination.FORCE_LIMIT, peak_force_n=17.0,
                       displacement_mm=4.0, required_force_n=15.0,
                       soft_width_mm=22.0, pull_width_mm=width)
    assert result.result == expected
    if width == 15.99:
        assert result.reason_code == "FAIL_GRIP_WIDTH"
