"""RG2 component를 상속해 시퀀스에서 사용할 그리퍼 API를 제공한다."""

import time
from rclpy.node import Node
from cable_inspection.gripper_tool.rg2 import RG2Gripper



class GripperToolNode(Node, RG2Gripper):
    """RG2 전용 연결·피드백을 소유하며 Robot 노드 없이 생성·사용할 수 있다."""



    # 기능: 독립 RG2 노드와 통신 연결을 한 번 생성한다.
    #     mode: real 또는 virtual.
    #     반환: 없음. 생성 실패 시 노드를 해제한다.
    def __init__(self, mode="real"):
        Node.__init__(self, "ccc_gripper_tool_node")

        try:
            RG2Gripper.__init__(self, mode)
            self.initialized = False
            self.status_stale_s = 2.0

        except Exception:
            self.destroy_node()
            raise



    # 기능: RG2 서비스와 real/virtual 제공자가 준비됐는지 확인한다.
    #     인자: 없음.
    #     반환: 없음. 준비되지 않았으면 예외.
    def check_ready(self):
        self._wait_for_services()



    # 기능: 최초 준비 성공 시 그리퍼 힘 명령의 기준값을 동기화한다.
    #     인자: 없음.
    #     반환: 없음. 성공 시 initialized=True.
    def initialize(self):
        if not self.initialized:
            if self.mode == "real":
                self._initialize_rg2_force()

            self.initialized = True



    # 기능: 폭·힘 명령을 전달한다. 파지·Open 완료 판단은 시퀀스가 담당한다.
    #     width_mm: 목표 폭(mm).
    #     force_n: 목표 힘(N).
    #     opening: True이면 이전 파지 힘 변경보다 Open 폭 명령을 먼저 전송한다.
    #     반환: 없음. 범위 오류 또는 통신 실패 시 예외.
    def set_grip(self, width_mm, force_n, opening=False):
        """폭·힘 명령만 적용한다. 파지·Open 완료 판단은 Sequence가 한다."""
        self._set_gripper(width_mm, force_n, opening=opening)



    # 기능: 호출 이후의 새 RG2 폭 피드백을 기다린다.
    #     timeout_s: 새 피드백 대기 제한(s).
    #     반환: (측정 폭(mm), monotonic 수신 시각(s)). 시간 초과 시 예외.
    def read_width(self, timeout_s):
        return self._read_fresh_gripper_width(timeout_s)



    # 기능: 그리퍼 폭 피드백의 유효성·경과시간을 제공한다. 별도 서비스 조회는 하지 않는다.
    #     now: monotonic 시각(s). 생략하면 현재 시각.
    #     반환: gripper_width_mm의 value·valid·age_s·error 사전. 오류·만료 값은 None.
    def status_snapshot(self, now=None):
        now = time.monotonic() if now is None else now
        age = max(0.0, now - self.width_received_at) if self.width_received_at is not None else None
        valid = bool(age is not None and not self.width_error and age <= self.status_stale_s)

        return {"gripper_width_mm": {
            "value": self.measured_width_mm if valid else None,
            "valid": valid, "age_s": age,
            "error": "" if valid else (self.width_error or "데이터 만료") if age is not None else "수신 없음",
        }}
