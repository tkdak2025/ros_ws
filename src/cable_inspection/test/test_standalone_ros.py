"""선택 실행: cable_pkg/HMI 없는 설치에서 실제 launch·서비스·구독을 검증한다."""
import importlib.util
import json
import os
from pathlib import Path
import signal
import subprocess
import time

import pytest

pytestmark = pytest.mark.skipif(
    os.environ.get("CCCIS_STANDALONE_TEST") != "1",
    reason="격리 워크스페이스에서 CCCIS_STANDALONE_TEST=1로 실행",
)



def test_standalone_launches_and_services(tmp_path):
    assert importlib.util.find_spec("cable_pkg") is None
    assert importlib.util.find_spec("cable_management") is None
    assert importlib.util.find_spec("cable_hmi") is None
    import rclpy
    from rclpy.node import Node
    from rclpy.qos import QoSProfile, ReliabilityPolicy, DurabilityPolicy
    from std_msgs.msg import String
    from cable_interfaces.msg import InspectionResult
    from cable_interfaces.srv import StartInspection
    from ament_index_python.packages import get_package_share_directory
    from importlib.metadata import distribution
    from cable_inspection.recipe.recipe import Recipe
    from cable_inspection.recipe.node_recipe import RecipeNode

    env = dict(os.environ)
    env.pop("ROS_DISCOVERY_SERVER", None)
    env["ROS_DOMAIN_ID"] = "232"
    env["ROS_AUTOMATIC_DISCOVERY_RANGE"] = "LOCALHOST"
    env["ROS_LOG_DIR"] = str(tmp_path / "ros_logs")
    processes, logs = [], []
    node = None

    try:
        for name, arguments in (
            ("inspection", ["control_mode:=hmi", f"results_dir:={tmp_path}/raw"]),
        ):
            logfile = (tmp_path / f"{name}.log").open("w+")
            logs.append(logfile)
            processes.append(subprocess.Popen(
                ["ros2", "launch", "cable_inspection", f"{name}.launch.py", *arguments],
                stdout=logfile, stderr=subprocess.STDOUT, env=env,
                start_new_session=True,
            ))

        rclpy.init(domain_id=232)
        node = Node("standalone_test_client")
        statuses = {}
        qos = QoSProfile(depth=10, reliability=ReliabilityPolicy.RELIABLE,
                         durability=DurabilityPolicy.TRANSIENT_LOCAL)
        node.create_subscription(String, "cable_inspection/work_status",
            lambda m: statuses.update(work=json.loads(m.data)), qos)
        node.create_subscription(String, "cable_inspection/robot_status",
            lambda m: statuses.update(robot=json.loads(m.data)), 10)



        def wait_until(predicate, timeout=15):
            deadline = time.monotonic() + timeout

            while time.monotonic() < deadline:
                assert all(p.poll() is None for p in processes), "launch exited early"

                if predicate():
                    return

                rclpy.spin_once(node, timeout_sec=0.05)

            raise AssertionError("ROS discovery/response timed out")



        def call(service, name, request):
            client = node.create_client(service, "cable_inspection/" + name)

            try:
                wait_until(client.service_is_ready)
                future = client.call_async(request)
                wait_until(future.done)
                return future.result()

            finally:
                node.destroy_client(client)



        wait_until(lambda: "work" in statuses and "robot" in statuses)
        assert statuses["work"]["run_state"] == "SYSTEM_READY"
        assert statuses["work"]["control_mode"] == "hmi"
        assert not statuses["robot"]["robot_connected"]
        wait_until(lambda: {"ccc_sequence_node", "ccc_hmi_node", "ccc_inspection_node", "ccc_recipe_node", "ccc_robot_node", "ccc_gripper_tool_node"}.issubset(
            {name for name, namespace in node.get_node_names_and_namespaces()}))
        assert "ccc_robot_state" not in {name for name, _ in node.get_node_names_and_namespaces()}

        # 설치 결과에도 HMI 관리용 노드/launch가 남아 있으면 안 된다.
        share = Path(get_package_share_directory("cable_inspection"))
        assert not (share / "launch/management.launch.py").exists()
        assert importlib.util.find_spec("cable_inspection.result_node") is None
        assert importlib.util.find_spec("cable_inspection.recipe_node") is None
        executables = {e.name for e in distribution("cable_inspection").entry_points
                       if e.group == "console_scripts"}
        assert "robot_state_node" not in subprocess.check_output(
            ["ros2", "pkg", "executables", "cable_inspection"], text=True)
        assert executables == {"main_sequence", "inspection_judgment",
                               "sequence_console", "manual_check"}
        services = {name for name, types in node.get_service_names_and_types()}
        recipe_services = {name for name, _types in
            node.get_service_names_and_types_by_node("ccc_hmi_node", "/")}
        assert "/cable_inspection/start" in recipe_services
        assert "/cable_inspection/start" not in {
            name for name, _ in node.get_service_names_and_types_by_node("ccc_sequence_node", "/")}

        for topic in ("work_status", "robot_status", "execution_snapshot", "judgment_result", "log"):
            wait_until(lambda topic=topic: bool(node.get_publishers_info_by_topic("cable_inspection/" + topic)))
            assert {info.node_name for info in node.get_publishers_info_by_topic(
                "cable_inspection/" + topic)} == {"ccc_hmi_node"}

        for topic in ("command", "hmi_heartbeat", "judgment_request"):
            wait_until(lambda topic=topic: bool(node.get_subscriptions_info_by_topic("cable_inspection/" + topic)))
            assert {info.node_name for info in node.get_subscriptions_info_by_topic(
                "cable_inspection/" + topic)} == {"ccc_hmi_node"}

        assert not any(name.startswith("/cable_inspection/recipes/")
                       or name == "/cable_inspection/results/query" for name in services)
        recipe = RecipeNode.encode_message(Recipe.load_json(
            share / "recipe/inspection/rcp_BMW_LWR_01.json"))

        # 유효 START/Home/STOP은 보내지 않는다. 잘못된 요청과 heartbeat 부재만 확인한다.
        rejected = call(StartInspection, "start", StartInspection.Request(recipe=recipe))
        assert not rejected.accepted and rejected.run_id == 0
        assert rejected.code == "INVALID_REQUEST_ID"
        rejected = call(StartInspection, "start", StartInspection.Request(
            request_id="standalone-no-heartbeat", recipe=recipe))
        assert not rejected.accepted and rejected.code == "HEARTBEAT_MISSING"
        node.create_subscription(InspectionResult, "cable_inspection/judgment_result", lambda m: None, 50)
        wait_until(lambda: node.count_publishers("cable_inspection/judgment_result") > 0)
        wait_until(lambda: node.count_publishers("cable_inspection/execution_snapshot") > 0)
        assert not (tmp_path / "raw").exists(), "검사가 시작되면 안 됩니다."

    finally:
        if node is not None:
            node.destroy_node()

        rclpy.try_shutdown()

        for process in processes:
            if process.poll() is None:
                # launch가 자식에게 SIGINT를 전달한다. 그룹에 보내면 중복 전달된다.
                process.send_signal(signal.SIGINT)

        for process in processes:
            try:
                process.wait(timeout=10)

            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait(timeout=5)

        for logfile in logs:
            logfile.seek(0)
            print(logfile.read())
            logfile.close()



