"""Grip 시험의 로봇·그리퍼 ROS2 연결을 담당한다.

GripPullRobot(mode): 이동은 공통으로 처리하고 연결·설정·그리퍼만 모드별로 구분한다.
검사 실행 순서는 main_node.py에서 관리한다. 서비스 연결과 측정 구현을 이 파일에 모았다.
"""

import json
import math
import time
import rclpy
import os
import copy
from pathlib import Path
from typing import Any, Protocol
from ament_index_python.packages import get_package_share_directory
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
    CheckMotion,
    GetRobotState,
    GetCurrentPosj,
)
from onrobot_rg_msgs.srv import SetCommand
from sensor_msgs.msg import JointState
from dataclasses import dataclass
from datetime import datetime
from cable_inspection.data_models.models import SequenceResult
from cable_inspection.recipe.inspection_recipe import OperatingInspectionRecipe, RobotPose, load_system_recipe
from cable_inspection.safety.workspace_boundary import BoxBoundary


class Pose(Protocol):
    joint: list[float] | None

def _validate_numbers(values, length, name):
    if len(values) != length or not all(isinstance(v, (int, float)) and math.isfinite(v) for v in values):
        raise ValueError(f"{name}: {length}개의 유효한 숫자가 필요합니다.")


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

    CONFIG_DIR = Path(get_package_share_directory("cable_inspection")) / "config"

    def __init__(self, mode: str) -> None:
        if mode not in ("real", "virtual"):
            raise ValueError("mode는 real 또는 virtual이어야 합니다.")
        self.mode = mode
        self.connection_verified = False
        self.events = []
        self.run_metadata = {"mode": mode}
        if mode == "virtual":
            self._load_virtual_settings()

        self.node = rclpy.create_node(f"cccis_inspection_{mode}")
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
        deadline = time.monotonic() + limit
        while not future.done() and time.monotonic() < deadline:
            # 전체 Job 실행 시에만 STOP/통신 만료 감시를 주입한다.
            poll = getattr(self, "control_poll", None)
            if poll is not None:
                try:
                    poll()
                except Exception:
                    future.cancel()
                    raise
            rclpy.spin_once(self.node, timeout_sec=0.02)
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
    entry_force_limit_n: float = 5.0
    entry_timeout_s: float = 10.0
    pull_force_limit_n: float = 15.0
    pull_timeout_s: float = 10.0

# 이 파일은 '어떻게 움직이고 측정하는가'를 담당한다. 단계 순서는 sequence/에 있다.
# 공통 DSR/RG2 서비스 구현은 hardware/dsr_rg2_base.py에 있다.
#   _call(): 서비스 전송/응답 확인, 이동·그리퍼·정지 명령 전 실물 모드 재확인
#   _set_gripper(): RG2 힘과 폭 명령 전송
#   get_tcp()/get_tool_wrench(): BASE 기준 실측값 조회
#   safe_abort(): 연결 확인된 로봇에 Quick Stop 요청(그리퍼 해제는 하지 않음)
# 일반 오류는 운영 실행점까지 전달되어 safe_abort()와 결과 저장으로 이어진다.

