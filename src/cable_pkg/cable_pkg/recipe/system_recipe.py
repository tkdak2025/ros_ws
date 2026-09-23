"""System Recipe 로딩. 실제 좌표는 config/system_recipe.json에서 관리한다."""

import json
import math
from pathlib import Path

from cable_pkg.recipe.inspection_recipe import RobotPose
from cable_pkg.safety.workspace_boundary import BoxBoundary


def load_system_recipe(path):
    """미입력 좌표는 거부한다. Tool/TCP를 등록하거나 Fault를 해제하지 않는다."""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if data.get("coordinate_frame") != "BASE":
        raise ValueError("System Recipe는 BASE 기준이어야 합니다.")
    for name in ("home_pose", "work_Access_safe_pose"):
        raw = data.get(name)
        if not raw or raw.get("task") is None or raw.get("joint") is None:
            raise ValueError(f"System Recipe의 {name} 좌표를 입력하세요.")
        RobotPose(**raw).validate(name)
    for name in ("work_area", "allowed_workspace"):
        if not data.get(name):
            raise ValueError(f"System Recipe의 {name} 경계를 입력하세요.")
        BoxBoundary(**data[name]).validate(name)
    if not data.get("safe_home_route"):
        raise ValueError("검증된 safe_home_route를 입력하세요. 마지막 Pose는 Home이어야 합니다.")
    for index, raw in enumerate(data["safe_home_route"]):
        RobotPose(**raw).validate(f"safe_home_route[{index}]")
    if data["safe_home_route"][-1] != data["home_pose"]:
        raise ValueError("safe_home_route의 마지막 Pose가 home_pose와 다릅니다.")
    direction = data.get("tool_approach_axis")
    if (not isinstance(direction, list) or len(direction) != 3
            or not all(isinstance(v, (int, float)) and math.isfinite(v) for v in direction)
            or math.hypot(*direction) == 0):
        raise ValueError("Tool 좌표계 접근축 tool_approach_axis를 입력하세요.")
    for key in ("max_escape_distance_mm", "escape_clearance_mm", "heartbeat_timeout_s",
                "communication_recovery_timeout_s", "judgment_timeout_s",
                "relax_width_mm", "relax_force_n"):
        value = data.get(key)
        if not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
            raise ValueError(f"System Recipe의 {key}는 양수여야 합니다.")
    if data["max_escape_distance_mm"] > 30:
        raise ValueError("Safe Escape 상한은 30 mm 이하여야 합니다.")
    allowed = BoxBoundary(**data["allowed_workspace"])
    for raw in [data["home_pose"], data["work_Access_safe_pose"], *data["safe_home_route"]]:
        if not allowed.contains_inside(raw["task"][:3], 0):
            raise ValueError("공통 Pose가 allowed_workspace 밖입니다.")
    if BoxBoundary(**data["work_area"]).contains_inside(data["work_Access_safe_pose"]["task"][:3], 0):
        raise ValueError("Work Access Safe Pose는 work_area 밖이어야 합니다.")
    return data