def test_recipe_node_preserves_component_storage():
    import rclpy
    from cable_inspection.recipe.node_recipe import RecipeNode
    package = Path(__file__).parents[1]
    rclpy.init()
    recipes = None

    try:
        recipes = RecipeNode(package / "config/system_recipe.json", [
            package / "cable_inspection/recipe/inspection/lan_inspection_recipe.json"])
        recipe_id, = recipes.available_ids()
        recipe = recipes.get(recipe_id)
        decoded = recipes.decode_message(RecipeNode.encode_message(recipe))
        recipes.accept(decoded)
        decoded["points"].reverse()
        assert recipes.get(recipe_id)["points"] == recipe["points"]
        assert recipes.system_recipe()["coordinate_frame"] == "BASE"

    finally:
        if recipes is not None:
            recipes.destroy_node()

        rclpy.try_shutdown()



@pytest.mark.parametrize("mode", ["real", "virtual"])
def test_devices_communicate_independently_with_simulated_ros_servers(mode):
    """격리 ROS 도메인의 모의 서버만 사용한다. 실제 장비에는 연결하지 않는다."""
    import math
    import threading
    import rclpy
    from rclpy.node import Node
    from rclpy.executors import SingleThreadedExecutor
    from onrobot_rg_msgs.srv import SetCommand
    from dsr_msgs2.srv import GetRobotSystem, MoveJoint
    from sensor_msgs.msg import JointState
    from cable_inspection.gripper_tool.node_gripper_tool import GripperToolNode
    from cable_inspection.robot.node_robot import RobotNode

    rclpy.init(domain_id=232)
    servers = []
    gripper = robot = executor = thread = None
    done = threading.Event()
    commands, motions = [], []

    try:
        rg_server = Node('OnRobotRGControllerServer' if mode == 'real' else 'gripper_virtual_node', namespace='/dsr01')
        servers.append(rg_server)



        def grip(request, response):
            commands.append(request.command)
            response.success = True

            return response



        rg_server.create_service(SetCommand, '/onrobot/sendCommand', grip)
        topic = '/onrobot_joint_states' if mode == 'real' else '/dsr01/gripper_joint_states'
        publisher = rg_server.create_publisher(JointState, topic, 10)
        rg_server.create_timer(0.02, lambda: publisher.publish(
            JointState(position=[0.0], effort=[1.0])))
        executor = SingleThreadedExecutor()
        executor.add_node(rg_server)



        def serve():
            while not done.is_set():
                executor.spin_once(timeout_sec=0.02)



        thread = threading.Thread(target=serve)
        thread.start()

        # Robot 노드를 만들지 않은 상태에서 RG2 자체 서비스와 피드백을 확인한다.
        gripper = GripperToolNode(mode)
        executor.add_node(gripper)
        deadline = time.monotonic() + 5.

        while True:
            try:
                gripper.check_ready()
                break

            except RuntimeError:
                if time.monotonic() >= deadline:
                    raise

                time.sleep(0.02)

        gripper.set_grip(25., 40., opening=True)
        width, stamp = gripper.read_width(2.)
        expected = (math.cos(0.76794) * 0.055 - 0.0144 + 0.108505 * math.cos(1.41371)) * 2000.
        assert width == pytest.approx(expected)
        assert gripper.gripper_busy is True
        expected_command = ('250' if mode == 'real' else str(
            math.acos((25. / 2000. + 0.0144 - 0.108505 * math.cos(1.41371)) / 0.055) - 0.76794))
        assert commands == [expected_command]
        executor.remove_node(gripper)
        gripper.destroy_node()
        gripper = None

        # GripperTool 노드를 닫은 상태에서 Robot 자체 서비스 요청을 확인한다.
        robot_server = Node('simulated_m0609', namespace='/dsr01')
        servers.append(robot_server)



        def system(request, response):
            response.success = True
            response.robot_system = 0 if mode == "real" else 1

            return response



        def move(request, response):
            motions.append((list(request.pos), request.sync_type))
            response.success = True

            return response



        robot_server.create_service(GetRobotSystem, '/dsr01/dsr_controller2/system/get_robot_system', system)
        robot_server.create_service(MoveJoint, '/dsr01/dsr_controller2/motion/move_joint', move)
        executor.add_node(robot_server)
        robot = RobotNode(mode)
        executor.add_node(robot)
        assert robot.system_client.wait_for_service(timeout_sec=5.)
        assert robot.movej_client.wait_for_service(timeout_sec=5.)
        robot.move_joint([0.] * 6, 10., 20.)
        assert motions == [([0.] * 6, 1)]
        assert commands == [expected_command]

    finally:
        done.set()

        if thread is not None:
            thread.join(timeout=5.)

        if executor is not None:
            executor.shutdown()

        for device in (robot, gripper):
            if device is not None:
                device.destroy_node()

        for server in reversed(servers):
            server.destroy_node()

        rclpy.try_shutdown()



