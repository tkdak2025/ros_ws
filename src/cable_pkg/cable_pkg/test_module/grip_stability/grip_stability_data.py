"""Grip 시험의 레시피·조건·결과 파일을 관리한다.

로봇 제어는 하지 않는다. 시험 수치는 GripPullConfig에서 수정하고,
검사포인트 좌표는 recipe/grip_stability/grip_pull_recipe.json에서 수정한다.
"""

import csv
import json
import math
from dataclasses import asdict, dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any

# ----------------------------------------------------------------------
# 레시피와 시험 설정
# ----------------------------------------------------------------------


@dataclass(frozen=True)
class Pose:
    task: list[float]
    joint: list[float] | None = None

    def validate(self, name: str) -> None:
        _validate_numbers(self.task, 6, f"{name}.task")
        if self.joint is not None:
            _validate_numbers(self.joint, 6, f"{name}.joint")


@dataclass(frozen=True)
class GripPullPoint:
    point_id: str
    point_name: str
    cable_condition: dict[str, Any] | None
    enabled: bool
    ready_pose: Pose
    entry_pose: Pose
    entry_direction: list[float]
    entry_depth_mm: float
    grip_setting: dict[str, float] | None = None
    pull_setting: dict[str, float] | None = None

    def validate(self) -> None:
        if not self.point_id.strip() or not self.point_name.strip():
            raise ValueError("point_id와 point_name은 비어 있을 수 없습니다.")
        if self.cable_condition is not None:
            for key in ("connector_type", "cable_type", "expected_state"):
                if not str(self.cable_condition.get(key, "")).strip():
                    raise ValueError(f"cable_condition.{key}가 필요합니다.")
            direction = self.cable_condition.get("connection_direction")
            if not isinstance(direction, list):
                raise ValueError("cable_condition.connection_direction이 필요합니다.")
            _validate_numbers(direction, 3, "cable_condition.connection_direction")
            if math.isclose(_vector_length(direction), 0.0):
                raise ValueError("connection_direction은 0 벡터일 수 없습니다.")
        self.ready_pose.validate("ready_pose")
        self.entry_pose.validate("entry_pose")
        if self.ready_pose.joint is None:
            raise ValueError("ready_pose.joint는 필수입니다.")
        _validate_numbers(self.entry_direction, 3, "entry_direction")
        if math.isclose(_vector_length(self.entry_direction), 0.0):
            raise ValueError("entry_direction은 0 벡터일 수 없습니다.")
        if not math.isfinite(self.entry_depth_mm) or self.entry_depth_mm <= 0.0:
            raise ValueError("entry_depth_mm은 0보다 커야 합니다.")
        if self.enabled and self.entry_pose.joint is None:
            raise ValueError(f"{self.point_id}: entry_pose.joint가 필요합니다.")
        if self.grip_setting is not None:
            required = (
                "soft_open_width_mm",
                "soft_close_width_mm",
                "hard_width_mm",
            )
            for key in required:
                value = self.grip_setting.get(key)
                if value is None or not math.isfinite(float(value)):
                    raise ValueError(f"grip_setting.{key}가 필요합니다.")
                if not 0.0 <= float(value) <= 110.0:
                    raise ValueError(f"grip_setting.{key} 범위는 0~110 mm입니다.")
            if self.grip_setting["soft_open_width_mm"] < self.grip_setting[
                "soft_close_width_mm"
            ]:
                raise ValueError("Soft Open 폭은 Soft Close 폭 이상이어야 합니다.")
        if self.pull_setting is not None:
            for key in ("force_limit_n", "max_distance_mm", "timeout_s", "speed_mm_s"):
                value = self.pull_setting.get(key)
                if value is None or not math.isfinite(float(value)) or float(value) <= 0:
                    raise ValueError(f"pull_setting.{key}는 0보다 큰 값이어야 합니다.")

    def normalized_entry_direction(self) -> list[float]:
        """이 검사포인트의 Depth 진입축을 단위벡터로 반환한다."""
        length = _vector_length(self.entry_direction)
        return [value / length for value in self.entry_direction]

    def pull_direction(self) -> list[float]:
        """이 검사포인트 진입축의 반대방향을 반환한다."""
        return [-value for value in self.normalized_entry_direction()]


