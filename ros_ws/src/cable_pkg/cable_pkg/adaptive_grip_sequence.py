"""Adaptive Grip 작업검증계획서 v0.1의 단계와 Gate를 실행한다.

이 파일은 검증 순서를 관리한다. 아직 수치와 판정식이 확정되지 않은 로봇,
그리퍼, 힘 제어 동작은 임의로 구현하지 않고 단계별 메서드로 분리한다.
"""

import json
import math
from dataclasses import asdict, dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any


# ----------------------------------------------------------------------
# 검증 단계와 결과
# ----------------------------------------------------------------------


class ValidationStage(str, Enum):
    """작업검증계획서 V01~V09의 실행 순서."""

    RECIPE = "V01_RECIPE"
    READY_ENTRY = "V02_READY_ENTRY"
    DEPTH_COMPENSATION = "V03_DEPTH_COMPENSATION"
    SOFT_GRIP = "V04_SOFT_GRIP"
    MICRO_WIGGLE = "V05_MICRO_WIGGLE"
    FINE_ALIGNMENT = "V06_FINE_ALIGNMENT"
    HARD_GRIP = "V07_HARD_GRIP"
    GRIP_STABILITY = "V08_GRIP_STABILITY"
    GRIP_PULL_LOGGING = "V09_GRIP_PULL_LOGGING"


@dataclass(frozen=True)
class StageResult:
    """한 단계의 Gate 판정과 다음 단계에 전달할 데이터."""

    stage: ValidationStage
    passed: bool
    message: str
    data: dict[str, Any] = field(default_factory=dict)


# ----------------------------------------------------------------------
# Adaptive Grip 검사포인트 입력
# ----------------------------------------------------------------------


@dataclass(frozen=True)
class AdaptiveGripPoint:
    """Adaptive Grip 시퀀스에 필요한 Nominal 위치와 진입 조건."""

    recipe_id: str
    point_id: str
    point_name: str
    nominal_task: list[float]
    connector_axis: list[float]
    ready_joint: list[float]
    entry_task: list[float]
    depth_offset_mm: float
    search_range_mm: float

    def validate(self) -> None:
        """V01에서 요구하는 필수 레시피 정보를 검증한다."""
        for name, value in (
            ("recipe_id", self.recipe_id),
            ("point_id", self.point_id),
            ("point_name", self.point_name),
        ):
            if not value.strip():
                raise ValueError(f"{name}은 비어 있을 수 없습니다.")

        self._validate_vector(self.nominal_task, 6, "nominal_task")
        self._validate_vector(self.connector_axis, 3, "connector_axis")
        self._validate_vector(self.ready_joint, 6, "ready_joint")
        self._validate_vector(self.entry_task, 6, "entry_task")

        axis_length = math.sqrt(sum(value * value for value in self.connector_axis))
        if axis_length <= 0.0:
            raise ValueError("connector_axis는 0 벡터일 수 없습니다.")
        if not math.isfinite(self.depth_offset_mm):
            raise ValueError("depth_offset_mm은 유효한 숫자여야 합니다.")
        if not math.isfinite(self.search_range_mm) or self.search_range_mm <= 0.0:
            raise ValueError("search_range_mm은 0보다 커야 합니다.")

    def normalized_connector_axis(self) -> list[float]:
        """Connector Axis를 단위벡터로 반환한다."""
        length = math.sqrt(sum(value * value for value in self.connector_axis))
        return [value / length for value in self.connector_axis]

    @classmethod
    def load_json(cls, path: str | Path) -> "AdaptiveGripPoint":
        """단일 검사포인트 JSON을 읽고 V01 조건을 확인한다."""
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError("Adaptive Grip 레시피는 JSON 객체여야 합니다.")

        point = cls(**data)
        point.validate()
        return point

    @staticmethod
    def _validate_vector(values: list[float], length: int, name: str) -> None:
        if len(values) != length:
            raise ValueError(f"{name}은 {length}개 값이어야 합니다.")
        if not all(math.isfinite(value) for value in values):
            raise ValueError(f"{name}에 유효하지 않은 숫자가 있습니다.")


# ----------------------------------------------------------------------
# Adaptive Grip 검증 시퀀스
# ----------------------------------------------------------------------


