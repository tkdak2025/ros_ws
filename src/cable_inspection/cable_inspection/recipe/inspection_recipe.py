"""검사 실행용 레시피 모델·검증·ROS 메시지 변환과 시스템 설정 로더.

Main은 전달받은 검사 레시피의 복사본을 검증하고 실행한다.
이 파일은 ROS 노드나 DB를 생성하지 않는다. 원본 레시피 관리와 이력 조회는 HMI 담당이다.
"""

import json
import math
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any
from cable_inspection.safety.workspace_boundary import BoxBoundary
from rosidl_runtime_py.convert import message_to_ordereddict
from rosidl_runtime_py.set_message import set_message_fields
from cable_interfaces.msg import InspectionRecipe as RecipeMessage


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
    entry_setting: dict[str, float]
    grip_setting: dict[str, float]
    pull_setting: dict[str, float]

    # 기능: Entry의 ZYZ 자세에서 Tool +Z를 BASE 기준 진입 방향으로 계산한다.
    #     자세 입력: entry_pose.task의 [A, B, C](deg). Tool +Z를 체결축에 맞춰 교시한다.
    #
    #     ------------------------------------------------------------
    #     반환: BASE 기준 단위벡터 [dx, dy, dz]. Pull은 이 벡터의 반대 방향이다.
    def normalized_entry_direction(self) -> list[float]:
        a, b, _c = map(math.radians, self.entry_pose.task[3:])
        # Rz(A) × Ry(B) × Rz(C)의 세 번째 열. C는 Tool +Z 방향에 영향을 주지 않는다.
        direction = [math.cos(a) * math.sin(b), math.sin(a) * math.sin(b), math.cos(b)]
        length = math.sqrt(sum(value * value for value in direction))
        return [0.0 if abs(value) < 1e-12 else value / length for value in direction]


    def validate(self) -> None:
        self.ready_pose.validate("ready_pose")
        self.entry_pose.validate("entry_pose")
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

    def add_point(self, point: OperatingInspectionPoint) -> None:
        """새 Point를 등록하고 실행목록 끝에 추가한다. 기존 Point는 덮어쓰지 않는다."""
        from copy import deepcopy

        self.validate()
        point.validate()
        if not point.point_id.strip():
            raise ValueError("새 검사포인트의 point_id가 필요합니다.")
        if point.point_id in self.points:
            raise ValueError(f"이미 등록된 검사포인트입니다: {point.point_id}")
        self.points[point.point_id] = deepcopy(point)
        self.execution_order.append(point.point_id)

    def save_json(self, path: str | Path) -> None:
        """Point와 실행 순서를 함께 저장한다. 실행 중 Job Snapshot에는 영향을 주지 않는다."""
        self.validate()
        target = Path(path)
        temporary = target.with_suffix(target.suffix + ".tmp")
        temporary.write_text(
            json.dumps(asdict(self), ensure_ascii=False, indent=2, allow_nan=False) + "\n",
            encoding="utf-8",
        )
        temporary.replace(target)

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
        return cls.from_dict(json.loads(Path(path).read_text(encoding="utf-8")))

    @classmethod
    def from_dict(cls, data):
        # 이전 파일에 남은 entry_direction은 사용하지 않는다. Entry ABC가 방향의 기준이다.
        points = {}
        for point_id, raw in data["points"].items():
            point_data = dict(raw)
            point_data.pop("entry_direction", None)
            point_data["ready_pose"] = RobotPose(**raw["ready_pose"])
            point_data["entry_pose"] = RobotPose(**raw["entry_pose"])
            points[point_id] = OperatingInspectionPoint(**point_data)
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

MAX_POINTS = 1000


