"""#03~#05 포인트 검사 동작과 #06 비동기 판정 요청."""

import math
import time

from cable_inspection.recipe.recipe import RobotPose
from cable_inspection.sequence.common.geometry import reverse_tool_axis, orientation_error_deg

from cable_inspection.sequence.inspection.data_models.grip_completion_timeout import GripCompletionTimeout
from cable_inspection.sequence.inspection.data_models.inspection_point_result import InspectionPointResult
from cable_inspection.sequence.inspection.data_models.judgment_request import JudgmentRequest
from cable_inspection.sequence.inspection.data_models.judgment_status import JudgmentStatus
from cable_inspection.sequence.inspection.data_models.pull_termination import PullTermination
from cable_inspection.sequence.common.data_models.sequence_status import SequenceStatus



class InspectionSequence:
    """전달받은 검사포인트 하나의 Cycle을 수행한다. 순회·진행 관리는 Recipe가 맡는다."""



    # 기능: 한 포인트 검사에 사용할 모션과 판정 API를 보관한다.
    def __init__(self, hardware, judgment=None, checkpoint=lambda _step: None,
                 on_pending=lambda _run_id, _point_id: None):
        self.motion = hardware
        self.robot, self.gripper = hardware.robot, hardware.gripper
        self.point = None
        self.axis = None
        self.measurement_kind = None
        self.sample_origin = self.force_origin = self.measurement_direction = None
        self.judgment = judgment
        self.checkpoint = checkpoint
        self.on_pending = on_pending
        self.run_id = 0
        self.recipe_id = self.recipe_version = self.connector_type = ""



    # 기능: 새 실행의 판정 목록과 식별 정보를 초기화한다. 통신 연결은 유지한다.
    def begin(self, run_id):
        self.run_id = run_id
        self.recipe_id = self.recipe_version = self.connector_type = ""
        self.judgment.reset(run_id)



    # 기능: 판정에 필요한 레시피 식별 정보만 받고 판정 노드 준비를 확인한다.
    def prepare(self, recipe_id, recipe_version, connector_type, poll_control):
        self.recipe_id, self.recipe_version, self.connector_type = recipe_id, recipe_version, connector_type
        poll_control()

        if not self.judgment.is_ready():
            raise RuntimeError("Inspection 판정 Worker가 실행 중이지 않습니다.")



    # 기능: 판정 요청을 등록하고 Recipe에 해당 포인트의 대기 상태를 알린다.
    def submit_judgment(self, request):
        self.on_pending(request.run_id, request.point_id)
        self.judgment.submit(request)



    # 기능: 모션과 별개로 수신된 확정 판정의 복사본을 제공한다.
    def results(self):
        return self.judgment.snapshot()



    # 기능: 한 Point에서 #03 접근 → #04 파지 → #05 Pull/복귀를 수행한다.
    def run_point(self, point):
        # 이번 포인트의 접근축과 측정 기준을 초기화한다.
        self.point = point
        self.motion.latest_sample = None
        self.axis = reverse_tool_axis(point["entry_pose"]["task"][3:], [0.0, 0.0, -1.0])
        self.measurement_kind = None
        self.sample_origin = self.force_origin = self.measurement_direction = None

        # #03 접근 → #04 파지 → #05 Pull/복귀. 측정 직후 #06을 비동기로 요청한다.
        transition = self.point_transition(point)

        try:
            adaptive = self.adaptive_grip(point)

        except GripCompletionTimeout as error:
            return self.recover_grip_failure(point, transition, error)

        # 파지가 끝나면 Pull을 실행하고 실제 종료 사유를 결과에 남긴다.
        pull = self.pull_inspection(point, adaptive)
        pull_data = pull["pull"]
        termination = self._pull_termination(pull_data["stop_reason"])

        return InspectionPointResult(
            point_id=point["point_id"],
            transition=transition,
            adaptive_grip=adaptive,
            pull_inspection=pull,
            entry_displacement_mm=adaptive["entry"].get("entry_displacement_mm"),
            peak_pull_force_n=float(pull_data["peak_pull_force_n"]),
            pull_displacement_mm=float(pull_data["pull_displacement_mm"]),
            termination_reason=termination,
            judgment_status=JudgmentStatus.PENDING,
            sequence_status=SequenceStatus.SUCCESS,
            result=None,
            reason="판정 요청을 등록했습니다.",
        )



    def recover_grip_failure(self, point, transition, error):
        """파지 완료 timeout만 복구한다. Open/복귀 예외는 상위 Job 오류로 전달한다."""
        self.motion.phase = "GRIP_FAILURE_RECOVERY"
        reason = f"{error.stage.upper()}_GRIP_TIMEOUT: {error}"

        # 제품 불량으로 추론하지 않고, 미실시 Pull을 TIMEOUT/SYSTEM_ERROR로 기록한다.
        self.submit_judgment(JudgmentRequest(
            run_id=self.run_id, recipe_id=self.recipe_id,
            recipe_version=self.recipe_version, point_id=point["point_id"],
            point_name=point["point_name"], connector_type=self.connector_type,
            peak_pull_force_n=0.0, pull_displacement_mm=0.0,
            termination_reason=PullTermination.TIMEOUT,
            required_force_n=point["pull_setting"]["force_limit_n"],
            normal_displacement_limit_mm=point["pull_setting"]["normal_displacement_limit_mm"],
            entry_task=point["entry_pose"]["task"], entry_joint=point["entry_pose"]["joint"],
            error_reason=reason,
        ))
        opened = self.open_gripper(point)
        width = opened["measured"]["width_mm"]

        if (not math.isfinite(width)
                or abs(width - point["grip_setting"]["soft_open_width_mm"])
                > self.motion.config.width_tolerance_mm):
            raise RuntimeError("파지 실패 복구 Open 폭 확인 실패")

        # 추가 진입 위치에서 기존 Entry로 직선 후퇴 후 Ready로 복귀한다.
        entry = self.motion.move_linear(point["entry_pose"]["task"],
            speed_mm_s=point["pull_setting"]["speed_mm_s"], sample=self.sample)
        ready = self.return_ready(point)
        self.checkpoint("GRIP_FAILURE_RECOVERED")
        return InspectionPointResult(
            point_id=point["point_id"], transition=transition,
            adaptive_grip={
                "entry": {},
                "hard_grip": {"failed_stage": error.stage, "measured": error.measured},
                "soft_width_mm": None,
                "adaptive_grip_done": False,
            },
            pull_inspection={"skipped":True, "reason":reason, "soft_open":opened,
                             "return_entry":entry, "return_ready":ready},
            entry_displacement_mm=None, peak_pull_force_n=0.0, pull_displacement_mm=0.0,
            termination_reason=PullTermination.TIMEOUT,
            judgment_status=JudgmentStatus.PENDING, sequence_status=SequenceStatus.INCOMPLETE,
            result=None, reason=reason,
        )



    # 기능: Pull 정지 직후 폭 차이를 계산해 #06 판정을 요청한다. 복귀와 병행한다.
    def submit_pull_result(self, point, adaptive, pull_data):
        pull_data["width_delta_mm"] = pull_data["pull_width_mm"] - adaptive["soft_width_mm"]
        termination = self._pull_termination(pull_data["stop_reason"])
        self.submit_judgment(JudgmentRequest(
            run_id=self.run_id,
            recipe_id=self.recipe_id,
            recipe_version=self.recipe_version,
            point_id=point["point_id"],
            point_name=point["point_name"],
            soft_width_mm=adaptive["soft_width_mm"],
            pull_width_mm=pull_data["pull_width_mm"],
            connector_type=self.connector_type,
            peak_pull_force_n=float(pull_data["peak_pull_force_n"]),
            pull_displacement_mm=float(pull_data["pull_displacement_mm"]),
            termination_reason=termination,
            required_force_n=point["pull_setting"]["force_limit_n"],
            normal_displacement_limit_mm=(
                point["pull_setting"]["normal_displacement_limit_mm"]
            ),
            entry_task=point["entry_pose"]["task"],
            entry_joint=point["entry_pose"]["joint"],
        ))



    # 기능: 장비 종료 문자열을 시퀀스의 Pull 종료 Enum으로 변환한다.
    @staticmethod
    def _pull_termination(stop_reason):
        mapping = {
            "PULL_FORCE_LIMIT": PullTermination.FORCE_LIMIT,
            "PULL_MAX_DISTANCE": PullTermination.MAX_DISTANCE,
            "PULL_STOPPED_SHORT": PullTermination.STOPPED_SHORT,
            "PULL_TIMEOUT": PullTermination.TIMEOUT,
        }

        return mapping.get(stop_reason, PullTermination.MOTION_ERROR)



    # 기능: #03 그리퍼를 열고 Ready→Entry 자세로 MoveJ 접근한 뒤 도달을 확인한다.
    #     point: Open 조건과 Ready/Entry task·joint 자세를 가진 검사포인트.
    #     반환: Open과 두 이동의 결과. 접근 미도달은 예외로 전달하여 후속 파지를 막는다.
    def point_transition(self, point):
        self.motion.phase = "SEQ_03_POINT_TRANSITION"
        opened = self.open_gripper(point)
        ready = self.motion.move_joint(RobotPose(**point["ready_pose"]), sample=self.sample)
        self.checkpoint("READY_REACHED")
        entry = self.motion.move_joint(RobotPose(**point["entry_pose"]), sample=self.sample)
        self.checkpoint("ENTRY_REACHED")  # 기존 이름을 유지하며 Entry 자세까지의 접근을 뜻한다.
        return {"soft_open": opened, "ready": ready, "entry": entry}



    # 기능: 검사포인트의 Soft Open 폭과 힘으로 그리퍼를 연다.
    def open_gripper(self, point):
        return self.motion.open_gripper(
            point["grip_setting"]["soft_open_width_mm"],
            point["grip_setting"]["soft_force_n"],
            sample=self.sample,
        )



    # 기능: #04 Soft Grip→Tool +Z 진입→실제 폭 측정→Hard Grip을 실행한다.
    def adaptive_grip(self, point):
        self.motion.phase = "SEQ_04_ADAPTIVE_GRIP"

        # Soft Grip → 추가진입 → 기준 폭 측정 → Hard Grip 순서로 진행한다.
        grip = point["grip_setting"]
        self.close_gripper(grip["soft_close_width_mm"], grip["soft_force_n"])
        entry = self.contact_move(point, "ENTRY")

        # Entry가 끝난 후 Hard 명령 전에 새로운 폭을 읽는다. busy는 진행 조건이 아니다.
        soft = self.sample()
        hard = self.close_gripper(grip["hard_width_mm"], grip["hard_force_n"], wait_for_completion=True)
        self.checkpoint("HARD_GRIP_DONE")
        return {
            "entry": entry,
            "hard_grip": hard,
            "soft_width_mm": soft["width_mm"],
            "adaptive_grip_done": True,
        }



    # 기능: #05 Tool −Z Pull 후 판정을 요청하고 Open→Entry→Ready로 복귀한다.
    def pull_inspection(self, point, adaptive):
        self.motion.phase = "SEQ_05_PULL_INSPECTION"
        pull = self.contact_move(point, "PULL")
        self.submit_pull_result(point, adaptive, pull)  # 판정과 해제·복귀를 병행한다.
        opened = self.open_gripper(point)
        entry = self.motion.move_linear(point["entry_pose"]["task"],
            speed_mm_s=point["pull_setting"]["speed_mm_s"], sample=self.sample)
        ready = self.return_ready(point)

        return {"pull": pull, "soft_open": opened,
                "return_entry": entry, "return_ready": ready}



    # 기능: Ready 자세로 MoveJ 복귀하고 포인트 완료점을 기록한다.
    def return_ready(self, point):
        ready = self.motion.move_joint(RobotPose(**point["ready_pose"]), sample=self.sample)
        self.checkpoint("POINT_READY_RETURNED")
        return ready



    # 기능: 접근·파지·복귀 실패를 SYSTEM_ERROR로 확정해 늦은 정상 판정의 덮어쓰기를 막는다.
    def record_error(self, point, error):
        # 정상 Pull 요청이 먼저 도착했어도 복귀 실패가 나면 SYSTEM_ERROR가 최종값이다.
        request = JudgmentRequest(
            run_id=self.run_id, recipe_id=self.recipe_id, recipe_version=self.recipe_version,
            point_id=point["point_id"], point_name=point["point_name"], connector_type=self.connector_type,
            peak_pull_force_n=0.0, pull_displacement_mm=0.0,
            termination_reason=PullTermination.MOTION_ERROR,
            required_force_n=point["pull_setting"]["force_limit_n"],
            normal_displacement_limit_mm=point["pull_setting"]["normal_displacement_limit_mm"],
            entry_task=point["entry_pose"]["task"], entry_joint=point["entry_pose"]["joint"],
            error_reason=f"{type(error).__name__}: {error}",
        )
        self.judgment.record_error(request)



    # 기능: 공통 원시 측정에 검사 단계의 힘·변위·포인트 정보를 붙여 기록한다.
    def sample(self):
        return self.motion.sample(enrich=self.measure)



    # 기능: Entry/Pull 축 투영과 감속 구간을 포함한 최대 힘·최소 폭을 계산한다.
    def measure(self, sample):
        tcp, wrench = sample["tcp"], sample["wrench_base"]
        displacement = (sum((tcp[i] - self.sample_origin[i]) * self.measurement_direction[i]
                            for i in range(3)) if self.measurement_direction is not None else None)
        pull_force = (abs(sum((wrench[i] - self.force_origin[i]) * self.measurement_direction[i]
                             for i in range(3))) if self.measurement_kind == "PULL" else None)
        sample.update({
            "point_id": self.point["point_id"], "measurement_kind": self.measurement_kind,
            "connector_axis_base": self.axis,
            "axial_force_n": sum(wrench[i] * self.axis[i] for i in range(3)),
            "axial_displacement_mm": (sum((tcp[i] - self.sample_origin[i]) * self.axis[i]
                                         for i in range(3)) if self.sample_origin is not None else None),
            "entry_displacement_mm": displacement if self.measurement_kind == "ENTRY" else None,
            "pull_displacement_mm": displacement if self.measurement_kind == "PULL" else None,
            "pull_force_n": pull_force,
        })

        if self.measurement_kind is not None:
            delta = math.hypot(*[wrench[i] - self.force_origin[i] for i in range(3)])
            self.peak_force_delta = max(self.peak_force_delta, delta)

            if self.measurement_kind == "PULL":
                self.peak_pull_force = max(self.peak_pull_force, pull_force)
                self.pull_min_width = min(self.pull_min_width, sample["width_mm"])



    # 기능: Soft는 명령 후 진행하고 Hard는 목표 폭 또는 폭 안정화로 완료한다.
    def close_gripper(self, width, force, wait_for_completion=False):
        self.sample()
        self.robot.verify_mode()
        self.gripper.set_grip(width, force)
        started = time.monotonic()
        config = self.motion.config

        if not wait_for_completion:
            latest, reason = self.sample(), "COMMAND_ACCEPTED"

        else:
            window = []

            while True:
                latest = self.sample()
                now = time.monotonic()

                if abs(latest["width_mm"] - width) <= config.width_tolerance_mm:
                    reason = "TARGET_WIDTH_REACHED"
                    break

                window.append((now, latest["width_mm"]))
                window = [(stamp, value) for stamp, value in window if now - stamp <= 1.5]

                if (len(window) >= 2 and now - window[0][0] >= 1.45
                        and max(value for _, value in window) - min(value for _, value in window) <= 0.2):
                    reason = "WIDTH_STABILIZED"
                    break

                if now - started >= config.gripper_timeout_s:
                    raise GripCompletionTimeout("Hard", latest)

                time.sleep(config.sample_period_s)

        return {"command_width_mm": width, "command_force_n": force,
                "completion_reason": reason, "measured": latest}



    # 기능: 레시피의 Entry/Pull 조건으로 이동하고 실제 도달량과 종료 사유를 반환한다.
    def contact_move(self, point, kind):
        settings = point["entry_setting"] if kind == "ENTRY" else point["pull_setting"]
        direction = self.axis if kind == "ENTRY" else [-v for v in self.axis]
        target = self.motion.relative_target(self.sample()["tcp"], direction, settings["max_distance_mm"])
        before = self.sample()
        self.sample_origin, self.force_origin = before["tcp"][:], before["wrench_base"][:]
        self.measurement_kind, self.measurement_direction = kind, direction
        self.peak_force_delta = self.peak_pull_force = 0.0
        self.pull_min_width = math.inf

        try:
            self.motion.control_poll()
            self.robot.move_linear(target, point["pull_setting"]["speed_mm_s"], self.motion.config.linear_acc_mm_s2)
            return self.monitor_contact(target, before, kind, settings)

        finally:
            # 오류·STOP도 측정 구간을 닫아 다음 Open/Home에 이전 이동량이 섞이지 않게 한다.
            self.measurement_kind = None
            self.sample_origin = self.force_origin = self.measurement_direction = None



    # 기능: 검사 힘·도달·미도달·시간 조건을 순서대로 검사하며 중단 사유를 확정한다.
    def monitor_contact(self, target, before, kind, settings):
        started = time.monotonic()
        config = self.motion.config

        while True:
            latest = self.sample()
            delta = math.hypot(*[latest["wrench_base"][i] - before["wrench_base"][i] for i in range(3)])
            force = delta if kind == "ENTRY" else latest["pull_force_n"]
            limit = settings["force_guard_n"] if kind == "ENTRY" else settings["force_limit_n"]

            if force >= limit:
                latest = self.motion.stop_and_wait(sample=self.sample)
                reason = kind + "_FORCE_LIMIT"
                break

            if self.robot.motion_status() == 0:
                reached = (math.dist(latest["tcp"][:3], target[:3]) <= config.position_tolerance_mm
                    and orientation_error_deg(latest["tcp"][3:], target[3:]) <= config.orientation_tolerance_deg)
                reason = (("ENTRY_DISTANCE_REACHED" if kind == "ENTRY" else "PULL_MAX_DISTANCE")
                          if reached else kind + "_STOPPED_SHORT")
                break  # 접촉 중 미도달은 실제 결과로 남기며 Job 예외로 바꾸지 않는다.

            elapsed = time.monotonic() - started

            if elapsed >= settings["timeout_s"]:
                latest = self.motion.stop_and_wait(sample=self.sample)
                reason = kind + "_TIMEOUT"
                break

            if elapsed >= config.motion_timeout_s:
                raise TimeoutError("이동 완료/목표 위치 확인 시간 초과")

            time.sleep(config.sample_period_s)

        return {"stop_reason": reason, "peak_force_delta_n": self.peak_force_delta,
            "target_task_error_mm": math.dist(latest["tcp"][:3], target[:3]),
            "target_orientation_error_deg": orientation_error_deg(latest["tcp"][3:], target[3:]),
            "peak_pull_force_n": self.peak_pull_force if kind == "PULL" else None,
            "pull_width_mm": self.pull_min_width if kind == "PULL" else None,
            "start_tcp": before["tcp"], "end_tcp": latest["tcp"], "target_tcp": target,
            "displacement_mm": math.dist(before["tcp"][:3], latest["tcp"][:3]),
            "entry_displacement_mm": latest["entry_displacement_mm"],
            "pull_displacement_mm": latest["pull_displacement_mm"]}
