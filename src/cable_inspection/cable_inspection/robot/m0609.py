"""M0609 연결, Tool/TCP 설정과 저수준 로봇 명령."""

import json
import math
import time
from pathlib import Path
from typing import Any

from ament_index_python.packages import get_package_share_directory
from dsr_msgs2.srv import (
    ConfigCreateTcp, ConfigCreateTool, GetCurrentTcp, GetCurrentTool,
    GetCurrentPosx, GetRobotSystem, GetRobotState, GetToolForce, MoveJoint,
    MoveLine, MoveStop, SetCurrentTcp, SetCurrentTool, SetRobotMode,
    CheckMotion, GetCurrentPosj,
)



class M0609Robot:
    """RobotNode가 상속하는 M0609 통신 component. 다른 장비는 참조하지 않는다."""

    SERVICE_ROOT = "/dsr01/dsr_controller2"
    SERVICE_TIMEOUT_S = 5.0
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

        self.control_poll = lambda: None
        root = self.SERVICE_ROOT
        self.system_client = self.create_client(
            GetRobotSystem, root + "/system/get_robot_system")

        # 이동·정지 명령 클라이언트. 명령 순서는 시퀀스 Worker가 관리한다.
        self.movej_client = self.create_client(
            MoveJoint, root + "/motion/move_joint")
        self.movel_client = self.create_client(
            MoveLine, root + "/motion/move_line")
        self.stop_client = self.create_client(
            MoveStop, root + "/motion/move_stop")

        # 실측 상태 조회 클라이언트. 시퀀스와 비동기 모니터링에서 재사용한다.
        self.tcp_client = self.create_client(
            GetCurrentPosx, root + "/aux_control/get_current_posx")
        self.force_client = self.create_client(
            GetToolForce, root + "/aux_control/get_tool_force")
        self.check_client = self.create_client(
            CheckMotion, root + "/motion/check_motion")
        self.joint_client = self.create_client(
            GetCurrentPosj, root + "/aux_control/get_current_posj")
        self.state_client = self.create_client(
            GetRobotState, root + "/system/get_robot_state")

        # 활성 Tool/TCP 이름 조회 클라이언트.
        self.active_tcp_client = self.create_client(GetCurrentTcp, root + "/tcp/get_current_tcp")
        self.active_tool_client = self.create_client(GetCurrentTool, root + "/tool/get_current_tool")

        # 모니터링도 장비의 기존 조회 클라이언트를 사용하되 요청 future는 별도로 관리한다.
        self.status_channels = {}

        for key, client, request, decode in (
            ("task", self.tcp_client, GetCurrentPosx.Request(ref=0),
             lambda r: self.status_vector(r.task_pos_info[0].data[:6])),
            ("joint", self.joint_client, GetCurrentPosj.Request(), lambda r: self.status_vector(r.pos)),
            ("wrench_base", self.force_client, GetToolForce.Request(ref=0),
             lambda r: self.status_vector(r.tool_force)),
            ("robot_state_code", self.state_client, GetRobotState.Request(), lambda r: int(r.robot_state)),
            ("motion_status", self.check_client, CheckMotion.Request(), lambda r: int(r.status)),
            ("tcp_name", self.active_tcp_client, GetCurrentTcp.Request(), lambda r: str(r.info)),
            ("tool_name", self.active_tool_client, GetCurrentTool.Request(), lambda r: str(r.info)),
        ):
            self.status_channels[key] = {
                "client": client, "request": request, "decode": decode,
                "future": None, "started": 0.0, "next": 0.0,
                "period": 1.0 if key in {"tcp_name", "tool_name"} else 0.2,
            }



    # 기능: 로봇 측정 응답의 6축 수치를 검증한다.
    #     values: 위치·관절각·힘 응답의 수치 배열. 단위는 해당 서비스 기준이다.
    #     반환: 유한한 float 6개 목록. 길이 또는 수치가 잘못되면 ValueError.
    @staticmethod
    def status_vector(values):
        result = [float(value) for value in values]

        if len(result) != 6 or not all(math.isfinite(value) for value in result):
            raise ValueError("6개의 유효한 측정값이 필요합니다.")

        return result



    def _check_robot_mode(self) -> None:
        """선택한 모드와 실제 연결된 제어기의 모드가 일치해야 한다."""
        self.connection_verified = False
        response = self._call(self.system_client, GetRobotSystem.Request())
        expected = 1 if self.mode == "virtual" else 0

        if response.robot_system != expected:
            raise RuntimeError(f"{self.mode} 모드와 연결된 로봇 시스템이 다릅니다.")

        self.connection_verified = True



    # 기능: Worker에서 장비 요청을 보내고 executor가 처리하는 응답 완료를 기다린다.
    #     client: ROS 서비스 클라이언트. request: 해당 서비스 요청.
    #     timeout: 응답 제한(s). None이면 SERVICE_TIMEOUT_S.
    #     반환: 성공 응답. STOP·시간 초과·서비스 오류는 예외. executor 콜백 안에서 호출하지 않는다.
    def _call(self, client: Any, request: Any, timeout: float | None = None) -> Any:
        # STOP 자체는 계속 허용하고 나머지 장비 요청은 제어 상태를 먼저 확인한다.
        if client is not self.stop_client:
            poll = getattr(self, "control_poll", None)

            if poll is not None:
                poll()

        # 로봇 이동·정지 명령 전 연결 모드를 다시 확인한다.
        # 시스템 조회 자체는 이 분기를 타지 않으므로 재귀 호출하지 않는다.
        if client in (self.movej_client, self.movel_client,
                      self.stop_client):
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

            # 콜백은 외부 executor가 처리한다. Worker는 STOP을 감시하며 완료만 기다린다.
            time.sleep(0.01)

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



    def move_joint_raw(self, joints, speed_deg_s, acceleration_deg_s2):
        """M0609 비동기 MoveJ 요청만 전송한다. 완료 판정은 sequence가 맡는다."""
        request = MoveJoint.Request()
        request.pos = [float(value) for value in joints]
        request.vel = float(speed_deg_s)
        request.acc = float(acceleration_deg_s2)
        request.sync_type = 1
        self._call(self.movej_client, request)



    def move_linear_raw(self, target, speed_mm_s, acceleration_mm_s2):
        """M0609 비동기 MoveL 요청만 전송한다."""
        request = MoveLine.Request()
        request.pos = [float(value) for value in target]
        request.vel = [float(speed_mm_s), -10000.0]
        request.acc = [float(acceleration_mm_s2), -10000.0]
        request.ref = 0
        request.mode = 0
        request.sync_type = 1
        self._call(self.movel_client, request)



    def stop_motion_raw(self, stop_mode):
        request = MoveStop.Request()
        request.stop_mode = stop_mode
        self._call(self.stop_client, request, timeout=2.0)



    def _motion_status_raw(self):
        return self._call(self.check_client, CheckMotion.Request()).status



    def _robot_state_raw(self):
        return self._call(self.state_client, GetRobotState.Request()).robot_state



    def _read_joints_raw(self):
        return list(self._call(self.joint_client, GetCurrentPosj.Request()).pos)



    def _verify_active_tool_tcp(self, config):
        """현재 활성 Tool/TCP를 읽기만 하고 예상 설정과 비교한다."""

        for client, service, expected in (
            (self.active_tcp_client, GetCurrentTcp, config.tcp_name),
            (self.active_tool_client, GetCurrentTool, config.tool_name),
        ):
            if not client.wait_for_service(timeout_sec=self.SERVICE_TIMEOUT_S):
                raise RuntimeError(f"서비스 없음: {client.srv_name}")

            if self._call(client, service.Request()).info != expected:
                raise RuntimeError(f"활성 설정 불일치: {expected}")



    def _get_tcp_raw(self) -> list[float]:
        request = GetCurrentPosx.Request()
        request.ref = 0
        response = self._call(self.tcp_client, request)

        if not response.task_pos_info:
            raise RuntimeError("현재 TCP 응답이 비어 있습니다.")

        values = [float(value) for value in response.task_pos_info[0].data]

        if len(values) < 6:
            raise RuntimeError("현재 TCP 응답 길이가 잘못되었습니다.")

        return values[:6]



    def _get_tool_wrench_raw(self, reference: int) -> list[float]:
        request = GetToolForce.Request()
        request.ref = reference
        response = self._call(self.force_client, request)

        return [float(value) for value in response.tool_force]



    def _safe_abort_raw(self) -> None:
        if not self.connection_verified:
            return

        request = MoveStop.Request()
        request.stop_mode = 1  # DR_QSTOP

        try:
            self._call(self.stop_client, request, timeout=2.0)

        except Exception as error:
            print(f"로봇 정지 서비스 실패: {error}")



    # 기능: TCP·Tool 설정의 좌표계·단위·수치 필드를 검사한다.
    #     config_dir: tcp.json과 tool.json이 있는 디렉터리.
    #     반환: 검증된 (TCP 사전, Tool 사전). 잘못된 설정은 예외.
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

        numeric_fields = [(tcp["pos"], 6, "tcp.pos"),
                          ([tool["weight"]], 1, "tool.weight"),
                          (tool["cog"], 3, "tool.cog")]

        if tool["inertia"] is not None:
            numeric_fields.append((tool["inertia"], 6, "tool.inertia"))

        for values, length, name in numeric_fields:
            if len(values) != length or not all(
                    isinstance(v, (int, float)) and math.isfinite(v) for v in values):
                raise ValueError(f"{name}: {length}개의 유효한 숫자가 필요합니다.")

        if tool["weight"] < 0:
            raise ValueError("tool.weight는 0 이상이어야 합니다.")

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
        """가상 제어기를 Manual로 전환해 TCP·Tool을 설정한 뒤 Autonomous로 복귀한다."""
        mode_client = self.create_client(
            SetRobotMode, self.SERVICE_ROOT + "/system/set_robot_mode"
        )

        try:
            if not mode_client.wait_for_service(timeout_sec=self.SERVICE_TIMEOUT_S):
                raise RuntimeError("가상 로봇 모드 전환 서비스를 찾지 못했습니다.")

            self._call(mode_client, SetRobotMode.Request(robot_mode=0))

            try:
                self._register_virtual_settings()

            finally:
                # DRCF는 TCP·Tool 생성에 Manual 모드를 요구한다.
                # 설정 실패 때도 모션 실행을 위한 Autonomous 모드로 돌린다.
                self._call(mode_client, SetRobotMode.Request(robot_mode=1))

        finally:
            self.destroy_client(mode_client)



    def _register_virtual_settings(self) -> None:
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
            client = self.create_client(service, self.SERVICE_ROOT + "/" + path)

            try:
                if not client.wait_for_service(timeout_sec=self.SERVICE_TIMEOUT_S):
                    raise RuntimeError(f"서비스를 찾지 못했습니다: {path}")

                self._call(client, service.Request(**values))

            finally:
                self.destroy_client(client)

        for path, service, expected in (
            ("tcp/get_current_tcp", GetCurrentTcp, self.tcp_name),
            ("tool/get_current_tool", GetCurrentTool, self.tool_name),
        ):
            client = self.create_client(service, self.SERVICE_ROOT + "/" + path)

            try:
                if not client.wait_for_service(timeout_sec=self.SERVICE_TIMEOUT_S):
                    raise RuntimeError(path)

                actual = self._call(client, service.Request()).info

                if actual != expected:
                    raise RuntimeError(f"{path}: {actual} != {expected}")

            finally:
                self.destroy_client(client)

        print(f"가상 설정 적용: TCP={self.tcp_name} {self.tcp_offset}, "
              f"Tool={self.tool_name} {self.tool_weight} kg, CoG={self.tool_cog}")



    def _wait_for_services(self) -> None:
        """M0609 동작에 필요한 서비스와 선택한 시스템 모드를 확인한다."""
        clients = (
            self.system_client, self.movej_client, self.movel_client,
            self.stop_client, self.tcp_client, self.force_client,
            self.check_client, self.joint_client, self.state_client,
        )

        for client in clients:
            if not client.wait_for_service(timeout_sec=self.SERVICE_TIMEOUT_S):
                raise RuntimeError(f"서비스를 찾지 못했습니다: {client.srv_name}")

        self._check_robot_mode()