def validate_recipe(recipe):
    recipe.validate()
    for name in ("recipe_id", "recipe_version", "connector_type"):
        value = getattr(recipe, name)
        if not isinstance(value, str) or not value.strip() or len(value) > 256:
            raise ValueError(f"{name}: 1~256자 문자열이 필요합니다.")
    if not 1 <= len(recipe.points) <= MAX_POINTS:
        raise ValueError(f"검사 포인트는 1~{MAX_POINTS}개여야 합니다.")
    if set(recipe.execution_order) != set(recipe.points):
        raise ValueError("모든 Point가 실행 배열에 한 번씩 있어야 합니다. 제외할 Point는 enabled=false로 지정하세요.")
    for point in recipe.points.values():
        if not point.point_id.strip() or len(point.point_id) > 256 or len(point.point_name) > 256:
            raise ValueError("Point ID/이름이 유효하지 않습니다.")
        if type(point.enabled) is not bool:
            raise ValueError("enabled는 bool이어야 합니다.")
    return recipe


# 기능: 공통 Joint 이동 속도를 확인한다. 검사 단독 실행에서도 좌표 검증 없이 사용한다.
#     system: System Recipe JSON을 읽은 dict. joint_speed_deg_s 단위는 deg/s.
#
#     ------------------------------------------------------------
#     반환: MoveJ 명령에 적용할 Joint 속도(deg/s).
def joint_speed_from_system(system):
    value = system.get("joint_speed_deg_s")
    if (isinstance(value, bool) or not isinstance(value, (int, float))
            or not math.isfinite(value) or value <= 0):
        raise ValueError("System Recipe의 joint_speed_deg_s는 유한한 양수여야 합니다.")
    return float(value)


def load_system_recipe(path):
    """미입력 좌표는 거부한다. Tool/TCP를 등록하거나 Fault를 해제하지 않는다."""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    joint_speed_from_system(data)
    if data.get("coordinate_frame") != "BASE":
        raise ValueError("System Recipe는 BASE 기준이어야 합니다.")
    for name in ("home_pose", "work_Access_safe_pose"):
        raw = data.get(name)
        if not raw or raw.get("task") is None or raw.get("joint") is None:
            raise ValueError(f"System Recipe의 {name} 좌표를 입력하세요.")
        RobotPose(**raw).validate(name)
    for name in ("work_area",):
        if not data.get(name):
            raise ValueError(f"System Recipe의 {name} 경계를 입력하세요.")
        BoxBoundary(**data[name]).validate(name)
    if any(value != 0 for value in data["home_pose"]["joint"]):
        raise ValueError("Home 복귀의 home_pose.joint는 모두 0도여야 합니다.")
    direction = data.get("tool_approach_axis")
    # 현재 Home Return은 Safe Escape를 호출하지 않으므로 접근축은 필수가 아니다.
    if direction is not None and (not isinstance(direction, list) or len(direction) != 3
            or not all(isinstance(v, (int, float)) and math.isfinite(v) for v in direction)
            or math.hypot(*direction) == 0):
        raise ValueError("Tool 좌표계 접근축 tool_approach_axis를 입력하세요.")
    for key in ("max_escape_distance_mm", "escape_clearance_mm", "heartbeat_timeout_s",
                "communication_recovery_timeout_s", "judgment_timeout_s",
                "relax_width_mm", "relax_force_n"):
        value = data.get(key)
        if not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
            raise ValueError(f"System Recipe의 {key}는 양수여야 합니다.")
    if data["max_escape_distance_mm"] > 30:
        raise ValueError("Safe Escape 상한은 30 mm 이하여야 합니다.")
    return data


def from_message(message):
    raw = message_to_ordereddict(message)
    ids = [point["point_id"] for point in raw["points"]]
    if len(ids) != len(set(ids)):
        raise ValueError("중복 Point ID입니다.")
    raw["execution_order"] = ids
    raw["points"] = {point["point_id"]: point for point in raw["points"]}
    return validate_recipe(OperatingInspectionRecipe.from_dict(raw))


def to_message(recipe):
    validate_recipe(recipe)
    raw = asdict(recipe)
    raw["points"] = [raw["points"][key] for key in raw.pop("execution_order")]
    message = RecipeMessage()
    set_message_fields(message, raw)
    return message
