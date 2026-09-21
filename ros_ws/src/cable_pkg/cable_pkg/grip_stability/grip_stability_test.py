"""M0609 Grip/Pull 시험을 레시피의 검사포인트 순서대로 반복한다.

읽는 순서: main() → run() → run_trial() → Entry/Pull 기록 함수.
프로그램 메뉴에서 모드를 선택하고, 종료할 때까지 시험을 반복한다.

시험조건·레시피·CSV/JSON: grip_stability_data.py
실물/가상 ROS2 연결: grip_stability_robot.py
"""

import time
from datetime import datetime
from pathlib import Path
from typing import Any

import rclpy
from rclpy.executors import ExternalShutdownException

from grip_stability_data import (
    GripPullConfig,
    GripPullLogger,
    GripPullRecipe,
    TestState,
    TrialSummary,
    _dot,
    _round_optional,
    _validate_numbers,
    _wrench_columns,
)
from grip_stability_evaluator import ConnectionEvaluator, PullSample
from grip_stability_robot import GripPullRobot


# 실행하는 터미널 위치와 무관하게 프로젝트 안의 레시피를 찾는다.
PROJECT_DIR = Path(__file__).resolve().parents[2]
RECIPE_DIR = PROJECT_DIR / "src/recipe/grip_stability"
RECIPE_OPTIONS = {
    "1": ("USB", RECIPE_DIR / "grip_pull_recipe.json"),
    "2": ("LAN", RECIPE_DIR / "lan_grip_pull_recipe.json"),
}
OUTPUT_DIR = PROJECT_DIR / "measurement_results"


