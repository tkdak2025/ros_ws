"""#02 Home Return 흐름. Main이 보유한 실행권 안에서만 호출한다."""

import math

from cable_inspection.sequence.common.data_models.sequence_result import SequenceResult
from cable_inspection.recipe.recipe import RobotPose
from cable_inspection.sequence.common.geometry import orientation_error_deg, reverse_tool_axis
from cable_inspection.safety.workspace_boundary import BoxBoundary



class HomeReturnSequence:
    """#02 경로만 실행한다. Job 상태와 실행권은 Main이 관리한다."""



    # 기능: Main의 실행권과 시스템 설정을 받아 복귀 시퀀스를 준비한다.
    def __init__(self, backend, checkpoint, poll_control, system):
        self.backend = backend
        self.system = system
        self.checkpoint = checkpoint
        self.poll_control = poll_control



    # 기능: 이미 연결된 Robot API에서 현재 TCP를 읽는다.
    def current_tcp(self):
        return self.backend.robot.get_tcp()



    # 기능: 현재 TCP가 설정된 작업영역 내부인지 확인한다.
    def tcp_is_in_work_area(self, tcp):
        return BoxBoundary(**self.system["work_area"]).contains_inside(tcp[:3], 0)



    # 기능: START와 HOME이 현재 Work Access 도달 여부를 같은 기준으로 확인한다.
    #     tcp: 현재 BASE 기준 TCP [X,Y,Z,A,B,C](mm/deg). virtual은 실측 관절을 사용한다.
    #     반환: real의 위치·자세 또는 virtual의 관절이 Access 허용오차 이내이면 True.
    def tcp_is_at_work_access(self, tcp):
        backend = self.backend

        if backend.robot.mode == "virtual":
            # 가상 FK와 교시 TASK 사이의 상수 오차가 있으므로 관절 도달로 검사한다.
            target_joint = self.system["work_Access_safe_pose"]["joint"]

            return all(abs((actual - target + 180.0) % 360.0 - 180.0) <= 0.1
                       for actual, target in zip(self.current_joints(), target_joint))

        target = self.system["work_Access_safe_pose"]["task"]

        return (len(tcp) == 6
                and math.dist(tcp[:3], target[:3]) <= backend.config.position_tolerance_mm
                and orientation_error_deg(tcp[3:], target[3:])
                <= backend.config.orientation_tolerance_deg)



    # 기능: Safe Escape 전에 그리퍼를 열고 실제 개방 폭을 확인한다.
    def relax_grip(self):
        backend = self.backend
        opened = backend.open_gripper(self.system["relax_width_mm"], self.system["relax_force_n"])
        measured = opened["measured"]

        if (not math.isfinite(measured["width_mm"])
                or abs(measured["width_mm"] - self.system["relax_width_mm"])
                > backend.config.width_tolerance_mm):
            raise RuntimeError("Safe Escape 전 그리퍼 Open 폭 확인 실패")

        return SequenceResult(True, "GRIP_RELAXED", "GRIP_RELAXED")



    def safe_escape(self, distance_mm):
        """현재 Tool 접근축 반대로 지정 거리만큼 후퇴하고 목표 도달을 확인한다."""
        backend = self.backend
        tcp = backend.robot.get_tcp()
        RobotPose(task=tcp, joint=[0.0] * 6).validate("현재 TCP")

        if (isinstance(distance_mm, bool) or not isinstance(distance_mm, (int, float))
                or not math.isfinite(distance_mm) or not 0 < distance_mm <= 30.0):
            raise ValueError("Safe Escape 거리는 0 초과 30 mm 이하여야 합니다.")

        direction = reverse_tool_axis(tcp[3:], self.system["tool_approach_axis"])
        target = [tcp[i] + direction[i] * distance_mm for i in range(3)] + tcp[3:]
        motion = backend.move_linear(target)

        if motion.get("stop_reason") != "TARGET_REACHED":
            raise RuntimeError("Safe Escape 후퇴 목표 도달 확인 실패")

        return SequenceResult(True, "SAFE_ESCAPE_DONE", "SAFE_ESCAPE_DONE",
                              {"distance_mm": distance_mm})



    def move_safe_route_home(self):
        """사전에 설정한 경유점만 사용한다. 실패 시 대체 경로를 생성하지 않는다."""
        backend = self.backend
        route = self.system.get("safe_home_route")

        if not route or route[-1] != self.system["home_pose"]:
            raise ValueError("검증된 safe_home_route와 마지막 Home 자세가 필요합니다.")

        for pose in route[:-1]:
            backend.move_joint(RobotPose(**pose))

        return self.move_home_pose()



    # 기능: 설정된 Home으로 MoveJ하고 실제 관절각 도달을 확인한다.
    def move_home_pose(self):
        backend = self.backend
        pose = RobotPose(**self.system["home_pose"])
        backend.move_joint(pose)
        tolerance = self.system["home_joint_tolerance_deg"]

        if any(abs(actual - target) > tolerance
               for actual, target in zip(self.current_joints(), pose.joint)):
            raise RuntimeError("Home 복귀 후 목표 관절각 도달 확인 실패")

        return SequenceResult(True, "HOME_REACHED", "HOME_REACHED")



    # 기능: 현재 관절값 여섯 개의 유효성을 확인한다.
    def current_joints(self):
        joints = self.backend.robot.read_joints()

        if len(joints) != 6 or not all(math.isfinite(v) for v in joints):
            raise RuntimeError("현재 관절값이 유효하지 않습니다.")

        return joints



    # 기능: 현재 Access 도달 여부를 먼저 확인하고 작업영역에 따라 Home 경로를 선택한다.
    #     인자: 없음. 장비의 현재 TCP와 시스템 설정을 사용한다.
    #     반환: 선택 경로·시작 TCP와 Home 도달 결과를 담은 SequenceResult.
    def run(self) -> SequenceResult:
        self.backend.phase = "SEQ_02_HOME_RETURN"

        # Main이 장비 준비·운전 가능 상태를 확인한 후 이 시퀀스를 호출한다.
        tcp = self.current_tcp()

        if len(tcp) != 6 or not all(math.isfinite(value) for value in tcp):
            return SequenceResult(False, "INVALID_TCP", "현재 TCP 값이 잘못되었습니다.")

        # Access가 작업영역 내부여도 이미 도달했다면 중복 Open·후퇴를 생략한다.
        if self.tcp_is_at_work_access(tcp):
            result = self.return_via_home_route()
            route = "VERIFIED_ACCESS_HOME"

        elif self.tcp_is_in_work_area(tcp):
            result = self.return_from_work_area()
            route = "WORK_AREA_ESCAPE"

        else:
            result = self.return_via_home_route()
            route = "SAFE_ROUTE_HOME"

        if not result.success:
            return result

        return SequenceResult(
            True,
            "HOME_RETURN_OK",
            "Home Return을 완료했습니다.",
            {"route": route, "start_tcp": tcp[:6]},
        )



    # 기능: 작업영역에서 그리퍼를 열고 현재 Tool 접근축 반대로 후퇴한다.
    #     인자: 없음. 시스템 설정의 Open 폭·힘과 후퇴 거리를 사용한다.
    #     반환: 마지막 단계의 SequenceResult. 실패하면 Access 이동을 실행하지 않는다.
    def escape_work_area(self):
        # 케이블 파지 여부를 추정하지 않고 이완 → 역방향 탈출을 수행한다.
        steps = (
            ("GRIP_RELAXED", self.relax_grip),
            ("SAFE_ESCAPE_DONE", lambda: self.safe_escape(
                self.system["max_escape_distance_mm"])),
        )

        for checkpoint, action in steps:
            self.poll_control()
            result = action()

            if not result.success:
                return result

            self.checkpoint(checkpoint)

        return result



    # 기능: 작업영역에서 Safe Escape 후 Work Access를 거쳐 Home으로 복귀한다.
    #     인자: 없음. 생성 시 전달받은 시스템 설정과 공통 모션을 사용한다.
    #     반환: 탈출 실패 또는 Home 도달 결과를 담은 SequenceResult.
    def return_from_work_area(self):
        result = self.escape_work_area()

        if not result.success:
            return result

        self.poll_control()
        self.backend.move_joint(RobotPose(**self.system["work_Access_safe_pose"]))
        self.checkpoint("WORK_ACCESS_REACHED")
        return self.return_via_home_route()



    # 기능: 설정 경로로 Home에 도달한 후 완료점을 기록한다.
    def return_via_home_route(self):
        result = self.move_safe_route_home()

        if result.success:
            self.checkpoint("HOME_REACHED")

        return result