def test_inspection_receives_judgment_without_robot_ros_entities(tmp_path):
    """Robot ROS 노드 없이 Inspection의 요청·판정 수신과 기존 결과 토픽을 검증한다."""
    from types import SimpleNamespace
    import rclpy
    from rclpy.executors import SingleThreadedExecutor
    from cable_inspection.recipe.recipe import Recipe
    from cable_inspection.sequence.main.node_main import MainSequenceNode
    from cable_inspection.sequence.inspection.node_inspection import InspectionJudgmentNode

    rclpy.init(domain_id=232)
    node = hmi = judge = executor = None

    try:
        recipe = Recipe.load_json(Path(__file__).parents[1] /
            'cable_inspection/recipe/inspection/lan_inspection_recipe.json')
        recipes = Recipe()
        recipes.accept(recipe)
        recipes.begin(recipe['recipe_id'], 991)
        point = recipes.next_point()

        # 이 객체에는 create_publisher/create_subscription/spin API가 없다.
        motion = SimpleNamespace(robot=status_devices()[0], gripper=status_devices()[1], latest_sample=None)
        judge = InspectionJudgmentNode('ownership_test_judgment')
        node = MainSequenceNode(motion, tmp_path, recipes=recipes, judgment=judge)
        from cable_inspection.hmi.node_hmi import HmiNode
        hmi = HmiNode(node, judge)
        assert motion.robot.control_poll is motion.control_poll
        assert motion.gripper.control_poll is motion.control_poll
        executor = SingleThreadedExecutor()
        executor.add_node(node)
        executor.add_node(judge)
        executor.add_node(hmi)
        inspection = node.controller.inspection
        inspection.begin(991)
        deadline = time.monotonic() + 10

        while not inspection.judgment.is_ready():
            assert time.monotonic() < deadline
            executor.spin_once(timeout_sec=0.05)

        inspection.prepare(recipe['recipe_id'], recipe['recipe_version'],
                           recipe['connector_type'], lambda: None)
        from cable_interfaces.msg import InspectionResult
        published = []
        node.create_subscription(InspectionResult, 'cable_inspection/judgment_result', published.append, 10)

        while hmi.result_pub.get_subscription_count() == 0:
            assert time.monotonic() < deadline
            executor.spin_once(timeout_sec=0.05)

        assert node.count_publishers('cable_inspection/judgment_request') == 0
        inspection.submit_pull_result(point, {'soft_width_mm': 22.}, {
            'stop_reason': 'PULL_FORCE_LIMIT', 'pull_width_mm': 16.5,
            'peak_pull_force_n': 16., 'pull_displacement_mm': 2.,
        })
        assert recipes.progress()['pending_judgments'] == 1

        while point['point_id'] not in inspection.results():
            assert time.monotonic() < deadline
            time.sleep(0.01)  # Executor 수신 없이도 별도 Worker가 내부 결과를 확정한다.

        while not published:
            assert time.monotonic() < deadline
            executor.spin_once(timeout_sec=0.05)

        assert published[0].result == 'PASS'
        results = inspection.results()
        assert results[point['point_id']]['result'] == 'PASS'
        recipes.apply_judgments(991, results)
        assert recipes.progress()['pending_judgments'] == 0

        # 조회한 복사본 수정으로 수신 결과를 훼손할 수 없다.
        results[point['point_id']]['result'] = 'FAIL'
        assert inspection.results()[point['point_id']]['result'] == 'PASS'

    finally:
        if node is not None:
            node.close()

        if judge is not None:
            judge.close()

        if executor is not None:
            executor.shutdown()

        for item in (hmi, node, judge):
            if item is not None:
                item.destroy_node()

        rclpy.try_shutdown()



