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
    from cable_inspection.recipe.inspection_recipe import OperatingInspectionRecipe, to_message

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
                if predicate(): return
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
        wait_until(lambda: {"ccc_sequence_node", "ccc_robot_state", "inspection_judgment_node"}.issubset(
            {name for name, namespace in node.get_node_names_and_namespaces()}))
        # 설치 결과에도 HMI 관리용 노드/launch가 남아 있으면 안 된다.
        share = Path(get_package_share_directory("cable_inspection"))
        assert not (share / "launch/management.launch.py").exists()
        assert importlib.util.find_spec("cable_inspection.result_node") is None
        assert importlib.util.find_spec("cable_inspection.recipe_node") is None
        executables = {e.name for e in distribution("cable_inspection").entry_points
                       if e.group == "console_scripts"}
        assert executables == {"main_sequence", "inspection_judgment", "robot_state_node",
                               "sequence_console", "inspection_sequence", "manual_check"}
        services = {name for name, types in node.get_service_names_and_types()}
        assert not any(name.startswith("/cable_inspection/recipes/")
                       or name == "/cable_inspection/results/query" for name in services)
        recipe = to_message(OperatingInspectionRecipe.load_json(
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
