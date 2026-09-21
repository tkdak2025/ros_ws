"""DART 수동 이동 중 BASE TCP/관절 상태를 읽어서 CSV로 기록한다.

이미 연결된 두산 ROS 2 드라이버와 해당 워크스페이스 환경이 필요하다.
일반 실행: python3 pose_range_observer.py
실행 인자 없이 시작한다. 목표 기록 주기는 10 Hz이며 Ctrl+C로 종료한다.
X/Y/Z와 각 축의 시작 대비 변위를 모두 기록한다. 이동 변위는 위치 오차가 아니다.
허용오차 판정 없이 측정값과 자세 변화량만 기록한다.

기준 자세에서 정지 후 Enter를 누르면 첫 유효 샘플을 기준으로 기록한다.
DART에서 직접 이동하고 Ctrl+C로 기록을 끝낸다. 이 프로그램은 이동,
서보, 운전 모드, TCP, 디지털 출력을 변경하지 않으며 로봇 정지도 하지 않는다.
드라이버 실행 자체의 제어권/운전 모드 영향은 기존 연결 환경에서 확인해야 한다.

TCP와 관절은 별도 서비스로 순차 조회하므로 동시 측정이 아니다.
호스트 수신 시간/조회 지연을 저장하며 설정 주기는 보장되지 않는다.
로봇이 보고하는 위치이지 외부 실측값이 아니다. TCP 설정은 기록 중 유지한다.
기록 구간은 사용 가능 범위 인증이 아니며 샘플 사이의 이탈을 놓칠 수 있다.
"""

import csv
import json
import math
import time
from datetime import datetime
from pathlib import Path
from uuid import uuid4

import rclpy
from rclpy.executors import ExternalShutdownException
from dsr_msgs2.srv import GetCurrentPosj, GetCurrentPosx