@pytest.mark.parametrize('control_mode', ['hmi', 'terminal'])
def test_hmi_gateway_routes_requests_and_preserves_wire_contract(tmp_path, control_mode):
    """실제 ROS 통신을 사용하되 Worker 시작만 대체해 실물 명령은 발생시키지 않는다."""
    from types import SimpleNamespace as NS
    from unittest.mock import Mock
    import rclpy
    from rclpy.node import Node
    from rclpy.executors import SingleThreadedExecutor
    from rclpy.qos import QoSProfile, DurabilityPolicy, ReliabilityPolicy
    from std_msgs.msg import String, Empty
    from cable_interfaces.srv import StartInspection
    from cable_inspection.recipe.node_recipe import RecipeNode
    from cable_inspection.sequence.main.node_main import MainSequenceNode
    from cable_inspection.sequence.inspection.node_inspection import InspectionJudgmentNode
    from cable_inspection.hmi.node_hmi import HmiNode
    from cable_inspection.sequence.main.data_models.system_state import SystemState

    rclpy.init(domain_id=232)
    nodes, executor = [], None
    main = judge = None

    try:
        package = Path(__file__).parents[1]
        recipes = RecipeNode(package/'config/system_recipe.json', [
            package/'cable_inspection/recipe/inspection/lan_inspection_recipe.json'])
        nodes.append(recipes)
        recipe = recipes.get(recipes.available_ids()[0])
        judge = InspectionJudgmentNode('gateway_test_judgment')
        nodes.append(judge)
        motion = NS(robot=status_devices()[0], gripper=status_devices()[1], latest_sample=None)
        main = MainSequenceNode(motion, tmp_path, recipes=recipes, judgment=judge)
        nodes.append(main)
        main.launch_operation = Mock()  # 실제 모션 Worker만 차단한다.
        hmi = HmiNode(main, judge, control_mode=control_mode, heartbeat_timeout_s=30.)
        nodes.append(hmi)
        client = Node('gateway_test_client')
        nodes.append(client)
        executor = SingleThreadedExecutor()

        for node in nodes:
            executor.add_node(node)



        def wait_until(predicate):
            deadline = time.monotonic()+5

            while not predicate():
                assert time.monotonic() < deadline
                executor.spin_once(timeout_sec=.02)



        heart = client.create_publisher(Empty, f'cable_inspection/{control_mode}_heartbeat', 10)
        command_topic = 'command' if control_mode == 'hmi' else 'terminal_command'
        commands = client.create_publisher(String, 'cable_inspection/'+command_topic, 10)
        snapshots, robot_status, work_status = [], [], []
        qos = QoSProfile(depth=10, reliability=ReliabilityPolicy.RELIABLE,
                         durability=DurabilityPolicy.TRANSIENT_LOCAL)
        client.create_subscription(String, 'cable_inspection/execution_snapshot',
                                   lambda msg:snapshots.append(json.loads(msg.data)), qos)
        client.create_subscription(String, 'cable_inspection/robot_status',
                                   lambda msg:robot_status.append(json.loads(msg.data)), 10)
        client.create_subscription(String, 'cable_inspection/work_status',
                                   lambda msg:work_status.append(json.loads(msg.data)), qos)
        wait_until(lambda:heart.get_subscription_count() == 1 and commands.get_subscription_count() == 1)
        heart.publish(Empty())
        wait_until(hmi.is_connected)
        assert main.controller.hmi_available()
        wait_until(lambda:bool(robot_status))
        raw = robot_status[-1]
        assert raw['robot_connected'] is False and raw['task'] is None
        assert raw['validity']['task'] is False
        assert raw['errors']['task'] == '수신 없음'
        assert set(raw) == {'schema_version','stamp','robot_connected','gripper_connected',
            'task','joint','wrench_base','force_norm_n','gripper_width_mm','robot_state_code',
            'motion_status','robot_motion','servo','servo_source','tool','validity','age_s','errors'}
        assert client.count_publishers('cable_inspection/internal/robot_status') == 0

        if control_mode == 'hmi':
            service = client.create_client(StartInspection, 'cable_inspection/start')
            wait_until(service.service_is_ready)
            request = StartInspection.Request(request_id='gateway-1', recipe=RecipeNode.encode_message(recipe))
            first = service.call_async(request)
            wait_until(first.done)
            accepted = first.result()
            assert accepted.accepted and accepted.code == 'ACCEPTED'
            wait_until(lambda:bool(snapshots))
            assert snapshots[0]['request_id'] == request.request_id
            assert snapshots[0]['run_id'] == accepted.run_id
            second = service.call_async(request)
            wait_until(second.done)
            assert second.result().code == 'ALREADY_ACCEPTED'
            main.launch_operation.assert_called_once()
            assert len(snapshots) == 1

            # HMI command 토픽의 START는 전체 Recipe 서비스 우회로 쓰이지 않는다.
            commands.publish(String(data='{"name":"START"}'))

        else:
            commands.publish(String(data=json.dumps({'name':'START','args':{'recipe_id':recipe['recipe_id']}})))
            wait_until(lambda:main.launch_operation.call_count == 1)

        commands.publish(String(data='{"name":"STOP"}'))
        wait_until(lambda:main.controller.state == SystemState.STOPPED)
        main.launch_operation.assert_called_once()
        wait_until(lambda:any(s['run_state']=='STOPPED' for s in work_status))

        # Heartbeat 유실·복구 통지는 HMI가, Safe Pause 정책은 Main이 처리한다.
        main.controller.state = SystemState.RUNNING
        hmi.last_heartbeat = time.monotonic()-31.
        wait_until(lambda:main.controller.pause_requested.is_set())
        assert main.controller.comm_lost_at is not None
        heart.publish(Empty())
        wait_until(lambda:main.controller.comm_lost_at is None)
        assert main.controller.pause_requested.is_set()  # 복구만으로 재개하지 않는다.

    finally:
        if main is not None:
            main.close()

        if judge is not None:
            judge.close()

        if executor is not None:
            executor.shutdown()

        for node in reversed(nodes):
            node.destroy_node()

        rclpy.try_shutdown()



