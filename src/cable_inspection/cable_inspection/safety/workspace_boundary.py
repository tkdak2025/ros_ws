"""Home Return 분기에 사용하는 BASE 기준 TCP 작업영역 경계."""

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
