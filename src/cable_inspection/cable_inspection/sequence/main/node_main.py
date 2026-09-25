"""Main 실행 객체를 구성하고 단일 모션 Worker를 관리한다.
HMI 요청은 공개 메서드로 받고 통신 연결·메시지 발행은 HmiNode에 맡긴다.
종료 시 모션과 판정 Worker를 끝낸 뒤 각 노드를 해제한다.
"""

import argparse
import io
import signal
import threading
from pathlib import Path
import rclpy
from ament_index_python.packages import get_package_share_directory
from rclpy.executors import SingleThreadedExecutor
from rclpy.node import Node
from rclpy.signals import SignalHandlerOptions
from rclpy.utilities import remove_ros_args
from cable_inspection.sequence.main.data_models.system_state import SystemState
from cable_inspection.sequence.common.data_models.sequence_result import SequenceResult
from cable_inspection.recipe.node_recipe import RecipeNode
from cable_inspection.robot.node_robot import RobotNode
from cable_inspection.gripper_tool.node_gripper_tool import GripperToolNode
from cable_inspection.hmi.node_hmi import HmiNode
from cable_inspection.sequence.inspection.node_inspection import InspectionJudgmentNode
from cable_inspection.sequence.inspection.seq_inspection import InspectionSequence
from cable_inspection.sequence.home_return.seq_home_return import HomeReturnSequence
from cable_inspection.sequence.main.seq_main import MainSequence
from cable_inspection.sequence.common.motion import SequenceMotion



