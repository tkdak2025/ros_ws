"""V01~V09 실물 시험 순서. 수치 판정과 작업자의 Gate 관찰을 함께 기록한다."""

import math
from dataclasses import dataclass

from cable_pkg.test_module.adaptive_grip.sequence import (
    AdaptiveGripPoint, AdaptiveGripSequence, StageResult, ValidationStage,
)
from cable_pkg.test_module.adaptive_grip_hardware.adaptive_grip_sequence import (
    AdaptiveGripSequence as AdaptiveGripSequence04,
)
from cable_pkg.sequence.seq_06_inspection_judgment import judge_pull
from cable_pkg.data_models.sequence_models import PullTermination

# 읽는 순서: HardwareSequence.__init__ → V02~V09 메서드 → robot.py의 동작 함수.
# 전체 반복문(run), V01 레시피 검증, 단계 결과 저장은 부모 클래스가 담당한다.
# 부모 위치: cable_pkg/adaptive_grip/sequence.py의 AdaptiveGripSequence.
# run()은 V01부터 순서대로 호출하고 Gate 실패 또는 지정 종료 단계에서 멈춘다.

# ----------------------------------------------------------------------
# 1. 시험조건: recipe.json의 points는 좌표, conditions는 속도·힘·허용오차다.
# ----------------------------------------------------------------------

@dataclass(frozen=True)
class HardwareConfig:
    """Adaptive Grip 시험에서 공통으로 사용하는 고정 운전조건."""

    # 검사포인트마다 달라지는 값은 V03 최대 탐색거리뿐이다.
    # recipe.json의 entry_depth_mm에서 전달한다.
    search_mm: float

    # 아래 값은 이 시험의 공통 정책값이다. 검사포인트마다 바꾸지 않는다.
    joint_speed_deg_s: float = 30.0
    joint_acc_deg_s2: float = 30.0
    linear_speed_mm_s: float = 10.0
    linear_acc_mm_s2: float = 30.0
    motion_timeout_s: float = 20.0
    entry_timeout_s: float = 10.0
    sample_period_s: float = 0.05
    # Entry 접촉 기준은 이동 시작 대비 힘 변화량이다(N).
    # Hard Grip의 힘은 Pull 정지값이 아니라 Pull 시작 전 완료 조건이다.
    entry_force_limit_n: float = 5.0
    pull_force_limit_n: float = 20.0
    pull_timeout_s: float = 10.0
    normal_displacement_limit_mm: float = 5.0
    # V03 탐색 → V05 Wiggle → V06 보정 → V08 사전하중 → V09 Pull 거리(mm).
    # wiggle_axis는 BASE 기준 방향이며, 생성 시 단위벡터로 바꾼다.
    wiggle_axis: tuple[float, float, float] = (1.0, 0.0, 0.0)
    wiggle_mm: float = 0.5
    alignment_max_mm: float = 0.5
    preload_mm: float = 1.0
    pull_mm: float = 25.0
    # 목표 도달과 파지 안정성을 판단하는 허용오차/관찰시간.
    position_tolerance_mm: float = 0.2
    orientation_tolerance_deg: float = 1.0
    width_tolerance_mm: float = 2.5
    stability_time_s: float = 1.0
    stability_width_delta_mm: float = 1.0
    stability_tcp_delta_mm: float = 0.2
    gripper_timeout_s: float = 20.0
    # RG2 명령 힘(N)과 제어기에 이미 등록된 TCP/Tool 이름.
    soft_force_n: float = 10.0
    hard_force_n: float = 20.0
    tcp_name: str = "GripperDA_v1"
    tool_name: str = "ToolWeight"

    def validate(self):
        # 로봇에 연결하기 전에 입력값 자체와 조건 간 모순을 확인한다.
        for name, value in vars(self).items():
            if name in ("wiggle_axis", "tcp_name", "tool_name"):
                continue
            if (isinstance(value, bool) or not isinstance(value, (int, float))
                    or not math.isfinite(value) or value <= 0):
                raise ValueError(f"{name}: 0보다 큰 유한한 수를 입력하세요.")
        if self.search_mm > 25.0:
            raise ValueError("entry_depth_mm은 시스템 최대 진입거리 25 mm 이하여야 합니다.")
        if self.position_tolerance_mm >= min(self.wiggle_mm, self.preload_mm, self.pull_mm, self.search_mm):
            raise ValueError("위치 허용오차는 각 시험 이동거리보다 작아야 합니다.")
        if self.sample_period_s >= min(self.motion_timeout_s, self.stability_time_s):
            raise ValueError("샘플 주기는 타임아웃과 안정성 관찰시간보다 작아야 합니다.")
        for force in (self.soft_force_n, self.hard_force_n):
            if force > 40 or not math.isclose(force / 2.5, round(force / 2.5)):
                raise ValueError("RG2 힘은 40 N 이하, 2.5 N 단위여야 합니다.")
        if self.soft_force_n > self.hard_force_n:
            raise ValueError("Hard Grip 힘은 Soft Grip 힘 이상이어야 합니다.")
        if not all(isinstance(s, str) and s.strip() for s in (self.tcp_name, self.tool_name)):
            raise ValueError("tcp_name과 tool_name이 필요합니다.")
        if (not isinstance(self.wiggle_axis, (list, tuple)) or len(self.wiggle_axis) != 3
                or not all(isinstance(v, (int, float)) and math.isfinite(v) for v in self.wiggle_axis)
                or math.hypot(*self.wiggle_axis) == 0):
            raise ValueError("wiggle_axis는 유한한 3차원 비영벡터여야 합니다.")


