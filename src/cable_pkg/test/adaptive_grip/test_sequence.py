"""V01~V09 순서, Gate 중단 및 실행 기록 검증."""

from dataclasses import asdict, replace
from datetime import datetime
import json
from unittest.mock import Mock

import pytest

from cable_pkg.test_module.adaptive_grip.sequence import (
    AdaptiveGripSequence, StageResult, ValidationStage,
)


# 구현의 STAGES를 그대로 기대값으로 쓰지 않고 계획서 순서를 고정한다.
STEPS = [
    (ValidationStage.RECIPE, "validate_recipe"),
    (ValidationStage.READY_ENTRY, "validate_ready_entry"),
    (ValidationStage.DEPTH_COMPENSATION, "depth_compensation"),
    (ValidationStage.SOFT_GRIP, "soft_grip"),
    (ValidationStage.MICRO_WIGGLE, "micro_wiggle"),
    (ValidationStage.FINE_ALIGNMENT, "fine_alignment"),
    (ValidationStage.HARD_GRIP, "hard_grip"),
    (ValidationStage.GRIP_STABILITY, "check_grip_stability"),
    (ValidationStage.GRIP_PULL_LOGGING, "grip_pull_test"),
]


def install_handlers(sequence, monkeypatch, fail_at=None, raise_at=None):
    """단계의 물리 동작 대신 통과/실패 응답과 호출 이력을 제공한다."""
    calls = []

    def handler(stage):
        calls.append(stage)
        if stage == raise_at:
            raise OSError("센서 통신 오류")
        return StageResult(stage, stage != fail_at, "테스트 Gate", {"simulated": True})

    for stage, name in STEPS:
        monkeypatch.setattr(sequence, name, Mock(side_effect=lambda s=stage: handler(s)))
    return calls


@pytest.mark.parametrize("index", range(9), ids=[s.value for s, _ in STEPS])
def test_stops_exactly_at_requested_stage(point, monkeypatch, index):
    sequence = AdaptiveGripSequence(point)
    calls = install_handlers(sequence, monkeypatch)
    results = sequence.run(STEPS[index][0])
    expected = [s for s, _ in STEPS[:index + 1]]
    assert calls == expected
    assert [r.stage for r in results] == expected
    assert all(r.passed for r in results)
    assert results == sequence.results
    assert results is not sequence.results


@pytest.mark.parametrize("index", range(9), ids=[s.value for s, _ in STEPS])
def test_gate_failure_records_failure_and_blocks_later_stages(point, monkeypatch, index):
    sequence = AdaptiveGripSequence(point)
    failed = STEPS[index][0]
    calls = install_handlers(sequence, monkeypatch, fail_at=failed)
    with pytest.raises(RuntimeError, match=f"{failed.value} Gate 실패"):
        sequence.run(ValidationStage.GRIP_PULL_LOGGING)
    expected = [s for s, _ in STEPS[:index + 1]]
    assert calls == expected
    assert [r.stage for r in sequence.results] == expected
    assert all(r.passed for r in sequence.results[:-1])
    assert not sequence.results[-1].passed


def test_invalid_recipe_blocks_ready_entry(point, monkeypatch):
    sequence = AdaptiveGripSequence(replace(point, point_id=""))
    motion = Mock(side_effect=AssertionError("V02 호출 금지"))
    monkeypatch.setattr(sequence, "validate_ready_entry", motion)
    with pytest.raises(RuntimeError, match="V01_RECIPE Gate 실패"):
        sequence.run(ValidationStage.GRIP_PULL_LOGGING)
    motion.assert_not_called()
    assert len(sequence.results) == 1
    assert not sequence.results[0].passed


def test_stage_exception_blocks_later_stages(point, monkeypatch):
    sequence = AdaptiveGripSequence(point)
    calls = install_handlers(sequence, monkeypatch, raise_at=ValidationStage.DEPTH_COMPENSATION)
    with pytest.raises(OSError, match="센서 통신 오류"):
        sequence.run(ValidationStage.GRIP_PULL_LOGGING)
    assert calls == [s for s, _ in STEPS[:3]]
    assert [r.stage for r in sequence.results] == [s for s, _ in STEPS[:2]]


def test_rerun_clears_previous_results_without_changing_returned_list(point, monkeypatch):
    sequence = AdaptiveGripSequence(point)
    install_handlers(sequence, monkeypatch)
    first = sequence.run(ValidationStage.GRIP_PULL_LOGGING)
    second = sequence.run(ValidationStage.RECIPE)
    assert len(first) == 9
    assert [r.stage for r in second] == [ValidationStage.RECIPE]
    assert sequence.results == second


@pytest.mark.parametrize("stage,name", STEPS[1:], ids=[s.value for s, _ in STEPS[1:]])
def test_unimplemented_physical_stages_are_explicit(point, stage, name):
    with pytest.raises(NotImplementedError, match=stage.value[:3]):
        getattr(AdaptiveGripSequence(point), name)()


def test_real_sequence_records_v01_then_stops_at_unimplemented_v02(point):
    sequence = AdaptiveGripSequence(point)
    with pytest.raises(NotImplementedError, match="V02"):
        sequence.run(ValidationStage.GRIP_PULL_LOGGING)
    assert [r.stage for r in sequence.results] == [ValidationStage.RECIPE]
    assert sequence.results[0].passed


@pytest.mark.parametrize("failed", [False, True])
def test_saved_results_include_metadata_and_gate_history(point, monkeypatch, tmp_path, failed):
    sequence = AdaptiveGripSequence(point)
    install_handlers(sequence, monkeypatch,
                     fail_at=ValidationStage.GRIP_STABILITY if failed else None)
    if failed:
        with pytest.raises(RuntimeError):
            sequence.run(ValidationStage.GRIP_PULL_LOGGING)
    else:
        sequence.run(ValidationStage.GRIP_PULL_LOGGING)
    path = tmp_path / "adaptive_grip" / "trial.json"
    sequence.save_results(path)
    saved = json.loads(path.read_text(encoding="utf-8"))
    assert saved["schema_version"] == 1
    assert saved["data_type"] == "adaptive_grip_validation"
    assert datetime.fromisoformat(saved["created_at"]).tzinfo is not None
    assert saved["point"] == asdict(point)
    assert saved["results"] == [
        {**asdict(r), "stage": r.stage.value} for r in sequence.results
    ]
    assert saved["results"][-1]["passed"] is (not failed)
