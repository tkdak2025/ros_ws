"""#06 검사 판정 규칙을 검증한다."""

from types import SimpleNamespace
from cable_inspection.sequence.inspection.node_inspection import InspectionJudgmentNode

from cable_inspection.sequence.inspection.data_models.inspection_result import InspectionResult
from cable_inspection.sequence.inspection.data_models.judgment_status import JudgmentStatus
from cable_inspection.sequence.inspection.data_models.pull_termination import PullTermination
from cable_inspection.sequence.common.data_models.sequence_status import SequenceStatus



def test_force_limit_with_small_displacement_is_pass():
    result = InspectionJudgmentNode.judge_request(SimpleNamespace(soft_width_mm=22.0, pull_width_mm=16.5, termination_reason=PullTermination.FORCE_LIMIT, peak_pull_force_n=15.2, pull_displacement_mm=4.9, required_force_n=15.0, normal_displacement_limit_mm=5.0))
    assert result.result == InspectionResult.PASS
    assert result.status == JudgmentStatus.COMPLETED



def test_force_limit_after_large_displacement_is_fail():
    result = InspectionJudgmentNode.judge_request(SimpleNamespace(soft_width_mm=22.0, pull_width_mm=16.5, termination_reason=PullTermination.FORCE_LIMIT, peak_pull_force_n=15.2, pull_displacement_mm=5.1, required_force_n=15.0, normal_displacement_limit_mm=5.0))
    assert result.result == InspectionResult.FAIL



def test_max_distance_without_slip_is_fail():
    result = InspectionJudgmentNode.judge_request(SimpleNamespace(soft_width_mm=22.0, pull_width_mm=16.5, termination_reason=PullTermination.MAX_DISTANCE, peak_pull_force_n=9.4, pull_displacement_mm=25.0, required_force_n=15.0, normal_displacement_limit_mm=5.0))
    assert result.result == InspectionResult.FAIL



def test_timeout_is_incomplete_without_product_result():
    result = InspectionJudgmentNode.judge_request(SimpleNamespace(soft_width_mm=22.0, pull_width_mm=16.5, termination_reason=PullTermination.TIMEOUT, peak_pull_force_n=10.0, pull_displacement_mm=8.0, required_force_n=15.0, normal_displacement_limit_mm=5.0))
    assert result.status == JudgmentStatus.ERROR
    assert result.sequence_status == SequenceStatus.INCOMPLETE
    assert result.result == InspectionResult.SYSTEM_ERROR




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
    assert InspectionJudgmentNode.judge_request(SimpleNamespace(soft_width_mm=22.0, pull_width_mm=16.5, termination_reason=termination, peak_pull_force_n=force, pull_displacement_mm=displacement, required_force_n=15.0, normal_displacement_limit_mm=5.0)).result == expected



def test_identifiable_invalid_request_returns_system_error(monkeypatch):
    import json
    from types import SimpleNamespace
    from cable_inspection.sequence.inspection import node_inspection as module
    published = []
    node = SimpleNamespace(tasks=__import__('queue').Queue(), submit=lambda request: None,
                           publish_result=published.append,
                           publish_log=lambda *args: None)
    module.InspectionJudgmentNode.receive_request(
        node, json.dumps({'run_id':1, 'point_id':'L2'}))
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
    from cable_inspection.sequence.inspection.data_models.judgment_request import JudgmentRequest
    from cable_inspection.sequence.inspection import node_inspection as module
    from rclpy.serialization import serialize_message, deserialize_message
    request = JudgmentRequest(
        run_id=21, recipe_id="LAN", recipe_version="1", point_id="LAN_L2",
        point_name="L2", connector_type="LAN", peak_pull_force_n=force,
        pull_displacement_mm=distance, termination_reason=termination,
        required_force_n=15.0, normal_displacement_limit_mm=5.0,
        entry_task=[1.0] * 6, entry_joint=[2.0] * 6,
        soft_width_mm=22.0, pull_width_mm=16.5,
    )
    judgment = InspectionJudgmentNode.judge_request(SimpleNamespace(soft_width_mm=22.0, pull_width_mm=16.5, termination_reason=termination, peak_pull_force_n=force, pull_displacement_mm=distance, required_force_n=15.0, normal_displacement_limit_mm=5.0))
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
    result = InspectionJudgmentNode.judge_request(SimpleNamespace(termination_reason=PullTermination.FORCE_LIMIT, peak_pull_force_n=17.0, pull_displacement_mm=4.0, required_force_n=15.0, soft_width_mm=22.0, pull_width_mm=width, normal_displacement_limit_mm=5.0))
    assert result.result == expected

    if width == 15.99:
        assert result.reason_code == "FAIL_GRIP_WIDTH"




