"""Grip 시험의 로봇·그리퍼 ROS2 연결을 담당한다.

GripPullRobot(mode): 이동은 공통으로 처리하고 연결·설정·그리퍼만 모드별로 구분한다.
시험 순서는 grip_stability_test.py의 run_trial()에서 관리한다.
"""

import json
import math
import time
from pathlib import Path
from typing import Any

import rclpy
from dsr_msgs2.srv import (
    ConfigCreateTcp,
    ConfigCreateTool,
    GetCurrentTcp,
    GetCurrentTool,
    GetCurrentPosx,
    GetRobotSystem,
    GetToolForce,
    MoveJoint,
    MoveLine,
    MoveStop,
    SetCurrentTcp,
    SetCurrentTool,
)
from onrobot_rg_msgs.srv import SetCommand
from sensor_msgs.msg import JointState

from grip_stability_data import Pose, _validate_numbers


class GripPullRobot:
    """M0609와 RG2를 real 또는 virtual 모드로 연결한다."""

    SERVICE_ROOT = "/dsr01/dsr_controller2"
    GRIPPER_SERVICE = "/onrobot/sendCommand"

    SERVICE_TIMEOUT_S = 5.0
    MOVE_TIMEOUT_S = 60.0
    JOINT_VELOCITY_DEG_S = 30.0
    JOINT_ACCELERATION_DEG_S2 = 30.0
    LINEAR_ACCELERATION_MM_S2 = 30.0

    RG2_MAX_WIDTH_MM = 110.0
    RG2_MAX_FORCE_N = 40.0
    RG2_FORCE_STEP_N = 2.5

    CONFIG_DIR = Path(__file__).resolve().parents[2] / "config"

    def __init__(self, mode: str) -> None:
        if mode not in ("real", "virtual"):
            raise ValueError("mode는 real 또는 virtual이어야 합니다.")
        self.mode = mode
        self.connection_verified = False
        self.events = []
        self.run_metadata = {"mode": mode}
        if mode == "virtual":
            self._load_virtual_settings()

        self.node = rclpy.create_node(f"grip_stability_{mode}")
        root = self.SERVICE_ROOT
        self.system_client = self.node.create_client(
            GetRobotSystem, root + "/system/get_robot_system"
        )
        self.movej_client = self.node.create_client(
            MoveJoint, root + "/motion/move_joint"
        )
        self.movel_client = self.node.create_client(
            MoveLine, root + "/motion/move_line"
        )
        self.stop_client = self.node.create_client(
            MoveStop, root + "/motion/move_stop"
        )
        self.tcp_client = self.node.create_client(
            GetCurrentPosx, root + "/aux_control/get_current_posx"
        )
        self.force_client = self.node.create_client(
            GetToolForce, root + "/aux_control/get_tool_force"
        )
        self.gripper_client = self.node.create_client(
            SetCommand, self.GRIPPER_SERVICE
        )
        if mode == "virtual":
            gripper_topic = "/dsr01/gripper_joint_states"
        else:
            gripper_topic = "/onrobot_joint_states"
        self.node.create_subscription(
            JointState,
            gripper_topic,
            self._gripper_state_callback,
            10,
        )

        # RG2 driver는 시작 시 최대힘(40 N)으로 초기화된다. i/d 명령을 보낼 때
        # 이 값을 같이 추적해 Soft/Hard Grip force를 재현한다.
        self.commanded_force_n = self.RG2_MAX_FORCE_N
        self.commanded_width_mm = self.RG2_MAX_WIDTH_MM
        self.measured_width_mm: float | None = None
        self.gripper_busy = False
        self.grip_detected = False
        self.motion_target: list[float] | None = None
        self.motion_direction: list[float] | None = None
        self.motion_limit_mm = 0.0
        self.motion_kind: str | None = None
        self.motion_error: str | None = None


    def wait_for_services(self) -> None:
        """연결을 확인한 뒤 모드에 필요한 초기 설정만 적용한다."""
        clients = (
            self.system_client, self.movej_client, self.movel_client,
            self.stop_client, self.tcp_client, self.force_client, self.gripper_client,
        )
        for client in clients:
            if not client.wait_for_service(timeout_sec=self.SERVICE_TIMEOUT_S):
                raise RuntimeError(f"서비스를 찾지 못했습니다: {client.srv_name}")
        self._check_robot_mode()

        # 같은 서비스에 실물·가상 그리퍼가 동시에 연결되지 않았는지 확인한다.
        providers = []
        for name, namespace in self.node.get_node_names_and_namespaces():
            services = self.node.get_service_names_and_types_by_node(name, namespace)
            if any(service == self.GRIPPER_SERVICE for service, _ in services):
                providers.append(f"{namespace.rstrip('/')}/{name}")
        if self.mode == "virtual":
            expected = "/dsr01/gripper_virtual_node"
        else:
            expected = "/dsr01/OnRobotRGControllerServer"
        if providers != [expected]:
            raise RuntimeError(f"{self.mode} 그리퍼 서비스 확인 실패: {providers}")
        self.run_metadata["gripper_service_providers"] = providers

        if self.mode == "virtual":
            self._apply_virtual_settings()
        else:
            # 실물 RG2 힘을 40 N으로 맞춘 뒤 2.5 N 단위로 증감한다.
            for _ in range(round(self.RG2_MAX_FORCE_N / self.RG2_FORCE_STEP_N)):
                self._send_gripper_command("i")
            self.commanded_force_n = self.RG2_MAX_FORCE_N

    def _check_robot_mode(self) -> None:
        """선택한 모드와 실제 연결된 제어기의 모드가 일치해야 한다."""
        self.connection_verified = False
        response = self._call(self.system_client, GetRobotSystem.Request())
        expected = 1 if self.mode == "virtual" else 0
        if response.robot_system != expected:
            raise RuntimeError(f"{self.mode} 모드와 연결된 로봇 시스템이 다릅니다.")
        self.connection_verified = True

    def close(self) -> None:
        self.node.destroy_node()


    # ------------------------------------------------------------------
    # ROS 서비스 통신
    # ------------------------------------------------------------------

    def _call(self, client: Any, request: Any, timeout: float | None = None) -> Any:
        # 이동·그리퍼·정지 명령 전 모드를 다시 확인한다.
        # 시스템 조회 자체는 이 분기를 타지 않으므로 재귀 호출하지 않는다.
        if client in (self.movej_client, self.movel_client,
                      self.stop_client, self.gripper_client):
            self._check_robot_mode()
        limit = self.SERVICE_TIMEOUT_S if timeout is None else timeout
        future = client.call_async(request)
        rclpy.spin_until_future_complete(self.node, future, timeout_sec=limit)
        if not future.done():
            future.cancel()
            raise TimeoutError(f"서비스 응답 시간 초과: {client.srv_name}")
        error = future.exception()
        if error is not None:
            raise RuntimeError(f"서비스 호출 실패: {client.srv_name}: {error}") from error
        response = future.result()
        if response is None or not response.success:
            message = getattr(response, "message", "") if response else "응답 없음"
            raise RuntimeError(f"서비스 실패: {client.srv_name}: {message}")
        return response


    def _gripper_state_callback(self, message: JointState) -> None:
        if not message.position:
            return
        joint = float(message.position[0])
        theta1, theta3 = 1.41371, 0.76794
        length1, length3, dy = 0.108505, 0.055, -0.0144
        width_m = (
            math.cos(joint + theta3) * length3
            + dy
            + length1 * math.cos(theta1)
        ) * 2.0
        self.measured_width_mm = max(0.0, width_m * 1000.0)
        self.gripper_busy = bool(message.effort and abs(message.effort[0]) > 0.0)


    # ------------------------------------------------------------------
    # 그리퍼 명령: 모드에 따라 전송 형식만 다르다
    # ------------------------------------------------------------------

    def _send_gripper_command(self, command: str) -> None:
        request = SetCommand.Request()
        request.command = command
        self._call(self.gripper_client, request)


    def _set_gripper(self, setting: dict[str, float]) -> None:
        width = float(setting["width_mm"])
        force = float(setting["force_n"])
        if not 0.0 <= width <= self.RG2_MAX_WIDTH_MM:
            raise ValueError(f"RG2 width 범위 초과: {width} mm")
        if not 0.0 <= force <= self.RG2_MAX_FORCE_N:
            raise ValueError(f"RG2 force 범위 초과: {force} N")

        if self.mode == "virtual":
            self._set_virtual_gripper(width, force)
            return

        steps = round((force - self.commanded_force_n) / self.RG2_FORCE_STEP_N)
        quantized = self.commanded_force_n + steps * self.RG2_FORCE_STEP_N
        if not math.isclose(quantized, force, abs_tol=1e-6):
            raise ValueError("RG2 힘은 2.5 N 단위로 지정해야 합니다.")
        for _ in range(abs(steps)):
            self._send_gripper_command("i" if steps > 0 else "d")
        self.commanded_force_n = force

        # OnRobot service 숫자 명령은 0.1 mm 단위의 목표 폭이다.
        self._send_gripper_command(str(round(width * 10.0)))
        self.commanded_width_mm = width


    def _set_virtual_gripper(self, width: float, force: float) -> None:
        # 실물은 폭(0.1 mm), 가상 노드는 관절각(rad)을 받으므로 변환한다.
        cosine = (width / 2000.0 + 0.0144 - 0.108505 * math.cos(1.41371)) / 0.055
        angle = math.acos(max(-1.0, min(1.0, cosine))) - 0.76794
        angle = max(-0.558505, min(0.785398, angle))
        model_width = (math.cos(angle + 0.76794) * 0.055 - 0.0144
                       + 0.108505 * math.cos(1.41371)) * 2000.0
        self._send_gripper_command(str(angle))
        self.commanded_width_mm, self.commanded_force_n = width, force
        self.events.append({"action": "grip", "width_mm": width,
                            "commanded_force_n": force, "virtual_joint_rad": angle,
                            "model_width_mm": model_width,
                            "width_clamped": abs(model_width - width) > 0.1})
        print(f"가상 Grip: 요청 {width} mm / 모델 {model_width:.3f} mm "
              f"/ 힘 명령값 {force} N")


    # ------------------------------------------------------------------
    # 공통 로봇 이동: 실물·가상 동일
    # ------------------------------------------------------------------

    def _movej(self, joint: list[float]) -> None:
        """실물·가상 모두 목표 관절각으로 한 번 이동하고 완료 응답을 기다린다."""
        request = MoveJoint.Request()
        request.pos = [float(value) for value in joint]
        request.vel = self.JOINT_VELOCITY_DEG_S
        request.acc = self.JOINT_ACCELERATION_DEG_S2
        request.time = 0.0
        request.radius = 0.0
        request.mode = 0
        request.blend_type = 0
        request.sync_type = 0
        self._call(self.movej_client, request, self.MOVE_TIMEOUT_S)


    def _start_relative_movel(
        self, direction: list[float], distance_mm: float, speed_mm_s: float, kind: str
    ) -> None:
        start = self.get_tcp()
        self.motion_target = [
            start[index] + direction[index] * distance_mm for index in range(3)
        ] + start[3:]
        self.motion_direction = direction[:]
        self.motion_limit_mm = distance_mm
        self.motion_kind = kind
        self.motion_error = None

        request = MoveLine.Request()
        request.pos = [float(value) for value in self.motion_target]
        request.vel = [float(speed_mm_s), -10000.0]
        request.acc = [self.LINEAR_ACCELERATION_MM_S2, -10000.0]
        request.time = 0.0
        request.radius = 0.0
        request.ref = 0
        request.mode = 0
        request.blend_type = 0
        request.sync_type = 1  # 비동기: 시퀀스가 이동 중 힘과 TCP를 기록한다.
        self._call(self.movel_client, request)


    def _motion_active(self) -> bool:
        """실물·가상 모두 목표 위치까지 남은 거리가 0.5 mm 이하면 완료다."""
        if self.motion_target is None:
            return False
        current = self.get_tcp()
        remaining = math.dist(current[:3], self.motion_target[:3])
        if remaining <= 0.5:
            self.motion_kind = None
            return False
        return True


    def _stop_motion(self) -> None:
        if self.motion_kind is None:
            return
        request = MoveStop.Request()
        request.stop_mode = 2  # DR_SSTO: 시험 중 정상 제한 도달 시 Soft Stop
        try:
            self._call(self.stop_client, request, timeout=2.0)
        finally:
            self.motion_kind = None


    # ------------------------------------------------------------------
    # 시험 시퀀스가 사용하는 동작
    # ------------------------------------------------------------------

    def move_ready(self, pose: Pose) -> None:
        if pose.joint is None:
            raise ValueError("ready_pose.joint가 필요합니다.")
        self._movej(pose.joint)


    def move_entry(self, pose: Pose) -> None:
        if pose.joint is None:
            raise ValueError("entry_pose.joint가 필요합니다.")
        self._movej(pose.joint)


    def start_soft_grip(self, setting: dict[str, float]) -> None:
        """Soft Grip 명령을 전송하고 물리 동작은 비동기로 계속 진행시킨다."""
        self._set_gripper(setting)


    def open_soft_grip(self, setting: dict[str, float]) -> None:
        """복귀 시 기존 파지력은 건드리지 않고 Soft Open 폭만 명령한다.

        힘 증감 i/d 명령은 현재 폭 목표도 다시 전송한다. Hard Grip 직후 힘부터
        낮추면 기존 Close 목표가 반복되어 떨릴 수 있으므로 복귀에서는 폭만 연다.
        """
        width = float(setting["width_mm"])
        if not 0.0 <= width <= self.RG2_MAX_WIDTH_MM:
            raise ValueError(f"RG2 width 범위 초과: {width} mm")
        self._send_gripper_command(str(round(width * 10.0)))
        self.commanded_width_mm = width


    def wait_for_gripper_open_width(
        self, target_width_mm: float, timeout_s: float, tolerance_mm: float = 2.5
    ) -> float:
        """실측 폭이 Open 목표에 도달할 때까지 기다린다."""
        deadline = time.monotonic() + timeout_s
        while True:
            rclpy.spin_once(self.node, timeout_sec=0.05)
            if (
                self.measured_width_mm is not None
                and abs(self.measured_width_mm - target_width_mm) <= tolerance_mm
            ):
                return self.measured_width_mm
            if time.monotonic() >= deadline:
                measured = (
                    "수신 없음"
                    if self.measured_width_mm is None
                    else f"{self.measured_width_mm:.3f} mm"
                )
                raise TimeoutError(
                    "Soft Grip Open 시간 초과: "
                    f"목표={target_width_mm:.3f} mm, 실측={measured}"
                )


    def wait_for_gripper_width(
        self, motion_start_width_mm: float, timeout_s: float
    ) -> float:
        """실측 폭이 기준 이하가 될 때까지 기다리고 도달 폭을 반환한다."""
        deadline = time.monotonic() + timeout_s
        while True:
            # JointState 구독 콜백을 처리해 실측 폭과 Busy 상태를 갱신한다.
            rclpy.spin_once(self.node, timeout_sec=0.05)
            if (
                self.measured_width_mm is not None
                and self.measured_width_mm <= motion_start_width_mm
            ):
                print(
                    "Soft Grip 실측 폭 "
                    f"{self.measured_width_mm:.3f} mm: Entry MoveL 시작"
                )
                return self.measured_width_mm
            if time.monotonic() >= deadline:
                measured = (
                    "수신 없음"
                    if self.measured_width_mm is None
                    else f"{self.measured_width_mm:.3f} mm"
                )
                raise TimeoutError(
                    "Soft Grip 사전 닫힘 시간 초과: "
                    f"기준={motion_start_width_mm:.3f} mm, 실측={measured}"
                )


    def start_entry_motion(
        self, direction: list[float], depth_mm: float, speed_mm_s: float
    ) -> None:
        """현재 TCP에서 Entry 방향으로 비동기 직선 이동을 시작한다."""
        self._start_relative_movel(direction, depth_mm, speed_mm_s, "entry")


    def entry_is_active(self) -> bool:
        return self.motion_kind == "entry" and self._motion_active()


    def stop_entry(self) -> None:
        self._stop_motion()


    def soft_grip_entry_completed(self) -> bool:
        return self.motion_error is None


    def hard_grip(self, setting: dict[str, float]) -> bool:
        self._set_gripper(setting)
        return True


    def get_tcp(self) -> list[float]:
        request = GetCurrentPosx.Request()
        request.ref = 0
        response = self._call(self.tcp_client, request)
        if not response.task_pos_info:
            raise RuntimeError("현재 TCP 응답이 비어 있습니다.")
        values = [float(value) for value in response.task_pos_info[0].data]
        if len(values) < 6:
            raise RuntimeError("현재 TCP 응답 길이가 잘못되었습니다.")
        return values[:6]


    def get_tool_wrench(self, reference: int) -> list[float]:
        request = GetToolForce.Request()
        request.ref = reference
        response = self._call(self.force_client, request)
        return [float(value) for value in response.tool_force]


    def get_gripper_status(self) -> dict[str, Any]:
        return {
            "width": round(
                self.measured_width_mm
                if self.measured_width_mm is not None
                else self.commanded_width_mm,
                3,
            ),
            "state": "moving" if self.gripper_busy else "holding",
        }


    def start_pull(
        self, direction: list[float], speed_mm_s: float, limit_mm: float
    ) -> None:
        self._start_relative_movel(direction, limit_mm, speed_mm_s, "pull")


    def pull_is_active(self) -> bool:
        return self.motion_kind == "pull" and self._motion_active()


    def stop_pull(self) -> None:
        self._stop_motion()


    def safety_stop_reason(self) -> str | None:
        return self.motion_error


    def safe_abort(self) -> None:
        if not self.connection_verified:
            return
        request = MoveStop.Request()
        request.stop_mode = 1  # DR_QSTOP
        try:
            self._call(self.stop_client, request, timeout=2.0)
        except Exception as error:
            print(f"로봇 정지 서비스 실패: {error}")
        self.motion_kind = None


    # ------------------------------------------------------------------
    # 가상모드 TCP·Tool 설정
    # ------------------------------------------------------------------

    @staticmethod
    def load_settings(config_dir: Path) -> tuple[dict, dict]:
        """ROS 명령 전 설정값·단위·좌표 순서를 검사한다."""
        tcp = json.loads((config_dir / "tcp.json").read_text(encoding="utf-8"))
        tool = json.loads((config_dir / "tool.json").read_text(encoding="utf-8"))
        for label, data in (("TCP", tcp), ("Tool", tool)):
            if not isinstance(data, dict):
                raise ValueError(f"{label} 설정은 JSON 객체여야 합니다.")
            if not isinstance(data.get("name"), str) or not data["name"].strip():
                raise ValueError(f"{label} 이름이 필요합니다.")
        if (tcp.get("reference_frame") != "FLANGE"
                or tcp.get("axis_order") != ["X", "Y", "Z", "A", "B", "C"]
                or tcp.get("units") != {"translation": "mm", "rotation": "deg"}):
            raise ValueError("TCP는 FLANGE 기준 XYZABC, mm/deg 설정이어야 합니다.")
        if (tool.get("cog_axis_order") != ["X", "Y", "Z"]
                or tool.get("units", {}).get("weight") != "kg"
                or tool.get("units", {}).get("cog") != "mm"):
            raise ValueError("Tool은 질량 kg, 무게중심 XYZ mm 설정이어야 합니다.")
        _validate_numbers(tcp["pos"], 6, "tcp.pos")
        _validate_numbers([tool["weight"]], 1, "tool.weight")
        _validate_numbers(tool["cog"], 3, "tool.cog")
        if tool["weight"] < 0:
            raise ValueError("tool.weight는 0 이상이어야 합니다.")
        if tool["inertia"] is not None:
            _validate_numbers(tool["inertia"], 6, "tool.inertia")
        return tcp, tool


    def _load_virtual_settings(self) -> None:
        tcp, tool = self.load_settings(self.CONFIG_DIR)
        self.tcp_name, self.tool_name = tcp["name"], tool["name"]
        self.tcp_offset = [float(value) for value in tcp["pos"]]
        self.tool_weight = float(tool["weight"])
        self.tool_cog = [float(value) for value in tool["cog"]]
        self.tool_inertia = ([0.0] * 6 if tool["inertia"] is None
                             else [float(value) for value in tool["inertia"]])
        self.run_metadata = {
            "mode": "virtual", "tcp_name": self.tcp_name,
            "tcp_offset_mm_deg": self.tcp_offset,
            "tool_name": self.tool_name, "tool_weight_kg": self.tool_weight,
            "tool_cog_mm": self.tool_cog, "tool_inertia": self.tool_inertia,
            "config_snapshot": {"tcp": tcp, "tool": tool},
            "inertia_note": ("Unknown real inertia; zeros used for virtual motion check only"
                             if tool["inertia"] is None else "Loaded from config/tool.json"),
            "force_note": "Emulator wrench and commanded grip force; no physical grip validation",
            "events": self.events,
        }


    def _apply_virtual_settings(self) -> None:
        """가상 제어기에만 JSON의 TCP·Tool을 등록하고 활성화한다."""
        for path, service, values in (
            ("tcp/config_create_tcp", ConfigCreateTcp,
             {"name": self.tcp_name, "pos": self.tcp_offset}),
            ("tool/config_create_tool", ConfigCreateTool,
             {"name": self.tool_name, "weight": self.tool_weight,
              "cog": self.tool_cog, "inertia": self.tool_inertia}),
            ("tcp/set_current_tcp", SetCurrentTcp, {"name": self.tcp_name}),
            ("tool/set_current_tool", SetCurrentTool, {"name": self.tool_name}),
        ):
            self._check_robot_mode()
            client = self.node.create_client(service, self.SERVICE_ROOT + "/" + path)
            try:
                if not client.wait_for_service(timeout_sec=self.SERVICE_TIMEOUT_S):
                    raise RuntimeError(f"서비스를 찾지 못했습니다: {path}")
                self._call(client, service.Request(**values))
            finally:
                self.node.destroy_client(client)
        for path, service, expected in (
            ("tcp/get_current_tcp", GetCurrentTcp, self.tcp_name),
            ("tool/get_current_tool", GetCurrentTool, self.tool_name),
        ):
            client = self.node.create_client(service, self.SERVICE_ROOT + "/" + path)
            try:
                if not client.wait_for_service(timeout_sec=self.SERVICE_TIMEOUT_S):
                    raise RuntimeError(path)
                actual = self._call(client, service.Request()).info
                if actual != expected:
                    raise RuntimeError(f"{path}: {actual} != {expected}")
            finally:
                self.node.destroy_client(client)
        print(f"가상 설정 적용: TCP={self.tcp_name} {self.tcp_offset}, "
              f"Tool={self.tool_name} {self.tool_weight} kg, CoG={self.tool_cog}")
