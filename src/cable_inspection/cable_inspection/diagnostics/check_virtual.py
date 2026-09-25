"""이미 실행 중인 M0609/RG2 가상 bringup으로 검사 Job을 재현한다."""

import json
import os
from pathlib import Path
import signal
import subprocess
import time


class VirtualInspectionCheck:
    """가상 장비 확인, 검사 launch, START, 완료 기록을 한 번의 검증으로 관리한다."""

    # 기능: 가상 검사 실행에 필요한 기록 위치와 제한시간을 준비한다.
    #     output: 검증 결과를 저장할 폴더. timeout_s: Job 완료 제한시간.
    #     반환: 없음.
    def __init__(self, output: Path, timeout_s: float = 600.0):
        self.output = output
        self.timeout_s = timeout_s
        self.status = {}
        self.logs = []
        self.launch_process = None
        self.heartbeat = None
        self.commands = None
        self.node = None

    # 기능: 현재 ROS 도메인에 가상 로봇과 가상 RG2만 연결됐는지 확인한다.
    #     인자: 없음.
    #     반환: 없음. 제공자가 없거나 실물 모드면 RuntimeError.
    def verify_virtual_devices(self):
        import rclpy
        from dsr_msgs2.srv import GetRobotSystem

        deadline = time.monotonic() + 5.0
        names = set()

        while time.monotonic() < deadline:
            names = set(self.node.get_node_names_and_namespaces())

            if ('gripper_virtual_node', '/dsr01') in names:
                break

            rclpy.spin_once(self.node, timeout_sec=0.1)

        if ('ccc_sequence_node', '/') in names:
            raise RuntimeError('이미 검사 Main 노드가 실행 중입니다. 중복 실행을 중단합니다.')

        if ('gripper_virtual_node', '/dsr01') not in names:
            raise RuntimeError('가상 RG2가 없습니다. 먼저 m0609_rg2_bringup을 mode:=virtual로 실행하세요.')

        providers = []
        deadline = time.monotonic() + 5.0

        while time.monotonic() < deadline:
            names = set(self.node.get_node_names_and_namespaces())
            providers = []

            for name, namespace in names:
                services = self.node.get_service_names_and_types_by_node(name, namespace)

                if any(service == '/onrobot/sendCommand' for service, _ in services):
                    providers.append(f"{namespace.rstrip('/')}/{name}")

            if providers:
                break

            rclpy.spin_once(self.node, timeout_sec=0.1)

        if providers != ['/dsr01/gripper_virtual_node']:
            raise RuntimeError(f'가상 RG2 외 서비스 제공자가 있습니다: {providers}')

        service = self.node.create_client(GetRobotSystem,
            '/dsr01/dsr_controller2/system/get_robot_system')

        try:
            if not service.wait_for_service(timeout_sec=3.0):
                raise RuntimeError('가상 M0609 서비스가 없습니다. virtual bringup을 확인하세요.')

            future = service.call_async(GetRobotSystem.Request())
            rclpy.spin_until_future_complete(self.node, future, timeout_sec=5.0)

            if not future.done() or future.result() is None:
                raise RuntimeError('가상 M0609 모드 조회에 실패했습니다.')

            if future.result().robot_system != 1:
                raise RuntimeError('M0609가 virtual 모드가 아닙니다. 검사 명령을 보내지 않습니다.')

        finally:
            self.node.destroy_client(service)

    # 기능: Heartbeat와 상태 요청을 보내며 검사 상태·프로세스 종료를 기다린다.
    #     predicate: 종료 조건. timeout_s: 이 단계의 제한시간.
    #     반환: 조건을 만족한 최신 상태. 오류·시간 초과 시 RuntimeError.
    def wait_for_status(self, predicate, timeout_s):
        import rclpy
        from std_msgs.msg import Empty, String

        deadline = time.monotonic() + timeout_s
        next_heartbeat = 0.0
        next_sync = 0.0

        while time.monotonic() < deadline:
            if self.launch_process.poll() is not None:
                raise RuntimeError('검사 launch가 종료되었습니다. virtual_launch.log를 확인하세요.')

            now = time.monotonic()

            if now >= next_heartbeat:
                self.heartbeat.publish(Empty())
                next_heartbeat = now + 0.5

            if now >= next_sync:
                self.commands.publish(String(data=json.dumps({'name': 'SYNC', 'args': {}})))
                next_sync = now + 1.0

            rclpy.spin_once(self.node, timeout_sec=0.1)

            if self.status.get('run_state') == 'ERROR':
                raise RuntimeError(f"검사 Job 오류: {self.status.get('alarm', '')}")

            if predicate(self.status):
                return self.status

        raise RuntimeError(f'가상 검사 응답 제한시간 {timeout_s:g}초 초과: {self.status}')

    # 기능: 검사 프로세스에 STOP을 전송한 뒤 이 검증이 띄운 launch만 종료한다.
    #     인자: 없음.
    #     반환: 없음.
    def close_launch(self):
        if self.launch_process is None or self.launch_process.poll() is not None:
            return

        if self.commands is not None and self.status.get('work_active'):
            from std_msgs.msg import String
            import rclpy

            self.commands.publish(String(data=json.dumps({'name': 'STOP', 'args': {}})))
            deadline = time.monotonic() + 5.0

            while time.monotonic() < deadline and self.status.get('work_active'):
                rclpy.spin_once(self.node, timeout_sec=0.1)

        os.killpg(self.launch_process.pid, signal.SIGINT)

        try:
            self.launch_process.wait(timeout=35)

        except subprocess.TimeoutExpired:
            os.killpg(self.launch_process.pid, signal.SIGTERM)
            self.launch_process.wait(timeout=10)

    # 기능: 실행 중인 가상 bringup에 검사 launch를 연결해 한 Job의 완료와 기록을 확인한다.
    #     인자: 없음.
    #     반환: 완료 상태·포인트 집계·결과 폴더. 실물 적합성 판정은 포함하지 않는다.
    def run(self):
        import rclpy
        from rclpy.node import Node
        from rclpy.qos import DurabilityPolicy, QoSProfile, ReliabilityPolicy
        from std_msgs.msg import Empty, String

        previous_discovery = os.environ.get('ROS_AUTOMATIC_DISCOVERY_RANGE')
        os.environ['ROS_AUTOMATIC_DISCOVERY_RANGE'] = 'LOCALHOST'
        rclpy.init()

        try:
            self.node = Node('inspection_virtual_check')
            self.verify_virtual_devices()

            raw_dir = self.output / 'virtual_run'
            launch_log = self.output / 'virtual_launch.log'
            environment = os.environ.copy()

            with launch_log.open('w') as stream:
                self.launch_process = subprocess.Popen([
                    'ros2', 'launch', 'cable_inspection', 'inspection.launch.py',
                    'robot_mode:=virtual', 'control_mode:=terminal', f'results_dir:={raw_dir}',
                ], cwd=self.output, env=environment, stdout=stream,
                   stderr=subprocess.STDOUT, start_new_session=True)

                self.heartbeat = self.node.create_publisher(
                    Empty, 'cable_inspection/terminal_heartbeat', 10)
                self.commands = self.node.create_publisher(
                    String, 'cable_inspection/terminal_command', 10)
                qos = QoSProfile(depth=1, reliability=ReliabilityPolicy.RELIABLE,
                                 durability=DurabilityPolicy.TRANSIENT_LOCAL)
                self.node.create_subscription(String, 'cable_inspection/work_status',
                    lambda message: self.status.update(json.loads(message.data)), qos)
                self.node.create_subscription(String, 'cable_inspection/log',
                    lambda message: self.logs.append(json.loads(message.data)), 50)

                self.wait_for_status(lambda state: state.get('run_state') == 'SYSTEM_READY'
                    and state.get('control_mode') == 'terminal'
                    and state.get('control_connected')
                    and self.commands.get_subscription_count() == 1, 45)

                self.commands.publish(String(data=json.dumps({'name': 'START', 'args': {}})))
                self.wait_for_status(lambda state: bool(state.get('run_id'))
                    and (state.get('work_active') or state.get('job_summary')), 30)
                status = self.wait_for_status(lambda state: state.get('run_state') == 'SYSTEM_READY'
                    and bool(state.get('job_summary')) and not state.get('work_active'),
                    self.timeout_s)

                runs = sorted(raw_dir.glob('*/status.json'))

                if len(runs) != 1:
                    raise RuntimeError(f'가상 실행 상태 파일 수가 {len(runs)}개입니다. 1개여야 합니다.')

                saved = json.loads(runs[0].read_text())
                summary_file = runs[0].with_name('job_summary.json')
                summary = json.loads(summary_file.read_text())

                if not saved.get('completed') or summary.get('job_status') != 'INSPECTION_COMPLETE':
                    raise RuntimeError(f'가상 Job 완료 기록이 아닙니다: {saved}, {summary}')

                result = {'run_id': status['run_id'], 'recipe_id': summary['recipe_id'],
                          'point_total': summary['point_total'], 'counts': summary['counts'],
                          'result_dir': str(runs[0].parent)}
                (self.output / 'virtual_result.json').write_text(
                    json.dumps(result, ensure_ascii=False, indent=2) + '\n')
                return result

        finally:
            try:
                self.close_launch()

            finally:
                if self.node is not None:
                    self.node.destroy_node()

                rclpy.try_shutdown()

                if previous_discovery is None:
                    os.environ.pop('ROS_AUTOMATIC_DISCOVERY_RANGE', None)

                else:
                    os.environ['ROS_AUTOMATIC_DISCOVERY_RANGE'] = previous_discovery
