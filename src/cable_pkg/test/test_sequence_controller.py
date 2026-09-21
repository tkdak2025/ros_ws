"""확정된 공통 시퀀스의 상태와 호출 순서를 검증한다."""

from cable_pkg.sequence.backend import UnimplementedPointExecutor
from cable_pkg.sequence.controller import SequenceController
from cable_pkg.sequence.models import SequenceResult, SystemState


class FakeBackend:
    """로봇을 움직이지 않고 호출 순서만 기록하는 테스트 Backend."""

    def __init__(self, inside=True):
        self.inside = inside
        self.calls = []

    def ok(self, name):
        self.calls.append(name)
        return SequenceResult(True, f"{name}_OK", name)

    def check_robot_operability(self): return self.ok("robot")
    def check_hmi_communication(self): return self.ok("hmi")
    def validate_system_recipe(self): return self.ok("system_recipe")
    def validate_inspection_recipe(self, recipe_id): return self.ok("inspection_recipe")
    def enabled_point_ids(self, recipe_id): return ["P01", "P02"]
    def current_tcp(self): self.calls.append("tcp"); return [1, 2, 3, 0, 0, 0]
    def tcp_is_in_work_area(self, tcp): self.calls.append("boundary"); return self.inside
    def relax_grip(self): return self.ok("relax")
    def safe_escape(self, distance): return self.ok(f"escape:{distance}")
    def move_work_access_safe_pose(self): return self.ok("work_access")
    def move_home_pose(self): return self.ok("home")
    def move_safe_route_home(self): return self.ok("safe_route_home")
    def request_pause_safe(self, context): return self.ok("pause_safe")
    def resume_from(self, context): return self.ok("resume")
    def request_motion_stop(self): return self.ok("stop")


def make_controller(backend):
    return SequenceController(backend, UnimplementedPointExecutor(), 30.0)


def test_start_runs_confirmed_initialize_and_home_route():
    backend = FakeBackend(inside=True)
    controller = make_controller(backend)

    result = controller.start("RECIPE_A")

    assert result.success
    assert controller.state == SystemState.RUNNING
    assert controller.context.current_sequence == "POINT_LOOP"
    assert backend.calls == [
        "robot", "hmi", "system_recipe", "inspection_recipe",
        "robot", "tcp", "boundary", "relax", "escape:30.0",
        "work_access", "home", "work_access",
    ]


def test_pause_preserves_context_and_stop_discards_it_without_home():
    backend = FakeBackend(inside=False)
    controller = make_controller(backend)
    assert controller.start("RECIPE_A").success
    context = controller.context

    assert controller.pause().success
    assert controller.state == SystemState.PAUSED
    assert controller.context is context

    assert controller.resume().success
    assert controller.state == SystemState.RUNNING
    assert controller.stop().success
    assert controller.state == SystemState.STOPPED
    assert controller.context is None
    assert backend.calls[-1] == "stop"


def test_unimplemented_point_sequence_fails_without_invented_motion():
    backend = FakeBackend(inside=False)
    controller = make_controller(backend)
    assert controller.start("RECIPE_A").success

    result = controller.execute_current_point()

    assert not result.success
    assert result.code == "POINT_SEQUENCE_NOT_IMPLEMENTED"
    assert controller.state == SystemState.ERROR
