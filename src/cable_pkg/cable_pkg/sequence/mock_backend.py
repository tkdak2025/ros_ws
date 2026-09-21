"""HMI 시퀀스 시험을 위한 비동작 Backend를 제공한다."""

from .models import JobContext, SequenceResult


class MockSequenceBackend:
    """모든 장비 동작을 성공 처리하고 호출 이력만 보관한다."""

    RECIPES = {
        "SEQUENCE_TEST_USB": ["USB_P01", "USB_P02"],
        "SEQUENCE_TEST_LAN": ["LAN_L2", "LAN_L5"],
    }

    def __init__(self, *, start_in_work_area: bool = True) -> None:
        self.start_in_work_area = start_in_work_area
        self.calls: list[str] = []

    @property
    def recipe_ids(self) -> list[str]:
        return list(self.RECIPES)

    def _ok(self, name: str) -> SequenceResult:
        self.calls.append(name)
        return SequenceResult(True, f"{name.upper()}_OK", name)

    def check_robot_operability(self):
        return self._ok("robot_operability")

    def check_hmi_communication(self):
        return self._ok("hmi_communication")

    def validate_system_recipe(self):
        return self._ok("system_recipe")

    def validate_inspection_recipe(self, recipe_id):
        if recipe_id not in self.RECIPES:
            return SequenceResult(False, "RECIPE_NOT_FOUND", f"없는 시험 레시피: {recipe_id}")
        return self._ok("inspection_recipe")

    def enabled_point_ids(self, recipe_id):
        return list(self.RECIPES.get(recipe_id, []))

    def current_tcp(self):
        self.calls.append("current_tcp")
        return [500.0, 0.0, 500.0, 0.0, 90.0, 0.0]

    def tcp_is_in_work_area(self, tcp):
        self.calls.append("work_area_check")
        return self.start_in_work_area

    def relax_grip(self):
        return self._ok("grip_relaxation")

    def safe_escape(self, max_distance_mm):
        return self._ok(f"safe_escape_max_{max_distance_mm:g}_mm")

    def move_work_access_safe_pose(self):
        return self._ok("work_access_safe_pose")

    def move_home_pose(self):
        return self._ok("home_pose")

    def move_safe_route_home(self):
        return self._ok("safe_route_home")

    def request_pause_safe(self, context: JobContext):
        context.resume_point = context.current_sequence
        return self._ok("pause_safe")

    def resume_from(self, context: JobContext):
        return self._ok(f"resume_from_{context.resume_point or 'current'}")

    def request_motion_stop(self):
        return self._ok("motion_stop")