class GripStabilityTest:
    """한 포인트의 Ready→Entry→Grip→Pull→복귀 순서를 관리한다."""

    DR_BASE = 0
    DR_TOOL = 1

    def __init__(
        self,
        recipe: GripPullRecipe,
        config: GripPullConfig,
        hardware: GripPullRobot,
        output_dir: str | Path,
    ) -> None:
        recipe.validate()
        config.validate()
        self.recipe = recipe
        self.point = next(point for point in recipe.points.values() if point.enabled)
        self.config = config
        self.hardware = hardware
        self.logger = GripPullLogger(output_dir, recipe, config)
        self.logger.run_metadata = getattr(hardware, "run_metadata", {"mode": "real"})
        self.state = TestState.INIT
        self.latest_recommendation: dict[str, Any] | None = None

    # ------------------------------------------------------------------
    # 전체 반복 실행
    # ------------------------------------------------------------------

    def run(self) -> None:
        """사용자가 종료할 때까지 JSON에 적힌 모든 포인트를 반복 실행한다."""
        try:
            self.state = TestState.LOAD_RECIPE
            test_number = 1
            while True:
                for point in self.recipe.points.values():
                    if not point.enabled:
                        continue
                    self.point = point
                    print(f"시험 {test_number}: {point.point_id}")
                    summary = self.run_trial(
                        f"TEST_{test_number:04d}_{point.point_id}"
                    )
                    self.logger.add_summary(summary)
                    if summary.abnormal_stop:
                        self.state = TestState.SAFE_ABORT
                        return
                if not self._select_next_test_action():
                    self.state = TestState.DONE
                    return
                test_number += 1
                self.state = TestState.NEXT_TEST
        except BaseException:
            self.state = TestState.SAFE_ABORT
            self.hardware.safe_abort()
            raise
        finally:
            self.logger.close()

    # ------------------------------------------------------------------
    # 1회 시험 순서
    # ------------------------------------------------------------------

    def run_trial(self, trial_id: str) -> TrialSummary:
        self._apply_point_grip_widths()
        summary = TrialSummary(
            trial_id,
            self.point.point_id,
            cable_condition=(
                dict(self.point.cable_condition)
                if self.point.cable_condition is not None
                else None
            ),
            soft_grip_setting=dict(self.config.soft_grip_setting),
            hard_grip_setting=dict(self.config.hard_grip_setting),
        )

        # 1. 완전 개방하지 않고 레시피의 Soft Open 폭을 확인한 뒤 Ready로 이동한다.
        self.state = TestState.PREPARE_SOFT_GRIP
        soft_open = self.config.soft_grip_open_command()
        self.hardware.open_soft_grip(soft_open)
        self._record_grip_event(trial_id, "INITIAL_SOFT_GRIP_OPEN_COMMAND")
        self.hardware.wait_for_gripper_open_width(
            soft_open["width_mm"],
            self.config.gripper_preclose_timeout_s,
        )
        self.hardware.start_soft_grip(soft_open)
        self._record_grip_event(trial_id, "INITIAL_SOFT_GRIP_OPEN_REACHED")

        self.state = TestState.MOVE_READY
        self.hardware.move_ready(self.point.ready_pose)

        # 2. 진입 시작점으로 이동한 뒤, Soft Grip 상태로 지정 깊이까지 진입한다.
        self.state = TestState.MOVE_ENTRY
        self.hardware.move_entry(self.point.entry_pose)

        self._execute_soft_grip_entry(summary)
        if not summary.soft_grip_completed:
            return self._finish_abnormal(summary, "soft_grip_entry_failed")
        time.sleep(self.config.grip_stabilization_time_s)
        self._record_grip_event(summary.trial_id, "SOFT_GRIP_STABILIZATION_END")

        # 3. Hard Grip 후 안정화 시간을 두고 진입축 반대 방향으로 Pull한다.
        self.state = TestState.HARD_GRIP
        summary.hard_grip_completed = self.hardware.hard_grip(
            self.config.hard_grip_setting
        )
        self._record_grip_event(summary.trial_id, "HARD_GRIP_COMMAND")
        if not summary.hard_grip_completed:
            return self._finish_abnormal(summary, "hard_grip_failed")
        time.sleep(self.config.grip_stabilization_time_s)
        self._record_grip_event(summary.trial_id, "HARD_GRIP_STABILIZATION_END")

        self._execute_pull(summary)

        # 4. 관찰 후 Soft Grip 폭으로 벌리면서 Ready로 복귀한다.
        self.state = TestState.SAVE_RESULT
        if self.hardware.mode == "virtual":
            print("가상 시험: Cable 이탈·Grip Slip·Fixture 이동은 미평가(null)")
        else:
            self._collect_manual_observations(summary)
            self._show_evaluation_and_collect_feedback(summary)
            self._recommend_next_settings(summary)

        self.state = TestState.RELEASE
        soft_open = self.config.soft_grip_open_command()
        self.hardware.open_soft_grip(soft_open)
        self._record_grip_event(summary.trial_id, "RETURN_SOFT_GRIP_COMMAND")
        self.hardware.wait_for_gripper_open_width(
            soft_open["width_mm"],
            self.config.gripper_preclose_timeout_s,
        )
        # 폭이 열린 뒤 같은 Open 위치에서 Soft 힘을 적용하면 Hard Close 목표가
        # 반복 전송되지 않아 복귀 전 떨림을 줄일 수 있다.
        self.hardware.start_soft_grip(soft_open)
        self._record_grip_event(summary.trial_id, "RETURN_SOFT_GRIP_OPEN_REACHED")

        self.state = TestState.RETURN_READY
        self.hardware.move_ready(self.point.ready_pose)
        return summary

    def _apply_point_grip_widths(self) -> None:
        """레시피에 폭이 정의된 경우 현재 검사포인트 설정을 적용한다."""
        setting = self.point.grip_setting
        if setting is None:
            return
        self.config.soft_grip_setting["open_width_mm"] = setting[
            "soft_open_width_mm"
        ]
        self.config.soft_grip_setting["close_width_mm"] = setting[
            "soft_close_width_mm"
        ]
        self.config.hard_grip_setting["width_mm"] = setting["hard_width_mm"]

    # ------------------------------------------------------------------
    # Soft Grip 상태의 진입과 기록
    # ------------------------------------------------------------------

    def _execute_soft_grip_entry(self, summary: TrialSummary) -> None:
        """Soft Grip 상태로 Depth 진입하며 TCP·Force를 CSV에 기록한다."""
        self.state = TestState.SOFT_GRIP_ENTRY
        start_tcp = self.hardware.get_tcp()
        # 현재 힘을 영점으로 삼아 이동 중 힘 변화량을 기록한다.
        baseline_base = self.hardware.get_tool_wrench(self.DR_BASE)
        baseline_tool = self.hardware.get_tool_wrench(self.DR_TOOL)
        _validate_numbers(start_tcp, 6, "entry_start_tcp")
        _validate_numbers(baseline_base, 6, "entry_force_baseline_base")
        _validate_numbers(baseline_tool, 6, "entry_force_baseline_tool")
        summary.entry_force_baseline_base = baseline_base[:]
        summary.entry_force_baseline_tool = baseline_tool[:]
        direction = self.point.normalized_entry_direction()
        interval = 1.0 / self.config.logging_rate_hz
        self.hardware.start_soft_grip(self.config.soft_grip_close_command())
        self._record_grip_event(
            summary.trial_id,
            "SOFT_GRIP_COMMAND",
            baseline_base,
            baseline_tool,
        )
        self.hardware.wait_for_gripper_width(
            self.config.soft_grip_setting["open_width_mm"],
            self.config.gripper_preclose_timeout_s,
        )
        self._record_grip_event(
            summary.trial_id,
            "ENTRY_MOTION_START_WIDTH_REACHED",
            baseline_base,
            baseline_tool,
        )
        self.hardware.start_entry_motion(
            direction,
            self.point.entry_depth_mm,
            self.config.entry_speed_mm_s,
        )
        started = time.monotonic()

        try:
            while self.hardware.entry_is_active():
                if time.monotonic() - started >= self.config.entry_timeout_s:
                    summary.abnormal_stop = True
                    summary.stop_reason = "entry_timeout"
                    break

                abort_reason = self.hardware.safety_stop_reason()
                if abort_reason:
                    summary.abnormal_stop = True
                    summary.stop_reason = abort_reason
                    break

                tcp = self.hardware.get_tcp()
                wrench_base = self.hardware.get_tool_wrench(self.DR_BASE)
                wrench_tool = self.hardware.get_tool_wrench(self.DR_TOOL)
                gripper = self.hardware.get_gripper_status()
                entry_force = abs(_dot(
                    [wrench_base[i] - baseline_base[i] for i in range(3)],
                    direction,
                ))
                entry_depth = _dot(
                    [tcp[i] - start_tcp[i] for i in range(3)],
                    direction,
                )

                summary.peak_entry_force_n = max(
                    summary.peak_entry_force_n,
                    abs(entry_force),
                )
                summary.entry_depth_at_stop_mm = entry_depth
                self.logger.write_sample(
                    self._sample_row(
                        summary.trial_id,
                        tcp,
                        wrench_base,
                        baseline_base,
                        wrench_tool,
                        baseline_tool,
                        gripper,
                        entry_force=entry_force,
                        entry_depth=entry_depth,
                    )
                )

                if entry_depth >= self.point.entry_depth_mm:
                    break
                time.sleep(interval)
        finally:
            self.hardware.stop_entry()

        summary.soft_grip_completed = (
            not summary.abnormal_stop
            and self.hardware.soft_grip_entry_completed()
        )

    # ------------------------------------------------------------------
    # Pull과 종료 조건 확인
    # ------------------------------------------------------------------

    def _execute_pull(self, summary: TrialSummary) -> None:
        self.state = TestState.PULL_PREPARE
        start_tcp = self.hardware.get_tcp()
        # 현재 힘을 영점으로 삼아 이동 중 힘 변화량을 기록한다.
        baseline_base = self.hardware.get_tool_wrench(self.DR_BASE)
        baseline_tool = self.hardware.get_tool_wrench(self.DR_TOOL)
        summary.pull_force_baseline_base = baseline_base[:]
        summary.pull_force_baseline_tool = baseline_tool[:]
        _validate_numbers(start_tcp, 6, "pull_start_tcp")
        _validate_numbers(baseline_base, 6, "force_baseline_base")
        _validate_numbers(baseline_tool, 6, "force_baseline_tool")

        direction = self.point.pull_direction()
        interval = 1.0 / self.config.logging_rate_hz
        started = time.monotonic()
        self.hardware.start_pull(
            direction,
            self.config.pull_speed_mm_s,
            self.config.pull_distance_limit_mm,
        )
        pull_samples: list[PullSample] = []

        self.state = TestState.PULL_TEST
        try:
            while self.hardware.pull_is_active():
                if time.monotonic() - started >= self.config.pull_timeout_s:
                    summary.abnormal_stop = True
                    summary.stop_reason = "pull_timeout"
                    break

                abort_reason = self.hardware.safety_stop_reason()
                if abort_reason:
                    summary.abnormal_stop = True
                    summary.stop_reason = abort_reason
                    break

                tcp = self.hardware.get_tcp()
                wrench_base = self.hardware.get_tool_wrench(self.DR_BASE)
                wrench_tool = self.hardware.get_tool_wrench(self.DR_TOOL)
                gripper = self.hardware.get_gripper_status()
                pull_force = abs(_dot(
                    [wrench_base[i] - baseline_base[i] for i in range(3)],
                    direction,
                ))
                displacement = _dot(
                    [tcp[i] - start_tcp[i] for i in range(3)],
                    direction,
                )

                summary.peak_pull_force_n = max(
                    summary.peak_pull_force_n,
                    pull_force,
                )
                summary.pull_displacement_at_stop_mm = displacement
                pull_samples.append(
                    PullSample(
                        displacement_mm=displacement,
                        force_n=pull_force,
                        gripper_width_mm=gripper.get("width"),
                    )
                )
                self.logger.write_sample(
                    self._sample_row(
                        summary.trial_id,
                        tcp,
                        wrench_base,
                        baseline_base,
                        wrench_tool,
                        baseline_tool,
                        gripper,
                        pull_force=pull_force,
                        pull_displacement=displacement,
                    )
                )

                # 설정 힘은 합격 기준이 아니라 Pull을 멈추는 안전 상한이다.
                if pull_force >= self.config.pull_force_limit_n:
                    summary.force_limit_reached = True
                    summary.stop_reason = "pull_force_limit"
                    break
                if displacement >= self.config.pull_distance_limit_mm:
                    summary.stop_reason = "pull_distance_limit"
                    break

                time.sleep(interval)
        finally:
            self.state = TestState.PULL_STOP
            self.hardware.stop_pull()

        if summary.stop_reason == "not_started":
            summary.stop_reason = "pull_motion_completed"

        try:
            evaluation = ConnectionEvaluator().evaluate(
                pull_samples,
                self.config.pull_distance_limit_mm,
                self.config.pull_force_limit_n,
            )
        except ValueError as error:
            summary.automatic_evaluation = {"reason": str(error)}
        else:
            summary.automatic_connection_abnormal = evaluation.abnormal
            summary.automatic_evaluation = evaluation.to_dict()

    # ------------------------------------------------------------------
    # 측정 행 생성 및 중단·수동 관찰
    # ------------------------------------------------------------------

    def _record_grip_event(
        self,
        trial_id: str,
        event: str,
        baseline_base: list[float] | None = None,
        baseline_tool: list[float] | None = None,
    ) -> None:
        """그립 단계 전환 시점의 TCP·Force·실측 그리퍼 폭을 한 행으로 저장한다."""
        tcp = self.hardware.get_tcp()
        wrench_base = self.hardware.get_tool_wrench(self.DR_BASE)
        wrench_tool = self.hardware.get_tool_wrench(self.DR_TOOL)
        self.logger.write_sample(
            self._sample_row(
                trial_id,
                tcp,
                wrench_base,
                baseline_base or wrench_base,
                wrench_tool,
                baseline_tool or wrench_tool,
                self.hardware.get_gripper_status(),
                grip_event=event,
            )
        )

    def _sample_row(
        self,
        trial_id: str,
        tcp: list[float],
        wrench_base: list[float],
        baseline_base: list[float],
        wrench_tool: list[float],
        baseline_tool: list[float],
        gripper: dict[str, Any],
        entry_force: float | None = None,
        entry_depth: float | None = None,
        pull_force: float | None = None,
        pull_displacement: float | None = None,
        grip_event: str = "",
    ) -> dict[str, Any]:
        return {
            "timestamp": datetime.now().astimezone().isoformat(
                timespec="milliseconds"
            ),
            "trial_id": trial_id,
            "inspection_point_id": self.point.point_id,
            "state": self.state.value,
            "grip_event": grip_event,
            **dict(zip(("tcp_x", "tcp_y", "tcp_z", "tcp_rx", "tcp_ry", "tcp_rz"), tcp)),
            **_wrench_columns("base", wrench_base, baseline_base),
            **_wrench_columns("tool", wrench_tool, baseline_tool),
            "entry_force_n": _round_optional(entry_force),
            "entry_depth_mm": _round_optional(entry_depth),
            "pull_force_n": _round_optional(pull_force),
            "pull_displacement_mm": _round_optional(pull_displacement),
            "gripper_width": gripper.get("width"),
            "gripper_state": gripper.get("state"),
        }

    def _finish_abnormal(
        self, summary: TrialSummary, reason: str
    ) -> TrialSummary:
        summary.abnormal_stop = True
        summary.stop_reason = reason
        self.state = TestState.SAFE_ABORT
        self.hardware.safe_abort()
        return summary

    @staticmethod
    def _collect_manual_observations(summary: TrialSummary) -> None:
        """자동 검출하지 않는 세 항목을 시험자에게 확인한다."""
        summary.cable_detached = _read_yes_no("Cable 이탈 여부")
        summary.grip_slip = _read_yes_no("Grip Slip 여부")
        summary.fixture_moved = _read_yes_no("Fixture/작업대 움직임 여부")

    @staticmethod
    def _show_evaluation_and_collect_feedback(summary: TrialSummary) -> None:
        """판정 제안과 모든 근거를 공개하고 시험자의 피드백을 저장한다."""
        basis: list[str] = []
        if summary.automatic_connection_abnormal is None:
            basis.append("측정값 부족으로 힘 곡선 판정 불가")
        else:
            metrics = summary.automatic_evaluation or {}
            basis.append(
                f"힘 곡선={metrics.get('reason')}, "
                f"Peak={metrics.get('peak_force_n')} N, "
                f"안정구간={metrics.get('settled_force_n')} N, "
                f"감소량={metrics.get('force_drop_n')} N, "
                f"그리퍼 폭 변화={metrics.get('gripper_width_range_mm')} mm"
            )
        if summary.cable_detached is True:
            basis.append("작업자 관찰: Cable 이탈=y")
            suggested_abnormal = True
        elif summary.automatic_connection_abnormal is not None:
            if summary.cable_detached is False:
                basis.append("작업자 관찰: Cable 이탈=n")
            else:
                basis.append("작업자 관찰: Cable 이탈=미확인")
            suggested_abnormal = summary.automatic_connection_abnormal
        else:
            suggested_abnormal = None

        summary.suggested_connection_abnormal = suggested_abnormal
        summary.judgement_basis = basis
        if suggested_abnormal is None:
            print("판정 제안: 판정 불가")
        else:
            result = "불량 후보" if suggested_abnormal else "정상 후보"
            print(f"판정 제안: {result}")
        print("판정 근거:")
        for item in basis:
            print(f"  - {item}")
        summary.automatic_judgement_correct = _read_yes_no(
            "이 판정 제안이 맞았습니까"
        )

    def _select_next_test_action(self) -> bool:
        """현재 힘을 보여주고 유지·조정·종료 중 다음 행동을 선택한다."""
        soft = self.config.soft_grip_setting
        hard = self.config.hard_grip_setting
        while True:
            print(
                f"\n현재 Grip 힘: Soft={soft['force_n']:g} N, "
                f"Hard={hard['force_n']:g} N\n"
                f"현재 Pull 제한: {self.config.pull_force_limit_n:g} N, "
                f"최대거리={self.config.pull_distance_limit_mm:g} mm"
            )
            if self.latest_recommendation is None:
                recommendation_menu = "3. 추천 설정 없음"
            else:
                recommendation_menu = (
                    "3. 추천 설정 적용 후 계속 "
                    f"(Soft={self.latest_recommendation['soft_grip_force_n']:g} N, "
                    f"Hard={self.latest_recommendation['hard_grip_force_n']:g} N, "
                    f"Pull={self.latest_recommendation['pull_force_limit_n']:g} N)"
                )
            print(
                "1. 현재 설정으로 계속\n"
                "2. 직접 조정 후 계속\n"
                f"{recommendation_menu}\n"
                "0. 시험 종료"
            )
            action = input("선택: ").strip()
            if action == "0":
                return False
            if action == "1":
                return True
            if action == "3":
                if self.latest_recommendation is None:
                    print("적용할 추천 설정이 없습니다.")
                    continue
                recommendation = self.latest_recommendation
                soft["force_n"] = recommendation["soft_grip_force_n"]
                hard["force_n"] = recommendation["hard_grip_force_n"]
                self.config.pull_force_limit_n = recommendation["pull_force_limit_n"]
                print(
                    "추천 설정을 다음 시험에 적용했습니다: "
                    f"Soft={soft['force_n']:g} N, "
                    f"Hard={hard['force_n']:g} N, "
                    f"Pull={self.config.pull_force_limit_n:g} N"
                )
                return True
            if action != "2":
                print("0, 1, 2, 3 중에서 선택하세요.")
                continue

            next_soft = _read_grip_force("다음 Soft Grip 힘 [N]")
            next_hard = _read_grip_force("다음 Hard Grip 힘 [N]")
            if next_hard < next_soft:
                print("Hard Grip 힘은 Soft Grip 힘 이상이어야 합니다.")
                continue
            soft["force_n"] = next_soft
            hard["force_n"] = next_hard
            self.config.pull_force_limit_n = _read_positive_number(
                "다음 Pull 정지 힘 [N]"
            )
            self.config.pull_distance_limit_mm = _read_positive_number(
                "다음 최대 Pull 거리 [mm]"
            )
            print(
                f"다음 시험 설정: Soft={next_soft:g} N, "
                f"Hard={next_hard:g} N, "
                f"Pull={self.config.pull_force_limit_n:g} N, "
                f"최대거리={self.config.pull_distance_limit_mm:g} mm"
            )
            return True

    def _recommend_next_settings(self, summary: TrialSummary) -> None:
        """손상 방지와 파지 안정성을 우선해 다음 시험조건을 제안한다."""
        soft_force = float(self.config.soft_grip_setting["force_n"])
        hard_force = float(self.config.hard_grip_setting["force_n"])
        pull_limit = float(self.config.pull_force_limit_n)
        reasons: list[str] = []

        if summary.grip_slip is True:
            hard_force = min(40.0, hard_force + 2.5)
            reasons.append("Grip Slip 발생: Hard Grip을 2.5 N 증가")

        if summary.cable_detached is True:
            safe_limit = _floor_force_step(summary.peak_pull_force_n * 0.7)
            pull_limit = min(pull_limit, max(5.0, safe_limit))
            reasons.append("Cable 이탈 관찰: Pull 힘 제한 축소")

        if summary.fixture_moved is True:
            pull_limit = min(pull_limit, 5.0)
            reasons.append("Fixture 이동: 다음 시험 Pull 힘을 보수적으로 제한")

        recommendation = {
            "soft_grip_force_n": soft_force,
            "hard_grip_force_n": hard_force,
            "pull_force_limit_n": pull_limit,
            "reasons": reasons or ["이상 관찰 없음: 현재 설정 유지"],
        }
        summary.setting_recommendation = recommendation
        self.latest_recommendation = recommendation
        print(
            "추천 설정: "
            f"Soft={soft_force:g} N, Hard={hard_force:g} N, "
            f"Pull={pull_limit:g} N"
        )
        for reason in recommendation["reasons"]:
            print(f"  - {reason}")

