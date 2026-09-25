"""여러 시퀀스가 공유하는 이동·정지·Open과 원시 측정 기록."""

import json
import math
import time
from datetime import datetime

from cable_inspection.sequence.common.data_models.robot_runtime_config import RobotRuntimeConfig
from cable_inspection.sequence.common.geometry import orientation_error_deg



class SequenceMotion:
    """장비 API로 공통 동작을 실행한다. 장비 준비·레시피·검사 조건은 소유하지 않는다."""



    # 기능: 실행 노드에서 생성한 두 장비와 기록 스트림을 사용한다. 초기화 순서는 Main이 정한다.
    def __init__(self, robot, gripper, stream):
        self.robot, self.gripper = robot, gripper
        self.config, self.stream = RobotRuntimeConfig(), stream
        self.phase = "PREFLIGHT"
        self.latest_sample = None
        self.control_poll = lambda: None



    # 기능: 원시값을 조회하고 호출 시퀀스의 부가 측정값을 합쳐 한 샘플로 기록한다.
    def sample(self, enrich=None):
        self.control_poll()
        width, width_time = self.gripper.read_width(self.config.gripper_timeout_s)

        # 순차 조회이며 하드웨어 동기 계측은 아니다. TCP는 mm/deg, 힘은 BASE 기준이다.
        tcp = self.robot.get_tcp()
        tcp_time = time.monotonic()
        wrench = self.robot.get_tool_wrench(0)
        force_time = time.monotonic()

        if (len(tcp) != 6 or len(wrench) != 6 or width is None
                or not all(math.isfinite(v) for v in [*tcp, *wrench, width])):
            raise ValueError("TCP/Force/Width 실측값이 유효하지 않습니다.")

        sample = {
            "timestamp": datetime.now().astimezone().isoformat(timespec="milliseconds"),
            "monotonic_s": force_time, "phase": self.phase, "tcp": tcp,
            "wrench_base": wrench, "width_mm": width,

            # 명령 목표값이며 실제 파지력 센서값이 아니다. busy는 기록만 한다.
            "commanded_width_mm": self.gripper.commanded_width_mm,
            "commanded_force_n": self.gripper.commanded_force_n,
            "gripper_busy": self.gripper.gripper_busy,
            "tcp_read_monotonic_s": tcp_time, "width_read_monotonic_s": width_time,
            "force_norm_n": math.hypot(*wrench[:3]),
        }

        if enrich is not None:
            enrich(sample)

        self.stream.write(json.dumps(sample, ensure_ascii=False, allow_nan=False) + "\n")
        self.stream.flush()
        self.latest_sample = sample

        return sample



    # 기능: 지정 폭·힘으로 Open하고 실제 폭 도달을 확인한다. 실패 정책은 호출자가 결정한다.
    def open_gripper(self, width, force, sample=None):
        sample = sample or self.sample
        sample()
        self.robot.verify_mode()
        self.gripper.set_grip(width, force, opening=True)
        started = time.monotonic()

        while True:
            latest = sample()

            if abs(latest["width_mm"] - width) <= self.config.width_tolerance_mm:
                return {"command_width_mm": width, "command_force_n": force,
                        "completion_reason": "COMMAND_ACCEPTED", "measured": latest}

            if time.monotonic() - started >= self.config.gripper_timeout_s:
                raise TimeoutError("Open 폭 도달 실패")

            time.sleep(self.config.sample_period_s)



    # 기능: MoveJ 후 도달을 확인한다. 미도달 허용 여부는 호출 시퀀스가 지정한다.
    def move_joint(self, pose, allow_incomplete=False, sample=None):
        self.control_poll()
        sample = sample or self.sample
        before = sample()
        self.robot.move_joint(pose.joint, self.config.joint_speed_deg_s, self.config.joint_acc_deg_s2)
        return self._monitor(pose.task, before, sample=sample, allow_incomplete=allow_incomplete,
                             joint_target=pose.joint if self.robot.mode == "virtual" else None)



    # 기능: 지정 속도의 일반 MoveL 후 도달을 확인한다. 검사 접촉 조건은 처리하지 않는다.
    def move_linear(self, target, speed_mm_s=None, sample=None):
        self.control_poll()
        sample = sample or self.sample
        before = sample()
        speed = self.config.linear_speed_mm_s if speed_mm_s is None else speed_mm_s
        self.robot.move_linear(target, speed, self.config.linear_acc_mm_s2)
        return self._monitor(target, before, sample=sample)



    # 기능: BASE 단위 방향과 거리로 상대 이동의 절대 목표를 계산한다.
    @staticmethod
    def relative_target(origin, direction, distance):
        return [origin[i] + direction[i] * distance for i in range(3)] + origin[3:]



    # 기능: 일반 이동의 위치·자세·관절 도달과 공통 대기시간을 확인한다.
    def _monitor(self, target, before, allow_incomplete=False, joint_target=None, sample=None):
        sample = sample or self.sample
        started = time.monotonic()

        while True:
            latest = sample()
            position_error = math.dist(latest["tcp"][:3], target[:3])
            angle_error = orientation_error_deg(latest["tcp"][3:], target[3:])

            if self.robot.motion_status() == 0:
                if joint_target is not None:
                    # 가상 FK와 교시 TASK의 오차를 피하도록 MoveJ는 관절 도달로 확인한다.
                    joints = self.robot.read_joints()
                    reached = len(joints) == 6 and all(
                        abs((actual - goal + 180.0) % 360.0 - 180.0) <= 0.1
                        for actual, goal in zip(joints, joint_target))

                else:
                    reached = (position_error <= self.config.position_tolerance_mm
                               and angle_error <= self.config.orientation_tolerance_deg)

                if reached:
                    reason = "TARGET_REACHED"
                    break

            if time.monotonic() - started >= self.config.motion_timeout_s:
                if not allow_incomplete:
                    raise TimeoutError("이동 완료/목표 위치 확인 시간 초과")

                latest = self.stop_and_wait(sample=sample)
                reason = "TARGET_NOT_REACHED"
                break

            time.sleep(self.config.sample_period_s)

        return {"stop_reason": reason, "start_tcp": before["tcp"], "end_tcp": latest["tcp"],
                "target_tcp": target,
                "target_task_error_mm": math.dist(latest["tcp"][:3], target[:3]),
                "target_orientation_error_deg": orientation_error_deg(latest["tcp"][3:], target[3:]),
                "displacement_mm": math.dist(before["tcp"][:3], latest["tcp"][:3])}



    # 기능: 감속 정지 후 실제 정지를 기다린다. 감속 중에도 호출자의 계측을 계속한다.
    def stop_and_wait(self, sample=None):
        sample = sample or self.sample
        self.robot.stop_motion(2)
        deadline = time.monotonic() + self.config.motion_timeout_s

        while self.robot.motion_status() != 0:
            sample()

            if time.monotonic() >= deadline:
                raise TimeoutError("정지 완료 확인 실패")

            time.sleep(self.config.sample_period_s)

        return sample()



    # 기능: STOP 자체가 STOP 감시에 차단되지 않도록 임시 해제하고 원래 감시를 복원한다.
    def request_motion_stop(self):
        targets = (self, self.robot, self.gripper)
        polls = [target.control_poll for target in targets]

        try:
            for target in targets:
                target.control_poll = lambda: None

            self.stop_and_wait()

        finally:
            for target, poll in zip(targets, polls):
                target.control_poll = poll
