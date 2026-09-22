"""기존 DSR/RG2 연결을 재사용하는 실물 시험용 감시·기록 어댑터."""

import json
import math
import os
import time
from datetime import datetime

import rclpy
from dsr_msgs2.srv import CheckMotion, GetCurrentTcp, GetCurrentTool, MoveJoint, MoveLine, MoveStop

from cable_pkg.test_module.grip_stability.grip_stability_robot import GripPullRobot

# 이 파일은 '어떻게 움직이고 측정하는가'를 담당한다. 단계 순서는 sequence.py에 있다.
# 부모 구현 위치: cable_pkg/grip_stability/grip_stability_robot.py.
#   _call(): 서비스 전송/응답 확인, 이동·그리퍼·정지 명령 전 실물 모드 재확인
#   _set_gripper(): RG2 힘과 폭 명령 전송
#   get_tcp()/get_tool_wrench(): BASE 기준 실측값 조회
#   safe_abort(): 연결 확인된 로봇에 Quick Stop 요청(그리퍼 해제는 하지 않음)
# 일반 오류는 run.py까지 전달되어 safe_abort()와 결과 저장으로 이어진다.

class HardwareRobot(GripPullRobot):
    # ------------------------------------------------------------------
    # 1. ROS 클라이언트 생성과 실물 연결 확인
    # ------------------------------------------------------------------
    def __init__(self, config, stream):
        super().__init__(mode="real")
        self.config, self.stream = config, stream
        self.phase = "PREFLIGHT"
        self.axis = None
        self.sample_origin = None
        self.measurement_kind = None
        self.measurement_direction = None
        self.force_origin = None
        self.width_received_at = None
        self.check_client = self.node.create_client(CheckMotion, self.SERVICE_ROOT + "/motion/check_motion")

    def _gripper_state_callback(self, message):
        # 부모가 JointState 관절값을 폭(mm)으로 환산하고, 여기서는 수신 시각을 추가한다.
        super()._gripper_state_callback(message)
        if message.position:
            self.width_received_at = time.monotonic()

    def connect(self):
        # TCP/Tool 조회는 읽기 전용이다. 실물의 활성 설정은 변경하지 않는다.
        # 노드 생성 직후에는 DDS 서비스 발견이 끝나지 않았을 수 있다.
        # 발견 전에 요청을 보내면 서비스 부재도 응답 시간초과로만 표시된다.
        if not self.system_client.wait_for_service(timeout_sec=self.SERVICE_TIMEOUT_S):
            raise RuntimeError(
                f"로봇 시스템 조회 서비스를 찾지 못했습니다: {self.system_client.srv_name}. "
                f"ROS_DOMAIN_ID={os.environ.get('ROS_DOMAIN_ID', '0')}, "
                f"RMW_IMPLEMENTATION={os.environ.get('RMW_IMPLEMENTATION', '(기본값)')}. "
                "실물 bringup 실행 여부, /dsr01 네임스페이스 및 양쪽 터미널의 "
                "ROS_DOMAIN_ID/DDS 설정을 확인하세요."
            )
        self._check_robot_mode()
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
        if not self.check_client.wait_for_service(timeout_sec=self.SERVICE_TIMEOUT_S):
            raise RuntimeError("check_motion 서비스 없음")
        if self._call(self.check_client, CheckMotion.Request()).status != 0:
            raise RuntimeError("로봇이 이미 움직이고 있습니다.")
        # 부모 함수는 서비스/그리퍼 제공자를 확인하고 RG2 힘을 40 N으로 동기화한다.
        # 실제 Open 폭과 Soft 힘은 이후 V02의 grip()에서 적용한다.
        self.wait_for_services()
        self.sample()

    # ------------------------------------------------------------------
    # 2. 측정과 기록: 새 폭 수신 → TCP 조회 → Force 조회 → JSONL 저장
    # ------------------------------------------------------------------
    def sample(self):
        started = time.monotonic()
        # 이전 폭을 새 실측값처럼 사용하지 않는다.
        while self.width_received_at is None or self.width_received_at < started:
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
        self.stream.write(json.dumps(sample, ensure_ascii=False, allow_nan=False) + "\n")
        self.stream.flush()
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
                if abs(latest["width_mm"] - width) <= self.config.width_tolerance_mm:
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

    def relative(self, direction, distance, entry_guard=False):
        # 단위 방향벡터 × 거리(mm)를 현재 XYZ에 더한다. ABC는 그대로 유지한다.
        # 상대 목표를 계산한 뒤 절대 좌표 MoveL로 전송한다.
        origin = self.sample()["tcp"]
        target = [origin[i] + direction[i] * distance for i in range(3)] + origin[3:]
        kind = "ENTRY" if entry_guard else (
            "PULL" if self.phase == "V09_GRIP_PULL_LOGGING" else None
        )
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
        peak_width_change = 0.0
        stop_reason = None
        while True:
            latest = self.sample()
            # 시작 시 힘을 기준으로 한 변화벡터의 크기(N). 절대 힘 상한과는 별개다.
            delta = math.hypot(*[latest["wrench_base"][i] - before["wrench_base"][i] for i in range(3)])
            peak = max(peak, delta)
            if pull_guard:
                peak_pull_force = max(peak_pull_force, latest["pull_force_n"])
                peak_width_change = max(
                    peak_width_change, abs(latest["width_mm"] - before["width_mm"])
                )
                if latest["pull_force_n"] >= self.config.pull_force_limit_n:
                    self.controlled_stop()
                    self._wait_idle()
                    latest = self.sample()
                    peak_pull_force = max(peak_pull_force, latest["pull_force_n"])
                    peak_width_change = max(
                        peak_width_change, abs(latest["width_mm"] - before["width_mm"])
                    )
                    stop_reason = "PULL_FORCE_LIMIT"
                    break
            if entry_guard and delta >= self.config.entry_force_limit_n:
                self.controlled_stop()
                self._wait_idle()
                latest = self.sample()
                stop_reason = "ENTRY_FORCE_LIMIT"
                break
            # 정지 상태만으로 성공 처리하지 않는다. 목표 XYZ와 ABC도 확인한다.
            # ABC는 각 성분의 ±180도 주기 차이로 비교하며 회전행렬 오차는 아니다.
            idle = self._call(self.check_client, CheckMotion.Request()).status == 0
            position_ok = math.dist(latest["tcp"][:3], target[:3]) <= self.config.position_tolerance_mm
            angle_error = max(abs((a - b + 180) % 360 - 180) for a, b in zip(latest["tcp"][3:], target[3:]))
            if idle and position_ok and angle_error <= self.config.orientation_tolerance_deg:
                stop_reason = ("ENTRY_DISTANCE_REACHED" if entry_guard else
                               "PULL_MAX_DISTANCE" if pull_guard else "TARGET_REACHED")
                break
            elapsed = time.monotonic() - started
            if entry_guard and elapsed >= self.config.entry_timeout_s:
                self.controlled_stop()
                self._wait_idle()
                latest = self.sample()
                stop_reason = "ENTRY_TIMEOUT"
                break
            if pull_guard and elapsed >= self.config.pull_timeout_s:
                self.controlled_stop()
                self._wait_idle()
                latest = self.sample()
                peak_pull_force = max(peak_pull_force, latest["pull_force_n"])
                stop_reason = "PULL_TIMEOUT"
                break
            if elapsed >= self.config.motion_timeout_s:
                if allow_incomplete:
                    self.controlled_stop()
                    self._wait_idle()
                    latest = self.sample()
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
                "grip_width_change_mm": peak_width_change if pull_guard else None,
                "start_tcp": before["tcp"], "end_tcp": latest["tcp"],
                "start_width_mm": before["width_mm"],
                "end_width_mm": latest["width_mm"],
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

    def _wait_idle(self):
        # 접촉 정지 요청 후 실제 정지 상태까지 기다린다. 대기 중에도 측정은 계속한다.
        deadline = time.monotonic() + self.config.motion_timeout_s
        while self._call(self.check_client, CheckMotion.Request()).status != 0:
            self.sample()
            if time.monotonic() >= deadline:
                raise TimeoutError("정지 완료 확인 실패")
            time.sleep(self.config.sample_period_s)
