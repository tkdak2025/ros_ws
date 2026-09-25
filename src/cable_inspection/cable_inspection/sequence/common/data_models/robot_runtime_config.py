"""포인트 레시피 밖에 있는 장비 통신·이동 공통값."""

from __future__ import annotations
from dataclasses import dataclass



@dataclass
class RobotRuntimeConfig:
    """포인트 레시피 밖에 있는 장비 통신·이동 공통값."""

    joint_speed_deg_s: float = 10.0  # 운영 실행 시 System Recipe 값으로 적용한다.
    joint_acc_deg_s2: float = 10.0
    linear_speed_mm_s: float = 10.0
    linear_acc_mm_s2: float = 10.0
    sample_period_s: float = 0.05
    motion_timeout_s: float = 60.0
    position_tolerance_mm: float = 0.5
    orientation_tolerance_deg: float = 1.0
    width_tolerance_mm: float = 2.5
    gripper_timeout_s: float = 20.0
    tcp_name: str = "GripperDA_v1"
    tool_name: str = "ToolWeight"