# ----------------------------------------------------------------------
# 실행 옵션과 시작·종료 처리
# ----------------------------------------------------------------------

def _read_yes_no(label: str) -> bool | None:
    """y/n/u 입력을 True/False/미확인으로 변환한다."""
    while True:
        value = input(f"{label} [y/n/u]: ").strip().lower()
        if value in {"y", "yes"}:
            return True
        if value in {"n", "no"}:
            return False
        if value in {"u", "unknown"}:
            return None
        print("y(예), n(아니오), u(미확인) 중 하나를 입력하세요.")


def _read_grip_force(label: str) -> float:
    """RG2가 지원하는 0~40 N, 2.5 N 단위의 힘을 입력받는다."""
    while True:
        try:
            force = float(input(f"{label} (0~40, 2.5 단위): ").strip())
        except ValueError:
            print("숫자로 입력하세요.")
            continue
        if 0.0 <= force <= 40.0 and abs(force / 2.5 - round(force / 2.5)) < 1e-9:
            return force
        print("0~40 N 범위에서 2.5 N 단위로 입력하세요.")


def _floor_force_step(force_n: float) -> float:
    """추천 힘을 RG2 조정 단위인 2.5 N 이하 방향으로 맞춘다."""
    return max(0.0, int(force_n / 2.5) * 2.5)


