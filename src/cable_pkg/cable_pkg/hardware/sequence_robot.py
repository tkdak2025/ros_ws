"""공통 시퀀스의 장비 동작. Inspection과 동일한 HardwareRobot을 사용한다."""

import math
from pathlib import Path

from dsr_msgs2.srv import GetRobotState, GetCurrentPosj, GetCurrentTcp, GetCurrentTool

from cable_pkg.data_models.sequence_models import SequenceResult
from cable_pkg.hardware.inspection_robot import HardwareRobot, RobotRuntimeConfig
from cable_pkg.recipe.inspection_recipe import OperatingInspectionRecipe, RobotPose
from cable_pkg.recipe.system_recipe import load_system_recipe
from cable_pkg.safety.workspace_boundary import BoxBoundary


class SequenceRobot(HardwareRobot):
    """서비스 조회/이동만 담당한다. 순회, Pause, Job 종료 정책은 Main Work에 있다."""

    def __init__(self, system_path, recipe_paths, stream):
        super().__init__(RobotRuntimeConfig(), stream)
        self.system_path = Path(system_path)
        self.recipe_paths = {key: Path(value) for key, value in recipe_paths.items()}
        self.system = None
        self.recipe = None
        self.connected = False
        self.hmi_available = lambda: False
        self.control_poll = lambda: None
        self.state_client = self.node.create_client(GetRobotState, self.SERVICE_ROOT + "/system/get_robot_state")
        self.joint_client = self.node.create_client(GetCurrentPosj, self.SERVICE_ROOT + "/aux_control/get_current_posj")

    @staticmethod
    def ok(code, data=None):
        return SequenceResult(True, code, code, data or {})

    def _call(self, client, request, timeout=None):
        # 한 Worker만 장비 노드를 spin한다. STOP은 이 서비스 대기 중에도 감지한다.
        if client is not self.stop_client:
            self.control_poll()
        return super()._call(client, request, timeout)

    def check_robot_operability(self):
        if not self.state_client.wait_for_service(timeout_sec=self.SERVICE_TIMEOUT_S):
            raise RuntimeError("Robot State 서비스를 찾을 수 없습니다.")
        state = self._call(self.state_client, GetRobotState.Request()).robot_state
        if state != 1:  # 드라이버 정의: 1=STANDBY. Safety Stop 등을 자동 해제하지 않는다.
            raise RuntimeError(f"Robot이 STANDBY가 아닙니다: state={state}")
        if not self.connected:
            self.connect()  # 최초 연결 시에만 그리퍼 힘 동기화
        else:
            self._check_robot_mode()
            self.sample()
            # 재개/Home 호출 시에도 활성 Tool/TCP를 읽기만 하며 설정을 덮어쓰지 않는다.
            for suffix, service, expected in (
                ("tcp/get_current_tcp", GetCurrentTcp, self.config.tcp_name),
                ("tool/get_current_tool", GetCurrentTool, self.config.tool_name),
            ):
                client = self.node.create_client(service, self.SERVICE_ROOT + "/" + suffix)
                try:
                    if self._call(client, service.Request()).info != expected:
                        raise RuntimeError(f"활성 Tool/TCP 설정 불일치: {expected}")
                finally:
                    self.node.destroy_client(client)
        joints = self._call(self.joint_client, GetCurrentPosj.Request()).pos
        if len(joints) != 6 or not all(math.isfinite(v) for v in joints):
            raise RuntimeError("현재 관절값이 유효하지 않습니다.")
        self.connected = True
        return self.ok("ROBOT_OPERABLE")

    def check_hmi_communication(self):
        if not self.hmi_available():
            return SequenceResult(False, "HMI_COMM_LOST", "HMI Heartbeat가 없습니다.")
        return self.ok("HMI_CONNECTED")

    def validate_system_recipe(self):
        self.system = load_system_recipe(self.system_path)
        return self.ok("SYSTEM_RECIPE_VALID")

    def validate_inspection_recipe(self, recipe_id):
        if recipe_id not in self.recipe_paths:
            raise ValueError(f"등록되지 않은 Recipe: {recipe_id}")
        self.recipe = OperatingInspectionRecipe.load_json(self.recipe_paths[recipe_id])
        if self.recipe.recipe_id != recipe_id:
            raise ValueError("선택한 Recipe ID와 파일의 ID가 다릅니다.")
        for point in self.recipe.points.values():
            if point.enabled:
                self._check_target(point.ready_pose.task)
                self._check_target(point.entry_pose.task)
        return self.ok("INSPECTION_RECIPE_VALID")

    def enabled_point_ids(self, recipe_id):
        return [key for key in self.recipe.execution_order if self.recipe.points[key].enabled]

    def current_tcp(self):
        return self.get_tcp()

    def tcp_is_in_work_area(self, tcp):
        return BoxBoundary(**self.system["work_area"]).contains_inside(tcp[:3], 0)

    def _check_target(self, task):
        if self.system is not None:
            if not BoxBoundary(**self.system["allowed_workspace"]).contains_inside(task[:3], 0):
                raise ValueError(f"목표 TCP가 allowed_workspace 밖입니다: {task[:3]}")

    def move_joint(self, pose, allow_incomplete=False):
        self._check_target(pose.task)
        self.control_poll()
        return super().move_joint(pose, allow_incomplete)

    def move_linear(self, target, entry_guard=False, measurement_kind=None):
        self._check_target(target)
        self.control_poll()
        return super().move_linear(target, entry_guard, measurement_kind)

    def relax_grip(self):
        self.grip(self.system["relax_width_mm"], self.system["relax_force_n"], opening=True)
        self.wait_gripper_idle()
        return self.ok("GRIP_RELAXED")

    def safe_escape(self, max_distance_mm):
        # 현재 TCP의 ZYZ 자세로 Tool 접근축을 BASE로 회전한 뒤 반대로 빠진다.
        tcp = self.get_tcp()
        direction = reverse_tool_axis(tcp[3:], self.system["tool_approach_axis"])
        box = BoxBoundary(**self.system["work_area"])
        exits = []
        for position, component, low, high in zip(tcp[:3], direction,
                (box.x_min_mm, box.y_min_mm, box.z_min_mm),
                (box.x_max_mm, box.y_max_mm, box.z_max_mm)):
            if abs(component) > 1e-9:
                exits.append(((high if component > 0 else low) - position) / component)
        distance = min(value for value in exits if value >= 0) + self.system["escape_clearance_mm"]
        if distance > min(30.0, max_distance_mm):
            raise RuntimeError("Safe Escape 상한 내에서 작업영역을 벗어날 수 없습니다.")
        target = [tcp[i] + direction[i] * distance for i in range(3)] + tcp[3:]
        self.move_linear(target)
        if self.tcp_is_in_work_area(self.get_tcp()):
            raise RuntimeError("Safe Escape 후에도 TCP가 작업영역 내부입니다.")
        return self.ok("SAFE_ESCAPE_DONE", {"distance_mm": distance})

    def move_work_access_safe_pose(self):
        self.move_joint(RobotPose(**self.system["work_Access_safe_pose"]))
        return self.ok("WORK_ACCESS_REACHED")

    def move_home_pose(self):
        self.move_joint(RobotPose(**self.system["home_pose"]))
        return self.ok("HOME_REACHED")

    def move_safe_route_home(self):
        for raw in self.system["safe_home_route"]:
            self.move_joint(RobotPose(**raw))
        return self.ok("HOME_REACHED")

    def request_motion_stop(self):
        # STOP 자체는 control_poll로 다시 차단하지 않는다.
        poll, self.control_poll = self.control_poll, lambda: None
        try:
            self.controlled_stop()
            self._wait_idle()
        finally:
            self.control_poll = poll
        return self.ok("MOTION_STOPPED")


def reverse_tool_axis(abc, tool_axis):
    """ZYZ: Rz(A) Ry(B) Rz(C). 반환값은 BASE 기준 단위 이탈벡터다."""
    a, b, c = map(math.radians, abc)
    x, y, z = tool_axis
    x, y = math.cos(c)*x - math.sin(c)*y, math.sin(c)*x + math.cos(c)*y
    x, z = math.cos(b)*x + math.sin(b)*z, -math.sin(b)*x + math.cos(b)*z
    x, y = math.cos(a)*x - math.sin(a)*y, math.sin(a)*x + math.cos(a)*y
    length = math.hypot(x, y, z)
    return [-x / length, -y / length, -z / length]
