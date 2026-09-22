"""실제 검사 작업에서 사용할 검사포인트 위치 레시피.

이 모듈은 로봇을 움직이지 않으며 검사 조건이나 시험 시퀀스를 포함하지 않는다.
검사포인트 번호별 BASE TASK·JOINT 위치를 저장하고 조회하는 역할만 담당한다.
"""

import json
import math
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class InspectionPoint:
    """하나의 검사포인트를 식별하는 번호와 로봇 위치정보."""

    point_id: str
    point_name: str
    task: list[float]
    joint: list[float]
    coordinate_frame: str = "BASE"
    solution_space: int | None = None

    def validate(self) -> None:
        """포인트 식별자와 좌표 형식을 확인한다."""
        if not self.point_id.strip():
            raise ValueError("point_id는 비어 있을 수 없습니다.")
        if not self.point_name.strip():
            raise ValueError(f"{self.point_id}: point_name이 비어 있습니다.")
        if self.coordinate_frame != "BASE":
            raise ValueError(
                f"{self.point_id}: 현재는 BASE 좌표계만 지원합니다."
            )

        self._validate_pose(self.task, "task")
        self._validate_pose(self.joint, "joint")
        if self.solution_space is not None and not 0 <= self.solution_space <= 7:
            raise ValueError(
                f"{self.point_id}: solution_space는 0~7 또는 미지정이어야 합니다."
            )

    def to_dict(self) -> dict[str, Any]:
        """JSON 저장이 가능한 dict로 변환한다."""
        return asdict(self)

    @staticmethod
    def _validate_pose(values: list[float], name: str) -> None:
        if len(values) != 6:
            raise ValueError(f"{name} 좌표는 6개 값이어야 합니다.")
        if not all(math.isfinite(value) for value in values):
            raise ValueError(f"{name} 좌표에 유효하지 않은 숫자가 있습니다.")