def make_worker():
    import queue
    import threading
    from unittest.mock import Mock
    from cable_inspection.sequence.inspection.node_inspection import InspectionJudgmentNode
    node = object.__new__(InspectionJudgmentNode)
    node.tasks = queue.Queue()
    node._lock = threading.RLock()
    node._generation, node._run_id, node._closed = 0, None, False
    node._pending, node._results = set(), {}
    node.publish_result = Mock()
    node.publish_log = Mock()
    node.worker = threading.Thread(target=node._work, daemon=True)
    node.worker.start()
    return node



def request_for(run_id=1):
    from cable_inspection.sequence.inspection.data_models.judgment_request import JudgmentRequest

    return JudgmentRequest(run_id=run_id, recipe_id='LAN', recipe_version='1',
        point_id='P', point_name='P', connector_type='RJ45_LAN', peak_pull_force_n=16.,
        pull_displacement_mm=2., termination_reason=PullTermination.FORCE_LIMIT,
        required_force_n=15., normal_displacement_limit_mm=5.,
        entry_task=[0.] * 6, entry_joint=[0.] * 6, soft_width_mm=22., pull_width_mm=16.5)



def test_ros_request_and_direct_request_share_worker_and_result_store():
    import json
    from types import SimpleNamespace
    node = make_worker()

    try:
        node.receive_request(json.dumps(request_for().to_dict()))
        node.tasks.join()
        assert node.snapshot()['P']['result'] == 'PASS'
        node.submit(request_for())  # 중복 요청은 다시 판정·발행하지 않는다.
        node.tasks.join()
        assert node.publish_result.call_count == 1
        copied = node.snapshot()
        copied['P']['result'] = 'FAIL'
        assert node.snapshot()['P']['result'] == 'PASS'

    finally:
        node.close()
        node.close()  # 소유자가 반복 종료해도 Worker는 한 번만 종료한다.

    assert not node.worker.is_alive()



def test_old_inflight_judgment_cannot_overwrite_new_run_or_motion_error():
    import threading
    from dataclasses import replace
    node = make_worker()
    entered, release = threading.Event(), threading.Event()
    original = node.judge_request



    def delayed(request):
        if request.run_id == 1:
            entered.set()
            assert release.wait(2)

        return original(request)



    node.judge_request = delayed

    try:
        node.reset(1)
        node.submit(request_for(1))
        assert entered.wait(2)
        node.reset(2)
        node.submit(request_for(2))
        node.record_error(replace(request_for(2), termination_reason=PullTermination.MOTION_ERROR,
                                  error_reason='return failed'))
        release.set()
        node.tasks.join()
        assert node.snapshot()['P']['run_id'] == 2
        assert node.snapshot()['P']['result'] == 'SYSTEM_ERROR'
        assert node.publish_result.call_count == 1
        assert not node._pending

    finally:
        release.set()
        node.close()



def test_worker_exception_finishes_pending_as_system_error():
    node = make_worker()



    def fail(request):
        raise RuntimeError('judgment failed')



    node.judge_request = fail

    try:
        node.submit(request_for())
        node.tasks.join()
        assert node.snapshot()['P']['result'] == 'SYSTEM_ERROR'
        assert not node._pending

    finally:
        node.close()
