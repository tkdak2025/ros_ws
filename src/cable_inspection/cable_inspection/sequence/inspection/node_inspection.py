"""#06 Inspection Judgment: 로봇 모션과 별도 Worker에서 검사 결과를 판정한다.
1. 수신한 측정 요청을 Queue에 저장한다.
2. Worker가 종료 사유·힘·변위·폭을 판정한다.
3. PASS/FAIL/SYSTEM_ERROR를 저장하고 HMI 노드에 결과를 전달한다.
4. 외부 통신은 HMI 노드가 담당하며 내부 호출은 Queue API를 사용한다."""

import json
import math
import queue
import threading
from copy import deepcopy
from datetime import datetime
from cable_interfaces.msg import InspectionResult as InspectionResultMessage
from rosidl_runtime_py.convert import message_to_ordereddict
from cable_inspection.sequence.inspection.data_models.judgment import Judgment
from cable_inspection.sequence.inspection.data_models.judgment_request import JudgmentRequest
from cable_inspection.sequence.inspection.data_models.inspection_result import InspectionResult
from cable_inspection.sequence.inspection.data_models.judgment_status import JudgmentStatus
from cable_inspection.sequence.inspection.data_models.pull_termination import PullTermination
from cable_inspection.sequence.common.data_models.sequence_status import SequenceStatus


try:
    import rclpy
    from rclpy.executors import ExternalShutdownException
    from rclpy.node import Node

except ModuleNotFoundError:  # 순수 판정 단위 테스트는 ROS 환경 없이 실행한다.
    rclpy = None
    ExternalShutdownException = Exception
    Node = object



