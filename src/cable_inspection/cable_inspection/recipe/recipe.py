"""검사 레시피 수신 데이터, 포인트 순회와 실행 현황을 소유한다. ROS에는 의존하지 않는다."""

import json
import math
from dataclasses import dataclass
from copy import deepcopy
from threading import RLock
from pathlib import Path
from cable_inspection.safety.workspace_boundary import BoxBoundary
from cable_inspection.sequence.inspection.data_models.inspection_point_result import InspectionPointResult
from cable_inspection.sequence.inspection.data_models.inspection_result import InspectionResult
from cable_inspection.sequence.inspection.data_models.judgment_status import JudgmentStatus
from cable_inspection.sequence.common.data_models.sequence_status import SequenceStatus
from cable_inspection.sequence.common.data_models.sequence_result import SequenceResult



@dataclass(frozen=True)
class RobotPose:
    """Point Transition에서 사용하는 TASK와 JOINT 한 쌍이다."""

    task: list[float]
    joint: list[float]



    def validate(self, name: str) -> None:
        for label, values in (("task", self.task), ("joint", self.joint)):
            if len(values) != 6:
                raise ValueError(f"{name}.{label} 좌표는 6개 값이어야 합니다.")

            if not all(not isinstance(value, bool) and isinstance(value, (int, float))
                       and math.isfinite(value) for value in values):
                raise ValueError(f"{name}.{label} 좌표에 유효하지 않은 숫자가 있습니다.")



