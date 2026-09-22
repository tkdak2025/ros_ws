"""ROS 설치 없이 소스의 Adaptive Grip을 테스트하기 위한 fixture."""

from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from cable_pkg.test_module.adaptive_grip.sequence import AdaptiveGripPoint  # noqa: E402


@pytest.fixture
def point():
    """실물 이동에 사용하지 않는 단위테스트 전용 입력."""
    return AdaptiveGripPoint(
        recipe_id="UNIT_TEST", point_id="P01", point_name="테스트 포인트",
        nominal_task=[100, 200, 300, 0, 0, 0],
        connector_axis=[0, 3, 4], ready_joint=[0] * 6,
        entry_task=[100, 200, 280, 0, 0, 0],
        depth_offset_mm=2.0, search_range_mm=10.0,
    )
