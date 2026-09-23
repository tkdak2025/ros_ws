"""검사 레시피와 독립적으로 TCP 작업영역을 판정한다.

이 모듈은 목표 TCP만 검사한다. MoveJ 중간 경로, 로봇 링크, 그리퍼, 케이블의
충돌 여부는 별도의 충돌 검사기가 담당해야 한다.
"""

import math
from dataclasses import dataclass


@dataclass(frozen=True)
class BoxBoundary:
    """BASE 좌표계의 축 정렬 직육면체 영역."""

    x_min_mm: float
    x_max_mm: float
    y_min_mm: float
    y_max_mm: float
    z_min_mm: float
    z_max_mm: float

    def validate(self, name: str) -> None:
        values = (
            self.x_min_mm,
            self.x_max_mm,
            self.y_min_mm,
            self.y_max_mm,
            self.z_min_mm,
            self.z_max_mm,
        )
        if not all(math.isfinite(value) for value in values):
            raise ValueError(f"{name} 경계에 유효하지 않은 숫자가 있습니다.")

        for axis, minimum, maximum in (
            ("X", self.x_min_mm, self.x_max_mm),
            ("Y", self.y_min_mm, self.y_max_mm),
            ("Z", self.z_min_mm, self.z_max_mm),
        ):
            if minimum >= maximum:
                raise ValueError(
                    f"{name}의 {axis} 최소값은 최대값보다 작아야 합니다."
                )

    def contains_inside(self, xyz: list[float], margin_mm: float) -> bool:
        """안전 여유만큼 축소한 영역 안에 TCP가 있는지 확인한다."""
        x, y, z = xyz
        return (
            self.x_min_mm + margin_mm <= x <= self.x_max_mm - margin_mm
            and self.y_min_mm + margin_mm <= y <= self.y_max_mm - margin_mm
            and self.z_min_mm + margin_mm <= z <= self.z_max_mm - margin_mm
        )

    def contains_expanded(self, xyz: list[float], margin_mm: float) -> bool:
        """안전 여유만큼 확장한 영역 안에 TCP가 있는지 확인한다."""
        x, y, z = xyz
        return (
            self.x_min_mm - margin_mm <= x <= self.x_max_mm + margin_mm
            and self.y_min_mm - margin_mm <= y <= self.y_max_mm + margin_mm
            and self.z_min_mm - margin_mm <= z <= self.z_max_mm + margin_mm
        )


@dataclass(frozen=True)
class ForbiddenRegion:
    """이름이 지정된 TCP 금지영역."""

    name: str
    boundary: BoxBoundary


@dataclass(frozen=True)
class BoundaryCheckResult:
    """TCP 작업영역 판정 결과."""

    allowed: bool
    reasons: tuple[str, ...]


@dataclass
class WorkspaceBoundary:
    """허용 작업영역과 금지영역을 이용해 목표 TCP를 판정한다."""

    allowed_workspace: BoxBoundary
    forbidden_regions: list[ForbiddenRegion]
    safety_margin_mm: float = 0.0

    def validate(self) -> None:
        self.allowed_workspace.validate("허용 작업영역")

        if not math.isfinite(self.safety_margin_mm) or self.safety_margin_mm < 0:
            raise ValueError("safety_margin_mm은 0 이상의 유한값이어야 합니다.")

        for region in self.forbidden_regions:
            if not region.name.strip():
                raise ValueError("금지영역 이름은 비어 있을 수 없습니다.")
            region.boundary.validate(f"금지영역 {region.name}")

    def check_task(self, task: list[float]) -> BoundaryCheckResult:
        """TASK의 XYZ가 허용영역 안이고 금지영역 밖인지 검사한다."""
        if len(task) != 6 or not all(math.isfinite(value) for value in task):
            raise ValueError("TASK는 6개의 유효한 숫자여야 합니다.")

        xyz = task[:3]
        reasons = []

        if not self.allowed_workspace.contains_inside(xyz, self.safety_margin_mm):
            reasons.append("허용 작업영역 밖이거나 안전 여유를 침범함")

        for region in self.forbidden_regions:
            if region.boundary.contains_expanded(xyz, self.safety_margin_mm):
                reasons.append(f"금지영역 침범: {region.name}")

        return BoundaryCheckResult(
            allowed=not reasons,
            reasons=tuple(reasons),
        )