class AdaptiveGripSequence:
    """V01부터 지정 단계까지 실행하고 Gate 실패 시 즉시 중단한다."""

    STAGES = tuple(ValidationStage)

    def __init__(self, point: AdaptiveGripPoint) -> None:
        self.point = point
        self.results: list[StageResult] = []

    def run(self, stop_after: ValidationStage) -> list[StageResult]:
        """계획서 순서로 실행하며 요청한 검증 단계에서 멈춘다."""
        handlers = {
            ValidationStage.RECIPE: self.validate_recipe,
            ValidationStage.READY_ENTRY: self.validate_ready_entry,
            ValidationStage.DEPTH_COMPENSATION: self.depth_compensation,
            ValidationStage.SOFT_GRIP: self.soft_grip,
            ValidationStage.MICRO_WIGGLE: self.micro_wiggle,
            ValidationStage.FINE_ALIGNMENT: self.fine_alignment,
            ValidationStage.HARD_GRIP: self.hard_grip,
            ValidationStage.GRIP_STABILITY: self.check_grip_stability,
            ValidationStage.GRIP_PULL_LOGGING: self.grip_pull_test,
        }

        self.results.clear()
        for stage in self.STAGES:
            result = handlers[stage]()
            self._record(result)

            if not result.passed:
                raise RuntimeError(
                    f"{stage.value} Gate 실패: {result.message}"
                )
            if stage == stop_after:
                return self.results[:]

        return self.results[:]

    # ------------------------------------------------------------------
    # V01: Recipe / Inspection Point
    # ------------------------------------------------------------------

    def validate_recipe(self) -> StageResult:
        """필수 검사포인트 정보와 Connector Axis를 확인한다."""
        try:
            self.point.validate()
        except ValueError as error:
            return StageResult(
                ValidationStage.RECIPE,
                False,
                str(error),
            )

        return StageResult(
            ValidationStage.RECIPE,
            True,
            "필수 검사포인트 정보 확인 완료",
            {
                "recipe_id": self.point.recipe_id,
                "point_id": self.point.point_id,
                "point_name": self.point.point_name,
                "connector_axis": self.point.normalized_connector_axis(),
                "nominal_task": self.point.nominal_task,
                "ready_joint": self.point.ready_joint,
                "entry_task": self.point.entry_task,
                "depth_offset_mm": self.point.depth_offset_mm,
                "search_range_mm": self.point.search_range_mm,
            },
        )

    # ------------------------------------------------------------------
    # V02~V09: 실물 검증 후 구현할 단계별 인터페이스
    # ------------------------------------------------------------------

    def validate_ready_entry(self) -> StageResult:
        """Open 상태에서 Ready→Entry 반복성과 간섭 여부를 검증한다."""
        raise NotImplementedError(
            "V02는 그리퍼 Open, MoveJ Ready, Entry 이동 방식과 "
            "간섭 확인 조건을 확정한 뒤 구현합니다."
        )

    def depth_compensation(self) -> StageResult:
        """Connector Axis 방향 Search로 깊이 보정값을 구한다."""
        raise NotImplementedError(
            "V03은 Search 속도와 Force Detection 조건 확정 후 구현합니다."
        )

    def soft_grip(self) -> StageResult:
        """Micro-Wiggle이 가능한 Soft Grip 조건을 적용한다."""
        raise NotImplementedError(
            "V04는 RG2 힘·폭·파지 깊이 조건을 실험으로 정한 뒤 구현합니다."
        )

    def micro_wiggle(self) -> StageResult:
        """Connector Axis 수직 방향의 ±미세 이동과 힘 반응을 기록한다."""
        raise NotImplementedError(
            "V05는 이동축·거리·속도와 Tool Force API 확정 후 구현합니다."
        )

    def fine_alignment(self) -> StageResult:
        """Wiggle 반응을 비교해 보정하고 재측정한다."""
        raise NotImplementedError(
            "V06 판정식은 Force Difference/Ratio 데이터를 확보한 뒤 정합니다."
        )

    def hard_grip(self) -> StageResult:
        """Grip-Pull 동안 Slip을 막는 Hard Grip 조건을 적용한다."""
        raise NotImplementedError(
            "V07은 Hard Grip 힘·폭 조건을 검증한 뒤 구현합니다."
        )

    def check_grip_stability(self) -> StageResult:
        """Pull 전에 Gripper-Cable 파지 안정성을 판정한다."""
        raise NotImplementedError(
            "V08은 Width·TCP·초기 힘·사전 하중 판정 조건 확정 후 구현합니다."
        )

    def grip_pull_test(self) -> StageResult:
        """Connector Axis Pull과 동기화된 Force/TCP 기록을 수행한다."""
        raise NotImplementedError(
            "V09 Data Logger와 Pull 종료 조건을 구현한 뒤 연결합니다."
        )

    # ------------------------------------------------------------------
    # 결과 기록
    # ------------------------------------------------------------------

    def _record(self, result: StageResult) -> None:
        """중복 단계 없이 실행 결과를 메모리에 기록한다."""
        if self.results and self.results[-1].stage == result.stage:
            raise RuntimeError(f"단계가 중복 실행됐습니다: {result.stage.value}")
        self.results.append(result)

    def save_results(self, path: str | Path) -> None:
        """Adaptive Grip 검증 결과를 체결검사 데이터와 분리해 저장한다."""
        output = {
            "schema_version": 1,
            "created_at": datetime.now().astimezone().isoformat(
                timespec="milliseconds"
            ),
            "data_type": "adaptive_grip_validation",
            "point": asdict(self.point),
            "results": [
                {
                    **asdict(result),
                    "stage": result.stage.value,
                }
                for result in self.results
            ],
        }

        output_path = Path(path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(
            json.dumps(output, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )


def main() -> int:
    """V01 레시피 검증만 실행한다. 로봇 동작 단계는 자동 실행하지 않는다."""
    try:
        recipe_path = input("Adaptive Grip 검사포인트 JSON 경로: ").strip()
        point = AdaptiveGripPoint.load_json(recipe_path)
        sequence = AdaptiveGripSequence(point)
        result = sequence.run(ValidationStage.RECIPE)[0]
        print(f"{result.stage.value}: {result.message}")
    except Exception as error:
        print(f"검증 실패: {error}")
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
