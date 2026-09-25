"""교체 가능한 RG2 서비스·JointState 피드백과 그리퍼 명령."""

import math
import time

from onrobot_rg_msgs.srv import SetCommand
from sensor_msgs.msg import JointState



class RG2Gripper:
    """GripperToolNode가 상속하는 RG2 통신 component. Robot은 참조하지 않는다."""

    GRIPPER_SERVICE = "/onrobot/sendCommand"
    RG2_MAX_WIDTH_MM = 110.0
    RG2_MAX_FORCE_N = 40.0
    RG2_FORCE_STEP_N = 2.5
    SERVICE_TIMEOUT_S = 5.0



    def __init__(self, mode):
        if mode not in ("real", "virtual"):
            raise ValueError("mode는 real 또는 virtual이어야 합니다.")

        self.mode = mode
        self.events = []
        self.run_metadata = {"mode": mode}
        self.control_poll = lambda: None
        self._configure_rg2()



    # 기능: Worker에서 RG2 요청을 보내고 executor의 응답 처리를 기다린다.
    #     client: 서비스 클라이언트. request: RG2 명령 요청.
    #     timeout: 응답 제한(s). None이면 SERVICE_TIMEOUT_S.
    #     반환: 성공 응답. STOP·시간 초과·통신 오류는 예외. executor 콜백 안에서 호출하지 않는다.
    def _call(self, client, request, timeout=None):
        """RG2 요청·응답을 자체 ROS 노드에서 처리한다."""
        self.control_poll()
        limit = self.SERVICE_TIMEOUT_S if timeout is None else timeout
        future = client.call_async(request)
        deadline = time.monotonic() + limit

        while not future.done() and time.monotonic() < deadline:
            try:
                self.control_poll()

            except Exception:
                future.cancel()
                raise

            time.sleep(0.01)

        if not future.done():
            future.cancel()
            raise TimeoutError(f"서비스 응답 시간 초과: {client.srv_name}")

        error = future.exception()

        if error is not None:
            raise RuntimeError(f"서비스 호출 실패: {client.srv_name}: {error}") from error

        response = future.result()

        if response is None or not response.success:
            message = getattr(response, "message", "") if response else "응답 없음"
            raise RuntimeError(f"서비스 실패: {client.srv_name}: {message}")

        return response



    def _configure_rg2(self):
        self.gripper_client = self.create_client(
            SetCommand, self.GRIPPER_SERVICE)
        gripper_topic = (
            "/dsr01/gripper_joint_states" if self.mode == "virtual"
            else "/onrobot_joint_states")
        self.create_subscription(
            JointState, gripper_topic, self._gripper_state_callback, 10)

        # 명령 목표값과 실측 피드백을 분리해 보관한다.
        self.commanded_force_n = self.RG2_MAX_FORCE_N
        self.commanded_width_mm = self.RG2_MAX_WIDTH_MM
        self.measured_width_mm = None
        self.width_received_at = None
        self.width_error = ""
        self.gripper_busy = False



    def _verify_rg2_provider(self):
        providers = []

        for name, namespace in self.get_node_names_and_namespaces():
            services = self.get_service_names_and_types_by_node(name, namespace)

            if any(service == self.GRIPPER_SERVICE for service, _ in services):
                providers.append(f"{namespace.rstrip('/')}/{name}")

        expected = ("/dsr01/gripper_virtual_node" if self.mode == "virtual"
                    else "/dsr01/OnRobotRGControllerServer")

        if providers != [expected]:
            raise RuntimeError(f"{self.mode} 그리퍼 서비스 확인 실패: {providers}")

        self.run_metadata["gripper_service_providers"] = providers



    def _initialize_rg2_force(self):
        # 실물 드라이버의 초기 힘을 최대힘(40 N)으로 동기화한다.
        for _ in range(round(self.RG2_MAX_FORCE_N / self.RG2_FORCE_STEP_N)):
            self._send_gripper_command("i")

        self.commanded_force_n = self.RG2_MAX_FORCE_N



    # 기능: RG2 피드백을 폭으로 변환하고 수신 시각·오류를 기록한다.
    #     message: 관절각(rad)과 busy 참고값을 담은 JointState.
    #     반환: 없음. 잘못된 피드백은 이전 폭을 무효화하며 busy로 동작을 제한하지 않는다.
    def _gripper_state_callback(self, message: JointState) -> None:
        try:
            joint = float(message.position[0])

            if not math.isfinite(joint):
                raise ValueError("그리퍼 관절값이 유효하지 않습니다.")

            width = (math.cos(joint + 0.76794) * 0.055 - 0.0144
                     + 0.108505 * math.cos(1.41371)) * 2000.0
            self.measured_width_mm = max(0.0, width)
            self.width_error = ""
            self.gripper_busy = bool(message.effort and abs(message.effort[0]) > 0.0)

        except (ValueError, IndexError, TypeError) as error:
            self.measured_width_mm = None
            self.width_error = str(error)

        self.width_received_at = time.monotonic()



    # 기능: 호출 이후 수신된 폭 피드백을 Worker에서 기다린다.
    #     timeout_s: 새 피드백 대기 제한(s). 콜백은 외부 executor가 처리한다.
    #     반환: (폭(mm), monotonic 수신 시각(s)). STOP·시간 초과·잘못된 피드백은 예외.
    def _read_fresh_gripper_width(self, timeout_s):
        """executor가 새 피드백을 처리할 때까지 STOP을 감시하며 기다린다."""
        started = time.monotonic()

        while self.width_received_at is None or self.width_received_at < started:
            poll = getattr(self, "control_poll", None)

            if poll is not None:
                poll()

            time.sleep(0.01)

            if time.monotonic() - started > timeout_s:
                raise TimeoutError("새 그리퍼 폭 피드백이 없습니다.")

        if self.width_error:
            raise RuntimeError(f"그리퍼 피드백 오류: {self.width_error}")

        return self.measured_width_mm, self.width_received_at



    def _send_gripper_command(self, command: str) -> None:
        self.control_poll()
        self._verify_rg2_provider()
        request = SetCommand.Request()
        request.command = command
        self._call(self.gripper_client, request)



    # 기능: RG2 폭·힘을 검증하고 모드별 raw 명령으로 전송한다.
    #     width_mm: 목표 폭(mm).
    #     force_n: 목표 힘(N). 실물은 2.5 N 단위.
    #     opening: True이면 폭 명령을 힘 변경보다 먼저 전송한다.
    #     반환: 없음. 범위 오류·통신 실패 시 예외.
    def _set_gripper(self, width_mm: float, force_n: float, opening: bool = False) -> None:
        width = float(width_mm)
        force = float(force_n)

        if not 0.0 <= width <= self.RG2_MAX_WIDTH_MM:
            raise ValueError(f"RG2 width 범위 초과: {width} mm")

        if not 0.0 <= force <= self.RG2_MAX_FORCE_N:
            raise ValueError(f"RG2 force 범위 초과: {force} N")

        if self.mode == "virtual":
            self._set_virtual_gripper(width, force)
            return

        steps = round((force - self.commanded_force_n) / self.RG2_FORCE_STEP_N)
        quantized = self.commanded_force_n + steps * self.RG2_FORCE_STEP_N

        if not math.isclose(quantized, force, abs_tol=1e-6):
            raise ValueError("RG2 힘은 2.5 N 단위로 지정해야 합니다.")

        # RG2의 i/d 명령은 현재 폭 목표도 다시 전송한다. Open에서는 폭을
        # 먼저 보내 이전 Hard Grip의 Close 목표가 반복되지 않게 한다.
        if opening:
            self._send_gripper_command(str(round(width * 10.0)))
            self.commanded_width_mm = width

        for _ in range(abs(steps)):
            self._send_gripper_command("i" if steps > 0 else "d")
            self.commanded_force_n += self.RG2_FORCE_STEP_N if steps > 0 else -self.RG2_FORCE_STEP_N

        if not opening:
            # OnRobot service 숫자 명령은 0.1 mm 단위의 목표 폭이다.
            self._send_gripper_command(str(round(width * 10.0)))
            self.commanded_width_mm = width



    def _set_virtual_gripper(self, width: float, force: float) -> None:
        # 실물은 폭(0.1 mm), 가상 노드는 관절각(rad)을 받으므로 변환한다.
        cosine = (width / 2000.0 + 0.0144 - 0.108505 * math.cos(1.41371)) / 0.055
        angle = math.acos(max(-1.0, min(1.0, cosine))) - 0.76794
        angle = max(-0.558505, min(0.785398, angle))
        model_width = (math.cos(angle + 0.76794) * 0.055 - 0.0144
                       + 0.108505 * math.cos(1.41371)) * 2000.0
        self._send_gripper_command(str(angle))
        self.commanded_width_mm, self.commanded_force_n = width, force
        self.events.append({"action": "grip", "width_mm": width,
                            "commanded_force_n": force, "virtual_joint_rad": angle,
                            "model_width_mm": model_width,
                            "width_clamped": abs(model_width - width) > 0.1})
        print(f"가상 Grip: 요청 {width} mm / 모델 {model_width:.3f} mm "
              f"/ 힘 명령값 {force} N")



    def _wait_for_services(self) -> None:
        """RG2 서비스와 선택한 real/virtual 제공자를 확인한다."""

        if not self.gripper_client.wait_for_service(timeout_sec=self.SERVICE_TIMEOUT_S):
            raise RuntimeError(f"서비스를 찾지 못했습니다: {self.gripper_client.srv_name}")

        self._verify_rg2_provider()