# ----------------------------------------------------------------------
# 2. 검사포인트 준비와 공통 Gate 처리
# ----------------------------------------------------------------------

class HardwareSequence(AdaptiveGripSequence):
    """기존 Gate 실행기를 사용하되 실제 하드웨어 단계로 연결한다."""

    # 정상 운전 Flow는 설계문서에 맞춰 구성한다.
    # V05/V06 Wiggle과 V08 파지 추론은 별도 단위시험 코드로 남기고 여기서는 실행하지 않는다.
    STAGES = (
        ValidationStage.RECIPE,
        ValidationStage.READY_ENTRY,
        ValidationStage.SOFT_GRIP,
        ValidationStage.DEPTH_COMPENSATION,
        ValidationStage.HARD_GRIP,
        ValidationStage.GRIP_PULL_LOGGING,
    )

    def __init__(self, recipe, point_id, config, hardware, confirm):
        recipe.validate()
        config.validate()
        source = recipe.get_point(point_id)
        if not source.enabled or source.grip_setting is None:
            raise ValueError("활성 포인트와 포인트별 grip_setting이 필요합니다.")
        # 진입축과 Wiggle 축을 단위벡터로 만들고 서로 수직인지 확인한다.
        axis = source.normalized_entry_direction()
        length = math.hypot(*config.wiggle_axis)
        self.wiggle_axis = [v / length for v in config.wiggle_axis]
        if abs(sum(a * b for a, b in zip(axis, self.wiggle_axis))) > 1e-6:
            raise ValueError("wiggle_axis는 진입축과 수직이어야 합니다(BASE).")
        # 공유 레시피를 부모 실행기가 사용하는 입력 형태로 연결한다.
        # 여기서는 Entry TASK를 nominal로 사용하며 초기 depth_offset은 0이다.
        # 실제 탐색 결과는 V03 결과 데이터에 기록하고 레시피 좌표는 수정하지 않는다.
        super().__init__(AdaptiveGripPoint(
            recipe.recipe_id, source.point_id, source.point_name,
            source.entry_pose.task, axis, source.ready_pose.joint,
            source.entry_pose.task, 0.0, config.search_mm,
        ))
        self.source, self.config, self.hardware = source, config, hardware
        self.confirm = confirm
        self.adaptive_grip = (
            AdaptiveGripSequence04(source, config, hardware) if hardware else None
        )

    def set_hardware(self, hardware):
        """실물 연결 후 #04 실행기에 같은 Hardware adapter를 연결한다."""
        self.hardware = hardware
        self.adaptive_grip = AdaptiveGripSequence04(self.source, self.config, hardware)

    def gate(self, stage, data, condition=True):
        # 수치 조건이 실패하면 작업자 확인 없이 실패 처리한다.
        # 조건을 만족하면 run.py의 confirm()에서 PASS를 입력받는다.
        passed = condition and self.confirm(stage, data)
        return StageResult(stage, passed, "실물 Gate 통과" if passed else "실물 Gate 미통과", data)

    # ------------------------------------------------------------------
    # V02. 접근: Open 확인 → Ready MoveJ 완료 → Entry MoveJ 완료 → 자동 판정
    # ------------------------------------------------------------------
    def validate_ready_entry(self):
        self.hardware.phase = ValidationStage.READY_ENTRY.value
        h, c = self.hardware, self.config
        h.grip(self.source.grip_setting["soft_open_width_mm"], c.soft_force_n, opening=True)
        # 두 이동 모두 관절 이동이다. TCP 직선 경로나 중간 경유점을 생성하지 않는다.
        # move_joint()가 완료를 확인하고 반환하므로 Ready 후 Entry가 실행된다.
        ready = h.move_joint(self.source.ready_pose)
        # Entry 목표 미도달은 상태만 기록하고 다음 단계로 진행한다.
        # 서비스/제어기/충돌 오류는 move_joint()에서 예외로 전달되어 중단된다.
        entry = h.move_joint(self.source.entry_pose, allow_incomplete=True)
        # grip()은 Open 폭 도달을, move_joint()는 목표 TASK 위치/자세 도달을 확인한다.
        # 어느 단계든 실패하면 예외가 발생하므로 여기까지 반환되면 자동 통과다.
        return StageResult(
            ValidationStage.READY_ENTRY,
            True,
            "Open/Ready 완료, Entry 상태 확인 완료",
            {"ready": ready, "entry": entry},
        )

    # ------------------------------------------------------------------
    # V03. Entry: Soft Grip 상태로 진입축 방향 이동, Guard 도달 시 정상 종료
    # ------------------------------------------------------------------
    def depth_compensation(self):
        self.hardware.phase = ValidationStage.DEPTH_COMPENSATION.value
        result = self.adaptive_grip.enter()
        # 거리 도달, 5 N Force Limit, 10초 Timeout은 모두 정상 종료 사유다.
        # Robot/Controller 오류만 예외로 전달되어 시퀀스를 중단한다.
        return StageResult(
            ValidationStage.DEPTH_COMPENSATION,
            True,
            f"Entry 종료: {result['stop_reason']}",
            result,
        )

    # ------------------------------------------------------------------
    # V04. Soft Grip: 레시피의 Close 폭과 조건의 Soft 힘 적용
    # ------------------------------------------------------------------
    def soft_grip(self):
        self.hardware.phase = ValidationStage.SOFT_GRIP.value
        result = self.adaptive_grip.soft_grip()
        # 폭 도달 여부로 Cable 파지 성공/실패를 추론하지 않는다.
        # 명령/Tool 오류가 있으면 hardware.grip()에서 예외가 발생한다.
        return StageResult(ValidationStage.SOFT_GRIP, True, "Soft Grip 명령 완료", result)

    # ------------------------------------------------------------------
    # V05/V06 공통 측정: +방향 → 시작점 → -방향 → 시작점
    # ------------------------------------------------------------------
    def wiggle(self):
        h = self.hardware
        # 매 호출 시 현재 TCP가 새 기준점이다. XYZ만 이동하고 ABC 자세는 유지한다.
        origin = h.sample()["tcp"]
        measurements = []
        for sign in (1, -1):
            target = origin[:]
            target[:3] = [origin[i] + sign * self.wiggle_axis[i] * self.config.wiggle_mm for i in range(3)]
            measurements.append(h.move_linear(target))
            h.move_linear(origin)
        return {"positive": measurements[0], "negative": measurements[1], "origin": origin}

    # V05. 보정 전 양방향 반응을 측정하고 작업자가 결과를 확인한다.
    def micro_wiggle(self):
        self.hardware.phase = ValidationStage.MICRO_WIGGLE.value
        return self.gate(ValidationStage.MICRO_WIGGLE, self.wiggle())

    # ------------------------------------------------------------------
    # V06. 수동 정렬: 부호 있는 보정량 입력 → 1회 보정 → 양방향 재측정
    # ------------------------------------------------------------------
    def fine_alignment(self):
        self.hardware.phase = ValidationStage.FINE_ALIGNMENT.value
        # 힘→보정 방향 판정식은 미확정. 작업자가 기록을 보고 한 번의 보정을 입력한다.
        distance = float(input("V06: wiggle_axis 방향 보정량 [mm, 보정 없음=0]: "))
        if not math.isfinite(distance) or abs(distance) > self.config.alignment_max_mm:
            raise ValueError("V06 보정량이 alignment_max_mm 범위를 벗어났습니다.")
        # 양수는 wiggle_axis 방향, 음수는 반대 방향. 0이면 보정 없이 재측정한다.
        if distance:
            direction = [math.copysign(1, distance) * v for v in self.wiggle_axis]
            self.hardware.relative(direction, abs(distance))
        data = {"manual_correction_mm": distance, "remeasurement": self.wiggle()}
        return self.gate(ValidationStage.FINE_ALIGNMENT, data)

    # ------------------------------------------------------------------
    # V07. Hard Grip: Pull 전에 레시피의 Hard 폭과 지정 힘 적용
    # ------------------------------------------------------------------
    def hard_grip(self):
        self.hardware.phase = ValidationStage.HARD_GRIP.value
        result = self.adaptive_grip.hard_grip()
        force_applied = math.isclose(
            result["command_force_n"], self.config.hard_force_n, abs_tol=1e-6
        )
        result["completion_force_n"] = self.config.hard_force_n
        result["force_condition_met"] = force_applied
        self.grip_width_hard_mm = result["grip_width_hard_mm"]
        return StageResult(
            ValidationStage.HARD_GRIP,
            force_applied,
            (f"Hard Grip {self.config.hard_force_n:g} N 적용 완료"
             if force_applied else "Hard Grip 힘 적용 실패"),
            result,
        )

    # ------------------------------------------------------------------
    # V08. 파지 안정성: 짧게 당김 → 원위치 → 폭/TCP 변화 관찰 → Gate
    # ------------------------------------------------------------------
    def check_grip_stability(self):
        self.hardware.phase = ValidationStage.GRIP_STABILITY.value
        before = self.hardware.sample()
        self.hardware.relative([-v for v in self.point.connector_axis], self.config.preload_mm)
        self.hardware.move_linear(before["tcp"])
        samples = self.hardware.observe(self.config.stability_time_s)
        # 판정 대상은 사전하중 전 값과 복귀 후 관찰값이다.
        # 의도적으로 움직인 사전하중 구간 자체의 변위는 이 변화량에 넣지 않는다.
        samples.insert(0, before)
        widths = [s["width_mm"] for s in samples]
        width_delta = max(widths) - min(widths)
        tcp_delta = max(math.dist(before["tcp"][:3], s["tcp"][:3]) for s in samples)
        data = {"width_delta_mm": width_delta, "tcp_delta_mm": tcp_delta}
        stable = (width_delta <= self.config.stability_width_delta_mm
                  and tcp_delta <= self.config.stability_tcp_delta_mm)
        return self.gate(ValidationStage.GRIP_STABILITY, data, stable)

    # ------------------------------------------------------------------
    # V09. Pull: 진입축 반대 방향으로 당기며 robot.py에서 TCP/힘을 기록
    # ------------------------------------------------------------------
    def grip_pull_test(self):
        self.hardware.phase = ValidationStage.GRIP_PULL_LOGGING.value
        pull = self.hardware.relative([-v for v in self.point.connector_axis], self.config.pull_mm)
        pull["grip_width_hard_mm"] = self.grip_width_hard_mm
        # 문서 #05: Pull 후 Soft Open, 절대 Entry TASK MoveL, Ready JOINT MoveJ.
        soft_open = self.hardware.grip(
            self.source.grip_setting["soft_open_width_mm"],
            self.config.soft_force_n,
            opening=True,
        )
        return_entry = self.hardware.move_linear(self.source.entry_pose.task)
        return_ready = self.hardware.move_joint(self.source.ready_pose)
        termination = {
            "PULL_FORCE_LIMIT": PullTermination.FORCE_LIMIT,
            "PULL_MAX_DISTANCE": PullTermination.MAX_DISTANCE,
            "PULL_TIMEOUT": PullTermination.TIMEOUT,
        }.get(pull["stop_reason"], PullTermination.MOTION_ERROR)
        judgment = judge_pull(
            termination=termination,
            peak_force_n=pull["peak_pull_force_n"],
            displacement_mm=pull["pull_displacement_mm"],
            required_force_n=self.config.pull_force_limit_n,
            normal_displacement_limit_mm=self.config.normal_displacement_limit_mm,
            # Slip 임계값은 아직 TBD이므로 현재 자동 추론하지 않는다.
            slip_confirmed=False,
        )
        data = {"pull": pull, "soft_open": soft_open,
                "return_entry": return_entry, "return_ready": return_ready}
        data["judgment"] = {
            "status": judgment.status.value,
            "sequence_status": judgment.sequence_status.value,
            "result": judgment.result.value if judgment.result else None,
            "reason": judgment.reason,
        }
        # 제품 FAIL도 검사 시퀀스가 정상 완료된 결과다. 미완료만 단계 실패로 처리한다.
        completed = judgment.result is not None
        return StageResult(
            ValidationStage.GRIP_PULL_LOGGING,
            completed,
            "검사 및 복귀 완료" if completed else judgment.reason,
            data,
        )
