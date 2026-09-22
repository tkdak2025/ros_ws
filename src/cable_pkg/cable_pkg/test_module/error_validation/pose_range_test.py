"""저장된 검사레시피의 TASK·JOINT로 MoveJ 오차 시험을 수행한다.

이 파일은 TASK 생성, IK 계산, solution 선택을 하지 않는다. 레시피의 sequence에
저장된 관절좌표로 이동하고 도착 후 실제 TASK·JOINT 오차만 기록한다.
"""

import argparse
import csv
import json
import math
import time
from datetime import datetime
from pathlib import Path

import rclpy
from dsr_msgs2.srv import (
    GetCurrentPosj,
    GetCurrentPosx,
    GetCurrentTcp,
    GetCurrentTool,
    GetRobotSystem,
    MoveJoint,
    MoveStop,
)
from rclpy.executors import ExternalShutdownException

from ..recipe import InspectionPoint, InspectionRecipe


class PoseRangeTester:
    """레시피 sequence 실행과 도착점 오차 기록을 담당한다."""

    # ------------------------------------------------------------------
    # ROS 연결 및 시험 조건
    # ------------------------------------------------------------------

    SERVICE_PREFIX = "/dsr01/dsr_controller2"
    OUTPUT_DIR = (
        Path(__file__).resolve().parents[4]
        / "measurement_results/error_validation"
    )

    REQUIRED_TCP = "GripperDA_v1"
    REQUIRED_TOOL = "ToolWeight"

    JOINT_VELOCITY_DEG_S = 30.0
    JOINT_ACCELERATION_DEG_S2 = 60.0
    MOVE_TIMEOUT_S = 60.0
    SERVICE_TIMEOUT_S = 3.0
    SETTLE_TIME_S = 0.5

    MAX_JOINT_CHANGE_DEG = 90.0
    JOINT_LIMITS_DEG = (360.0, 95.0, 150.0, 360.0, 135.0, 360.0)
    ELBOW_MARGIN_FULL_DEG = 30.0
    WRIST_MARGIN_FULL_DEG = 30.0
    POSITION_TOLERANCE_MM = 1.0
    ORIENTATION_TOLERANCE_DEG = 1.0

    CSV_VALUE_DECIMALS = 3
    CSV_DETAIL_DECIMALS = 4

    def __init__(self, recipe: InspectionRecipe, *, virtual_joint_only=False,
                 prepare_start=False, confirm_virtual=False):
        """레시피와 필요한 ROS 서비스 클라이언트를 준비한다."""
        self.recipe = recipe
        self.virtual_joint_only = virtual_joint_only
        self.prepare_start = prepare_start
        self.confirm_virtual = confirm_virtual
        if (prepare_start or confirm_virtual) and not virtual_joint_only:
            raise ValueError("시작 자세 준비·자동 확인은 가상 관절 시험 전용입니다.")
        self.robot_system = None
        self.active_tcp = None
        self.active_tool = None
        self.preparation_joints = []
        self.sequence = self._load_sequence()
        self.reference_point = self.sequence[0]

        self.node = rclpy.create_node("pose_range_tester")
        prefix = self.SERVICE_PREFIX
        self.system_client = self.node.create_client(
            GetRobotSystem, prefix + "/system/get_robot_system",
        )

        self.task_client = self.node.create_client(
            GetCurrentPosx,
            prefix + "/aux_control/get_current_posx",
        )
        self.joint_client = self.node.create_client(
            GetCurrentPosj,
            prefix + "/aux_control/get_current_posj",
        )
        self.movej_client = self.node.create_client(
            MoveJoint,
            prefix + "/motion/move_joint",
        )
        self.stop_client = self.node.create_client(
            MoveStop,
            prefix + "/motion/move_stop",
        )
        self.tcp_client = self.node.create_client(
            GetCurrentTcp,
            prefix + "/tcp/get_current_tcp",
        )
        self.tool_client = self.node.create_client(
            GetCurrentTool,
            prefix + "/tool/get_current_tool",
        )

        self.motion_started = False
        self.stop_reason = "not_started"

    # ------------------------------------------------------------------
    # 레시피 검증
    # ------------------------------------------------------------------

    def _load_sequence(self) -> list[InspectionPoint]:
        """레시피 실행 순서를 검사하고 포인트 객체 목록으로 변환한다."""
        self.recipe.validate()

        if self.recipe.test_axis not in {"Y", "Z"}:
            raise ValueError("범위 시험 레시피의 test_axis는 Y 또는 Z여야 합니다.")
        if not self.recipe.sequence:
            raise ValueError("범위 시험 레시피에 sequence가 없습니다.")

        sequence = [
            self.recipe.get_point(point_id)
            for point_id in self.recipe.sequence
        ]

        if "REFERENCE_START" not in sequence[0].point_id:
            raise ValueError("sequence의 첫 포인트는 REFERENCE_START여야 합니다.")

        for previous, current in zip(sequence, sequence[1:]):
            max_change = self._max_joint_change(previous.joint, current.joint)
            if max_change > self.MAX_JOINT_CHANGE_DEG:
                raise ValueError(
                    f"{previous.point_id} → {current.point_id} 최대 관절 변화가 "
                    f"{self.MAX_JOINT_CHANGE_DEG:.0f}°를 초과합니다: "
                    f"{max_change:.3f}°"
                )

        return sequence

    @staticmethod
    def _max_joint_change(first: list[float], second: list[float]) -> float:
        return max(abs(a - b) for a, b in zip(first, second))

    @classmethod
    def posture_margins(cls, joints: list[float]) -> dict[str, float]:
        """저장된 JOINT의 관절 한계·팔꿈치·손목 여유를 0~1로 계산한다."""
        limit_margin = min(
            max(0.0, (limit - abs(angle)) / limit)
            for angle, limit in zip(joints, cls.JOINT_LIMITS_DEG)
        )
        elbow_margin = min(1.0, abs(joints[2]) / cls.ELBOW_MARGIN_FULL_DEG)
        wrist_margin = min(1.0, abs(joints[4]) / cls.WRIST_MARGIN_FULL_DEG)

        return {
            "joint_limit_margin": limit_margin,
            "elbow_margin": elbow_margin,
            "wrist_margin": wrist_margin,
            "freedom_score": min(
                limit_margin,
                elbow_margin,
                wrist_margin,
            ),
        }

    # ------------------------------------------------------------------
    # ROS 서비스 통신과 상태 조회
    # ------------------------------------------------------------------

    def call(self, client, request, timeout=None):
        """서비스 시간 초과와 success=False를 예외로 변환한다."""
        future = client.call_async(request)
        rclpy.spin_until_future_complete(
            self.node,
            future,
            timeout_sec=self.SERVICE_TIMEOUT_S if timeout is None else timeout,
        )

        if not future.done():
            future.cancel()
            raise TimeoutError(f"서비스 응답 시간 초과: {client.srv_name}")

        response = future.result()
        if response is None or not response.success:
            raise RuntimeError(f"서비스 실패: {client.srv_name}")

        return response

    def read_state(self):
        """현재 BASE TCP, JOINT, solution space를 조회한다."""
        request = GetCurrentPosx.Request()
        request.ref = 0  # DR_BASE

        task_response = self.call(self.task_client, request)
        if not task_response.task_pos_info:
            raise RuntimeError("현재 TCP 응답이 비어 있습니다.")

        task_data = [
            float(value)
            for value in task_response.task_pos_info[0].data
        ]
        joints = [
            float(value)
            for value in self.call(
                self.joint_client,
                GetCurrentPosj.Request(),
            ).pos
        ]

        if len(task_data) < 7 or len(joints) != 6:
            raise RuntimeError("TCP 또는 JOINT 응답 길이가 잘못되었습니다.")

        return task_data[:6], joints, int(round(task_data[6]))

    # ------------------------------------------------------------------
    # 이동과 정지
    # ------------------------------------------------------------------

    def movej(self, joints: list[float]) -> None:
        """저장된 JOINT 목표로 이동하고 완료 응답을 기다린다."""
        if self.virtual_joint_only:
            self.require_virtual()
        request = MoveJoint.Request()
        request.pos = [float(value) for value in joints]
        request.vel = self.JOINT_VELOCITY_DEG_S
        request.acc = self.JOINT_ACCELERATION_DEG_S2
        request.time = 0.0
        request.radius = 0.0
        request.mode = 0
        request.blend_type = 0
        request.sync_type = 0

        self.motion_started = True
        self.call(self.movej_client, request, timeout=self.MOVE_TIMEOUT_S)
        self.motion_started = False

    def stop_robot(self) -> None:
        """이동 중 오류나 사용자 중단 시 Stop Category 2를 요청한다."""
        request = MoveStop.Request()
        request.stop_mode = 1  # DR_QSTOP

        try:
            self.call(self.stop_client, request, timeout=1.0)
        except Exception as error:
            print(f"정지 서비스 호출 실패: {error}")

    # ------------------------------------------------------------------
    # 방향 및 오차 계산
    # ------------------------------------------------------------------

    @staticmethod
    def rotation(angles):
        """두산 Euler ZYZ 각도를 회전행렬로 변환한다."""
        a, b, c = map(math.radians, angles)
        ca, sa = math.cos(a), math.sin(a)
        cb, sb = math.cos(b), math.sin(b)
        cc, sc = math.cos(c), math.sin(c)

        return (
            (ca * cb * cc - sa * sc, -ca * cb * sc - sa * cc, ca * sb),
            (sa * cb * cc + ca * sc, -sa * cb * sc + ca * cc, sa * sb),
            (-sb * cc, sb * sc, cb),
        )

    @classmethod
    def rotation_error(cls, expected, actual):
        """두 TCP 방향 사이의 최소 상대 회전각을 반환한다."""
        left = cls.rotation(expected)
        right = cls.rotation(actual)
        trace = sum(
            left[i][j] * right[i][j]
            for i in range(3)
            for j in range(3)
        )

        return math.degrees(
            math.acos(max(-1.0, min(1.0, (trace - 1.0) / 2.0)))
        )

    # ------------------------------------------------------------------
    # 실행 전 확인과 계획 출력
    # ------------------------------------------------------------------

    def require_virtual(self):
        """가상 전용 옵션으로 실물 시스템에 명령을 보내지 않는다."""
        self.robot_system = self.call(
            self.system_client, GetRobotSystem.Request(),
        ).robot_system
        if self.robot_system != 1:
            raise RuntimeError("가상 시험은 robot_system=1에서만 실행 가능합니다.")

    def preflight(self) -> list[float]:
        """서비스·TCP·Tool·현재 위치와 저장 경로를 확인한다."""
        clients = (
            self.system_client,
            self.task_client,
            self.joint_client,
            self.movej_client,
            self.stop_client,
            self.tcp_client,
            self.tool_client,
        )

        for client in clients:
            if not client.wait_for_service(timeout_sec=self.SERVICE_TIMEOUT_S):
                raise RuntimeError(f"서비스를 찾지 못했습니다: {client.srv_name}")

        if self.virtual_joint_only:
            self.require_virtual()
        else:
            self.robot_system = self.call(
                self.system_client, GetRobotSystem.Request(),
            ).robot_system
        tcp_name = self.call(self.tcp_client, GetCurrentTcp.Request()).info
        tool_name = self.call(self.tool_client, GetCurrentTool.Request()).info
        self.active_tcp, self.active_tool = tcp_name, tool_name
        if self.virtual_joint_only:
            print("가상 관절 시퀀스 시험: TASK 오차 판정 제외, 현재 TCP/Tool 사용")
        elif tcp_name != self.REQUIRED_TCP or tool_name != self.REQUIRED_TOOL:
            raise RuntimeError(
                f"필요 설정은 TCP={self.REQUIRED_TCP}, "
                f"Tool={self.REQUIRED_TOOL}입니다. "
                f"현재 TCP={tcp_name}, Tool={tool_name}"
            )

        current_task, current_joint, _ = self.read_state()
        initial_change = self._max_joint_change(
            current_joint,
            self.reference_point.joint,
        )

        print(
            f"레시피={self.recipe.recipe_id} v{self.recipe.recipe_version}, "
            f"축={self.recipe.test_axis}, 포인트={len(self.sequence)}개"
        )
        print("현재 TCP:", [round(value, 3) for value in current_task])
        print("현재 Joint:", [round(value, 3) for value in current_joint])
        print(f"첫 포인트까지 최대 ΔJ={initial_change:.3f}°")

        if initial_change > self.MAX_JOINT_CHANGE_DEG and not self.prepare_start:
            raise RuntimeError(
                "현재 자세에서 첫 포인트까지 최대 관절 변화가 "
                f"{self.MAX_JOINT_CHANGE_DEG:.0f}°를 초과합니다."
            )

        if self.prepare_start:
            steps = max(1, math.ceil(initial_change / self.MAX_JOINT_CHANGE_DEG))
            self.preparation_joints = [
                [a + (b - a) * step / steps
                 for a, b in zip(current_joint, self.reference_point.joint)]
                for step in range(1, steps + 1)
            ]
            print("가상 시작 자세 준비 경유점:", self.preparation_joints)

        print("\n저장된 MoveJ 실행 순서:")
        previous = current_joint
        for point in self.sequence:
            max_change = self._max_joint_change(previous, point.joint)
            print(
                f"{point.point_id} | TASK={point.task} | "
                f"JOINT={point.joint} | max ΔJ={max_change:.3f}°"
            )
            previous = point.joint

        if not self.confirm_virtual and input("전체 경로가 안전하면 MOVE 입력: ").strip() != "MOVE":
            raise RuntimeError("사용자가 시험을 취소했습니다.")

        for joints in self.preparation_joints:
            self.movej(joints)
        if self.preparation_joints:
            _, current_joint, _ = self.read_state()
            if self._max_joint_change(current_joint, self.reference_point.joint) > 1.0:
                raise RuntimeError("가상 시작 자세 준비 후 관절 오차가 1°를 초과합니다.")

        return current_joint

    # ------------------------------------------------------------------
    # CSV 행 생성
    # ------------------------------------------------------------------

    def make_row(
        self,
        point: InspectionPoint,
        actual_task: list[float],
        actual_joint: list[float],
        actual_solution: int,
        elapsed: float,
        previous_command_joint: list[float],
    ) -> dict:
        """저장 목표와 실제 좌표 및 오차를 CSV 한 행으로 만든다."""
        reference_task = self.reference_point.task
        reference_joint = self.reference_point.joint

        offset = [
            round(point.task[index] - reference_task[index], 3)
            for index in range(3)
        ]
        position_error = math.dist(point.task[:3], actual_task[:3])
        orientation_error = self.rotation_error(
            point.task[3:],
            actual_task[3:],
        )
        margins = self.posture_margins(point.joint)

        row = {
            "host_time": datetime.now().astimezone().isoformat(
                timespec="milliseconds"
            ),
            "recipe_id": self.recipe.recipe_id,
            "recipe_version": self.recipe.recipe_version,
            "source_point_id": self.recipe.source_point_id,
            "test_axis": self.recipe.test_axis,
            "point_id": point.point_id,
            "point_name": point.point_name,
            "target_offset_xyz_mm": "[" + ", ".join(
                f"{value:.3f}" for value in offset
            ) + "]",
            "target_dx_mm": offset[0],
            "target_dy_mm": offset[1],
            "target_dz_mm": offset[2],
            "selected_solution_space": point.solution_space,
            "actual_solution_space": actual_solution,
            "max_command_joint_change_deg": round(
                self._max_joint_change(previous_command_joint, point.joint),
                self.CSV_VALUE_DECIMALS,
            ),
            **{
                name: round(value, self.CSV_DETAIL_DECIMALS)
                for name, value in margins.items()
            },
            "move_elapsed_s": round(elapsed, self.CSV_DETAIL_DECIMALS),
            "position_error_mm": round(
                position_error,
                self.CSV_VALUE_DECIMALS,
            ),
            "orientation_error_deg": round(
                orientation_error,
                self.CSV_VALUE_DECIMALS,
            ),
            "within_tolerance": bool(
                position_error <= self.POSITION_TOLERANCE_MM
                and orientation_error <= self.ORIENTATION_TOLERANCE_DEG
            ),
        }

        for index, axis in enumerate("xyzabc"):
            unit = "mm" if index < 3 else "deg"
            error = actual_task[index] - point.task[index]
            if index >= 3:
                error = (error + 180.0) % 360.0 - 180.0

            row[f"target_{axis}_{unit}"] = round(point.task[index], 3)
            row[f"actual_{axis}_{unit}"] = round(actual_task[index], 3)
            row[f"error_{axis}_{unit}"] = round(error, 3)
            row[f"delta_{axis}_{unit}"] = round(
                actual_task[index] - reference_task[index],
                3,
            )

        for index in range(6):
            number = index + 1
            row[f"target_j{number}_deg"] = round(point.joint[index], 3)
            row[f"actual_j{number}_deg"] = round(actual_joint[index], 3)
            row[f"error_j{number}_deg"] = round(
                actual_joint[index] - point.joint[index],
                3,
            )
            row[f"delta_j{number}_deg"] = round(
                actual_joint[index] - reference_joint[index],
                3,
            )

        row["max_joint_error_deg"] = round(
            self._max_joint_change(point.joint, actual_joint), 4,
        )
        row["joint_within_tolerance"] = row["max_joint_error_deg"] <= 1.0
        row["task_error_evaluated"] = not self.virtual_joint_only
        if self.virtual_joint_only:
            row["position_error_mm"] = None
            row["orientation_error_deg"] = None
            row["within_tolerance"] = None
            for axis in "xyzabc":
                unit = "mm" if axis in "xyz" else "deg"
                row[f"error_{axis}_{unit}"] = None
                row[f"delta_{axis}_{unit}"] = None

        return row

    # ------------------------------------------------------------------
    # 전체 시험 실행 및 결과 저장
    # ------------------------------------------------------------------

    def run(self) -> None:
        """레시피 sequence를 실행하고 한 폴더에 CSV·JSON을 저장한다."""
        source_id = self.recipe.source_point_id or self.recipe.recipe_id
        safe_source_id = "".join(
            character if character.isalnum() or character in "-_" else "_"
            for character in source_id
        )
        folder_name = (
            ("virtual_" if self.virtual_joint_only else "") +
            f"{safe_source_id}_{self.recipe.test_axis.lower()}_"
            f"{datetime.now():%Y%m%d_%H%M%S}"
        )

        self.OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        result_dir = self.OUTPUT_DIR / folder_name
        result_dir.mkdir(exist_ok=False)

        csv_path = result_dir / "pose_errors.csv"
        json_path = result_dir / "run_summary.json"

        completed_points = []
        out_of_tolerance = []

        try:
            previous_command_joint = self.preflight()

            writer = None
            with csv_path.open("x", newline="", encoding="utf-8") as stream:
                for point in self.sequence:
                    print(f"이동: {point.point_id}")
                    started = time.monotonic()
                    self.movej(point.joint)
                    elapsed = time.monotonic() - started

                    time.sleep(self.SETTLE_TIME_S)
                    actual_task, actual_joint, actual_solution = self.read_state()
                    row = self.make_row(
                        point,
                        actual_task,
                        actual_joint,
                        actual_solution,
                        elapsed,
                        previous_command_joint,
                    )
                    previous_command_joint = point.joint

                    if writer is None:
                        writer = csv.DictWriter(stream, fieldnames=list(row))
                        writer.writeheader()

                    writer.writerow(row)
                    stream.flush()
                    completed_points.append(point.point_id)

                    if self.virtual_joint_only and not row["joint_within_tolerance"]:
                        raise RuntimeError(f"{point.point_id}: 관절 도착 오차 1° 초과")
                    if row["within_tolerance"] is False:
                        out_of_tolerance.append(
                            {
                                "point_id": point.point_id,
                                "position_error_mm": row["position_error_mm"],
                                "orientation_error_deg": row[
                                    "orientation_error_deg"
                                ],
                            }
                        )
                        print(
                            f"경고: {point.point_id} 오차 초과 | "
                            f"위치={row['position_error_mm']:.3f} mm, "
                            f"방향={row['orientation_error_deg']:.3f}°"
                        )

            self.stop_reason = "completed"

        except (KeyboardInterrupt, ExternalShutdownException):
            self.stop_reason = "interrupted"
            if self.motion_started:
                self.stop_robot()
            raise

        except Exception as error:
            self.stop_reason = f"error: {error}"
            if self.motion_started:
                self.stop_robot()
            raise

        finally:
            summary = {
                "schema_version": 5,
                "virtual_joint_only": self.virtual_joint_only,
                "robot_system": self.robot_system,
                "active_tcp": self.active_tcp,
                "active_tool": self.active_tool,
                "task_error_evaluated": not self.virtual_joint_only,
                "preparation_joints": self.preparation_joints,
                "method": "stored recipe JOINT sequence -> MoveJ",
                "path_note": "MoveJ path is not straight; endpoint pose only",
                "recipe_snapshot": self.recipe.to_dict(),
                "required_tcp": self.REQUIRED_TCP,
                "required_tool": self.REQUIRED_TOOL,
                "joint_velocity_deg_s": self.JOINT_VELOCITY_DEG_S,
                "joint_acceleration_deg_s2": self.JOINT_ACCELERATION_DEG_S2,
                "move_timeout_s": self.MOVE_TIMEOUT_S,
                "position_tolerance_mm": self.POSITION_TOLERANCE_MM,
                "orientation_tolerance_deg": self.ORIENTATION_TOLERANCE_DEG,
                "posture_score_note": (
                    "0..1 heuristic from stored target JOINT; "
                    "not Jacobian manipulability"
                ),
                "joint_limits_deg": list(self.JOINT_LIMITS_DEG),
                "elbow_margin_full_deg": self.ELBOW_MARGIN_FULL_DEG,
                "wrist_margin_full_deg": self.WRIST_MARGIN_FULL_DEG,
                "completed_points": completed_points,
                "out_of_tolerance": out_of_tolerance,
                "stop_reason": self.stop_reason,
            }
            json_path.write_text(
                json.dumps(summary, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )

            print(f"시험 종료: {self.stop_reason}")
            print(f"결과 폴더: {result_dir}")


def main() -> int:
    """레시피를 선택하고 ROS 2 시험 객체의 수명을 관리한다."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--recipe", help="범위 시험 레시피 JSON 경로")
    parser.add_argument("--virtual-joint-only", action="store_true",
                        help="가상 시스템에서 관절 시퀀스만 검증, TASK 오차 판정 제외")
    parser.add_argument("--prepare-start", action="store_true",
                        help="가상 시작 자세를 최대 90도 관절 변화 경유점으로 준비")
    parser.add_argument("--confirm-virtual", action="store_true",
                        help="가상 관절 시험의 MOVE 입력 생략")
    args = parser.parse_args()
    try:
        recipe_path = args.recipe or input("범위 시험 레시피 JSON 경로: ").strip()
        if not recipe_path:
            raise ValueError("레시피 JSON 경로를 입력해야 합니다.")

        recipe = InspectionRecipe.load_json(recipe_path)
    except Exception as error:
        print(f"레시피 로드 실패: {error}")
        return 1

    rclpy.init(args=[])
    tester = None

    try:
        tester = PoseRangeTester(
            recipe, virtual_joint_only=args.virtual_joint_only,
            prepare_start=args.prepare_start, confirm_virtual=args.confirm_virtual,
        )
        tester.run()
    except (KeyboardInterrupt, ExternalShutdownException):
        print("사용자 중단")
    except Exception as error:
        print(f"시험 실패: {error}")
        return 1
    finally:
        if tester is not None:
            tester.node.destroy_node()
        rclpy.try_shutdown()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