@dataclass(frozen=True)
class GripPullRecipe:
    recipe_id: str
    recipe_version: str
    coordinate_frame: str
    points: dict[str, GripPullPoint]

    def validate(self) -> None:
        if not self.recipe_id.strip() or not self.recipe_version.strip():
            raise ValueError("recipe_id와 recipe_version은 필수입니다.")
        if self.coordinate_frame != "BASE":
            raise ValueError("현재 단위시험은 BASE 좌표계만 지원합니다.")
        if not self.points:
            raise ValueError("검사포인트가 한 개 이상 필요합니다.")
        if not any(point.enabled for point in self.points.values()):
            raise ValueError("활성 검사포인트가 한 개 이상 필요합니다.")

        for key, point in self.points.items():
            point.validate()
            if key != point.point_id:
                raise ValueError(f"points 키 {key}와 point_id가 다릅니다.")

    def get_point(self, point_id: str) -> GripPullPoint:
        try:
            return self.points[point_id]
        except KeyError as error:
            raise KeyError(f"정의되지 않은 검사포인트입니다: {point_id}") from error

    @classmethod
    def load_json(cls, path: str | Path) -> "GripPullRecipe":
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        points = {
            point_id: GripPullPoint(
                point_id=raw["point_id"],
                point_name=raw["point_name"],
                cable_condition=raw.get("cable_condition"),
                enabled=bool(raw.get("enabled", True)),
                ready_pose=Pose(**raw["ready_pose"]),
                entry_pose=Pose(**raw["entry_pose"]),
                entry_direction=[
                    raw["entry_direction"][axis] for axis in "xyz"
                ],
                entry_depth_mm=float(raw["entry_depth_mm"]),
                grip_setting=(
                    {
                        key: float(value)
                        for key, value in raw["grip_setting"].items()
                    }
                    if "grip_setting" in raw
                    else None
                ),
                pull_setting=(
                    {key: float(value) for key, value in raw["pull_setting"].items()}
                    if "pull_setting" in raw else None
                ),
            )
            for point_id, raw in data["points"].items()
        }
        recipe = cls(
            recipe_id=data["recipe_id"],
            recipe_version=data["recipe_version"],
            coordinate_frame=data["coordinate_frame"],
            points=points,
        )
        recipe.validate()
        return recipe


@dataclass
class GripPullConfig:
    """2-Stage Grip과 Pull 반복시험의 공통 조건."""

    soft_grip_setting: dict[str, float] | None = field(
        default_factory=lambda: {
            "open_width_mm": 22.0,
            "close_width_mm": 18.0,
            "force_n": 10.0,
        }
    )
    gripper_preclose_timeout_s: float = 20.0
    hard_grip_setting: dict[str, float] | None = field(
        default_factory=lambda: {"width_mm": 5.0, "force_n": 40.0}
    )
    pull_force_limit_n: float = 25.0
    entry_speed_mm_s: float = 10.0
    entry_timeout_s: float = 20.0
    pull_speed_mm_s: float = 10.0
    pull_distance_limit_mm: float = 50.0
    pull_timeout_s: float = 20.0
    grip_stabilization_time_s: float = 1.0
    logging_rate_hz: float = 20.0

    def validate(self) -> None:
        if self.soft_grip_setting is None or self.hard_grip_setting is None:
            raise ValueError("Soft/Hard Grip 설정이 필요합니다.")

        positive_values = {
            "pull_force_limit_n": self.pull_force_limit_n,
            "entry_speed_mm_s": self.entry_speed_mm_s,
            "entry_timeout_s": self.entry_timeout_s,
            "pull_speed_mm_s": self.pull_speed_mm_s,
            "pull_distance_limit_mm": self.pull_distance_limit_mm,
            "pull_timeout_s": self.pull_timeout_s,
            "logging_rate_hz": self.logging_rate_hz,
            "gripper_preclose_timeout_s": self.gripper_preclose_timeout_s,
        }
        for name, value in positive_values.items():
            if not math.isfinite(value) or value <= 0.0:
                raise ValueError(f"{name}은 0보다 커야 합니다.")
        soft_open = float(self.soft_grip_setting["open_width_mm"])
        soft_close = float(self.soft_grip_setting["close_width_mm"])
        if soft_open < soft_close:
            raise ValueError("Soft Grip open 폭은 close 폭 이상이어야 합니다.")

    def soft_grip_open_command(self) -> dict[str, float]:
        """Soft Grip Open 폭과 현재 힘을 RG2 명령 형식으로 반환한다."""
        return {
            "width_mm": float(self.soft_grip_setting["open_width_mm"]),
            "force_n": float(self.soft_grip_setting["force_n"]),
        }

    def soft_grip_close_command(self) -> dict[str, float]:
        """Soft Grip Close 폭과 현재 힘을 RG2 명령 형식으로 반환한다."""
        return {
            "width_mm": float(self.soft_grip_setting["close_width_mm"]),
            "force_n": float(self.soft_grip_setting["force_n"]),
        }
        if self.grip_stabilization_time_s < 0.0:
            raise ValueError("grip_stabilization_time_s는 0 이상이어야 합니다.")