def _read_positive_number(label: str) -> float:
    """0보다 큰 시험 설정값을 입력받는다."""
    while True:
        try:
            value = float(input(f"{label}: ").strip())
        except ValueError:
            print("숫자로 입력하세요.")
            continue
        if value > 0.0:
            return value
        print("0보다 큰 값을 입력하세요.")


def select_settings(recipe: GripPullRecipe):
    """실행 모드와 초기 설정을 확인한다."""
    while True:
        print("\n[Grip 시험 설정]\n1. 가상모드\n2. 실물모드\n0. 종료")
        choice = input("모드 선택: ").strip()
        if choice == "0":
            return None
        if choice not in ("1", "2"):
            print("0, 1, 2 중에서 선택하세요.")
            continue
        mode = "virtual" if choice == "1" else "real"
        config = GripPullConfig()
        first_point = next(point for point in recipe.points.values() if point.enabled)
        if first_point.grip_setting is not None:
            config.soft_grip_setting["open_width_mm"] = first_point.grip_setting[
                "soft_open_width_mm"
            ]
            config.soft_grip_setting["close_width_mm"] = first_point.grip_setting[
                "soft_close_width_mm"
            ]
            config.hard_grip_setting["width_mm"] = first_point.grip_setting[
                "hard_width_mm"
            ]
        config.validate()
        print(f"\n모드: {mode} / 종료할 때까지 연속 시험")
        print(
            "실행 순서:",
            " → ".join(
                point.point_id for point in recipe.points.values() if point.enabled
            ),
        )
        for point in recipe.points.values():
            status = "사용" if point.enabled else "비활성(Joint 미확정)"
            print(f"{point.point_id} [{status}]: Ready={point.ready_pose.joint}")
            print(f"  Entry={point.entry_pose.joint}, 진입={point.entry_depth_mm} mm")
        print(f"Soft Grip: {config.soft_grip_setting}")
        print(
                "Entry 이동 시작 폭: "
                f"{config.soft_grip_setting['open_width_mm']} mm 이하"
        )
        print(f"Hard Grip: {config.hard_grip_setting}")
        print(f"Pull: 최대 {config.pull_distance_limit_mm} mm / "
              f"정지하중 {config.pull_force_limit_n} N")
        print("1. 설정 확인 후 실행\n2. 모드 선택으로 돌아가기\n0. 종료")
        answer = input("선택: ").strip()
        if answer == "1":
            return mode, config
        if answer == "0":
            return None


