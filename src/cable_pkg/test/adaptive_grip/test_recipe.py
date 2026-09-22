"""V01 필수 정보, 벡터, 탐색 범위 및 JSON 입력 검증."""

from dataclasses import asdict, replace
import json

import pytest

from cable_pkg.test_module.adaptive_grip.sequence import AdaptiveGripPoint, AdaptiveGripSequence


def test_valid_recipe_preserves_input_and_normalizes_axis(point):
    before = asdict(point)
    result = AdaptiveGripSequence(point).validate_recipe()
    assert result.passed
    assert result.data == {**before, "connector_axis": [0, 0.6, 0.8]}
    assert asdict(point) == before


@pytest.mark.parametrize("field", ["recipe_id", "point_id", "point_name"])
@pytest.mark.parametrize("value", ["", " \t\n"])
def test_empty_identifiers_fail(point, field, value):
    with pytest.raises(ValueError, match=field):
        replace(point, **{field: value}).validate()


@pytest.mark.parametrize("field,size", [
    ("nominal_task", 6), ("connector_axis", 3),
    ("ready_joint", 6), ("entry_task", 6),
])
@pytest.mark.parametrize("case", ["short", "long", "nan", "inf", "negative_inf"])
def test_invalid_vectors_fail(point, field, size, case):
    if case in ("short", "long"):
        values = [1.0] * (size + (-1 if case == "short" else 1))
    else:
        values = [1.0] * size
        values[-1] = {"nan": float("nan"), "inf": float("inf"),
                      "negative_inf": -float("inf")}[case]
    with pytest.raises(ValueError, match=field):
        replace(point, **{field: values}).validate()


def test_zero_axis_fails(point):
    with pytest.raises(ValueError, match="connector_axis"):
        replace(point, connector_axis=[0, 0, 0]).validate()


@pytest.mark.parametrize("field,value", [
    ("depth_offset_mm", float("nan")), ("depth_offset_mm", float("inf")),
    ("depth_offset_mm", -float("inf")), ("search_range_mm", float("nan")),
    ("search_range_mm", float("inf")), ("search_range_mm", -float("inf")),
    ("search_range_mm", 0), ("search_range_mm", -1),
])
def test_invalid_scalar_fails(point, field, value):
    with pytest.raises(ValueError, match=field):
        replace(point, **{field: value}).validate()


@pytest.mark.parametrize("offset", [-2.0, 0.0, 2.0])
def test_finite_signed_depth_offset_is_allowed(point, offset):
    replace(point, depth_offset_mm=offset).validate()


def test_json_load_is_repeatable(point, tmp_path):
    path = tmp_path / "point.json"
    path.write_text(json.dumps(asdict(point), ensure_ascii=False), encoding="utf-8")
    assert AdaptiveGripPoint.load_json(path) == point
    assert AdaptiveGripPoint.load_json(path) == point


@pytest.mark.parametrize("payload", ["[]", "null", "123", '"text"'])
def test_json_requires_object(tmp_path, payload):
    path = tmp_path / "point.json"
    path.write_text(payload, encoding="utf-8")
    with pytest.raises(ValueError, match="JSON 객체"):
        AdaptiveGripPoint.load_json(path)


def test_json_load_validates_contents(point, tmp_path):
    path = tmp_path / "point.json"
    path.write_text(json.dumps({**asdict(point), "search_range_mm": 0}), encoding="utf-8")
    with pytest.raises(ValueError, match="search_range_mm"):
        AdaptiveGripPoint.load_json(path)