class MainSequenceNode(Node):
    """Main의 실행권과 Worker 수명을 소유한다. HMI 통신을 생성하지 않는다."""



    # 기능: Main·Inspection 실행 객체를 구성하고 장비에 STOP 감시를 연결한다.
    #     backend: 이미 생성한 Robot·GripperTool을 사용하는 공통 모션 객체.
    #     results_dir: 검사 결과 저장 경로.
    #     recipes: 레시피 검증·순회·진행 상태 담당 객체.
    #     judgment: 비동기 판정 담당 노드.
    #     반환: 없음. HMI 서비스·토픽과 장비 연결을 새로 생성하지 않는다.
    def __init__(self, backend, results_dir="results/inspection_sequence", *, recipes, judgment):
        super().__init__("ccc_sequence_node")
        self.controller = MainSequence(backend, results_dir,
            home_return_sequence=HomeReturnSequence,
            inspection=InspectionSequence(backend, judgment=judgment), recipes=recipes)
        backend.robot.control_poll = backend.control_poll
        backend.gripper.control_poll = backend.control_poll
        self.worker = None
        self.selected_recipe = next(iter(recipes.available_ids()), "")
        self.operation = ""
        self.closing = False



    # 기능: 이전 작업의 실행 또는 정리 Worker가 살아 있는지 확인한다.
    #     반환: Worker가 실행 중이면 True.
    def is_running(self):
        return self.worker is not None and self.worker.is_alive()



    # 기능: 기존 Worker가 없을 때 단일 모션 Worker에서 작업을 시작한다.
    #     action: 실행할 인자 없는 작업 함수. SequenceResult를 반환한다.
    #     operation: INSPECTION 또는 HOME 작업 구분.
    #     반환: 없음. 이미 실행 중이면 경고를 남기고 새 작업을 시작하지 않는다.
    def launch_operation(self, action, operation="INSPECTION"):
        if self.closing or (self.worker is not None and self.worker.is_alive()):
            self.controller.notify("WARN", "이전 시퀀스가 실행/정지 처리 중입니다.")
            return



        # 기능: 요청 작업을 실행하고 오류 시 정지 처리와 Main 상태 갱신을 수행한다.
        #     반환: 없음. 작업 결과와 예외를 로그 콜백에 전달한다.
        def work():
            try:
                result = action()
                self.controller.notify("INFO" if result.success else "ERROR", f"{result.code}: {result.message}")

            except Exception as error:
                self.controller._abort_motion()
                self.controller.last_error = str(error)
                self.controller.state = SystemState.ERROR
                self.controller.notify("ERROR", str(error))



        self.operation = operation
        self.controller.backend.latest_sample = None
        self.worker = threading.Thread(target=work, name="sequence-worker", daemon=False)
        self.worker.start()



    # 기능: Main의 대기 상태를 확인하고 등록된 검사 레시피를 선택한다.
    #     recipe_id: Recipe 담당에 등록된 레시피 식별자.
    #     반환: 없음. 미등록 또는 실행 중 선택은 ValueError.
    def select_recipe(self, recipe_id):
        if not isinstance(recipe_id, str) or recipe_id not in self.controller.recipes.available_ids():
            raise ValueError(f"등록되지 않은 Recipe: {recipe_id}")

        if (self.controller.state not in {SystemState.SYSTEM_READY, SystemState.STOPPED, SystemState.ERROR}
                or self.controller.context is not None
                or (self.worker is not None and self.worker.is_alive())):
            raise ValueError("진행 중인 작업이 없는 대기·정지·오류 상태에서 Recipe를 선택할 수 있습니다.")

        self.selected_recipe = recipe_id
        self.controller.notify("INFO", f"RECIPE_SELECTED: {recipe_id}")




    # 기능: 명령에 맞는 Main 시퀀스 제어를 수행한다.
    #     name: START/HOME_RETURN/MOVE_HOME/PAUSE/RESUME/STOP/SELECT_RECIPE.
    #     args: 명령 인자 사전. 레시피 선택과 START에는 recipe_id를 사용한다.
    #     반환: 없음. 실행 정책 위반·미지원 명령은 호출자에게 전달한다.
    def execute_command(self, name, args):
        if name == "START":
            # 레시피 선택보다 먼저 실행 상태를 확인하여 실제 START 거절 원인을 알린다.
            if self.is_running() or self.controller.context is not None:
                raise ValueError("START 불가: 이전 작업의 실행 또는 정리 중입니다.")

            if self.controller.state not in {SystemState.SYSTEM_READY, SystemState.STOPPED, SystemState.ERROR}:
                raise ValueError(f"START 불가: 현재 {self.controller.state.value}. 실행 중인 작업을 먼저 종료하세요.")

            recipe_id = args.get("recipe_id", self.selected_recipe)
            self.select_recipe(recipe_id)
            self.launch_operation(lambda: self.controller.run(recipe_id))

        elif name in {"HOME_RETURN", "MOVE_HOME"}:
            self.launch_operation(self.controller.request_home_return, operation="HOME")

        elif name in {"PAUSE", "RESUME", "STOP"}:
            if name == "STOP" and not self.is_running():
                self.controller.context = None
                self.controller.state = SystemState.STOPPED
                self.controller.notify("INFO", "STOPPED: 진행 중인 Job이 없습니다.")
                return

            action = {"PAUSE": self.controller.pause, "RESUME": self.controller.resume,
                      "STOP": self.controller.stop}[name]
            result = action()
            self.controller.notify("INFO" if result.success else "WARN", f"{result.code}: {result.message}")

        elif name == "SELECT_RECIPE":
            self.select_recipe(args.get("recipe_id", ""))

        else:
            raise ValueError(f"지원하지 않는 명령: {name}")



    # 기능: 실행 가능 여부를 확인하고 수신 레시피로 검사 Worker를 시작한다.
    #     recipe: Recipe 노드가 해석·검증한 검사 레시피 사전.
    #     run_id: HMI 접수 단계에서 부여한 실행 식별자.
    #     반환: 접수 성공 또는 BUSY/NOT_READY/NO_ENABLED_POINTS를 담은 SequenceResult.
    def start_inspection(self, recipe, run_id):
        if self.closing or self.controller.context is not None or self.is_running():
            return SequenceResult(False, "BUSY", "진행 중이거나 정리되지 않은 작업이 있습니다.")

        if self.controller.state not in {SystemState.SYSTEM_READY, SystemState.STOPPED, SystemState.ERROR}:
            return SequenceResult(False, "NOT_READY", "진행 중인 작업이 없는 대기·정지·오류 상태에서 시작할 수 있습니다.")

        if not any(point["enabled"] for point in recipe["points"]):
            return SequenceResult(False, "NO_ENABLED_POINTS", "활성 검사포인트가 없습니다.")

        self.controller.recipes.accept(recipe)
        self.selected_recipe = recipe["recipe_id"]
        self.controller.snapshot_notify(run_id, recipe)
        self.launch_operation(lambda: self.controller.run(recipe["recipe_id"], run_id=run_id))
        return SequenceResult(True, "ACCEPTED", "검사 실행 요청을 접수했습니다.")



    # 기능: 실행 중 Worker에 STOP을 요청하고 장비 처리가 끝날 때까지 기다린다.
    #     executor: 현재 스레드가 소유한 executor. 외부에서 계속 spin 중이면 None.
    #     반환: 없음. Worker 정지 완료까지 응답을 처리한 후 장비 노드를 파괴할 수 있다.
    def close(self, executor=None):
        self.closing = True

        if self.is_running():
            self.controller.stop()

            # 종료 중에도 STOP 서비스 응답·상태 콜백을 처리한다. 조기 join은 응답을 막는다.
            if executor is not None:
                while self.is_running():
                    executor.spin_once(timeout_sec=0.05)

            self.worker.join()



