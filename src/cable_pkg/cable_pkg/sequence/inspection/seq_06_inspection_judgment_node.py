"""#06 판정을 Robot Motion과 분리해 실행하는 ROS2 Worker 노드."""

import json
import math
import queue
import threading
import time
from dataclasses import dataclass
from datetime import datetime

try:
    import rclpy
    from rclpy.executors import ExternalShutdownException
    from rclpy.node import Node
    from std_msgs.msg import String
except ModuleNotFoundError:  # 순수 판정 단위 테스트는 ROS 환경 없이 실행한다.
    rclpy = None
    ExternalShutdownException = Exception
    Node = object
    String = object

from cable_interfaces.msg import InspectionResult as InspectionResultMessage
from rosidl_runtime_py.convert import message_to_ordereddict

from cable_pkg.data_models.inspection_models import JudgmentRequest
from cable_pkg.data_models.sequence_models import (
    InspectionResult,
    JudgmentStatus,
    PullTermination,
    SequenceStatus,
)


TOPIC_JUDGMENT_REQUEST = "cable_inspection/judgment_request"
TOPIC_RESULT = "cable_inspection/judgment_result"
TOPIC_LOG = "cable_inspection/log"


@dataclass(frozen=True)
class Judgment:
    """#06이 생성하는 제품 판정과 시퀀스 처리 상태."""

    status: JudgmentStatus
    sequence_status: SequenceStatus
    result: InspectionResult | None
    reason: str
    reason_code: str = ""


def judge_pull(
    *,
    termination: PullTermination,
    peak_force_n: float,
    displacement_mm: float,
    required_force_n: float,
    normal_displacement_limit_mm: float = 5.0,
    soft_width_mm: float | None = None,
    pull_width_mm: float | None = None,
) -> Judgment:
    """종료 사유·힘·변위 및 Pull 최소 폭으로 검사와 파지 실패를 판정한다."""
    def system_error(reason):
        return Judgment(JudgmentStatus.ERROR, SequenceStatus.INCOMPLETE,
                        InspectionResult.SYSTEM_ERROR, reason, "SYSTEM_ERROR")

    values = (peak_force_n, displacement_mm, required_force_n,
              normal_displacement_limit_mm)
    if any(isinstance(v, bool) or not isinstance(v, (int, float))
           or not math.isfinite(v) for v in values):
        return system_error("유효하지 않은 Pull 측정값 또는 기준값입니다.")
    if min(values) < 0 or required_force_n <= 0:
        return system_error("Pull 측정값 또는 기준값의 범위가 잘못되었습니다.")
    if termination not in {PullTermination.FORCE_LIMIT, PullTermination.MAX_DISTANCE}:
        return system_error(f"Pull 종료 오류: {termination}")
    widths = (soft_width_mm, pull_width_mm)
    if any(isinstance(v, bool) or not isinstance(v, (int, float))
           or not math.isfinite(v) or v < 0 for v in widths):
        return system_error("유효한 Soft/Pull 그리퍼 실측 폭이 없습니다.")
    if pull_width_mm < 16.0:
        return Judgment(JudgmentStatus.COMPLETED, SequenceStatus.SUCCESS,
                        InspectionResult.FAIL, "Pull 중 실측 폭이 16 mm 미만으로 파지 실패입니다.",
                        "FAIL_GRIP_WIDTH")
    if termination == PullTermination.MAX_DISTANCE:
        return Judgment(JudgmentStatus.COMPLETED, SequenceStatus.SUCCESS,
                        InspectionResult.FAIL, "최대 Pull 거리에 도달했습니다.",
                        "FAIL_MAX_DISTANCE")
    if termination != PullTermination.FORCE_LIMIT:
        return system_error(f"Pull 종료 오류: {termination}")
    if peak_force_n < required_force_n:
        return system_error("FORCE_LIMIT 종료 사유와 최대 Pull 힘이 일치하지 않습니다.")
    passed = displacement_mm <= normal_displacement_limit_mm
    return Judgment(
        JudgmentStatus.COMPLETED, SequenceStatus.SUCCESS,
        InspectionResult.PASS if passed else InspectionResult.FAIL,
        "기준 힘 도달, 허용 변위 이내입니다." if passed else "허용 변위를 초과했습니다.",
        "PASS_FORCE_DISPLACEMENT_OK" if passed else "FAIL_DISPLACEMENT_LIMIT",
    )


