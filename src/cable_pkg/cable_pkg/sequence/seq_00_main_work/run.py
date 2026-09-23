"""전체 Job 실행부: 장비와 제어 노드를 묶어 실행한다.
1. System/Inspection Recipe 경로와 저장 경로를 읽는다.
2. 장비 객체, SequenceController, 명령 수신 노드를 만든다.
3. START 명령을 기다리고 종료 시 Worker부터 정리한다."""

import argparse
import io
import json
import signal
import threading
from pathlib import Path

import rclpy
from ament_index_python.packages import get_package_share_directory
from rclpy.executors import SingleThreadedExecutor
from rclpy.signals import SignalHandlerOptions
from rclpy.utilities import remove_ros_args

from cable_pkg.hardware.sequence_robot import SequenceRobot
from .sequence import SequenceController
from .node import SequenceNode


# 기능: 명령행 설정을 읽어 장비·Job 제어·명령 수신 노드를 만들고 START를 기다린다.
#     argv: 명령행 인자 목록. None이면 실행 시 전달된 인자를 읽는다.
def main(argv=None):
    share = Path(get_package_share_directory("cable_pkg"))
    parser = argparse.ArgumentParser(description="CCCIS 전체 Job 실행")
    parser.add_argument("--system-recipe", type=Path, default=share / "config/system_recipe.json")
    parser.add_argument("--recipe", type=Path, action="append",
                        help="등록할 Inspection Recipe. 여러 번 지정할 수 있습니다.")
    parser.add_argument("--results-dir", type=Path, default=Path("results/inspection_sequence"))
    parser.add_argument("--control-mode", choices=("hmi", "terminal"), default="hmi")
    # ros2 launch가 붙이는 --ros-args는 argparse에 넘기지 않는다.
    cli_args = remove_ros_args() if argv is None else remove_ros_args(args=["main_sequence", *argv])
    args = parser.parse_args(cli_args[1:])
    paths = args.recipe or [share / "recipe/inspection/rcp_BMW_LWR_01.json"]
    recipes = {}
    for path in paths:
        raw = json.loads(path.read_text(encoding="utf-8"))
        if raw["recipe_id"] in recipes:
            raise ValueError(f"중복 Recipe ID: {raw['recipe_id']}")
        recipes[raw["recipe_id"]] = path
    # 좌표 미입력 상태에서도 노드는 실행된다. START의 Initialize가 상세 사유를 반환한다.
    system = json.loads(args.system_recipe.read_text(encoding="utf-8"))
    # Ctrl+C 때 통신부터 닫히지 않게 하고, Worker 정지 요청을 먼저 마친다.
    shutdown_requested = threading.Event()
    previous_signals = {sig: signal.getsignal(sig) for sig in (signal.SIGINT, signal.SIGTERM)}
    for sig in previous_signals:
        signal.signal(sig, lambda *_: shutdown_requested.set())
    rclpy.init(args=argv, signal_handler_options=SignalHandlerOptions.NO)
    robot = SequenceRobot(args.system_recipe, recipes, io.StringIO())
    controller = SequenceController(robot, args.results_dir)
    node = SequenceNode(controller, heartbeat_timeout_s=system["heartbeat_timeout_s"],
                        control_mode=args.control_mode)
    executor = SingleThreadedExecutor(context=node.context)
    executor.add_node(node)  # 장비 노드는 Worker에서만 spin한다.
    print(f"Main Work 대기 중 [{args.control_mode}]. START 전에는 검사 모션을 시작하지 않습니다.", flush=True)
    if args.control_mode == "terminal":
        print("별도 터미널: ros2 run cable_pkg sequence_console", flush=True)
    try:
        while rclpy.ok() and not shutdown_requested.is_set():
            executor.spin_once(timeout_sec=0.1)
    except KeyboardInterrupt:
        pass
    finally:
        node.close()
        executor.shutdown()
        node.destroy_node()
        robot.close()
        rclpy.try_shutdown()
        for sig, handler in previous_signals.items():
            signal.signal(sig, handler)


if __name__ == "__main__":
    main()
