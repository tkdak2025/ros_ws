"""실제 검사 작업에서 사용할 검사포인트 위치 레시피.

이 모듈은 로봇을 움직이지 않으며 검사 조건이나 시험 시퀀스를 포함하지 않는다.
검사포인트 번호별 BASE TASK·JOINT 위치를 저장하고 조회하는 역할만 담당한다.
"""

import json
import math
from dataclasses import asdict, dataclass
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
        return {
            "recipe_id": self.recipe_id,
            "recipe_version": self.recipe_version,
            "points": {
                point_id: point.to_dict()
                for point_id, point in self.points.items()
            },
        }

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