class JudgmentClient:
    """#06 요청을 발행하고 비동기 판정 완료를 추적한다."""

    def __init__(self, node: Node):
        self.node = node
        self.publisher = node.create_publisher(String, TOPIC_JUDGMENT_REQUEST, 50)
        self.pending: set[tuple[int, str]] = set()
        self.results: dict[str, dict] = {}
        node.create_subscription(InspectionResultMessage, TOPIC_RESULT, self._receive_result, 50)

    def submit(self, request: JudgmentRequest) -> None:
        self.pending.add((request.run_id, request.point_id))
        self.publisher.publish(String(data=json.dumps(request.to_dict())))

    def wait_for_subscriber(self, timeout_s: float = 5.0) -> None:
        deadline = time.monotonic() + timeout_s
        while self.publisher.get_subscription_count() == 0:
            if time.monotonic() >= deadline:
                raise RuntimeError("Inspection Judgment 노드가 실행 중이지 않습니다.")
            time.sleep(0.05)

    def _receive_result(self, message: InspectionResultMessage) -> None:
        try:
            result = dict(message_to_ordereddict(message))
            key = (int(result["run_id"]), str(result["point_id"]))
        except (json.JSONDecodeError, KeyError, TypeError, ValueError):
            return
        if key not in self.pending:
            return
        if result.get("judgment_status") not in {"COMPLETED", "ERROR"}:
            return
        self.results[key[1]] = result
        self.pending.remove(key)

    def wait_for_all(self, timeout_s: float = 10.0) -> dict[str, dict]:
        """모션 종료 후 등록된 모든 Point 판정이 올 때까지만 기다린다."""
        deadline = time.monotonic() + timeout_s
        while self.pending:
            rclpy.spin_once(self.node, timeout_sec=0.05)
            if time.monotonic() >= deadline:
                waiting = ", ".join(point_id for _, point_id in sorted(self.pending))
                raise TimeoutError(f"Inspection Judgment 완료 시간 초과: {waiting}")
        return self.results.copy()