# ----------------------------------------------------------------------
# 시험 상태와 결과
# ----------------------------------------------------------------------


class TestState(str, Enum):
    INIT = "INIT"
    LOAD_RECIPE = "LOAD_RECIPE"
    MOVE_READY = "MOVE_READY"
    PREPARE_SOFT_GRIP = "PREPARE_SOFT_GRIP"
    MOVE_ENTRY = "MOVE_ENTRY"
    SOFT_GRIP_ENTRY = "SOFT_GRIP_ENTRY"
    HARD_GRIP = "HARD_GRIP"
    PULL_PREPARE = "PULL_PREPARE"
    PULL_TEST = "PULL_TEST"
    PULL_STOP = "PULL_STOP"
    SAVE_RESULT = "SAVE_RESULT"
    RELEASE = "RELEASE"
    RETURN_READY = "RETURN_READY"
    NEXT_TEST = "NEXT_TEST"
    DONE = "DONE"
    SAFE_ABORT = "SAFE_ABORT"


@dataclass
class TrialSummary:
    trial_id: str
    inspection_point_id: str
    cable_condition: dict[str, Any] | None = None
    soft_grip_setting: dict[str, float] | None = None
    hard_grip_setting: dict[str, float] | None = None
    soft_grip_completed: bool = False
    hard_grip_completed: bool = False
    entry_depth_at_stop_mm: float = 0.0
    peak_entry_force_n: float = 0.0
    entry_force_baseline_base: list[float] | None = None
    entry_force_baseline_tool: list[float] | None = None
    peak_pull_force_n: float = 0.0
    pull_displacement_at_stop_mm: float = 0.0
    force_limit_reached: bool = False
    pull_force_baseline_base: list[float] | None = None
    pull_force_baseline_tool: list[float] | None = None
    cable_detached: bool | None = None
    grip_slip: bool | None = None
    fixture_moved: bool | None = None
    automatic_connection_abnormal: bool | None = None
    automatic_evaluation: dict[str, Any] | None = None
    automatic_judgement_correct: bool | None = None
    suggested_connection_abnormal: bool | None = None
    judgement_basis: list[str] | None = None
    setting_recommendation: dict[str, Any] | None = None
    abnormal_stop: bool = False
    stop_reason: str = "not_started"


# ----------------------------------------------------------------------
# CSV 및 Summary 저장
# ----------------------------------------------------------------------


