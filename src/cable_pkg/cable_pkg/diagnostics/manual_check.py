"""실물 M0609의 현재 위치와 상태를 필요할 때 조회한다.

로봇 이동, Servo On/Off, 모드 변경 서비스는 호출하지 않는다.
"""

import rclpy
from dsr_msgs2.srv import (
    GetControlMode,
    GetCurrentPosj,
    GetCurrentPosx,
    GetCurrentSolutionSpace,
    GetCurrentTcp,
    GetCurrentTool,
    GetCurrentVelj,
    GetCurrentVelx,
    GetRobotMode,
    GetRobotState,
    GetRobotSystem,
)


class ManualRobotCheck:
    """현재 좌표·속도·제어기 상태를 한 번 조회한다."""

    SERVICE_PREFIX = "/dsr01/dsr_controller2"
    SERVICE_TIMEOUT_S = 3.0

    ROBOT_STATE_NAMES = {
        0: "INITIALIZING",
        1: "STANDBY",
        2: "MOVING",
        3: "SAFE_OFF",
        4: "TEACHING",
        5: "SAFE_STOP",
        6: "EMERGENCY_STOP",
        7: "HOMMING",
        8: "RECOVERY",
        9: "SAFE_STOP2",
        10: "SAFE_OFF2",
    }

    def __init__(self) -> None:
        self.node = rclpy.create_node("manual_robot_check")
        prefix = self.SERVICE_PREFIX

        self.clients = {
            "joint": self.node.create_client(
                GetCurrentPosj, prefix + "/aux_control/get_current_posj"
            ),
            "task": self.node.create_client(
                GetCurrentPosx, prefix + "/aux_control/get_current_posx"
            ),
            "joint_velocity": self.node.create_client(
                GetCurrentVelj, prefix + "/aux_control/get_current_velj"
            ),
            "task_velocity": self.node.create_client(
                GetCurrentVelx, prefix + "/aux_control/get_current_velx"
            ),
            "solution_space": self.node.create_client(
                GetCurrentSolutionSpace,
                prefix + "/aux_control/get_current_solution_space",
            ),
            "robot_state": self.node.create_client(
                GetRobotState, prefix + "/system/get_robot_state"
            ),
            "robot_mode": self.node.create_client(
                GetRobotMode, prefix + "/system/get_robot_mode"
            ),
            "robot_system": self.node.create_client(
                GetRobotSystem, prefix + "/system/get_robot_system"
            ),
            "control_mode": self.node.create_client(
                GetControlMode, prefix + "/aux_control/get_control_mode"
            ),
            "tcp": self.node.create_client(
                GetCurrentTcp, prefix + "/tcp/get_current_tcp"
            ),
            "tool": self.node.create_client(
                GetCurrentTool, prefix + "/tool/get_current_tool"
            ),
        }

    # ------------------------------------------------------------------
    # 서비스 호출
    # ------------------------------------------------------------------

    def call(self, name: str, request):
        """서비스 존재와 응답 성공 여부를 확인하고 응답을 반환한다."""
        client = self.clients[name]
        if not client.wait_for_service(timeout_sec=self.SERVICE_TIMEOUT_S):
            raise RuntimeError(f"서비스를 찾지 못했습니다: {client.srv_name}")

        future = client.call_async(request)
        rclpy.spin_until_future_complete(
            self.node,
            future,
            timeout_sec=self.SERVICE_TIMEOUT_S,
        )

        if not future.done():
            future.cancel()
            raise TimeoutError(f"서비스 응답 시간 초과: {client.srv_name}")

        response = future.result()
        if response is None or not response.success:
            raise RuntimeError(f"서비스 호출 실패: {client.srv_name}")

        return response

    # ------------------------------------------------------------------
    # 위치와 속도 조회
    # ------------------------------------------------------------------

    def get_joint_position(self) -> list[float]:
        """현재 J1~J6 관절각을 deg 단위로 반환한다."""
        response = self.call("joint", GetCurrentPosj.Request())
        return [float(value) for value in response.pos]

    def get_task_position(self) -> tuple[list[float], int]:
        """BASE 기준 TCP [X,Y,Z,A,B,C]와 solution space를 반환한다."""
        request = GetCurrentPosx.Request()
        request.ref = 0  # DR_BASE
        response = self.call("task", request)

        if not response.task_pos_info:
            raise RuntimeError("현재 TCP 응답이 비어 있습니다.")

        values = [float(value) for value in response.task_pos_info[0].data]
        if len(values) < 7:
            raise RuntimeError("현재 TCP 응답 길이가 잘못되었습니다.")

        return values[:6], int(round(values[6]))

    def get_velocity(self) -> tuple[list[float], list[float]]:
        """현재 관절속도와 BASE 기준 TCP 속도를 반환한다."""
        joint_response = self.call(
            "joint_velocity",
            GetCurrentVelj.Request(),
        )

        task_request = GetCurrentVelx.Request()
        task_request.ref = 0  # DR_BASE
        task_response = self.call("task_velocity", task_request)

        return (
            [float(value) for value in joint_response.joint_speed],
            [float(value) for value in task_response.vel],
        )

    # ------------------------------------------------------------------
    # 로봇 상태 조회
    # ------------------------------------------------------------------

    def get_robot_status(self) -> dict:
        """로봇 상태, 모드, 시스템, 제어 모드와 활성 Tool 정보를 반환한다."""
        state = int(
            self.call("robot_state", GetRobotState.Request()).robot_state
        )

        return {
            "robot_state": state,
            "robot_state_name": self.ROBOT_STATE_NAMES.get(
                state, f"UNKNOWN({state})"
            ),
            "robot_mode": int(
                self.call("robot_mode", GetRobotMode.Request()).robot_mode
            ),
            "robot_system": int(
                self.call(
                    "robot_system", GetRobotSystem.Request()
                ).robot_system
            ),
            "control_mode": int(
                self.call(
                    "control_mode", GetControlMode.Request()
                ).control_mode
            ),
            "solution_space": int(
                self.call(
                    "solution_space",
                    GetCurrentSolutionSpace.Request(),
                ).sol_space
            ),
            "tcp": self.call("tcp", GetCurrentTcp.Request()).info,
            "tool": self.call("tool", GetCurrentTool.Request()).info,
        }

    # ------------------------------------------------------------------
    # 전체 결과 출력
    # ------------------------------------------------------------------

    @staticmethod
    def print_values(title: str, values: list[float], unit: str) -> None:
        """6축 수치를 동일한 형식으로 출력한다."""
        print(f"{title} [{unit}]:", [round(value, 3) for value in values])

    def print_joint_position(self) -> None:
        """현재 J1~J6만 출력한다."""
        self.print_values("JOINT", self.get_joint_position(), "deg")

    def print_task_position(self) -> None:
        """현재 BASE TCP와 solution space만 출력한다."""
        task, solution_space = self.get_task_position()
        self.print_values("TASK", task, "mm, deg")
        print(f"Solution space: {solution_space}")

    def print_velocity(self) -> None:
        """현재 관절속도와 BASE TCP 속도만 출력한다."""
        joint_velocity, task_velocity = self.get_velocity()
        self.print_values("JOINT velocity", joint_velocity, "deg/s")
        self.print_values("TASK velocity", task_velocity, "mm/s, deg/s")

    def print_robot_status(self) -> None:
        """현재 제어기 상태와 활성 TCP·Tool만 출력한다."""
        status = self.get_robot_status()
        print(
            f"State : {status['robot_state']} "
            f"({status['robot_state_name']})"
        )
        print(f"Mode  : {status['robot_mode']}")
        print(f"System: {status['robot_system']}")
        print(f"Control mode : {status['control_mode']}")
        print(f"TCP / Tool   : {status['tcp']} / {status['tool']}")
        print(f"Solution space: {status['solution_space']}")

    def print_snapshot(self) -> None:
        """현재 위치·속도·상태를 사람이 읽기 쉬운 형식으로 출력한다."""
        task, task_solution = self.get_task_position()
        joints = self.get_joint_position()
        joint_velocity, task_velocity = self.get_velocity()
        status = self.get_robot_status()

        print("\n[로봇 상태]")
        print(
            f"State : {status['robot_state']} "
            f"({status['robot_state_name']})"
        )
        print(f"Mode  : {status['robot_mode']}")
        print(f"System: {status['robot_system']}")
        print(f"Control mode : {status['control_mode']}")
        print(f"TCP / Tool   : {status['tcp']} / {status['tool']}")
        print(
            f"Solution space: {status['solution_space']} "
            f"(TCP 응답: {task_solution})"
        )

        print("\n[현재 위치]")
        print("TASK  [mm, deg]:", [round(value, 3) for value in task])
        print("JOINT [deg]    :", [round(value, 3) for value in joints])

        print("\n[현재 속도]")
        print(
            "JOINT velocity [deg/s]:",
            [round(value, 3) for value in joint_velocity],
        )
        print(
            "TASK velocity          :",
            [round(value, 3) for value in task_velocity],
        )

    def run_menu(self) -> None:
        """선택한 항목을 한 번 조회하고 종료 입력 전까지 메뉴를 반복한다."""
        actions = {
            "1": self.print_joint_position,
            "2": self.print_task_position,
            "3": self.print_velocity,
            "4": self.print_robot_status,
            "5": self.print_snapshot,
        }

        try:
            while rclpy.ok():
                print("\n1. 관절 위치 J1~J6")
                print("2. BASE TCP 위치·자세")
                print("3. 관절·TCP 속도")
                print("4. 로봇 상태·모드·TCP·Tool")
                print("5. 전체 항목")
                print("Q. 종료")

                selection = input("확인할 항목: ").strip().upper()
                if selection == "Q":
                    break

                action = actions.get(selection)
                if action is None:
                    print("1~5 또는 Q를 입력하세요.")
                    continue

                print("\n----------------------------------------")
                action()
        except KeyboardInterrupt:
            pass

        print("\n상태 확인을 종료합니다.")


def main() -> int:
    """ROS 노드를 초기화하고 한 번 조회한 뒤 종료한다."""
    rclpy.init(args=[])
    checker = None

    try:
        checker = ManualRobotCheck()
        checker.run_menu()
    except Exception as error:
        print(f"조회 실패: {error}")
        return 1
    finally:
        if checker is not None:
            checker.node.destroy_node()
        rclpy.try_shutdown()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