class InspectionJudgmentNode(Node):
    """ROS Callback은 등록만 하고 Worker Thread가 판정을 수행한다."""

    def __init__(self):
        super().__init__("inspection_judgment_node")
        self.tasks: queue.Queue[JudgmentRequest | None] = queue.Queue()
        self.result_pub = self.create_publisher(InspectionResultMessage, TOPIC_RESULT, 50)
        self.log_pub = self.create_publisher(String, TOPIC_LOG, 50)
        self.create_subscription(String, TOPIC_JUDGMENT_REQUEST, self._receive, 50)
        self.worker = threading.Thread(
            target=self._work,
            name="inspection-judgment-worker",
            daemon=True,
        )
        self.worker.start()
        print("[Inspection Judgment] 검사 데이터 대기 중 — PASS / FAIL / SYSTEM_ERROR", flush=True)

    def _receive(self, message: String) -> None:
        raw = None
        try:
            raw = json.loads(message.data)
            if not isinstance(raw, dict):
                raise ValueError("Judgment 요청은 JSON 객체여야 합니다.")
            self.tasks.put_nowait(JudgmentRequest.from_dict(raw))
        except (json.JSONDecodeError, KeyError, TypeError, ValueError) as error:
            self._publish_log("ERROR", f"Judgment 요청 오류: {error}")
            # 포인트를 식별할 수 있는 잘못된 요청도 결과를 남겨 PENDING을 해소한다.
            if isinstance(raw, dict) and isinstance(raw.get("run_id"), int) and raw.get("point_id"):
                self.result_pub.publish(InspectionResultMessage(**{
                    "run_id": raw["run_id"], "point_id": str(raw["point_id"]),
                    "recipe_id": raw.get("recipe_id", ""),
                    "result": "SYSTEM_ERROR", "judgment_status": "ERROR",
                    "sequence_status": "INCOMPLETE", "termination_reason": "INVALID_DATA",
                    "reason_code": "SYSTEM_ERROR", "reason": f"잘못된 판정 요청: {error}",
                }))

    def _work(self) -> None:
        while True:
            request = self.tasks.get()
            try:
                if request is None:
                    return
                judgment = judge_pull(
                    termination=request.termination_reason,
                    peak_force_n=request.peak_pull_force_n,
                    displacement_mm=request.pull_displacement_mm,
                    required_force_n=request.required_force_n,
                    normal_displacement_limit_mm=request.normal_displacement_limit_mm,
                    soft_width_mm=request.soft_width_mm,
                    pull_width_mm=request.pull_width_mm,
                )
                # 모션 노드와 별개로, 이 판정 노드를 실행한 터미널에 결과를 표시한다.
                print(
                    f"\n[{judgment.result.value}] {request.point_id} | Run {request.run_id}\n"
                    f"  종료 조건: {request.termination_reason.value}\n"
                    f"  최대 Pull 힘: {request.peak_pull_force_n} N"
                    f" / 기준: {request.required_force_n} N\n"
                    f"  실제 Pull 변위: {request.pull_displacement_mm} mm"
                    f" / 허용: {request.normal_displacement_limit_mm} mm 이하\n"
                    f"  Soft 기준 폭: {request.soft_width_mm} mm / Pull 최소 폭: {request.pull_width_mm} mm\n"
                    f"  판정 사유: {request.error_reason or judgment.reason}",
                    flush=True,
                )
                self.result_pub.publish(self._result_message(request, judgment))
            except Exception as error:
                self._publish_log(
                    "ERROR", f"{getattr(request, 'point_id', '?')} 판정 실패: {error}",
                )
            finally:
                self.tasks.task_done()

    @staticmethod
    def _result_message(request: JudgmentRequest, judgment: Judgment) -> InspectionResultMessage:
        def numeric(value):
            # HMI에는 NaN/문자열을 수치로 보내지 않는다. 오류는 result/reason으로 전달한다.
            return float(value) if (isinstance(value, (int, float)) and not isinstance(value, bool)
                             and math.isfinite(value)) else 0.0

        return InspectionResultMessage(**{
            "run_id": request.run_id,
            "stamp": datetime.now().astimezone().isoformat(timespec="seconds"),
            "recipe_id": request.recipe_id,
            "recipe_version": request.recipe_version,
            "point_id": request.point_id,
            "point_name": request.point_name,
            "cable_type": request.connector_type,
            "result": judgment.result.value if judgment.result else "",
            "soft_width_mm": numeric(request.soft_width_mm),
            "pull_width_mm": numeric(request.pull_width_mm),
            "width_delta_mm": numeric(request.pull_width_mm) - numeric(request.soft_width_mm),
            "grip_failure_width_mm": 16.0,
            "max_force_n": numeric(request.peak_pull_force_n),
            "required_pull_force_n": numeric(request.required_force_n),
            "displacement_mm": numeric(request.pull_displacement_mm),
            "displacement_limit_mm": numeric(request.normal_displacement_limit_mm),
            "reason": request.error_reason or judgment.reason,
            "reason_code": judgment.reason_code,
            "force_data_id": request.force_data_id,
            "task": [float(v) for v in request.entry_task],
            "joint": [float(v) for v in request.entry_joint],
            "db_saved": False,
            "judgment_status": judgment.status.value,
            "sequence_status": judgment.sequence_status.value,
            "termination_reason": request.termination_reason.value,
        })

    def _publish_log(self, level: str, text: str) -> None:
        print(f"[{level}] {text}", flush=True)
        self.log_pub.publish(String(data=json.dumps(
            {"level": level, "text": text, "popup": level == "ERROR"},
            ensure_ascii=False,
        )))

    def close(self) -> None:
        self.tasks.put(None)
        self.worker.join()


def main(args=None) -> None:
    if rclpy is None:
        raise RuntimeError("ROS2 환경을 source한 뒤 실행하세요.")
    rclpy.init(args=args)
    node = InspectionJudgmentNode()
    try:
        rclpy.spin(node)
    except (KeyboardInterrupt, ExternalShutdownException):
        pass
    finally:
        node.close()
        node.destroy_node()
        rclpy.try_shutdown()


if __name__ == "__main__":
    main()