class HardwareRobot(GripPullRobot):
    # ------------------------------------------------------------------
    # 1. ROS 클라이언트 생성과 실물 연결 확인
    # ------------------------------------------------------------------
    def __init__(self, config, stream, mode="real"):
        super().__init__(mode=mode)
        self.config, self.stream = config, stream
        self.phase = "PREFLIGHT"
        self.axis = None
        self.sample_origin = None
        self.measurement_kind = None
        self.measurement_direction = None
        self.force_origin = None
        self.width_received_at = None
        self.latest_sample = None
        self.sample_point_id = ""
        self.check_client = self.node.create_client(CheckMotion, self.SERVICE_ROOT + "/motion/check_motion")

    def configure_point(self, point):
        """Entry ABC에서 감시 축을 계산하고 Entry/Pull 제한을 Recipe에서 적용한다."""
        self.latest_sample = None
        self.sample_point_id = point.point_id
        self.axis = point.normalized_entry_direction()
        self.config.entry_force_limit_n = point.entry_setting["force_guard_n"]
        self.config.entry_timeout_s = point.entry_setting["timeout_s"]
        self.config.pull_force_limit_n = point.pull_setting["force_limit_n"]
        self.config.pull_timeout_s = point.pull_setting["timeout_s"]
        self.config.linear_speed_mm_s = point.pull_setting["speed_mm_s"]

    def _gripper_state_callback(self, message):
        # 부모가 JointState 관절값을 폭(mm)으로 환산하고, 여기서는 수신 시각을 추가한다.
        super()._gripper_state_callback(message)
        if message.position:
            self.width_received_at = time.monotonic()

    def connect(self):
        # 실물 TCP/Tool은 읽기만 한다. 가상 모드는 설치된 설정을 적용한 뒤 검증한다.
        # 노드 생성 직후에는 DDS 서비스 발견이 끝나지 않았을 수 있다.
        # 발견 전에 요청을 보내면 서비스 부재도 응답 시간초과로만 표시된다.
        if not self.system_client.wait_for_service(timeout_sec=self.SERVICE_TIMEOUT_S):
            raise RuntimeError(
                f"로봇 시스템 조회 서비스를 찾지 못했습니다: {self.system_client.srv_name}. "
                f"ROS_DOMAIN_ID={os.environ.get('ROS_DOMAIN_ID', '0')}, "
                f"RMW_IMPLEMENTATION={os.environ.get('RMW_IMPLEMENTATION', '(기본값)')}. "
                f"{self.mode} bringup 실행 여부, /dsr01 네임스페이스 및 양쪽 터미널의 "
                "ROS_DOMAIN_ID/DDS 설정을 확인하세요."
            )
        self._check_robot_mode()
        if not self.check_client.wait_for_service(timeout_sec=self.SERVICE_TIMEOUT_S):
            raise RuntimeError("check_motion 서비스 없음")
        if self._call(self.check_client, CheckMotion.Request()).status != 0:
            raise RuntimeError("로봇이 이미 움직이고 있습니다.")
        if self.mode == "virtual":
            self.wait_for_services()
        for suffix, service, expected in (
            ("tcp/get_current_tcp", GetCurrentTcp, self.config.tcp_name),
            ("tool/get_current_tool", GetCurrentTool, self.config.tool_name),
        ):
            client = self.node.create_client(service, self.SERVICE_ROOT + "/" + suffix)
            try:
                if not client.wait_for_service(timeout_sec=self.SERVICE_TIMEOUT_S):
                    raise RuntimeError(f"서비스 없음: {suffix}")
                if self._call(client, service.Request()).info != expected:
                    raise RuntimeError(f"활성 설정 불일치: {expected}")
            finally:
                self.node.destroy_client(client)
        # 실물은 활성 TCP/Tool 확인 후 RG2 힘을 동기화한다.
        # 실제 Open 폭과 Soft 힘은 Point Transition의 grip()에서 적용한다.
        if self.mode == "real":
            self.wait_for_services()
        self.sample()

    # ------------------------------------------------------------------
    # 2. 측정과 기록: 새 폭 수신 → TCP 조회 → Force 조회 → JSONL 저장
    # ------------------------------------------------------------------
    def sample(self):
        started = time.monotonic()
        # 이전 폭을 새 실측값처럼 사용하지 않는다.
        while self.width_received_at is None or self.width_received_at < started:
            poll = getattr(self, "control_poll", None)
            if poll is not None:
                poll()
            rclpy.spin_once(self.node, timeout_sec=0.01)
            if time.monotonic() - started > self.config.gripper_timeout_s:
                raise TimeoutError("새 그리퍼 폭 피드백이 없습니다.")
        width = self.measured_width_mm
        width_time = self.width_received_at
        # 순차 조회이므로 하드웨어 동기 측정이 아니다. 조회 시각을 각각 남긴다.
        # TCP = [X,Y,Z,A,B,C] (mm/deg), wrench = [Fx,Fy,Fz,Mx,My,Mz].
        tcp = self.get_tcp()
        tcp_time = time.monotonic()
        wrench = self.get_tool_wrench(0)
        force_time = time.monotonic()
        if (len(tcp) != 6 or len(wrench) != 6 or width is None
                or not all(math.isfinite(v) for v in [*tcp, *wrench, width])):
            raise ValueError("TCP/Force/Width 실측값이 유효하지 않습니다.")
        # axial_force는 진입축 방향 성분이다. 반대 방향 Pull에서는 부호가 달라진다.
        # axial_displacement는 진입축 기준 부호 있는 변위다(Entry +, Pull -).
        # Entry/Pull 전용 필드는 각 동작 방향의 실제 이동량을 항상 양수로 기록한다.
        motion_displacement = (
            sum((tcp[i] - self.sample_origin[i]) * self.measurement_direction[i] for i in range(3))
            if self.measurement_direction and self.sample_origin else None
        )
        pull_force = (
            abs(sum((wrench[i] - self.force_origin[i]) * self.measurement_direction[i]
                    for i in range(3)))
            if self.measurement_kind == "PULL" and self.force_origin else None
        )
        sample = {
            "point_id": self.sample_point_id,
            "measurement_kind": self.measurement_kind,
            "timestamp": datetime.now().astimezone().isoformat(timespec="milliseconds"),
            "monotonic_s": force_time, "phase": self.phase, "tcp": tcp,
            "wrench_base": wrench, "width_mm": width,
            # RG2 토픽은 실제 폭을 제공하지만 파지력 센서값은 제공하지 않는다.
            # 아래 두 값은 드라이버로 보낸 마지막 목표값이며 실측값과 구분한다.
            "commanded_width_mm": self.commanded_width_mm,
            "commanded_force_n": self.commanded_force_n,
            "gripper_busy": self.gripper_busy,
            "tcp_read_monotonic_s": tcp_time, "width_read_monotonic_s": width_time,
            "force_norm_n": math.hypot(*wrench[:3]),
            "connector_axis_base": self.axis,
            "axial_force_n": sum(wrench[i] * self.axis[i] for i in range(3)) if self.axis else None,
            "axial_displacement_mm": (
                sum((tcp[i] - self.sample_origin[i]) * self.axis[i] for i in range(3))
                if self.axis and self.sample_origin else None),
            "entry_displacement_mm": (
                motion_displacement if self.measurement_kind == "ENTRY" else None),
            "pull_displacement_mm": (
                motion_displacement if self.measurement_kind == "PULL" else None),
            "pull_force_n": pull_force,
        }
        if self.measurement_kind == "PULL":
            self.pull_min_width_mm = min(getattr(self, "pull_min_width_mm", math.inf), width)
        self.stream.write(json.dumps(sample, ensure_ascii=False, allow_nan=False) + "\n")
        self.stream.flush()
        # 완성된 스냅샷만 교체하며 상태 발행부에서는 장비를 조회하지 않는다.
        self.latest_sample = sample
        return sample

    def observe(self, duration):
        # 새 이동 명령 없이 duration초 동안 상태를 기록한다.
        # sample_period_s는 조회 후 대기시간이므로 고정 샘플 주기를 보장하지 않는다.
        deadline = time.monotonic() + duration
        samples = []
        while True:
            samples.append(self.sample())
            if time.monotonic() >= deadline:
                return samples
            time.sleep(self.config.sample_period_s)

    # ------------------------------------------------------------------
    # 3. 그리퍼: 명령 적용 → Open 도달 확인 또는 Close 후 안정화 관찰
    # ------------------------------------------------------------------
    def wait_gripper_idle(self):
        """Soft Grip 동작 종료 후 기준 폭을 읽는다."""
        deadline = time.monotonic() + self.config.gripper_timeout_s
        while True:
            measured = self.sample()
            if not measured["gripper_busy"]:
                return measured
            if time.monotonic() >= deadline:
                raise TimeoutError("Soft Grip 동작 완료 확인 실패")
            time.sleep(self.config.sample_period_s)

    def grip(self, width, force, opening=False, wait_for_completion=False):
        # width는 mm, force는 N. 실제 RG2 명령 변환은 부모 _set_gripper() 담당.
        self.sample()
        self._set_gripper({"width_mm": width, "force_n": force})
        started = time.monotonic()
        if opening:
            while True:
                latest = self.sample()
                if abs(latest["width_mm"] - width) <= self.config.width_tolerance_mm:
                    break
                if time.monotonic() - started >= self.config.gripper_timeout_s:
                    raise TimeoutError("Open 폭 도달 실패")
                time.sleep(self.config.sample_period_s)
        elif wait_for_completion:
            # Hard Grip은 RG2가 실제 동작을 시작했다가 멈추거나 목표 폭에 도달해야 완료다.
            saw_busy = False
            while True:
                latest = self.sample()
                saw_busy = saw_busy or latest["gripper_busy"]
                if not latest["gripper_busy"] and abs(latest["width_mm"] - width) <= self.config.width_tolerance_mm:
                    completion_reason = "TARGET_WIDTH_REACHED"
                    break
                if saw_busy and not latest["gripper_busy"]:
                    completion_reason = "GRIPPER_MOTION_COMPLETED"
                    break
                if time.monotonic() - started >= self.config.gripper_timeout_s:
                    raise TimeoutError("Hard Grip 동작 완료 확인 실패")
                time.sleep(self.config.sample_period_s)
        else:
            # Close 폭 도달이나 Cable 파지 성공을 추론하지 않는다.
            # 명령 응답과 현재 상태만 기록하고 별도 Settling 없이 다음 동작으로 간다.
            latest = self.sample()
        return {"command_width_mm": width, "command_force_n": force,
                "completion_reason": locals().get("completion_reason", "COMMAND_ACCEPTED"),
                "measured": latest}

    # ------------------------------------------------------------------
    # 4. 이동 명령: MoveJ(접근), MoveL(탐색/Wiggle/보정/Pull)
    # ------------------------------------------------------------------
    def move_joint(self, pose, allow_incomplete=False):
        # 명령에는 JOINT(deg)를 쓰고, 완료 확인에는 레시피 TASK(mm/deg)를 쓴다.
        before = self.sample()
        self.sample_origin = before["tcp"][:]
        request = MoveJoint.Request()
        request.pos = [float(v) for v in pose.joint]
        request.vel = float(self.config.joint_speed_deg_s)
        request.acc = float(self.config.joint_acc_deg_s2)
        # 비동기로 시작하지만 아래 _monitor()가 완료까지 기다린 뒤 반환한다.
        request.sync_type = 1
        self._call(self.movej_client, request)
        return self._monitor(pose.task, before, allow_incomplete=allow_incomplete)

    def move_linear(self, target, entry_guard=False, measurement_kind=None):
        # target은 BASE 기준 절대 TASK. entry_guard=True이면 Entry 종료조건을 적용한다.
        before = self.sample()
        self.sample_origin = before["tcp"][:]
        self.force_origin = before["wrench_base"][:]
        if measurement_kind == "ENTRY" or entry_guard:
            self.measurement_kind = "ENTRY"
            self.measurement_direction = self.axis
        elif measurement_kind == "PULL":
            self.measurement_kind = "PULL"
            self.measurement_direction = [-v for v in self.axis]
        else:
            self.measurement_kind = None
            self.measurement_direction = None
        request = MoveLine.Request()
        request.pos = [float(v) for v in target]
        request.vel = [float(self.config.linear_speed_mm_s), -10000.0]
        request.acc = [float(self.config.linear_acc_mm_s2), -10000.0]
        request.ref = 0
        request.mode = 0
        request.sync_type = 1
        self._call(self.movel_client, request)
        return self._monitor(target, before, entry_guard, measurement_kind == "PULL")

    def relative(self, direction, distance, entry_guard=False, pull_guard=False):
        # 단위 방향벡터 × 거리(mm)를 현재 XYZ에 더한다. ABC는 그대로 유지한다.
        # 상대 목표를 계산한 뒤 절대 좌표 MoveL로 전송한다.
        origin = self.sample()["tcp"]
        target = [origin[i] + direction[i] * distance for i in range(3)] + origin[3:]
        kind = "ENTRY" if entry_guard else "PULL" if pull_guard else None
        return self.move_linear(target, entry_guard, kind)

    # ------------------------------------------------------------------
    # 5. 이동 감시: 측정 → 접촉 정지 여부 → 목표 도달 여부 → 시간초과
    # ------------------------------------------------------------------
    def controlled_stop(self):
        """정상 제한 도달 시 감속 정지한다. 오류/Ctrl+C의 Quick Stop과 구분한다."""
        request = MoveStop.Request()
        request.stop_mode = 2  # DR_SSTO
        self._call(self.stop_client, request, timeout=2.0)

    def _monitor(
        self, target, before, entry_guard=False, pull_guard=False,
        allow_incomplete=False,
    ):
        started = time.monotonic()
        peak = 0.0
        peak_pull_force = 0.0
        if pull_guard:
            self.pull_min_width_mm = math.inf
        def record_peak(sample):
            # 감속 중 샘플도 같은 이동 구간의 최대 힘에 포함한다.
            nonlocal peak, peak_pull_force
            delta = math.hypot(*[sample["wrench_base"][i] - before["wrench_base"][i] for i in range(3)])
            peak = max(peak, delta)
            if pull_guard:
                peak_pull_force = max(peak_pull_force, sample["pull_force_n"])
            return delta

        def stop_and_sample():
            self.controlled_stop()
            self._wait_idle(on_sample=record_peak)
            sample = self.sample()
            record_peak(sample)
            return sample

        stop_reason = None
        while True:
            latest = self.sample()
            delta = record_peak(latest)
            if pull_guard:
                if latest["pull_force_n"] >= self.config.pull_force_limit_n:
                    latest = stop_and_sample()
                    stop_reason = "PULL_FORCE_LIMIT"
                    break
            if entry_guard and delta >= self.config.entry_force_limit_n:
                latest = stop_and_sample()
                stop_reason = "ENTRY_FORCE_LIMIT"
                break
            # 정지 상태만으로 성공 처리하지 않는다. 목표 XYZ와 ABC도 확인한다.
            # B=180°에서는 서로 다른 ABC가 같은 자세일 수 있어 실제 회전 차이로 비교한다.
            idle = self._call(self.check_client, CheckMotion.Request()).status == 0
            position_ok = math.dist(latest["tcp"][:3], target[:3]) <= self.config.position_tolerance_mm
            angle_error = orientation_error_deg(latest["tcp"][3:], target[3:])
            if idle and position_ok and angle_error <= self.config.orientation_tolerance_deg:
                stop_reason = ("ENTRY_DISTANCE_REACHED" if entry_guard else
                               "PULL_MAX_DISTANCE" if pull_guard else "TARGET_REACHED")
                break
            elapsed = time.monotonic() - started
            if entry_guard and elapsed >= self.config.entry_timeout_s:
                latest = stop_and_sample()
                stop_reason = "ENTRY_TIMEOUT"
                break
            if pull_guard and elapsed >= self.config.pull_timeout_s:
                latest = stop_and_sample()
                stop_reason = "PULL_TIMEOUT"
                break
            if elapsed >= self.config.motion_timeout_s:
                if allow_incomplete:
                    latest = stop_and_sample()
                    stop_reason = "TARGET_NOT_REACHED"
                    break
                raise TimeoutError("이동 완료/목표 위치 확인 시간 초과")
            time.sleep(self.config.sample_period_s)
        direction = getattr(self, "measurement_direction", None)
        measurement_kind = getattr(self, "measurement_kind", None)
        motion_displacement = (
            sum((latest["tcp"][i] - before["tcp"][i]) * direction[i] for i in range(3))
            if direction else None
        )
        result = {"stop_reason": stop_reason, "peak_force_delta_n": peak,
                "peak_pull_force_n": peak_pull_force if pull_guard else None,
                "pull_width_mm": self.pull_min_width_mm if pull_guard else None,
                "start_tcp": before["tcp"], "end_tcp": latest["tcp"],
                "displacement_mm": math.dist(before["tcp"][:3], latest["tcp"][:3]),
                "entry_displacement_mm": (
                    motion_displacement if measurement_kind == "ENTRY" else None),
                "pull_displacement_mm": (
                    motion_displacement if measurement_kind == "PULL" else None),
                "target_tcp": target}
        # 다음 Grip/대기 샘플이 직전 이동량으로 잘못 기록되지 않게 이동 측정을 닫는다.
        self.measurement_kind = None
        self.measurement_direction = None
        self.sample_origin = None
        self.force_origin = None
        return result

    def _wait_idle(self, on_sample=None):
        # 접촉 정지 요청 후 실제 정지 상태까지 기다린다. 대기 중에도 측정은 계속한다.
        deadline = time.monotonic() + self.config.motion_timeout_s
        while self._call(self.check_client, CheckMotion.Request()).status != 0:
            sample = self.sample()
            if on_sample is not None:
                on_sample(sample)
            if time.monotonic() >= deadline:
                raise TimeoutError("정지 완료 확인 실패")
            time.sleep(self.config.sample_period_s)


