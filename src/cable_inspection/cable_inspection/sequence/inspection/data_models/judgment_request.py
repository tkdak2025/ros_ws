"""#05가 비동기 #06 Judgment 노드에 전달하는 측정 데이터."""

from __future__ import annotations
from dataclasses import dataclass
from typing import Any
from cable_inspection.sequence.inspection.data_models.pull_termination import PullTermination



@dataclass(frozen=True)
class JudgmentRequest:
    """#05가 비동기 #06 Judgment 노드에 전달하는 측정 데이터."""

    run_id: int
    recipe_id: str
    recipe_version: str
    point_id: str
    point_name: str
    connector_type: str
    peak_pull_force_n: float
    pull_displacement_mm: float
    termination_reason: PullTermination
    required_force_n: float
    normal_displacement_limit_mm: float
    entry_task: list[float]
    entry_joint: list[float]
    force_data_id: str = ""
    error_reason: str = ""
    soft_width_mm: float | None = None
    pull_width_mm: float | None = None



    def to_dict(self) -> dict[str, Any]:
        data = self.__dict__.copy()
        data["termination_reason"] = self.termination_reason.value

        return data



    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "JudgmentRequest":
        # 식별 가능한 요청은 누락/잘못된 측정값도 INVALID_DATA 결과로 남긴다.
        data = dict(data)

        for name in ("peak_pull_force_n", "pull_displacement_mm", "required_force_n",
                     "normal_displacement_limit_mm"):
            data.setdefault(name, None)

        try:
            data["termination_reason"] = PullTermination(data.get("termination_reason"))

        except ValueError:
            data["termination_reason"] = PullTermination.INVALID_DATA

        from dataclasses import fields
        names = {item.name for item in fields(cls)}

        return cls(**{key: value for key, value in data.items() if key in names})
