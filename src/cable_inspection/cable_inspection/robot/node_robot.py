"""M0609 component를 상속해 시퀀스에서 사용할 로봇 API를 제공한다."""

import os
import math
import time
from copy import deepcopy
from rclpy.node import Node
from cable_inspection.robot.m0609 import M0609Robot



class RobotNode(Node, M0609Robot):
    """연결은 생성 시 한 번 구성한다. 이동 API는 요청하며 완료 판단은 Sequence가 한다."""



    # 기능: 로봇 ROS 노드와 M0609 연결을 한 번 생성한다.
    #     mode: real 또는 virtual.
    #     반환: 없음. 생성 실패 시 노드를 해제하고 예외를 전달한다.
    def __init__(self, mode="real"):
        Node.__init__(self, "ccc_robot_node")

        try:
            M0609Robot.__init__(self, mode)
            self.initialized = False
            self.status_cache = {}
            self.status_timeout_s = 1.0
            self.status_stale_s = 2.0
            self.create_timer(0.1, self.poll_status)

        except Exception:
            self.destroy_node()
            raise



    # 기능: 요청 모드와 연결된 로봇 시스템의 일치 여부를 확인한다.
    #     인자: 없음.
    #     반환: 없음. 모드 불일치 시 예외.
    def verify_mode(self):
        self._check_robot_mode()



    # 기능: 서비스·STANDBY·모션 정지 상태를 확인한다. Safety Stop은 해제하지 않는다.
    #     인자: 없음.
    #     반환: 없음. 준비되지 않았으면 예외.
    def check_ready(self):
        state = self.robot_state()

        if state != 1:
            raise RuntimeError(f"Robot이 STANDBY가 아닙니다: state={state}")

        if not self.system_client.wait_for_service(timeout_sec=self.SERVICE_TIMEOUT_S):
            raise RuntimeError(
                f"로봇 시스템 조회 서비스를 찾지 못했습니다: {self.system_client.srv_name}. "
                f"ROS_DOMAIN_ID={os.environ.get('ROS_DOMAIN_ID', '0')}, "
                f"RMW_IMPLEMENTATION={os.environ.get('RMW_IMPLEMENTATION', '(기본값)')}. "
                f"{self.mode} bringup과 /dsr01 네임스페이스 및 DDS 설정을 확인하세요."
            )

        self._wait_for_services()

        if self.motion_status() != 0:
            raise RuntimeError("로봇이 이미 움직이고 있습니다.")



    # 기능: 최초 준비 성공 시에만 로봇 설정을 적용한다.
    #     config: 활성 Tool/TCP 이름을 포함한 운전 설정.
    #     반환: 없음. 성공 시 initialized=True.
    def initialize(self, config):
        if not self.initialized:
            if self.mode == "virtual":
                self._apply_virtual_settings()

            self.verify_active_tool_tcp(config)
            self.verify_mode()
            self.initialized = True



    # 기능: 시작·재개·Home 전에 운전 상태·모드·Tool/TCP·관절값을 검사한다.
    #     config: 활성 Tool/TCP 이름을 포함한 운전 설정.
    #     반환: 없음. 운전 불가 시 예외.
    def check_operability(self, config):
        state = self.robot_state()

        if state != 1:
            raise RuntimeError(f"Robot이 STANDBY가 아닙니다: state={state}")

        self.verify_mode()
        self.verify_active_tool_tcp(config)
        joints = self.read_joints()

        if len(joints) != 6 or not all(math.isfinite(v) for v in joints):
            raise RuntimeError("현재 관절값이 유효하지 않습니다.")



    # 기능: 제어기의 활성 Tool/TCP를 운전 설정과 대조한다.
    #     config: 요구하는 Tool/TCP 이름을 포함한 운전 설정.
    #     반환: 없음. 불일치 시 예외.
    def verify_active_tool_tcp(self, config):
        self._verify_active_tool_tcp(config)



    # 기능: 비동기 MoveJ를 요청한다. 도달 판정은 시퀀스가 담당한다.
    #     joints: 목표 관절각 6개(deg).
    #     speed_deg_s: 관절 속도(deg/s).
    #     acceleration_deg_s2: 관절 가속도(deg/s²).
    #     반환: 없음. 요청 실패 시 예외.
    def move_joint(self, joints, speed_deg_s, acceleration_deg_s2):
        self.move_joint_raw(joints, speed_deg_s, acceleration_deg_s2)



    # 기능: 비동기 MoveL을 요청한다. 도달 판정은 시퀀스가 담당한다.
    #     target: BASE 기준 XYZABC(mm, deg).
    #     speed_mm_s: 이동 속도(mm/s).
    #     acceleration_mm_s2: 이동 가속도(mm/s²).
    #     반환: 없음. 요청 실패 시 예외.
    def move_linear(self, target, speed_mm_s, acceleration_mm_s2):
        self.move_linear_raw(target, speed_mm_s, acceleration_mm_s2)



    # 기능: 지정된 정지 모드로 로봇 정지를 요청한다.
    #     stop_mode: 드라이버 MoveStop의 정지 모드 값.
    #     반환: 없음. 요청 실패 시 예외.
    def stop_motion(self, stop_mode):
        self.stop_motion_raw(stop_mode)



    # 기능: 제어기 모션 상태를 조회한다.
    #     인자: 없음.
    #     반환: 드라이버 상태 정수. 0이면 모션 정지.
    def motion_status(self):
        return self._motion_status_raw()



    # 기능: 상태 서비스 준비를 확인하고 로봇 운전 상태를 조회한다.
    #     인자: 없음.
    #     반환: 드라이버 로봇 상태 정수. 1이면 STANDBY.
    def robot_state(self):
        if not self.state_client.wait_for_service(timeout_sec=self.SERVICE_TIMEOUT_S):
            raise RuntimeError("Robot State 서비스를 찾을 수 없습니다.")

        return self._robot_state_raw()



    # 기능: 현재 로봇 관절각을 조회한다.
    #     인자: 없음.
    #     반환: 관절각 6개 목록(deg).
    def read_joints(self):
        return self._read_joints_raw()



    # 기능: 현재 TCP 자세를 조회한다.
    #     인자: 없음.
    #     반환: BASE 기준 XYZABC 목록(mm, deg).
    def get_tcp(self):
        return self._get_tcp_raw()



    # 기능: 지정 좌표계 기준 힘과 모멘트를 조회한다.
    #     reference: 드라이버 기준 좌표계 값. 기본값 0(BASE).
    #     반환: [Fx, Fy, Fz, Mx, My, Mz] 목록(N, Nm).
    def get_tool_wrench(self, reference=0):
        return self._get_tool_wrench_raw(reference)



    # 기능: 정지를 시도하고 통신 실패는 로그로 남긴다.
    #     인자: 없음.
    #     반환: 없음. 정지 서비스 예외는 내부에서 처리한다.
    def safe_abort(self):
        self._safe_abort_raw()



    # 기능: 로봇 상태를 비동기로 조회한다. STOP 감시와 명령 대기를 호출하지 않는다.
    #     now: monotonic 시각(s). 생략하면 현재 시각. 테스트에서 고정 시각을 주입한다.
    #     반환: 없음. 채널별 미완료 요청은 최대 한 건이며 결과·오류를 캐시에 기록한다.
    def poll_status(self, now=None):
        now = time.monotonic() if now is None else now

        for key, channel in self.status_channels.items():
            future, client = channel["future"], channel["client"]

            if future is not None:
                if future.done():
                    try:
                        response = future.result()

                        if response is None or not response.success:
                            raise ValueError("조회 실패")

                        self.store_status(key, channel["decode"](response))

                    except Exception as error:
                        self.store_status(key, error=str(error))

                    channel["future"] = None

                elif now - channel["started"] >= self.status_timeout_s:
                    client.remove_pending_request(future)
                    future.cancel()
                    self.store_status(key, error="조회 시간 초과")
                    channel["future"] = None

            if channel["future"] is None and now >= channel["next"]:
                channel["next"] = now + channel["period"]

                if client.service_is_ready():
                    try:
                        channel["future"] = client.call_async(channel["request"])
                        channel["started"] = now

                    except Exception as error:
                        self.store_status(key, error=str(error))

                else:
                    self.store_status(key, error="서비스 없음")



    # 기능: 상태 조회 결과를 수신 시각과 함께 교체한다.
    #     key: 상태 채널 이름. value: 측정값. error: 실패 사유, 정상이면 빈 문자열.
    #     반환: 없음. 실패 시 이전 값을 정상값으로 재사용하지 않는다.
    def store_status(self, key, value=None, error=""):
        self.status_cache[key] = {"value": value, "time": time.monotonic(), "error": error}



    # 기능: 로봇 상태의 유효성·경과시간을 계산해 복사본을 제공한다.
    #     now: monotonic 시각(s). 생략하면 현재 시각.
    #     반환: 채널별 value·valid·age_s·error 사전. 미수신·오류·만료 값은 None.
    def status_snapshot(self, now=None):
        now = time.monotonic() if now is None else now
        result = {}

        for key in self.status_channels:
            entry = self.status_cache.get(key)
            age = max(0.0, now - entry["time"]) if entry else None
            valid = bool(entry and not entry["error"] and age <= self.status_stale_s)
            result[key] = {
                "value": deepcopy(entry["value"]) if valid else None,
                "valid": valid, "age_s": age,
                "error": "" if valid else (entry["error"] or "데이터 만료") if entry else "수신 없음",
            }

        return result