class Recipe:
    """포인트 배열 순서대로 다음 검사를 제공하고 모션·판정·기록 현황을 관리한다."""

    MAX_POINTS = 1000



    def __init__(self, system_path=None, recipe_paths=()):
        # 레시피 원본 위치와 수신 저장소를 준비한다.
        self._system_path = Path(system_path) if system_path is not None else None
        self._paths = {}
        self._received = {}
        self._recipe_lock = RLock()

        # 실행 중인 배열·현재 포인트·결과 상태를 초기화한다.
        self._active = {}
        self._run_id = None
        self._running = False
        self._cursor = 0
        self._current = None
        self._completed = 0
        self._results = {}
        self._pending = set()

        # 초기 등록 파일을 읽고 ID 중복을 검사한다.
        for path in recipe_paths:
            path = Path(path)
            data = self.load_json(path)
            recipe_id = data["recipe_id"]

            if recipe_id in self._paths:
                raise ValueError(f"중복 Recipe ID: {recipe_id}")

            self._paths[recipe_id] = path



    @classmethod
    def validate(cls, data):
        """통신·파일 모두 포인트 배열 자체를 검증하며 별도 실행 목록을 만들지 않는다."""

        if not isinstance(data, dict):
            raise ValueError("Recipe는 객체여야 합니다.")

        # 레시피 식별 정보와 좌표계를 검사한다.
        for name in ("recipe_id", "recipe_version", "connector_type"):
            value = data.get(name)

            if not isinstance(value, str) or not value.strip() or len(value) > 256:
                raise ValueError(f"{name}: 1~256자 문자열이 필요합니다.")

        if data.get("coordinate_frame") != "BASE":
            raise ValueError("현재 운영 Recipe는 BASE 좌표계만 지원합니다.")

        # 배열 크기를 확인한 뒤 각 포인트의 식별자·자세·검사 조건을 검사한다.
        points = data.get("points")

        if not isinstance(points, list) or not 1 <= len(points) <= cls.MAX_POINTS:
            raise ValueError(f"검사 포인트 배열은 1~{cls.MAX_POINTS}개여야 합니다.")

        ids = set()

        for point in points:
            if not isinstance(point, dict):
                raise ValueError("검사포인트는 객체여야 합니다.")

            point_id = point.get("point_id")

            if (not isinstance(point_id, str) or not point_id.strip() or len(point_id) > 256
                    or not isinstance(point.get("point_name"), str) or len(point["point_name"]) > 256):
                raise ValueError("Point ID/이름이 유효하지 않습니다.")

            if point_id in ids:
                raise ValueError("중복 Point ID입니다.")

            ids.add(point_id)

            if type(point.get("enabled")) is not bool:
                raise ValueError("enabled는 bool이어야 합니다.")

            for name in ("ready_pose", "entry_pose"):
                RobotPose(**point[name]).validate(name)

            # 진입·파지·Pull 설정은 유한한 양수여야 한다.
            for group, keys in (
                ("entry_setting", ("max_distance_mm", "force_guard_n", "timeout_s")),
                ("grip_setting", ("soft_close_width_mm", "soft_open_width_mm", "hard_width_mm", "soft_force_n", "hard_force_n")),
                ("pull_setting", ("force_limit_n", "max_distance_mm", "timeout_s", "speed_mm_s", "normal_displacement_limit_mm")),
            ):
                for key in keys:
                    value = point[group].get(key)

                    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
                        raise ValueError(f"{point_id}: {group}.{key}가 유효하지 않습니다.")

            if point["entry_setting"]["max_distance_mm"] > 25.0:
                raise ValueError(f"{point_id}: Entry 최대거리는 25 mm 이하여야 합니다.")



    @classmethod
    def load_json(cls, path):
        data = json.loads(Path(path).read_text(encoding="utf-8"))

        # 기존 HMI 관리 파일은 그대로 읽는다. 구형 파일 형식은 입력 경계에서만 변환한다.
        if isinstance(data.get("points"), dict):
            points = data["points"]
            order = data.pop("execution_order", list(points))

            if len(order) != len(set(order)) or set(order) != set(points):
                raise ValueError("파일의 검사포인트 순서가 유효하지 않습니다.")

            if any(key != point["point_id"] for key, point in points.items()):
                raise ValueError("points 키와 point_id가 다릅니다.")

            data["points"] = [points[key] for key in order]

        else:
            data.pop("execution_order", None)

        for point in data.get("points", []):
            point.pop("entry_direction", None)  # Entry ABC가 방향 기준이다.

        cls.validate(data)
        return data



    def available_ids(self):
        with self._recipe_lock:
            return list(dict.fromkeys([*self._paths, *self._received]))



    def accept(self, data):
        candidate = deepcopy(data)
        self.validate(candidate)

        with self._recipe_lock:
            self._received[candidate["recipe_id"]] = candidate



    def get(self, recipe_id):
        with self._recipe_lock:
            if recipe_id in self._received:
                return deepcopy(self._received[recipe_id])

            path = self._paths.get(recipe_id)

        if path is None:
            raise ValueError(f"등록되지 않은 Recipe: {recipe_id}")

        data = self.load_json(path)

        if data["recipe_id"] != recipe_id:
            raise ValueError("선택한 Recipe ID와 파일의 ID가 다릅니다.")

        return data



    def begin(self, recipe_id, run_id):
        data = self.get(recipe_id)

        with self._recipe_lock:
            if self._running:
                raise RuntimeError("진행 중인 Recipe가 있습니다.")

            self._active, self._run_id, self._running = data, run_id, True
            self._cursor, self._current, self._completed = 0, None, 0
            self._results, self._pending = {}, set()



    def next_point(self):
        """미완료 포인트는 다시 반환한다. 완료 반영 전에는 다음 포인트로 넘어가지 않는다."""

        with self._recipe_lock:
            if not self._running:
                raise RuntimeError("실행 중인 Recipe가 없습니다.")

            if self._current is not None:
                return deepcopy(self._current)

            points = self._active["points"]

            while self._cursor < len(points):
                point = points[self._cursor]
                self._cursor += 1

                if not point["enabled"]:
                    continue

                self._current = point
                self._results[point["point_id"]] = InspectionPointResult(
                    point["point_id"], motion_status=SequenceStatus.RUNNING)

                return deepcopy(point)

            return None



    def complete_point(self, run_id, result):
        with self._recipe_lock:
            if (not self._running or run_id != self._run_id or self._current is None
                    or result.point_id != self._current["point_id"]):
                raise ValueError("현재 실행 중인 검사포인트의 결과가 아닙니다.")

            previous = self._results[result.point_id]
            result = deepcopy(result)
            result.motion_status = SequenceStatus.SUCCESS
            grip_ok = result.adaptive_grip["adaptive_grip_done"]
            result.adaptive_grip_status = SequenceStatus.SUCCESS if grip_ok else SequenceStatus.FAIL
            result.pull_status = SequenceStatus.SUCCESS if grip_ok else SequenceStatus.INCOMPLETE

            # 복귀 중 먼저 도착한 판정을 완료 결과로 덮어쓰지 않는다.
            if previous.judgment_status != JudgmentStatus.PENDING:
                for name in ("result", "judgment_status", "reason", "sequence_status"):
                    setattr(result, name, getattr(previous, name))

            self._results[result.point_id] = result
            self._completed += 1
            self._current = None



    def mark_pending(self, run_id, point_id):
        with self._recipe_lock:
            if not self._running or run_id != self._run_id or point_id not in self._results:
                raise ValueError("현재 실행의 판정 요청이 아닙니다.")

            self._pending.add(point_id)



    def apply_judgments(self, run_id, results):
        with self._recipe_lock:
            if not self._running or run_id != self._run_id:
                return

            for point_id, data in results.items():
                point = self._results.get(point_id)

                if (point is None or data.get("run_id") != run_id or data.get("point_id") != point_id
                        or data.get("judgment_status") not in {"COMPLETED", "ERROR"}):
                    continue

                point.result = InspectionResult(data["result"])
                point.judgment_status = JudgmentStatus(data["judgment_status"])
                point.reason = data["reason"]
                point.sequence_status = SequenceStatus(data["sequence_status"])
                self._pending.discard(point_id)



    def mark_logs_saved(self, run_id, point_ids):
        with self._recipe_lock:
            if run_id != self._run_id:
                return

            for point_id in point_ids:
                point = self._results.get(point_id)

                if point is not None and point.transition is not None:
                    point.log_saved = True



    def end(self, run_id):
        """순회는 종료하지만 HMI 조회를 위한 마지막 진행·결과는 유지한다."""

        with self._recipe_lock:
            if run_id != self._run_id:
                return

            if self._current is not None:
                self._results[self._current["point_id"]].motion_status = SequenceStatus.INCOMPLETE

            self._running = False



    def snapshot(self):
        with self._recipe_lock:
            return deepcopy(self._active)



    def progress(self, run_id=None):
        with self._recipe_lock:
            if run_id is not None and run_id != self._run_id:
                return {"run_id": run_id, "recipe_id": "", "recipe_version": "",
                    "total_points": 0, "execution_index": 0, "progress_percent": 0,
                    "current_point": "", "point": None, "pending_judgments": 0, "running": False}

            total = sum(point["enabled"] for point in self._active.get("points", []))

            return {
                "run_id": self._run_id, "recipe_id": self._active.get("recipe_id", ""),
                "recipe_version": self._active.get("recipe_version", ""),
                "total_points": total, "execution_index": self._completed,
                "progress_percent": round(100 * self._completed / total) if total else 0,
                "current_point": self._current["point_id"] if self._current else "",
                "point": deepcopy(self._current), "pending_judgments": len(self._pending),
                "running": self._running,
            }



    def inspection_results(self):
        with self._recipe_lock:
            return {key: value.inspection_dict() for key, value in self._results.items()
                    if value.transition is not None}



    def completion(self):
        with self._recipe_lock:
            missing = []
            counts = {result.value: 0 for result in InspectionResult}
            points = [point for point in self._active.get("points", []) if point["enabled"]]

            for data in points:
                point_id = data["point_id"]
                point = self._results.get(point_id)

                if (point is None or point.motion_status != SequenceStatus.SUCCESS
                        or point.result not in set(InspectionResult) or not point.log_saved):
                    missing.append(point_id)

                else:
                    counts[point.result.value] += 1

            complete = bool(points) and self._completed == len(points) and not self._pending and not missing

            return SequenceResult(complete,
                "WORK_FINISH_SUCCESS" if complete else "WORK_FINISH_NOT_COMPLETE",
                "완료" if complete else "모션·판정·로그 완료 대기",
                {"counts": counts, "missing_points": missing, "pending_points": sorted(self._pending)})



    def system_settings(self):
        """노드 시작에 필요한 설정을 읽는다. 실행 전에는 system_recipe로 전체 검증한다."""

        if self._system_path is None:
            raise ValueError("System Recipe 경로가 없습니다.")

        return json.loads(self._system_path.read_text(encoding="utf-8"))



    def system_recipe(self):
        """시스템 설정을 읽고 운전에 필요한 좌표·범위·조건 전체를 검증한다."""
        data = self.system_settings()
        speed = data.get("joint_speed_deg_s")

        if (isinstance(speed, bool) or not isinstance(speed, (int, float))
                or not math.isfinite(speed) or speed <= 0):
            raise ValueError("System Recipe의 joint_speed_deg_s는 유한한 양수여야 합니다.")

        if data.get("coordinate_frame") != "BASE":
            raise ValueError("System Recipe는 BASE 기준이어야 합니다.")

        for name in ("home_pose", "work_Access_safe_pose"):
            raw = data.get(name)

            if not raw or raw.get("task") is None or raw.get("joint") is None:
                raise ValueError(f"System Recipe의 {name} 좌표를 입력하세요.")

            RobotPose(**raw).validate(name)

        if not data.get("work_area"):
            raise ValueError("System Recipe의 work_area 경계를 입력하세요.")

        BoxBoundary(**data["work_area"]).validate("work_area")

        if any(value != 0 for value in data["home_pose"]["joint"]):
            raise ValueError("Home 복귀의 home_pose.joint는 모두 0도여야 합니다.")

        route = data.get("safe_home_route")

        if not isinstance(route, list) or not route:
            raise ValueError("검증된 safe_home_route를 입력하세요. 마지막 자세는 home_pose여야 합니다.")

        for index, pose in enumerate(route):
            RobotPose(**pose).validate(f"safe_home_route[{index}]")

        if route[-1] != data["home_pose"]:
            raise ValueError("safe_home_route의 마지막 자세는 home_pose와 같아야 합니다.")

        direction = data.get("tool_approach_axis")

        if (not isinstance(direction, list) or len(direction) != 3
                or not all(isinstance(v, (int, float)) and math.isfinite(v) for v in direction)
                or math.hypot(*direction) == 0):
            raise ValueError("Tool 좌표계 접근축 tool_approach_axis를 입력하세요.")

        for key in ("max_escape_distance_mm", "heartbeat_timeout_s",
                    "communication_recovery_timeout_s", "judgment_timeout_s",
                    "relax_width_mm", "relax_force_n", "home_joint_tolerance_deg"):
            value = data.get(key)

            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
                raise ValueError(f"System Recipe의 {key}는 양수여야 합니다.")

        if data["max_escape_distance_mm"] > 30:
            raise ValueError("Safe Escape 상한은 30 mm 이하여야 합니다.")

        return data