# 기능: 장비·시퀀스·HMI 노드를 구성하고 요청을 기다린 뒤 역순으로 종료한다.
#     argv: 명령행 인자 목록. None이면 프로세스 인자를 사용한다.
#     반환: 없음.
def main(argv=None):
    share = Path(get_package_share_directory("cable_inspection"))
    parser = argparse.ArgumentParser(description="CCCIS 전체 Job 실행")
    parser.add_argument("--system-recipe", type=Path, default=share / "config/system_recipe.json")
    parser.add_argument("--recipe", type=Path, action="append",
                        help="등록할 Inspection Recipe. 여러 번 지정할 수 있습니다.")
    parser.add_argument("--results-dir", type=Path, default=Path("results/inspection_sequence"))
    parser.add_argument("--robot-mode", choices=("real", "virtual"), default="real")
    parser.add_argument("--control-mode", choices=("hmi", "terminal"), default="hmi")

    # ros2 launch가 붙이는 --ros-args는 argparse에 넘기지 않는다.
    cli_args = remove_ros_args() if argv is None else remove_ros_args(args=["main_sequence", *argv])
    args = parser.parse_args(cli_args[1:])
    paths = args.recipe or ([] if args.control_mode == "hmi" else [share / "recipe/inspection/rcp_BMW_LWR_01.json"])

    # Ctrl+C 때 통신부터 닫히지 않게 하고, Worker 정지 요청을 먼저 마친다.
    shutdown_requested = threading.Event()
    previous_signals = {sig: signal.getsignal(sig) for sig in (signal.SIGINT, signal.SIGTERM)}

    for sig in previous_signals:
        signal.signal(sig, lambda *_: shutdown_requested.set())

    rclpy.init(args=argv, signal_handler_options=SignalHandlerOptions.NO)
    created_nodes = []
    node = hmi_node = judgment_node = executor = None

    try:
        recipes = RecipeNode(args.system_recipe, paths)
        created_nodes.append(recipes)
        system = recipes.system_settings()
        robot_node = RobotNode(args.robot_mode)
        created_nodes.append(robot_node)
        gripper_node = GripperToolNode(args.robot_mode)
        created_nodes.append(gripper_node)
        runtime = SequenceMotion(robot_node, gripper_node, io.StringIO())
        judgment_node = InspectionJudgmentNode("ccc_inspection_node")
        created_nodes.append(judgment_node)
        node = MainSequenceNode(runtime, args.results_dir, recipes=recipes, judgment=judgment_node)
        created_nodes.append(node)
        hmi_node = HmiNode(node, judgment_node, control_mode=args.control_mode,
                           heartbeat_timeout_s=system["heartbeat_timeout_s"])
        created_nodes.append(hmi_node)
        executor = SingleThreadedExecutor(context=node.context)

        for managed_node in created_nodes:
            executor.add_node(managed_node)

        # 모든 ROS 콜백은 여기서 처리한다. 모션 순서는 기존 단일 Worker만 담당한다.
        print(f"Main Work 대기 중 [{args.control_mode}]. START 전에는 검사 모션을 시작하지 않습니다.", flush=True)

        if args.control_mode == "terminal":
            print("별도 터미널: ros2 run cable_inspection sequence_console", flush=True)

        while rclpy.ok() and not shutdown_requested.is_set():
            executor.spin_once(timeout_sec=0.1)

    except KeyboardInterrupt:
        pass

    finally:
        if node is not None:
            node.close(executor)  # STOP 응답 처리를 유지한 채 Worker를 먼저 종료한다.

        if judgment_node is not None:
            judgment_node.close()

        if hmi_node is not None:
            hmi_node.publish_status()

        if executor is not None:
            executor.shutdown()

        for managed_node in reversed(created_nodes):
            managed_node.destroy_node()

        rclpy.try_shutdown()

        for sig, handler in previous_signals.items():
            signal.signal(sig, handler)



if __name__ == "__main__":
    main()