# 기능: ZYZ Euler 각을 회전행렬로 바꿔 실제 자세 차이를 계산한다.
#     actual_abc: 현재 TCP의 [A, B, C] 자세각(deg).
#     target_abc: 목표 TCP의 [A, B, C] 자세각(deg).
#
#     ------------------------------------------------------------
#     반환: 두 자세 사이의 최소 회전각(deg, 0~180). 동등한 Euler 표현은 0이다.
def orientation_error_deg(actual_abc, target_abc):
    # 기능: Rz(A) × Ry(B) × Rz(C) 회전행렬을 만든다.
    #     abc: [A, B, C] 자세각(deg).
    #
    #     ------------------------------------------------------------
    #     반환: Tool 축을 BASE로 변환하는 3×3 행렬.
    def rotation_matrix(abc):
        a, b, c = map(math.radians, abc)
        ca, sa = math.cos(a), math.sin(a)
        cb, sb = math.cos(b), math.sin(b)
        cc, sc = math.cos(c), math.sin(c)
        return (
            (ca*cb*cc - sa*sc, -ca*cb*sc - sa*cc, ca*sb),
            (sa*cb*cc + ca*sc, -sa*cb*sc + ca*cc, sa*sb),
            (-sb*cc, sb*sc, cb),
        )

    actual = rotation_matrix(actual_abc)
    target = rotation_matrix(target_abc)
    # trace(R_actual.T × R_target) = 1 + 2*cos(자세 차이).
    trace = sum(actual[i][j] * target[i][j] for i in range(3) for j in range(3))
    cosine = max(-1.0, min(1.0, (trace - 1.0) / 2.0))
    return math.degrees(math.acos(cosine))