@dataclass
class InspectionRecipe:
    """검사포인트 위치 목록을 ID로 관리하는 실제 작업용 레시피."""

    recipe_id: str
    recipe_version: str
    points: dict[str, InspectionPoint]
    source_point_id: str | None = None
    test_axis: str | None = None
    sequence: list[str] = field(default_factory=list)

    def validate(self) -> None:
        """레시피 식별자와 모든 검사포인트를 검증한다."""
        if not self.recipe_id.strip():
            raise ValueError("recipe_id는 비어 있을 수 없습니다.")
        if not self.recipe_version.strip():
            raise ValueError("recipe_version은 비어 있을 수 없습니다.")
        if not self.points:
            raise ValueError("검사포인트가 한 개 이상 필요합니다.")

        for key, point in self.points.items():
            point.validate()
            if key != point.point_id:
                raise ValueError(
                    f"points 키 {key}와 point_id {point.point_id}가 다릅니다."
                )

        if self.test_axis is not None and self.test_axis not in {"Y", "Z"}:
            raise ValueError("test_axis는 Y, Z 또는 미지정이어야 합니다.")

        if self.sequence:
            missing_points = [
                point_id
                for point_id in self.sequence
                if point_id not in self.points
            ]
            if missing_points:
                raise ValueError(
                    "sequence에 정의되지 않은 포인트가 있습니다: "
                    + ", ".join(missing_points)
                )

    def get_point(self, point_id: str) -> InspectionPoint:
        """포인트 번호로 위치정보를 조회한다."""
        try:
            return self.points[point_id]
        except KeyError as error:
            available = ", ".join(sorted(self.points))
            raise KeyError(
                f"검사포인트 {point_id}가 없습니다. 사용 가능: {available}"
            ) from error

    def to_dict(self) -> dict[str, Any]:
        """레시피를 JSON 저장이 가능한 dict로 변환한다."""
        data = {
            "recipe_id": self.recipe_id,
            "recipe_version": self.recipe_version,
            "points": {
                point_id: point.to_dict()
                for point_id, point in self.points.items()
            },
        }

        if self.source_point_id is not None:
            data["source_point_id"] = self.source_point_id
        if self.test_axis is not None:
            data["test_axis"] = self.test_axis
        if self.sequence:
            data["sequence"] = self.sequence[:]

        return data

    def save_json(self, path: str | Path) -> None:
        """레시피를 UTF-8 JSON 파일로 저장한다."""
        self.validate()
        output_path = Path(path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(
            json.dumps(self.to_dict(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "InspectionRecipe":
        """dict에서 검사포인트 레시피를 생성한다."""
        raw_points = data.get("points")
        if not isinstance(raw_points, dict):
            raise ValueError("points는 point_id를 키로 갖는 객체여야 합니다.")

        points = {
            point_id: InspectionPoint(**point_data)
            for point_id, point_data in raw_points.items()
        }

        recipe = cls(
            recipe_id=data["recipe_id"],
            recipe_version=data["recipe_version"],
            points=points,
            source_point_id=data.get("source_point_id"),
            test_axis=data.get("test_axis"),
            sequence=list(data.get("sequence", [])),
        )
        recipe.validate()
        return recipe

    @classmethod
    def load_json(cls, path: str | Path) -> "InspectionRecipe":
        """UTF-8 JSON 파일에서 레시피를 불러온다."""
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError("레시피 JSON 최상위 값은 객체여야 합니다.")

        return cls.from_dict(data)


@dataclass(frozen=True)
class RobotPose:
    """Point Transition에서 사용하는 TASK와 JOINT 한 쌍이다."""

    task: list[float]
    joint: list[float]

    def validate(self, name: str) -> None:
        InspectionPoint._validate_pose(self.task, f"{name}.task")
        InspectionPoint._validate_pose(self.joint, f"{name}.joint")


@dataclass(frozen=True)
class OperatingInspectionPoint:
    """#03~#05 실행에 필요한 검사포인트 조건 전체를 보관한다."""

    point_id: str
    point_name: str
    enabled: bool
    ready_pose: RobotPose
    entry_pose: RobotPose
    entry_direction: list[float]
    entry_setting: dict[str, float]
    grip_setting: dict[str, float]
    pull_setting: dict[str, float]

    def normalized_entry_direction(self) -> list[float]:
        length = math.sqrt(sum(value * value for value in self.entry_direction))
        return [value / length for value in self.entry_direction]

    def validate(self) -> None:
        self.ready_pose.validate("ready_pose")
        self.entry_pose.validate("entry_pose")
        if len(self.entry_direction) != 3:
            raise ValueError(f"{self.point_id}: entry_direction은 3개 값이어야 합니다.")
        if not all(math.isfinite(value) for value in self.entry_direction):
            raise ValueError(f"{self.point_id}: entry_direction 값이 유효하지 않습니다.")
        if math.sqrt(sum(value * value for value in self.entry_direction)) == 0:
            raise ValueError(f"{self.point_id}: entry_direction은 0 벡터일 수 없습니다.")
        required = {
            "entry_setting": (self.entry_setting, (
                "max_distance_mm", "force_guard_n", "timeout_s")),
            "grip_setting": (self.grip_setting, (
                "soft_close_width_mm", "soft_open_width_mm", "hard_width_mm",
                "soft_force_n", "hard_force_n")),
            "pull_setting": (self.pull_setting, (
                "force_limit_n", "max_distance_mm", "timeout_s", "speed_mm_s",
                "normal_displacement_limit_mm")),
        }
        for group_name, (group, keys) in required.items():
            for key in keys:
                value = group.get(key)
                if not isinstance(value, (int, float)) or value <= 0 or not math.isfinite(value):
                    raise ValueError(f"{self.point_id}: {group_name}.{key}가 유효하지 않습니다.")
        if self.entry_setting["max_distance_mm"] > 25.0:
            raise ValueError(f"{self.point_id}: Entry 최대거리는 25 mm 이하여야 합니다.")


@dataclass
class OperatingInspectionRecipe:
    """Recipe 순서와 #03~#05 Point 조건을 함께 관리한다."""

    recipe_id: str
    recipe_version: str
    coordinate_frame: str
    connector_type: str
    execution_order: list[str]
    points: dict[str, OperatingInspectionPoint]

    def validate(self) -> None:
        if self.coordinate_frame != "BASE":
            raise ValueError("현재 운영 Recipe는 BASE 좌표계만 지원합니다.")
        if len(self.execution_order) != len(set(self.execution_order)):
            raise ValueError("execution_order에 중복 Point가 있습니다.")
        for point_id in self.execution_order:
            if point_id not in self.points:
                raise ValueError(f"execution_order의 {point_id}가 points에 없습니다.")
        for key, point in self.points.items():
            if key != point.point_id:
                raise ValueError(f"points 키 {key}와 point_id가 다릅니다.")
            point.validate()

    @classmethod
    def load_json(cls, path: str | Path) -> "OperatingInspectionRecipe":
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        points = {
            point_id: OperatingInspectionPoint(
                **{**raw, "ready_pose": RobotPose(**raw["ready_pose"]),
                   "entry_pose": RobotPose(**raw["entry_pose"])},
            )
            for point_id, raw in data["points"].items()
        }
        recipe = cls(
            recipe_id=data["recipe_id"],
            recipe_version=data["recipe_version"],
            coordinate_frame=data["coordinate_frame"],
            connector_type=data["connector_type"],
            execution_order=list(data["execution_order"]),
            points=points,
        )
        recipe.validate()
        return recipe
