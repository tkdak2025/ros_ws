"""System Recipe 로딩. 실제 좌표는 config/system_recipe.json에서 관리한다."""

import json
import math
from pathlib import Path

from cable_pkg.recipe.inspection_recipe import RobotPose
from cable_pkg.safety.workspace_boundary import BoxBoundary


# 기능: 공통 Joint 이동 속도를 확인한다. 검사 단독 실행에서도 좌표 검증 없이 사용한다.
#     system: System Recipe JSON을 읽은 dict. joint_speed_deg_s 단위는 deg/s.
#
#     ------------------------------------------------------------
#     반환: MoveJ 명령에 적용할 Joint 속도(deg/s).
def joint_speed_from_system(system):
    value = system.get("joint_speed_deg_s")
    if (isinstance(value, bool) or not isinstance(value, (int, float))
            or not math.isfinite(value) or value <= 0):
        raise ValueError("System Recipe의 joint_speed_deg_s는 유한한 양수여야 합니다.")
    return float(value)



def load_system_recipe(path):
    """미입력 좌표는 거부한다. Tool/TCP를 등록하거나 Fault를 해제하지 않는다."""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    joint_speed_from_system(data)
    if data.get("coordinate_frame") != "BASE":
        raise ValueError("System Recipe는 BASE 기준이어야 합니다.")
    for name in ("home_pose", "work_Access_safe_pose"):
        raw = data.get(name)
        if not raw or raw.get("task") is None or raw.get("joint") is None:
            raise ValueError(f"System Recipe의 {name} 좌표를 입력하세요.")
        RobotPose(**raw).validate(name)
    for name in ("work_area",):
        if not data.get(name):
            raise ValueError(f"System Recipe의 {name} 경계를 입력하세요.")
        BoxBoundary(**data[name]).validate(name)
    if any(value != 0 for value in data["home_pose"]["joint"]):
        raise ValueError("Home 복귀의 home_pose.joint는 모두 0도여야 합니다.")
    direction = data.get("tool_approach_axis")
    # 현재 Home Return은 Safe Escape를 호출하지 않으므로 접근축은 필수가 아니다.
    if direction is not None and (not isinstance(direction, list) or len(direction) != 3
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
    return data