def status_devices():
    """ROS 장비 없이 HMI 계약 시험에 미수신 상태 API를 제공한다."""
    from types import SimpleNamespace as NS
    from cable_inspection.robot.node_robot import RobotNode
    from cable_inspection.gripper_tool.node_gripper_tool import GripperToolNode
    robot = NS(status_channels=dict.fromkeys(['task','joint','wrench_base','robot_state_code',
        'motion_status','tcp_name','tool_name']), status_cache={}, status_stale_s=2.)
    gripper = NS(width_received_at=None, measured_width_mm=None, width_error='', status_stale_s=2.)
    robot.status_snapshot = lambda now: RobotNode.status_snapshot(robot, now)
    gripper.status_snapshot = lambda now: GripperToolNode.status_snapshot(gripper, now)

    return robot, gripper



def test_monitoring_and_shutdown_stop_continue_while_motion_response_is_pending(tmp_path):
    """명령 응답 지연 중에도 실제 장비 노드의 상태 갱신·HMI 발행·종료 STOP이 진행된다."""
    import io
    import threading
    import rclpy
    from rclpy.node import Node
    from rclpy.executors import SingleThreadedExecutor, MultiThreadedExecutor
    from rclpy.callback_groups import ReentrantCallbackGroup
    from dsr_msgs2.srv import (GetRobotSystem, GetRobotState, GetCurrentPosj, GetCurrentPosx,
                              GetToolForce, CheckMotion, GetCurrentTcp, GetCurrentTool, MoveJoint, MoveStop)
    from std_msgs.msg import String, Float64MultiArray
    from sensor_msgs.msg import JointState
    from cable_inspection.robot.node_robot import RobotNode
    from cable_inspection.gripper_tool.node_gripper_tool import GripperToolNode
    from cable_inspection.sequence.common.motion import SequenceMotion
    from cable_inspection.sequence.main.node_main import MainSequenceNode
    from cable_inspection.sequence.inspection.node_inspection import InspectionJudgmentNode
    from cable_inspection.hmi.node_hmi import HmiNode
    from cable_inspection.recipe.recipe import Recipe
    from cable_inspection.sequence.common.data_models.sequence_result import SequenceResult

    rclpy.init(domain_id=232)
    entered, release, stopped, servers_done = (threading.Event() for _ in range(4))
    nodes = []
    executor = server_executor = thread = main = judge = None
    response_pending_status = []

    try:
        server = Node('monitor_migration_mock')
        nodes.append(server)
        group = ReentrantCallbackGroup()
        counts = {'state':0}
        root = '/dsr01/dsr_controller2'



        def service(request, response):
            response.success = True

            if hasattr(response, 'robot_system'):
                response.robot_system = 0

            if hasattr(response, 'robot_state'):
                response.robot_state = 1
                counts['state'] += 1

            if hasattr(response, 'pos'):
                response.pos = [0.] * 6

            if hasattr(response, 'task_pos_info'):
                response.task_pos_info = [Float64MultiArray(data=[0.] * 6)]

            if hasattr(response, 'tool_force'):
                response.tool_force = [0.] * 6

            if hasattr(response, 'status'):
                response.status = 0

            if hasattr(response, 'info'):
                response.info = 'test'

            return response



        for srv, path in (
            (GetRobotSystem, '/system/get_robot_system'), (GetRobotState, '/system/get_robot_state'),
            (GetCurrentPosj, '/aux_control/get_current_posj'), (GetCurrentPosx, '/aux_control/get_current_posx'),
            (GetToolForce, '/aux_control/get_tool_force'), (CheckMotion, '/motion/check_motion'),
            (GetCurrentTcp, '/tcp/get_current_tcp'), (GetCurrentTool, '/tool/get_current_tool'),
        ):
            server.create_service(srv, root+path, service, callback_group=group)



        def move(request, response):
            entered.set()
            release.wait(timeout=10.)
            response.success = True

            return response



        def stop(request, response):
            stopped.set()
            response.success = True

            return response



        server.create_service(MoveJoint, root+'/motion/move_joint', move, callback_group=group)
        server.create_service(MoveStop, root+'/motion/move_stop', stop, callback_group=group)
        feedback = server.create_publisher(JointState, '/onrobot_joint_states', 10)
        server.create_timer(.02, lambda:feedback.publish(JointState(position=[0.], effort=[1.])), callback_group=group)
        server_executor = MultiThreadedExecutor(num_threads=4)
        server_executor.add_node(server)



        def serve():
            while not servers_done.is_set():
                server_executor.spin_once(timeout_sec=.02)



        thread = threading.Thread(target=serve)
        thread.start()
        robot, gripper = RobotNode('real'), GripperToolNode('real')
        nodes.extend([robot, gripper])
        motion = SequenceMotion(robot, gripper, io.StringIO())
        judge = InspectionJudgmentNode('monitor_test_judgment')
        nodes.append(judge)
        main = MainSequenceNode(motion, tmp_path, recipes=Recipe(), judgment=judge)
        nodes.append(main)
        hmi = HmiNode(main, judge, control_mode='terminal')
        nodes.append(hmi)
        hmi.create_subscription(String, 'cable_inspection/robot_status',
            lambda msg: response_pending_status.append(json.loads(msg.data)), 10)
        executor = SingleThreadedExecutor()

        for node in nodes[1:]:
            executor.add_node(node)



        def wait_until(predicate, seconds=5.):
            deadline = time.monotonic()+seconds

            while not predicate():
                assert time.monotonic() < deadline, 'executor progress timed out'
                executor.spin_once(timeout_sec=.01)



        wait_until(lambda: response_pending_status and response_pending_status[-1]['robot_connected']
                   and response_pending_status[-1]['gripper_connected'])
        assert response_pending_status[-1]['task'] == [0.] * 6
        assert response_pending_status[-1]['wrench_base'] == [0.] * 6
        assert robot.movej_client.wait_for_service(timeout_sec=3.)



        def action():
            robot.move_joint([0.]*6, 10., 10.)
            return SequenceResult(True, 'DONE', 'DONE')



        main.launch_operation(action)
        wait_until(entered.is_set)
        before_count, before_messages = counts['state'], len(response_pending_status)
        wait_until(lambda: counts['state'] >= before_count+2 and len(response_pending_status) >= before_messages+3)
        assert main.is_running() and not release.is_set()
        assert all(msg['robot_connected'] and msg['gripper_connected']
                   for msg in response_pending_status[before_messages:])
        started = time.monotonic()
        main.close(executor)  # worker의 대기 중 STOP 감시와 실제 정지 서비스 응답을 처리한다.
        assert time.monotonic()-started < 3.
        assert stopped.is_set() and not main.is_running() and not release.is_set()

        # STOP 후에도 동일 장비 캐시와 HMI 타이머는 계속 갱신된다.
        before_count = counts['state']
        wait_until(lambda: counts['state'] > before_count)
        assert robot.status_snapshot()['robot_state_code']['valid']

    finally:
        release.set()

        if main is not None:
            main.close(executor)

        if judge is not None:
            judge.close()

        if executor is not None:
            executor.shutdown()

        servers_done.set()

        if thread is not None:
            thread.join(timeout=3.)

        if server_executor is not None:
            server_executor.shutdown()

        for node in reversed(nodes):
            node.destroy_node()

        rclpy.try_shutdown()