class InspectionJudgmentNode(Node):
    """HMI에서 전달받은 요청은 등록만 하고 Worker Thread가 판정을 수행한다."""



    # 기능: 요청 Queue와 결과 전달 콜백을 준비하고 판정 Worker를 시작한다.
    #     node_name: 판정 노드의 ROS 이름.
    #     반환: 없음. 외부 서비스·발행·구독은 HmiNode가 생성한다.
    def __init__(self, node_name="inspection_judgment_node"):
        super().__init__(node_name)
        self.tasks = queue.Queue()
        self._lock = threading.RLock()
        self._generation = 0
        self._run_id = None
        self._pending = set()
        self._results = {}
        self._closed = False
        self.publish_result = lambda message: None
        self.publish_log = lambda level, text: print(f"[{level}] {text}", flush=True)
        self.worker = threading.Thread(
            target=self._work,
            name="inspection-judgment-worker",
            daemon=True,
        )
        self.worker.start()
        print("[Inspection Judgment] 검사 데이터 대기 중 — PASS / FAIL / SYSTEM_ERROR", flush=True)



    # 기능: 새 실행을 시작하고 이전 Queue 작업이 새 결과를 덮지 못하게 세대를 바꾼다.
    def reset(self, run_id):
        with self._lock:
            if self._closed:
                raise RuntimeError("판정 노드가 종료되었습니다.")

            self._generation += 1
            self._run_id = run_id
            self._pending.clear()
            self._results.clear()



    # 기능: ROS discovery 대신 실제 판정 Worker의 실행 상태를 확인한다.
    def is_ready(self):
        return not self._closed and self.worker.is_alive()



    # 기능: 내부 검사와 외부 ROS 요청을 같은 판정 Queue에 등록한다.
    def submit(self, request):
        with self._lock:
            if self._closed:
                raise RuntimeError("판정 노드가 종료되었습니다.")

            if self._run_id is not None and request.run_id != self._run_id:
                raise ValueError("현재 실행의 판정 요청이 아닙니다.")

            key = (request.run_id, request.point_id)
            previous = self._results.get(request.point_id)

            if key in self._pending or (previous and previous["run_id"] == request.run_id):
                return

            self._pending.add(key)
            self.tasks.put_nowait((self._generation, request))



    # 기능: 확정된 결과의 복사본을 반환한다. 호출자는 내부 상태를 수정할 수 없다.
    def snapshot(self):
        with self._lock:
            return deepcopy(self._results)



    # 기능: 복귀 실패를 즉시 확정하고 진행 중인 정상 판정의 덮어쓰기를 차단한다.
    def record_error(self, request):
        with self._lock:
            if self._closed or (self._run_id is not None and request.run_id != self._run_id):
                return

            message = self._result_message(request, self.judge_request(request))
            self._pending.discard((request.run_id, request.point_id))
            self._results[request.point_id] = dict(message_to_ordereddict(message))
            self.publish_result(message)



    # 기능: HMI가 전달한 판정 요청을 검증하고 Queue에 넣는다.
    #     payload: 외부 측정 요청의 JSON 문자열.
    #     반환: 없음. 식별 가능한 잘못된 요청은 HMI 출력 콜백에 오류 결과를 전달한다.
    def receive_request(self, payload: str) -> None:
        raw = None

        try:
            raw = json.loads(payload)

            if not isinstance(raw, dict):
                raise ValueError("Judgment 요청은 JSON 객체여야 합니다.")

            request = JudgmentRequest.from_dict(raw)

            with self._lock:
                if self._closed or (self._run_id is not None and request.run_id != self._run_id):
                    return

                self.submit(request)

        except (json.JSONDecodeError, KeyError, TypeError, ValueError) as error:
            self.publish_log("ERROR", f"Judgment 요청 오류: {error}")

            # 포인트를 식별할 수 있는 잘못된 요청도 결과를 남겨 PENDING을 해소한다.
            if isinstance(raw, dict) and isinstance(raw.get("run_id"), int) and raw.get("point_id"):
                self.publish_result(InspectionResultMessage(**{
                    "run_id": raw["run_id"], "point_id": str(raw["point_id"]),
                    "recipe_id": raw.get("recipe_id", ""),
                    "result": "SYSTEM_ERROR", "judgment_status": "ERROR",
                    "sequence_status": "INCOMPLETE", "termination_reason": "INVALID_DATA",
                    "reason_code": "SYSTEM_ERROR", "reason": f"잘못된 판정 요청: {error}",
                }))



    # 기능: 별도 Worker에서 판정하고 현재 실행의 유효한 요청만 저장·발행한다.
    def _work(self):
        while True:
            item = self.tasks.get()

            try:
                if item is None:
                    return

                generation, request = item
                key = (request.run_id, request.point_id)

                with self._lock:
                    if generation != self._generation or key not in self._pending:
                        continue

                try:
                    judgment = self.judge_request(request)

                except Exception as error:
                    judgment = Judgment(JudgmentStatus.ERROR, SequenceStatus.INCOMPLETE,
                        InspectionResult.SYSTEM_ERROR, f"판정 오류: {error}", "SYSTEM_ERROR")

                message = self._result_message(request, judgment)

                with self._lock:
                    if generation != self._generation or key not in self._pending:
                        continue

                    self._results[request.point_id] = dict(message_to_ordereddict(message))
                    self._pending.remove(key)
                    self.publish_result(message)
                    self.display_result(request, judgment)

            except Exception as error:
                self.publish_log("ERROR", f"판정 결과 처리 실패: {error}")

            finally:
                self.tasks.task_done()



    # 기능: 요청 정보와 판정을 커스텀 결과 메시지로 채운다. 유효하지 않은 수치는 0으로 보낸다.
    @staticmethod
    def _result_message(request: JudgmentRequest, judgment: Judgment) -> InspectionResultMessage:
        # 기능: 판정 입력의 숫자가 유한한 값인지 확인한다.
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
            "task": ([numeric(v) for v in request.entry_task]
                     if isinstance(request.entry_task, (list, tuple)) and len(request.entry_task) == 6 else [0.0] * 6),
            "joint": ([numeric(v) for v in request.entry_joint]
                      if isinstance(request.entry_joint, (list, tuple)) and len(request.entry_joint) == 6 else [0.0] * 6),
            "db_saved": False,
            "judgment_status": judgment.status.value,
            "sequence_status": judgment.sequence_status.value,
            "termination_reason": request.termination_reason.value,
        })



    # 기능: 종료 신호를 Queue에 넣고 남은 요청 처리를 마친 Worker를 기다린다.
    def close(self) -> None:
        with self._lock:
            if not self._closed:
                self._closed = True
                self.tasks.put(None)

        self.worker.join()



    # 기능: 한 검사 요청의 종료 사유·힘·변위·폭으로 판정 결과를 직접 계산한다.
    @staticmethod
    def judge_request(request: JudgmentRequest) -> Judgment:
        termination = request.termination_reason
        peak_force_n = request.peak_pull_force_n
        displacement_mm = request.pull_displacement_mm
        required_force_n = request.required_force_n
        normal_displacement_limit_mm = request.normal_displacement_limit_mm
        soft_width_mm = request.soft_width_mm
        pull_width_mm = request.pull_width_mm



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

        if termination == PullTermination.STOPPED_SHORT:
            return system_error("Pull 중 힘 기준과 최대거리 도달 전에 이동이 종료되었습니다.")

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



    # 기능: 포인트 판정과 힘·변위·폭·사유를 터미널에 표시한다.
    @staticmethod
    def display_result(request, judgment):
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



# 기능: 판정 노드를 실행하고 종료 시 Worker와 ROS 자원을 정리한다.
#     args: ROS 초기화에 전달할 명령행 인자. None이면 기본 인자를 사용한다.
def main(args=None) -> None:
    if rclpy is None:
        raise RuntimeError("ROS2 환경을 source한 뒤 실행하세요.")

    rclpy.init(args=args)
    from cable_inspection.hmi.node_hmi import HmiNode
    from rclpy.executors import SingleThreadedExecutor
    node = InspectionJudgmentNode()
    hmi = HmiNode(None, node)
    executor = SingleThreadedExecutor()
    executor.add_node(node)
    executor.add_node(hmi)

    try:
        executor.spin()

    except (KeyboardInterrupt, ExternalShutdownException):
        pass

    finally:
        node.close()
        executor.shutdown()
        hmi.destroy_node()
        node.destroy_node()
        rclpy.try_shutdown()



if __name__ == "__main__":
    main()
