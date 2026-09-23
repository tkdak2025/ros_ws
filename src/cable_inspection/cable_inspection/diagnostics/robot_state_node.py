"""상시 읽기 전용 로봇 상태 수집. 시퀀스 장비 노드를 공유하거나 spin하지 않는다."""

import json
import math
import time
import rclpy
from datetime import datetime
from rclpy.node import Node
from sensor_msgs.msg import JointState
from std_msgs.msg import String
from dsr_msgs2.srv import (
    CheckMotion,
    GetCurrentPosj,
    GetCurrentPosx,
    GetToolForce,
    GetRobotState,
    GetCurrentTcp,
    GetCurrentTool,
)


STATE_NAMES = {
    0: "INITIALIZING", 1: "STANDBY", 2: "MOVING", 3: "SAFE_OFF",
    4: "TEACHING", 5: "SAFE_STOP", 6: "EMERGENCY_STOP", 7: "HOMMING",
    8: "RECOVERY", 9: "SAFE_STOP2", 10: "SAFE_OFF2", 15: "NOT_READY",
}


def vector(values):
    result = [float(value) for value in values]
    if len(result) != 6 or not all(math.isfinite(value) for value in result):
        raise ValueError("6개의 유효한 측정값이 필요합니다.")
    return result


class RobotStateNode(Node):
    """비동기 조회는 채널당 한 건만 유지하고 실패/오래된 값은 null로 표시한다."""

    def __init__(self):
        super().__init__("ccc_robot_state")
        self.declare_parameter("service_root", "/dsr01/dsr_controller2")
        self.declare_parameter("gripper_topic", "/onrobot_joint_states")
        self.declare_parameter("poll_period_s", 0.2)
        self.declare_parameter("request_timeout_s", 1.0)
        self.declare_parameter("stale_after_s", 2.0)
        root = self.get_parameter("service_root").value.rstrip("/")
        self.period = float(self.get_parameter("poll_period_s").value)
        self.timeout = float(self.get_parameter("request_timeout_s").value)
        self.stale = float(self.get_parameter("stale_after_s").value)
        if not all(math.isfinite(v) and v > 0 for v in (self.period, self.timeout, self.stale)):
            raise ValueError("조회 주기/제한 시간은 유한한 양수여야 합니다.")
        self.publisher = self.create_publisher(String, "cable_inspection/robot_status", 10)
        self.cache = {}
        self.channels = {}
        specs = [
            ("task", GetCurrentPosx, "/aux_control/get_current_posx", {"ref": 0},
             lambda r: vector(r.task_pos_info[0].data[:6])),
            ("joint", GetCurrentPosj, "/aux_control/get_current_posj", {}, lambda r: vector(r.pos)),
            ("wrench_base", GetToolForce, "/aux_control/get_tool_force", {"ref": 0},
             lambda r: vector(r.tool_force)),
            ("robot_state_code", GetRobotState, "/system/get_robot_state", {}, lambda r: int(r.robot_state)),
            ("motion_status", CheckMotion, "/motion/check_motion", {}, lambda r: int(r.status)),
            ("tcp_name", GetCurrentTcp, "/tcp/get_current_tcp", {}, lambda r: str(r.info)),
            ("tool_name", GetCurrentTool, "/tool/get_current_tool", {}, lambda r: str(r.info)),
        ]
        for key, srv, suffix, args, decode in specs:
            self.channels[key] = {
                "client": self.create_client(srv, root + suffix),
                "request": srv.Request(**args), "decode": decode,
                "future": None, "started": 0.0, "next": 0.0,
                "period": max(1.0, self.period) if key in {"tcp_name", "tool_name"} else self.period,
            }
        self.create_subscription(JointState, self.get_parameter("gripper_topic").value,
                                 self._gripper, 10)
        self.create_timer(min(0.1, self.period), self._tick)

    def _store(self, key, value=None, error=""):
        self.cache[key] = {"value": value, "time": time.monotonic(), "error": error}

    def _gripper(self, message):
        try:
            angle = float(message.position[0])
            if not math.isfinite(angle):
                raise ValueError("그리퍼 관절값이 유효하지 않습니다.")
            # 실제 RG2 드라이버의 관절각(rad)을 폭(mm)으로 변환한다.
            width = max(0.0, (math.cos(angle + 0.76794) * 0.055 - 0.0144
                             + 0.108505 * math.cos(1.41371)) * 2000.0)
            self._store("gripper_width_mm", width)
        except (ValueError, IndexError, TypeError) as error:
            self._store("gripper_width_mm", error=str(error))

    def _poll(self, now):
        for key, channel in self.channels.items():
            future, client = channel["future"], channel["client"]
            if future is not None:
                if future.done():
                    try:
                        response = future.result()
                        if response is None or not response.success:
                            raise ValueError("조회 실패")
                        self._store(key, channel["decode"](response))
                    except Exception as error:
                        self._store(key, error=str(error))
                    channel["future"] = None
                elif now - channel["started"] >= self.timeout:
                    client.remove_pending_request(future)
                    future.cancel()
                    self._store(key, error="조회 시간 초과")
                    channel["future"] = None
            if channel["future"] is None and now >= channel["next"]:
                channel["next"] = now + channel["period"]
                if client.service_is_ready():
                    try:
                        channel["future"] = client.call_async(channel["request"])
                        channel["started"] = now
                    except Exception as error:
                        self._store(key, error=str(error))
                else:
                    self._store(key, error="서비스 없음")

    def _snapshot(self, now):
        values, validity, ages, errors = {}, {}, {}, {}
        for key in [*self.channels, "gripper_width_mm"]:
            entry = self.cache.get(key)
            age = max(0.0, now - entry["time"]) if entry else None
            valid = bool(entry and not entry["error"] and age <= self.stale)
            values[key] = entry["value"] if valid else None
            validity[key], ages[key] = valid, age
            if not valid:
                errors[key] = (entry["error"] or "데이터 만료") if entry else "수신 없음"
        code, motion = values["robot_state_code"], values["motion_status"]
        wrench = values["wrench_base"]
        robot_motion = ""
        if motion is not None and motion >= 0:
            robot_motion = "MOVING" if motion != 0 else STATE_NAMES.get(code, "")
        return {
            "schema_version": 1,
            "stamp": datetime.now().astimezone().isoformat(timespec="milliseconds"),
            "robot_connected": validity["robot_state_code"],
            "gripper_connected": validity["gripper_width_mm"],
            "task": values["task"], "joint": values["joint"],
            "wrench_base": wrench, "force_norm_n": math.hypot(*wrench[:3]) if wrench else None,
            "gripper_width_mm": values["gripper_width_mm"],
            "robot_state_code": code, "motion_status": motion, "robot_motion": robot_motion,
            "servo": ("OFF" if code in {0, 3, 6, 10, 15} else "ON") if code in STATE_NAMES else "",
            "servo_source": "robot_state_inference",
            "tool": {"name": values["tool_name"], "tcp": values["tcp_name"]},
            "validity": validity, "age_s": ages, "errors": errors,
        }

    def _tick(self):
        self._poll(time.monotonic())
        self.publisher.publish(String(data=json.dumps(
            self._snapshot(time.monotonic()), ensure_ascii=False, allow_nan=False)))


def main(args=None):
    rclpy.init(args=args)
    node = RobotStateNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.try_shutdown()
