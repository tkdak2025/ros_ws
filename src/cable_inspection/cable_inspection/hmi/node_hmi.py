"""검사파트의 HMI ROS 통신을 한 노드에서 생성한다.
HMI·터미널 요청과 Heartbeat를 수신하고 상태·결과·로그를 발행한다.
실행 정책은 Main, 레시피 처리는 Recipe, 판정은 Inspection에 맡긴다.
"""

import weakref
from rclpy.node import Node
from rclpy.qos import QoSProfile, DurabilityPolicy, ReliabilityPolicy
from std_msgs.msg import Empty, String
from cable_interfaces.msg import InspectionResult
from cable_interfaces.srv import StartInspection
from cable_inspection.hmi.interface import HmiInterface



class HmiNode(Node, HmiInterface):
    """외부 통신을 소유하며 장비 연결이나 모션 Worker를 만들지 않는다."""



    # 기능: HMI 서비스·토픽을 생성하고 Main·판정 담당의 출력 콜백을 연결한다.
    #     main: Main 실행 노드. None이면 판정 단독 실행의 통신만 구성한다.
    #     judgment: 요청 Queue와 확정 결과를 소유하는 판정 노드.
    #     control_mode: hmi 또는 terminal. 수신 명령·Heartbeat 경로를 선택한다.
    #     heartbeat_timeout_s: Heartbeat 유효시간(s).
    #     반환: 없음. 외부 모션 실행이나 장비 초기화를 시작하지 않는다.
    def __init__(self, main, judgment, control_mode="hmi", heartbeat_timeout_s=2.0):
        super().__init__("ccc_hmi_node")

        if control_mode not in {"hmi", "terminal"}:
            raise ValueError(f"지원하지 않는 운전 모드: {control_mode}")

        # 담당 객체 참조와 통신 유효시간을 설정한다.
        self.main = weakref.proxy(main) if main is not None else None
        self.judgment = weakref.proxy(judgment)
        self.control_mode = control_mode
        self.heartbeat_timeout_s = heartbeat_timeout_s
        self.last_heartbeat = None
        self.communication_lost_handled = False

        # 중복 요청·Snapshot·상태 발행 이력을 초기화한다.
        self._request_id = ""
        self._start_requests = {}
        self._published_snapshots = set()
        self._last_status = None

        # 판정 단독 디버그와 전체 검사에서 공통으로 사용하는 통신이다.
        self.result_pub = self.create_publisher(InspectionResult, "cable_inspection/judgment_result", 50)
        self.log_pub = self.create_publisher(String, "cable_inspection/log", 50)
        self.create_subscription(String, "cable_inspection/judgment_request", self.receive_judgment_request, 50)
        node_ref = weakref.ref(self)



        # 기능: 살아 있는 HMI 노드에만 판정 결과를 전달한다.
        #     message: 확정된 InspectionResult 메시지.
        #     반환: 없음.
        def publish_result(message):
            node = node_ref()

            if node is not None:
                node.result_pub.publish(message)



        # 기능: 살아 있는 HMI 노드에만 로그를 전달한다.
        #     level: 로그 수준.
        #     text: 로그 본문.
        #     반환: 없음.
        def publish_log(level, text):
            node = node_ref()

            if node is not None:
                node.publish_log(level, text)



        judgment.publish_result = publish_result
        judgment.publish_log = publish_log

        # 판정 단독 실행도 외부 결과·로그 통신은 이 노드가 담당한다.
        if main is None:
            return

        self.status_pub = self.create_publisher(String, "cable_inspection/work_status",
            QoSProfile(depth=1, reliability=ReliabilityPolicy.RELIABLE,
                       durability=DurabilityPolicy.TRANSIENT_LOCAL))
        self.snapshot_pub = self.create_publisher(String, "cable_inspection/execution_snapshot",
            QoSProfile(depth=10, reliability=ReliabilityPolicy.RELIABLE,
                       durability=DurabilityPolicy.TRANSIENT_LOCAL))
        self.robot_status_pub = self.create_publisher(String, "cable_inspection/robot_status", 10)
        self.create_timer(0.1, self.publish_robot_status)
        self.create_service(StartInspection, "cable_inspection/start", self.receive_inspection_start)
        command_topic = "command" if control_mode == "hmi" else "terminal_command"
        self.create_subscription(String, f"cable_inspection/{command_topic}", self.receive_command, 50)
        self.create_subscription(Empty, f"cable_inspection/{control_mode}_heartbeat", self.receive_heartbeat, 10)
        self.create_timer(0.1, self.update_communication)



        # 기능: 살아 있는 HMI 노드에 실행 레시피를 전달한다.
        #     run_id: 실행 식별자.
        #     recipe: 이번 실행에 고정된 레시피.
        #     반환: 없음.
        def publish_snapshot(run_id, recipe):
            node = node_ref()

            if node is not None:
                node.publish_execution_snapshot(run_id, recipe)



        # 기능: HMI 노드 수명과 현재 통신 유효성을 조회한다.
        #     반환: 노드가 살아 있고 Heartbeat가 유효하면 True.
        def control_available():
            node = node_ref()

            return node is not None and node.is_connected()



        main.controller.notify = publish_log
        main.controller.snapshot_notify = publish_snapshot
        main.controller.hmi_available = control_available