class SequenceRobot(HardwareRobot):
    """서비스 조회/이동만 담당한다. 순회, Pause, Job 종료 정책은 Main Work에 있다."""

    def __init__(self, system_path, recipe_paths, stream, mode="real"):
        super().__init__(RobotRuntimeConfig(), stream, mode=mode)
        self.system_path = Path(system_path)
        self.recipe_paths = {key: Path(value) for key, value in recipe_paths.items()}
        self.system = None
        self.recipe = None
        self.received_recipe = None
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
        self.config.joint_speed_deg_s = self.system["joint_speed_deg_s"]
        return self.ok("SYSTEM_RECIPE_VALID")

    def accept_inspection_recipe(self, recipe):
        """HMI가 전달한 실행용 복사본만 보관한다. 원본 저장소를 소유하지 않는다."""
        from cable_inspection.recipe.inspection_recipe import validate_recipe
        self.received_recipe = copy.deepcopy(validate_recipe(recipe))

    def validate_inspection_recipe(self, recipe_id):
        if self.received_recipe is not None and self.received_recipe.recipe_id == recipe_id:
            self.recipe = copy.deepcopy(self.received_recipe)
            self.recipe.validate()
            return self.ok("INSPECTION_RECIPE_VALID")
        if recipe_id not in self.recipe_paths:
            raise ValueError(f"등록되지 않은 Recipe: {recipe_id}")
        self.recipe = OperatingInspectionRecipe.load_json(self.recipe_paths[recipe_id])
        if self.recipe.recipe_id != recipe_id:
            raise ValueError("선택한 Recipe ID와 파일의 ID가 다릅니다.")
        return self.ok("INSPECTION_RECIPE_VALID")

    def enabled_point_ids(self, recipe_id):
        return [key for key in self.recipe.execution_order if self.recipe.points[key].enabled]

    def current_tcp(self):
        return self.get_tcp()

    def tcp_is_in_work_area(self, tcp):
        return BoxBoundary(**self.system["work_area"]).contains_inside(tcp[:3], 0)

    def move_joint(self, pose, allow_incomplete=False):
        self.control_poll()
        return super().move_joint(pose, allow_incomplete)

    def move_linear(self, target, entry_guard=False, measurement_kind=None):
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
        if any(abs(value) > 0.1 for value in self.current_joints()):
            raise RuntimeError("Home 복귀 후 전체 관절 0도 확인 실패")
        return self.ok("HOME_REACHED")

    def current_joints(self):
        joints = list(self._call(self.joint_client, GetCurrentPosj.Request()).pos)
        if len(joints) != 6 or not all(math.isfinite(v) for v in joints):
            raise RuntimeError("현재 관절값이 유효하지 않습니다.")
        return joints

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