def execute_test(recipe: GripPullRecipe, mode: str, config: GripPullConfig) -> int:
    """확인한 설정으로 시험을 실행하고 연결을 정리한다."""
    rclpy.init(args=[])
    hardware: GripPullRobot | None = None
    try:
        hardware = GripPullRobot(mode=mode)
        output_dir = OUTPUT_DIR
        if mode == "virtual":
            output_dir = output_dir / "virtual"
        hardware.wait_for_services()
        test = GripStabilityTest(
            recipe=recipe,
            config=config,
            hardware=hardware,
            output_dir=output_dir,
        )
        test.run()
        if any(summary.abnormal_stop for summary in test.logger.summaries):
            print(f"시험 비정상 종료: {test.logger.result_dir}")
            return 1
        print(f"시험 완료: {test.logger.result_dir}")
        return 0
    except (KeyboardInterrupt, ExternalShutdownException):
        if hardware is not None:
            hardware.safe_abort()
        print("사용자 중단으로 로봇을 정지했습니다.")
        return 130
    except Exception as error:
        if hardware is not None:
            hardware.safe_abort()
        print(f"시험 중단: {error}")
        return 1
    finally:
        if hardware is not None:
            hardware.close()
        if rclpy.ok():
            rclpy.shutdown()


def select_recipe_path() -> Path | None:
    """USB 또는 LAN 검사 레시피를 선택한다."""
    while True:
        print("\n[검사 레시피]\n1. USB\n2. LAN (LAN_L2)\n0. 종료")
        choice = input("레시피 선택: ").strip()
        if choice == "0":
            return None
        if choice in RECIPE_OPTIONS:
            name, path = RECIPE_OPTIONS[choice]
            print(f"선택 레시피: {name} / {path.name}")
            return path
        print("0, 1, 2 중에서 선택하세요.")


def main() -> int:
    """시험이 끝나거나 취소되면 설정 메뉴로 돌아간다."""
    while True:
        try:
            recipe_path = select_recipe_path()
            if recipe_path is None:
                return 0
            recipe = GripPullRecipe.load_json(recipe_path)
            settings = select_settings(recipe)
            if settings is None:
                return 0
            mode, config = settings
            execute_test(recipe, mode, config)
        except (KeyboardInterrupt, EOFError):
            print("\n프로그램을 종료합니다.")
            return 0
        except Exception as error:
            print(f"설정 오류: {error}")
            return 1


if __name__ == "__main__":
    raise SystemExit(main())