class GripPoseObserver:
    """읽기 전용 서비스 두 개로 기준 자세 대비 변화를 관찰한다."""

    SERVICE_PREFIX = "/dsr01/dsr_controller2"
    SAMPLE_RATE_HZ = 10.0
    SERVICE_TIMEOUT_S = 3.0
    OUTPUT_DIR = Path(__file__).resolve().parents[2] / "measurement_results"

    def __init__(self):
        self.node = rclpy.create_node("grip_pose_observer")
        prefix = self.SERVICE_PREFIX
        self.task_client = self.node.create_client(
            GetCurrentPosx, prefix + "/aux_control/get_current_posx"
        )
        self.joint_client = self.node.create_client(
            GetCurrentPosj, prefix + "/aux_control/get_current_posj"
        )
        self.baseline = None
        self.reference_rotation = None
        self.started = None
        self.count = 0
        self.summary = {
            "status": "starting", "samples": 0,
            "max_orientation_error_deg": 0.0,
            **{f"{bound}_d{axis}_mm": None
               for axis in "xyz" for bound in ("min", "max")},
            "min_abs_j5_deg": None,
        }

    @staticmethod
    def rotation(angles):
        """Doosan 기본 Euler ZYZ: Rz(A) @ Ry(B) @ Rz(C)."""
        a, b, c = map(math.radians, angles)
        ca, sa, cb, sb, cc, sc = (
            math.cos(a), math.sin(a), math.cos(b), math.sin(b),
            math.cos(c), math.sin(c),
        )
        return (
            (ca * cb * cc - sa * sc, -ca * cb * sc - sa * cc, ca * sb),
            (sa * cb * cc + ca * sc, -sa * cb * sc + ca * cc, sa * sb),
            (-sb * cc, sb * sc, cb),
        )

    def read_service(self, client, request):
        start = time.monotonic()
        future = client.call_async(request)
        try:
            rclpy.spin_until_future_complete(
                self.node, future, timeout_sec=self.SERVICE_TIMEOUT_S
            )
            if not future.done():
                raise TimeoutError(f"조회 시간 초과: {client.srv_name}")
            response = future.result()
            if response is None or not response.success:
                raise RuntimeError(f"조회 실패: {client.srv_name}")
            end = time.monotonic()
            return response, end, (end - start) * 1000
        finally:
            if not future.done():
                future.cancel()

    def sample(self):
        request = GetCurrentPosx.Request()
        request.ref = 0  # DR_BASE; 이 서비스의 기본 자세 표현은 Euler ZYZ.
        task_response, task_time, task_latency = self.read_service(
            self.task_client, request
        )
        if not task_response.task_pos_info:
            raise RuntimeError("TCP 응답이 비어 있습니다.")
        data = list(task_response.task_pos_info[0].data)
        if len(data) < 7:
            raise RuntimeError("TCP 응답에 위치 6개/solution space가 없습니다.")
        pose = data[:6]
        joint_response, joint_time, joint_latency = self.read_service(
            self.joint_client, GetCurrentPosj.Request()
        )
        joints = list(joint_response.pos)
        if len(joints) != 6 or not all(math.isfinite(v) for v in data[:7] + joints):
            raise RuntimeError("위치/관절 응답에 유효하지 않은 값이 있습니다.")
        rotation = self.rotation(pose[3:])
        if self.baseline is None:
            self.baseline = {"task": pose[:], "joint": joints[:], "solution_space": data[6]}
            self.reference_rotation = rotation
            self.started = task_time
        delta = [pose[i] - self.baseline["task"][i] for i in range(3)]
        # ABC 변화량은 표시각의 최단 부호 차이이며 실제 회전량은 아래 angle이다.
        angle_delta = [
            (pose[i] - self.baseline["task"][i] + 180) % 360 - 180
            for i in range(3, 6)
        ]
        # 관절각은 다회전 정보를 보존하도록 현재값에서 기준값을 그대로 뺀다.
        joint_delta = [joints[i] - self.baseline["joint"][i] for i in range(6)]
        # trace(R0.T @ R)를 원소별 내적으로 계산한다. Euler 단순 차분을 쓰지 않는다.
        trace = sum(self.reference_rotation[i][j] * rotation[i][j]
                    for i in range(3) for j in range(3))
        angle = math.degrees(math.acos(max(-1.0, min(1.0, (trace - 1) / 2))))
        row = {
            "sample": self.count,
            "host_time": datetime.now().astimezone().isoformat(timespec="milliseconds"),
            "task_elapsed_s": task_time - self.started,
            "joint_elapsed_s": joint_time - self.started,
            "task_query_ms": task_latency, "joint_query_ms": joint_latency,
            "receive_gap_ms": (joint_time - task_time) * 1000,
            "solution_space": data[6],
            **{key: value for i, axis in enumerate("xyz")
               for key, value in ((f"{axis}_mm", pose[i]), (f"d{axis}_mm", delta[i]))},
            **{key: value for i, axis in enumerate("abc")
               for key, value in ((f"{axis}_deg", pose[i + 3]),
                                  (f"d{axis}_deg", angle_delta[i]))},
            **{key: value for i in range(6)
               for key, value in ((f"j{i + 1}_deg", joints[i]),
                                  (f"dj{i + 1}_deg", joint_delta[i]))},
            "orientation_error_deg": angle, "abs_j5_deg": abs(joints[4]),
        }
        return row

    def record(self):
        for client in (self.task_client, self.joint_client):
            if not client.wait_for_service(timeout_sec=self.SERVICE_TIMEOUT_S):
                raise RuntimeError(f"서비스를 찾지 못했습니다: {client.srv_name}")
        print("읽기 전용 관찰기입니다. 로봇 이동/정지 명령을 보내지 않습니다.")
        print("TCP 설정을 유지하고 기준 자세에 정지하세요. 기록 종료는 Ctrl+C입니다.")
        input("기준 자세 기록을 시작하려면 Enter: ")
        self.OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        name = f"pose_range_{datetime.now():%Y%m%d_%H%M%S}"
        csv_path = self.OUTPUT_DIR / (name + ".csv")
        json_path = self.OUTPUT_DIR / (name + ".json")
        print(f"CSV: {csv_path}")
        self.summary["status"] = "recording"
        last_print = -math.inf
        try:
            with csv_path.open("x", newline="", encoding="utf-8") as stream:
                writer = None
                while rclpy.ok():
                    cycle_start = time.monotonic()
                    row = self.sample()
                    if writer is None:
                        writer = csv.DictWriter(stream, fieldnames=list(row))
                        writer.writeheader()
                    writer.writerow(row)
                    stream.flush()
                    self.count += 1
                    self.summary["samples"] = self.count
                    self.summary["max_orientation_error_deg"] = max(
                        self.summary["max_orientation_error_deg"], row["orientation_error_deg"]
                    )
                    for axis in "xyz":
                        value = row[f"d{axis}_mm"]
                        for bound, operation in (("min", min), ("max", max)):
                            key = f"{bound}_d{axis}_mm"
                            old = self.summary[key]
                            self.summary[key] = value if old is None else operation(old, value)
                    old_j5 = self.summary["min_abs_j5_deg"]
                    self.summary["min_abs_j5_deg"] = (
                        row["abs_j5_deg"] if old_j5 is None else min(old_j5, row["abs_j5_deg"])
                    )
                    if cycle_start - last_print >= 1:
                        print(f"\n[{row['task_elapsed_s']:.1f}초] 현재값 (시작 대비 변화량)")
                        for label, axes, unit in (
                            ("TCP 위치", "xyz", "mm"),
                            ("TCP 표시각", "abc", "deg"),
                            ("관절각", [f"j{i}" for i in range(1, 7)], "deg"),
                        ):
                            values = "  ".join(
                                f"{axis.upper()}={row[f'{axis}_{unit}']:.3f} "
                                f"({row[f'd{axis}_{unit}']:+.3f})"
                                for axis in axes
                            )
                            print(f"{label} [{unit}]: {values}")
                        print(f"전체 방향 변화각: {row['orientation_error_deg']:.3f}°")
                        last_print = cycle_start
                    delay = 1 / self.SAMPLE_RATE_HZ - (time.monotonic() - cycle_start)
                    if delay > 0:
                        time.sleep(delay)
                if self.summary["status"] == "recording":
                    self.summary["status"] = "ros_shutdown"
        except (KeyboardInterrupt, ExternalShutdownException):
            self.summary["status"] = "interrupted"
        except Exception as error:
            self.summary.update(status="error", error=str(error))
            raise
        finally:
            metadata = {
                "coordinate_frame": "BASE", "orientation": "Euler ZYZ degrees",
                "service_prefix": self.SERVICE_PREFIX,
                "schema_version": 4, "recorded_axes": ["x", "y", "z"],
                "delta_reference": "first valid sample",
                "delta_definitions": {
                    "xyz": "current minus baseline (mm)",
                    "abc": "displayed Euler angle difference wrapped to [-180,180); not physical rotation",
                    "joints": "current minus baseline (degrees, unwrapped difference)",
                    "orientation_error_deg": "relative rotation angle from rotation matrices",
                },
                "requested_rate_hz": self.SAMPLE_RATE_HZ,
                "baseline": self.baseline, "summary": self.summary,
                "limitations": "Sequential host-timed service samples; no motion commands, "
                                "no automatic stop, no certified safe range or external metrology.",
            }
            with json_path.open("x", encoding="utf-8") as stream:
                json.dump(metadata, stream, ensure_ascii=False, indent=2, allow_nan=False)
            print(f"기록 종료: {self.count}개 샘플. 요약: {json_path}")


def main():
    rclpy.init(args=[])
    observer = None
    try:
        observer = GripPoseObserver()
        observer.record()
    except (KeyboardInterrupt, EOFError, ExternalShutdownException):
        print("관찰 종료.")
    except Exception as error:
        print(f"관찰 실패: {error}")
        return 1
    finally:
        if observer is not None:
            observer.node.destroy_node()
        rclpy.try_shutdown()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