class GripPullLogger:
    CSV_FIELDS = (
        "timestamp", "trial_id", "inspection_point_id", "state", "grip_event",
        "tcp_x", "tcp_y", "tcp_z", "tcp_rx", "tcp_ry", "tcp_rz",
        "base_fx", "base_fy", "base_fz", "base_tx", "base_ty", "base_tz",
        "base_dfx", "base_dfy", "base_dfz", "base_dtx", "base_dty", "base_dtz",
        "tool_fx", "tool_fy", "tool_fz", "tool_tx", "tool_ty", "tool_tz",
        "tool_dfx", "tool_dfy", "tool_dfz", "tool_dtx", "tool_dty", "tool_dtz",
        "entry_force_n", "entry_depth_mm",
        "pull_force_n", "pull_displacement_mm",
        "gripper_width", "gripper_state",
    )

    def __init__(
        self,
        output_dir: str | Path,
        recipe: GripPullRecipe,
        config: GripPullConfig,
    ) -> None:
        name = f"grip_stability_{datetime.now():%Y%m%d_%H%M%S}"
        self.result_dir = Path(output_dir) / name
        self.result_dir.mkdir(parents=True, exist_ok=False)
        self.csv_path = self.result_dir / "pull_measurements.csv"
        self.summary_path = self.result_dir / "trial_summaries.json"
        self.recipe = recipe
        self.config = config
        self.summaries: list[TrialSummary] = []
        self.run_metadata: dict[str, Any] = {}
        self.stream = self.csv_path.open("x", newline="", encoding="utf-8")
        self.writer = csv.DictWriter(self.stream, fieldnames=self.CSV_FIELDS)
        self.writer.writeheader()

    def write_sample(self, row: dict[str, Any]) -> None:
        self.writer.writerow(row)
        self.stream.flush()

    def add_summary(self, summary: TrialSummary) -> None:
        self.summaries.append(summary)

    def close(self) -> None:
        if not self.stream.closed:
            self.stream.close()
        data = {
            "schema_version": 1,
            "run_metadata": self.run_metadata,
            "test_type": "two_stage_approach_and_grip_pull_baseline",
            "force_limit_note": (
                f"{self.config.pull_force_limit_n:g} N is a stop limit, "
                "not PASS/FAIL"
            ),
            "recipe_id": self.recipe.recipe_id,
            "recipe_version": self.recipe.recipe_version,
            "test_conditions": {
                "entry_speed_mm_s": self.config.entry_speed_mm_s,
                "soft_grip_setting": self.config.soft_grip_setting,
                "entry_motion_start_width_mm": (
                    self.config.soft_grip_setting["open_width_mm"]
                ),
                "gripper_preclose_timeout_s": (
                    self.config.gripper_preclose_timeout_s
                ),
                "max_entry_depth_note": "point.entry_depth_mm",
                "entry_timeout_s": self.config.entry_timeout_s,
                "pull_speed_mm_s": self.config.pull_speed_mm_s,
                "pull_distance_limit_mm": self.config.pull_distance_limit_mm,
                "pull_force_limit_n": self.config.pull_force_limit_n,
                "pull_timeout_s": self.config.pull_timeout_s,
                "grip_stabilization_time_s": (
                    self.config.grip_stabilization_time_s
                ),
                "logging_rate_hz": self.config.logging_rate_hz,
                "completed_test_count": len(self.summaries),
            },
            "trials": [asdict(summary) for summary in self.summaries],
        }
        self.summary_path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

def _validate_numbers(values: list[float], length: int, name: str) -> None:
    valid = (
        len(values) == length
        and all(
            isinstance(value, (int, float))
            and not isinstance(value, bool)
            and math.isfinite(value)
            for value in values
        )
    )
    if not valid:
        raise ValueError(f"{name}은 {length}개의 유효한 숫자여야 합니다.")


def _vector_length(values: list[float]) -> float:
    return math.sqrt(sum(value * value for value in values))


def _dot(first: list[float], second: list[float]) -> float:
    return sum(a * b for a, b in zip(first, second))


def _round_optional(value: float | None) -> float | None:
    return None if value is None else round(value, 4)


def _wrench_columns(
    prefix: str,
    current: list[float],
    baseline: list[float],
) -> dict[str, float]:
    """BASE/TOOL Wrench 현재값과 초기값 대비 변화량 열을 만든다."""
    axes = ("fx", "fy", "fz", "tx", "ty", "tz")
    values = {
        f"{prefix}_{axis}": round(current[index], 4)
        for index, axis in enumerate(axes)
    }
    values.update(
        {
            f"{prefix}_d{axis}": round(current[index] - baseline[index], 4)
            for index, axis in enumerate(axes)
        }
    )
    return values
