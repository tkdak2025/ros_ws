"""MainSequenceNode: 명령·상태 통신과 검사 실행을 관리하는 노드.

이 파일에서 MainSequenceNode → SequenceController → InspectionSequence 순으로
실행을 확인한다. 뒤의 두 클래스는 노드 내부 Worker와 재사용 검사 구간이다.
Initialize/Home/Point/Grip/Pull/Finish는 별도 클래스 없이 내부 메서드다.
ROS callback과 장비 Worker의 spin 분리는 유지한다.
"""

import json
import threading
import time
import rclpy
import copy
import argparse
import io
import signal
from dataclasses import asdict, replace
from datetime import datetime
from rclpy.node import Node
from rclpy.qos import QoSProfile, DurabilityPolicy, ReliabilityPolicy
from std_msgs.msg import Empty, String
from cable_interfaces.srv import StartInspection
from cable_inspection.recipe.inspection_recipe import from_message
from cable_inspection.data_models.models import (
    SystemState,
    InspectionResult,
    JudgmentStatus,
    JobContext,
    PointRuntime,
    PullTermination,
    SequenceResult,
    SequenceStatus,
    JudgmentRequest,
    InspectionPointResult,
    AdaptiveGripResult,
)
from pathlib import Path
from cable_inspection.sequence.judgment_node import JudgmentClient
from ament_index_python.packages import get_package_share_directory
from rclpy.executors import SingleThreadedExecutor
from rclpy.signals import SignalHandlerOptions
from rclpy.utilities import remove_ros_args
from cable_inspection.hardware.robot import SequenceRobot


class MainSequenceNode(Node):
    """Callback은 짧게 유지한다. Worker만 장비 서비스를 호출한다."""

    # 기능: 명령 수신·상태 발행과 Heartbeat 감시를 준비한다.
    #     backend: 실제 로봇/RG2 통신 객체.
    #     results_dir: 실행별 측정·판정 기록을 저장할 경로.
    #     heartbeat_timeout_s: 선택한 운전 입력의 Heartbeat를 기다릴 최대 시간(s).
    #     control_mode: hmi 또는 terminal. 선택한 쪽의 명령/Heartbeat만 수신한다.
    def __init__(self, backend, results_dir="results/inspection_sequence",
                 heartbeat_timeout_s=2.0, control_mode="hmi"):
        super().__init__("ccc_sequence_node")
        if control_mode not in {"hmi", "terminal"}:
            raise ValueError(f"지원하지 않는 운전 모드: {control_mode}")
        self.control_mode = control_mode
        controller = SequenceController(backend, results_dir)
        self.controller = controller
        self.heartbeat_timeout_s = heartbeat_timeout_s
        self.last_heartbeat = None
        self.communication_lost_handled = False
        self.worker = None
        self.selected_recipe = next(iter(controller.backend.recipe_paths), "")
        self._operation = ""
        self._request_id = ""
        self._start_requests = {}
        self._published_snapshots = set()
        self._last_status = None
        self.status_pub = self.create_publisher(
            String, "cable_inspection/work_status",
            QoSProfile(depth=1, reliability=ReliabilityPolicy.RELIABLE,
                       durability=DurabilityPolicy.TRANSIENT_LOCAL))
        self.snapshot_pub = self.create_publisher(
            String, "cable_inspection/execution_snapshot",
            QoSProfile(depth=10, reliability=ReliabilityPolicy.RELIABLE,
                       durability=DurabilityPolicy.TRANSIENT_LOCAL))
        self.create_service(StartInspection, "cable_inspection/start", self._start_inspection)
        controller.snapshot_notify = self._publish_execution_snapshot
        self.log_pub = self.create_publisher(String, "cable_inspection/log", 50)
        command_topic = "command" if control_mode == "hmi" else "terminal_command"
        self.create_subscription(String, f"cable_inspection/{command_topic}", self._on_command, 50)
        self.create_subscription(Empty, f"cable_inspection/{control_mode}_heartbeat", self._on_heartbeat, 10)
        self.create_timer(0.1, self._tick)
        controller.notify = self._log
        controller.backend.hmi_available = self.hmi_available


    def _publish_execution_snapshot(self, run_id, recipe):
        if run_id in self._published_snapshots:
            return
        payload = {"run_id": run_id, "request_id": self._request_id,
                   "recipe_id": recipe.recipe_id, "recipe_version": recipe.recipe_version,
                   "recipe": asdict(recipe)}
        self.snapshot_pub.publish(String(data=json.dumps(payload, ensure_ascii=False, allow_nan=False)))
        self._published_snapshots.add(run_id)

    def _start_inspection(self, request, response):
        """접수만 짧게 처리한다. 실행은 Worker, 동일 요청 ID의 재전송은 재실행하지 않는다."""
        rejection_code = "INVALID_REQUEST_ID"
        try:
            if not request.request_id.strip() or len(request.request_id) > 128:
                raise ValueError("request_id는 1~128자여야 합니다.")
            rejection_code = "INVALID_RECIPE"
            recipe = from_message(request.recipe)
            payload = json.dumps(asdict(recipe), sort_keys=True, ensure_ascii=False, allow_nan=False)
            previous = self._start_requests.get(request.request_id)
            if previous:
                if previous[0] != payload:
                    rejection_code = "REQUEST_ID_CONFLICT"
                    raise ValueError("동일 request_id에 다른 레시피를 보낼 수 없습니다.")
                response.accepted, response.code, response.run_id = True, "ALREADY_ACCEPTED", previous[1]
                response.message = "이미 접수한 요청입니다. work_status로 실행 결과를 확인하세요."
                return response
            if self.control_mode != "hmi":
                rejection_code = "CONTROL_MODE_MISMATCH"
                raise ValueError("HMI 제어 모드가 아닙니다.")
            if not self.hmi_available():
                rejection_code = "HEARTBEAT_MISSING"
                raise ValueError("HMI Heartbeat가 유효하지 않습니다.")
            if (self.controller.context is not None
                    or (self.worker is not None and self.worker.is_alive())):
                rejection_code = "BUSY"
                raise ValueError("진행 중이거나 정리되지 않은 작업이 있습니다.")
            if self.controller.state != SystemState.SYSTEM_READY:
                rejection_code = "NOT_READY"
                raise ValueError("SYSTEM_READY에서만 시작할 수 있습니다.")
            if not any(point.enabled for point in recipe.points.values()):
                rejection_code = "NO_ENABLED_POINTS"
                raise ValueError("활성 검사포인트가 없습니다.")
            rejection_code = "INVALID_RECIPE"
            self.controller.backend.accept_inspection_recipe(recipe)
            run_id = time.time_ns() // 1000
            self.selected_recipe = recipe.recipe_id
            self._request_id = request.request_id
            self._start_requests[request.request_id] = (payload, run_id)
            self._publish_execution_snapshot(run_id, recipe)
            self._launch(lambda: self.controller.run(recipe.recipe_id, run_id=run_id))
            response.accepted, response.code, response.run_id = True, "ACCEPTED", run_id
            response.message = "접수 완료. 장비 초기화 및 실행 결과는 work_status/log로 확인하세요."
        except (ValueError, TypeError, KeyError, AttributeError) as error:
            response.accepted, response.code, response.message = False, rejection_code, str(error)
            response.run_id = 0
        return response

    # 기능: 최근 Heartbeat가 통신 제한시간 안에 도착했는지 확인한다.
    #
    #     ------------------------------------------------------------
    #     반환: 통신이 유효하면 True, 아니면 False.
    def hmi_available(self):
        return (self.last_heartbeat is not None
                and time.monotonic() - self.last_heartbeat <= self.heartbeat_timeout_s)


    # 기능: 실행 중인 Worker가 없을 때만 별도 스레드에서 Job 또는 Home 동작을 시작한다.
    #     action: 장비 Worker에서 실행할 인자 없는 함수.
    def _launch(self, action, operation="INSPECTION"):
        if self.worker is not None and self.worker.is_alive():
            self._log("WARN", "이전 시퀀스가 실행/정지 처리 중입니다.")
            return
        def work():
            try:
                result = action()
                self._log("INFO" if result.success else "ERROR", f"{result.code}: {result.message}")
            except Exception as error:
                self.controller._abort_motion()
                self.controller.last_error = str(error)
                self.controller.state = SystemState.ERROR
                self._log("ERROR", str(error))
        self._operation = operation
        if operation == "HOME":
            # 별도 HOME 명령은 이전 검사 START 요청에 속하지 않는다.
            # 검사 시퀀스 내부의 자동 HOME은 _launch를 거치지 않아 ID를 유지한다.
            self._request_id = ""
        self.controller.backend.latest_sample = None
        self.worker = threading.Thread(target=work, name="sequence-worker", daemon=False)
        self.worker.start()


    # 기능: 수신한 명령을 START/Home/Pause/Resume/STOP 등 해당 제어 기능에 전달한다.
    #     message: name과 args를 담은 JSON 형식의 std_msgs/String.
    def _on_command(self, message):
        try:
            raw = json.loads(message.data)
            if not isinstance(raw, dict) or not isinstance(raw.get("args", {}), dict):
                raise ValueError("명령은 name과 args를 가진 JSON 객체여야 합니다.")
            name, args = str(raw.get("name", "")).upper(), raw.get("args", {})
            if name == "START":
                if self.control_mode == "hmi":
                    raise ValueError("HMI START는 /cable_inspection/start 서비스로 검사 레시피 전체를 전달하세요.")
                recipe_id = args.get("recipe_id", self.selected_recipe)
                self._select_recipe(recipe_id)
                self._launch(lambda: self.controller.run(recipe_id))
            elif name in {"HOME_RETURN", "MOVE_HOME"}:
                self._launch(self.controller.request_home_return, operation="HOME")
            elif name == "PAUSE":
                self._report(self.controller.pause())
            elif name == "RESUME":
                self._report(self.controller.resume())
            elif name == "STOP":
                if self.worker is not None and self.worker.is_alive():
                    self._report(self.controller.stop())
                else:
                    self.controller.context = None
                    self.controller.state = SystemState.STOPPED
                    self._log("INFO", "STOPPED: 진행 중인 Job이 없습니다.")
            elif name == "SELECT_RECIPE":
                self._select_recipe(args.get("recipe_id", ""))
            elif name == "SYNC":
                self._publish_status()
            else:
                raise ValueError(f"지원하지 않는 명령: {name}")
        except (ValueError, TypeError, KeyError) as error:
            self._log("ERROR", str(error))


    # 기능: 대기 중 등록된 레시피를 선택하고 HMI에 선택 상태를 즉시 전달한다.
    #     recipe_id: 등록된 Inspection Recipe ID. 파일 경로가 아닌 식별자다.
    def _select_recipe(self, recipe_id):
        if not isinstance(recipe_id, str) or recipe_id not in self.controller.backend.recipe_paths:
            raise ValueError(f"등록되지 않은 Recipe: {recipe_id}")
        if (self.controller.state != SystemState.SYSTEM_READY
                or self.controller.context is not None
                or (self.worker is not None and self.worker.is_alive())):
            raise ValueError("작업이 끝나고 SYSTEM_READY일 때 Recipe를 선택할 수 있습니다.")
        self.selected_recipe = recipe_id
        self._log("INFO", f"RECIPE_SELECTED: {recipe_id}")
        self._publish_status()


    # 기능: Heartbeat 수신 시각을 갱신하고 유실 상태였다면 통신 복구를 알린다.
    #     _message: Heartbeat 수신 메시지. 내용 대신 수신 시각을 사용한다.
    def _on_heartbeat(self, _message):
        self.last_heartbeat = time.monotonic()
        if self.communication_lost_handled:
            self.controller.communication_recovered()
            self._log("INFO", "통신 복구. 상태를 다시 전달하며 RESUME을 기다립니다.")
        self.communication_lost_handled = False


    # 기능: 실행 중 통신 유실을 감시하고 현재 상태를 발행한다.
    def _tick(self):
        active = self.controller.state in {SystemState.RUNNING, SystemState.PAUSE_REQUEST, SystemState.PAUSED}
        if active and not self.hmi_available() and not self.communication_lost_handled:
            self.communication_lost_handled = True
            self.controller.communication_lost()
            self._log("WARN", f"{self.control_mode.upper()} COMM LOST: Safe Pause 요청")
        self._publish_status(force=False)


    # 기능: 현재 Job, Point, 진행률과 통신 상태를 상태 토픽에 발행한다.
    def _publish_status(self, force=True):
        context, backend = self.controller.context, self.controller.backend
        total = len(context.enabled_point_ids) if context else 0
        state = self.controller.state.value
        status = {
            "schema_version": 1,
            "operation": getattr(self, "_operation", ""),
            "request_id": getattr(self, "_request_id", ""),
            "state": "IDLE" if state == "SYSTEM_READY" else state,
            "run_state": state, "alarm": self.controller.last_error,
            "control_mode": self.control_mode, "control_connected": self.hmi_available(),
            "available_recipes": list(backend.recipe_paths), "run_id": self.controller.run_id,
            "recipe_id": context.recipe_id if context else self.selected_recipe,
            "selected_recipe_id": self.selected_recipe,
            "job_id": context.job_id if context else "",
            "recipe_version": context.recipe_snapshot.get("recipe_version", "") if context else "",
            "execution_index": context.current_point_index if context else 0,
            "resume_point": context.resume_point if context else "",
            "total_points": total, "current_point": context.current_point_id if context else "",
            "current_step": context.current_sequence if context else "",
            "pending_judgments": len(context.pending_judgments) if context else 0,
            "progress_percent": round(100 * context.current_point_index / total) if total else 0,
            "job_summary": self.controller.last_summary,
        }
        active = state in {"RUNNING", "PAUSE_REQUEST", "PAUSED"} or (
            self.worker is not None and self.worker.is_alive())
        status["work_active"] = active
        status["criteria"] = {}
        status["measurement"] = None
        if context and context.current_point_id:
            point = context.recipe_snapshot.get("points", {}).get(context.current_point_id)
            if point:
                pull, grip = point["pull_setting"], point["grip_setting"]
                status["criteria"] = {
                    "required_pull_force_n": pull["force_limit_n"],
                    "max_displacement_mm": pull["normal_displacement_limit_mm"],
                    "pull_max_distance_mm": pull["max_distance_mm"],
                    "grip_width_mm": grip["hard_width_mm"],
                }
            sample = getattr(backend, "latest_sample", None)
            if active and sample and sample.get("point_id") == context.current_point_id:
                age = max(0.0, time.monotonic() - sample["monotonic_s"])
                status["measurement"] = {
                    "sample_stamp": sample["timestamp"], "age_s": age,
                    "valid": age <= 2.0,
                    "phase": sample["phase"],
                    "measurement_kind": sample["measurement_kind"],
                    "pull_force_n": sample["pull_force_n"],
                    "pull_displacement_mm": sample["pull_displacement_mm"],
                }
        # 대기는 변경 시/SYNC에만 전송, 작업 중에는 10 Hz. 최종 상태는 보존한다.
        payload = json.dumps(status, ensure_ascii=False, allow_nan=False)
        if force or active or payload != self._last_status:
            status["stamp"] = datetime.now().astimezone().isoformat(timespec="milliseconds")
            self.status_pub.publish(String(data=json.dumps(status, ensure_ascii=False, allow_nan=False)))
            self._last_status = payload


    # 기능: 제어 요청의 성공 여부에 맞는 수준으로 결과를 로그에 남긴다.
    #     result: 성공 여부, 사유 코드, 부가 정보를 담은 SequenceResult.
    def _report(self, result):
        self._log("INFO" if result.success else "WARN", f"{result.code}: {result.message}")


    # 기능: 동일한 로그 내용을 터미널과 ROS 토픽에 전달한다.
    #     level: 로그 수준(INFO/WARN/ERROR).
    #     text: 터미널과 로그 토픽에 전달할 문자열.
    def _log(self, level, text):
        print(f"[{level}] {text}", flush=True)
        self.log_pub.publish(String(data=json.dumps({"level": level, "text": text,
                                                    "popup": level == "ERROR"}, ensure_ascii=False)))


    # 기능: 실행 중인 Worker에 STOP을 요청하고 장비 동작 처리가 끝날 때까지 기다린다.
    def close(self):
        if self.worker is not None and self.worker.is_alive():
            self.controller.stop()
            self.worker.join()  # 장비 서비스를 사용하는 Worker 종료 후 노드를 파괴한다.
        self._publish_status()


class JobStopped(RuntimeError):
    """STOP/통신 만료에 의한 흐름 종료. 제품 FAIL과 구분한다."""


class SequenceController:
    # 기능: Job 제어 상태와 기록 경로를 준비한다.
    #     backend: 로봇·통신·레시피 확인과 공통 이동을 제공하는 장비 객체.
    #     results_dir: 실행별 측정·판정 파일을 저장할 상위 폴더.
    def __init__(self, backend, results_dir="results/inspection_sequence"):
        self.backend = backend
        self.results_dir = Path(results_dir)
        self.state = SystemState.SYSTEM_READY
        self.context = None
        self.last_error = ""
        self.last_summary = {}
        self.run_id = 0
        self.snapshot_notify = lambda run_id, recipe: None
        self.output = None
        self.motion_results = {}
        self.judgment = None
        self.pause_requested = threading.Event()
        self.stop_requested = threading.Event()
        self.comm_lost_at = None
        self.stop_reason = "STOP"
        self.notify = lambda level, text: print(f"[{level}] {text}", flush=True)
        self.backend.control_poll = self.poll_control


    # 기능: 초기화 → Home → 포인트 순회 → 완료 확인 → Home으로 Job 한 번을 실행한다.
    #     recipe_id: 등록된 Inspection Recipe의 식별자.
    #
    #     ------------------------------------------------------------
    #     반환: Job 성공/중단/오류와 집계 정보를 담은 SequenceResult.
    def run(self, recipe_id, run_id=None):
        if self.state != SystemState.SYSTEM_READY or self.context is not None:
            return SequenceResult(False, "START_NOT_ALLOWED", "SYSTEM_READY에서만 시작할 수 있습니다.")
        stream, previous_stream = self.prepare_job(run_id)
        motion_started = False
        try:
            # #01 초기화 → #02 Home → 공통 진입 위치
            recipe = self.initialize_job(recipe_id)
            motion_started = True
            self._require(self.home_return())
            self.move_work_access("WORK_ACCESS_REACHED")

            # 활성 Point마다 #03 → #04 → #05 실행, #06은 비동기 판정
            self.inspect_points(recipe)

            # #07 결과 완료 확인 → #02 Home → 다음 START 대기
            self.move_work_access("WORK_ACCESS_FINISH")
            finish = self.wait_for_completion()
            self.last_summary = finish.data
            self._require(self.home_return())
            return self.complete_job()
        except JobStopped as error:
            return self.stop_job(error)
        except Exception as error:
            return self.fail_job(error, motion_started)
        finally:
            self.close_recording(stream, previous_stream)


    # 기능: 새 Job 상태, 실행 폴더, 측정 스트림과 판정 클라이언트를 준비한다.
    #
    #     ------------------------------------------------------------
    #     반환: (현재 측정 스트림, 이전 장비 스트림) 튜플.
    def prepare_job(self, run_id=None):
        self.stop_requested.clear()
        self.pause_requested.clear()
        self.comm_lost_at = None
        self.last_error = ""
        self.last_summary = {}
        self.motion_results = {}
        self.state = SystemState.RUNNING
        self.run_id = run_id if run_id is not None else time.time_ns() // 1000
        self.output = self.results_dir / self.now().strftime("%Y%m%d_%H%M%S_%f")
        self.output.mkdir(parents=True, exist_ok=False)
        stream = (self.output / "samples.jsonl").open("w", encoding="utf-8")
        previous_stream, self.backend.stream = self.backend.stream, stream
        self.judgment = JudgmentClient(self.backend.node)
        return stream, previous_stream


    # 기능: #01 및 판정 노드 준비를 확인하고 실행할 레시피 Snapshot을 고정한다.
    #     recipe_id: 등록된 Inspection Recipe의 식별자.
    #
    #     ------------------------------------------------------------
    #     반환: 이번 Job에서 사용할 Inspection Recipe 복사본.
    def initialize_job(self, recipe_id):
        initialized = self.work_initialize(recipe_id)
        self._require(initialized)
        # 판정 노드 발견 대기에서도 STOP/통신 만료를 확인한다.
        deadline = time.monotonic() + 5.0
        while self.judgment.publisher.get_subscription_count() == 0:
            self.pump()
            if time.monotonic() >= deadline:
                raise RuntimeError("Inspection Judgment 노드가 실행 중이지 않습니다.")
        recipe = copy.deepcopy(self.backend.recipe)
        self.context = JobContext(
            recipe_id=recipe_id, enabled_point_ids=initialized.data["enabled_point_ids"],
            job_id=str(self.run_id), recipe_snapshot=asdict(recipe), start_time=self.now(),
            state=SequenceStatus.RUNNING,
        )
        self.save("inputs.json", {"recipe": self.context.recipe_snapshot,
                                  "system_recipe": copy.deepcopy(self.backend.system)})
        self.snapshot_notify(self.run_id, recipe)
        self.checkpoint("INITIALIZE_DONE")
        return recipe


    # 기능: 공통 Work Access Safe Pose로 이동하고 완료점을 확인한다.
    #     checkpoint_name: Work Access 도달 후 기록할 완료점 이름.
    def move_work_access(self, checkpoint_name):
        self.backend.phase = "WORK_ACCESS"
        self._require(self.backend.move_work_access_safe_pose())
        self.checkpoint(checkpoint_name)


    # 기능: 활성 Point마다 #03~#05를 실행하고 측정·판정 수신 결과를 기록한다.
    #     recipe: 실행 순서와 포인트별 조건을 담은 Inspection Recipe.
    def inspect_points(self, recipe):
        inspection = InspectionSequence(self.backend, submit_judgment=self.submit_judgment,
                                        run_id=self.run_id, checkpoint=self.checkpoint)
        inspection.recipe = recipe
        for point_id in self.context.enabled_point_ids:
            self.checkpoint("POINT_START")
            point = recipe.points[point_id]
            self.context.point_runtime[point_id] = PointRuntime(point_id, motion_status=SequenceStatus.RUNNING)
            try:
                result = inspection.run_point(point)
            except JobStopped:
                raise
            except Exception as error:
                self._abort_motion()
                self.context.point_runtime[point_id].motion_status = SequenceStatus.INCOMPLETE
                self.record_point_error(point, recipe, error)
                raise
            self.motion_results[point_id] = result
            runtime = self.context.point_runtime[point_id]
            runtime.motion_status = SequenceStatus.SUCCESS
            runtime.adaptive_grip_status = SequenceStatus.SUCCESS
            runtime.pull_status = SequenceStatus.SUCCESS
            runtime.peak_pull_force = result.peak_pull_force_n
            runtime.pull_displacement = result.pull_displacement_mm
            runtime.termination_reason = result.termination_reason
            self.context.current_point_index += 1
            self.collect_results()
            self.save("inspection_results.json", {key: asdict(value) for key, value in self.motion_results.items()})


    # 기능: #07 완료를 확인한다. 미완료면 Pause 후 RESUME에서 재확인한다.
    #
    #     ------------------------------------------------------------
    #     반환: 모든 활성 Point의 완료 상태와 집계를 담은 SequenceResult.
    def wait_for_completion(self):
        while True:
            finish = self.work_finish()
            if finish.success:
                break
            self.notify("WARN", f"WORK_FINISH_NOT_COMPLETE: {finish.data}")
            self.pause_requested.set()
            self.checkpoint("WORK_FINISH_RETRY")  # RESUME 후 재확인, STOP이면 종료
        return finish


    # 기능: 최종 Home 도달 후 성공 상태를 기록하고 다음 START 대기로 전환한다.
    #
    #     ------------------------------------------------------------
    #     반환: Job 완료와 결과 집계를 담은 SequenceResult.
    def complete_job(self):
        self.context.state = SequenceStatus.SUCCESS
        self.save("status.json", {"completed": True, "state": "SYSTEM_READY", "run_id": self.run_id})
        self.context = None
        self.state = SystemState.SYSTEM_READY
        return SequenceResult(True, "JOB_COMPLETE", "Home 도달 후 대기합니다.", self.last_summary)


    # 기능: 정지 요청을 처리하고 상태를 기록한 뒤 재개 Context를 폐기한다.
    #     error: 작업 중 발생한 예외. 중단 사유와 결과 기록에 사용한다.
    #
    #     ------------------------------------------------------------
    #     반환: STOP 또는 COMM_ERROR를 담은 SequenceResult.
    def stop_job(self, error):
        self._abort_motion()
        self.state = SystemState.STOPPED if self.stop_reason == "STOP" else SystemState.ERROR
        self.last_error = str(error)
        self.save("status.json", {"completed": False, "state": self.state.value,
            "error": self.last_error, "phase": self.backend.phase,
            "context": asdict(self.context) if self.context else None})
        self.context = None  # STOP은 Resume 불가. 기록만 보존한다.
        return SequenceResult(False, self.stop_reason, self.last_error)


    # 기능: 초기화/모션 오류를 기록하고 해당 단계에 맞는 종료 상태로 전환한다.
    #     error: 작업 중 발생한 예외. 중단 사유와 결과 기록에 사용한다.
    #     motion_started: 모션 시작 여부. 실패 시 정지 요청과 종료 상태를 결정한다.
    #
    #     ------------------------------------------------------------
    #     반환: INIT_FAIL 또는 JOB_ERROR를 담은 SequenceResult.
    def fail_job(self, error, motion_started):
        if motion_started:
            self._abort_motion()
        self.last_error = f"{type(error).__name__}: {error}"
        self.state = SystemState.ERROR if motion_started else SystemState.SYSTEM_READY
        self.save("status.json", {"completed": False, "state": self.state.value,
            "error": self.last_error, "phase": self.backend.phase,
            "context": asdict(self.context) if self.context else None})
        self.context = None
        return SequenceResult(False, "JOB_ERROR" if motion_started else "INIT_FAIL", self.last_error)


    # 기능: 판정 기록을 저장하고 이번 Job의 클라이언트·스트림을 정리한다.
    #     stream: 현재 Job의 samples.jsonl 기록 스트림.
    #     previous_stream: Job 시작 전 장비에 연결되어 있던 기록 스트림.
    def close_recording(self, stream, previous_stream):
        try:
            self.save("judgment_results.json", self.judgment.results)
        finally:
            self.judgment.close()
            stream.close()
            self.backend.stream = previous_stream


    # 기능: 현재 지역 시간과 시간대를 읽는다.
    #
    #     ------------------------------------------------------------
    #     반환: 시간대가 포함된 datetime.
    @staticmethod
    def now():
        return datetime.now().astimezone()


    # 기능: 실행 폴더에 JSON을 임시 파일로 쓴 뒤 교체한다.
    #     name: 실행 폴더 안에 저장할 JSON 파일 이름.
    #     data: JSON으로 기록할 데이터.
    def save(self, name, data):
        self.output.mkdir(parents=True, exist_ok=True)
        target = self.output / name
        temporary = target.with_suffix(target.suffix + ".tmp")
        temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
        temporary.replace(target)


    # 기능: STOP/통신 만료를 확인하고 장비 노드의 수신 처리를 한 번 수행한다.
    def pump(self):
        self.poll_control()
        rclpy.spin_once(self.backend.node, timeout_sec=0.05)


    # 기능: 서비스 대기 중에도 STOP과 통신 복구시간 만료를 감시한다. 요청 시 JobStopped를 발생시킨다.
    def poll_control(self):
        if self.comm_lost_at is not None:
            limit = (self.backend.system or {}).get("communication_recovery_timeout_s", 30.0)
            if time.monotonic() - self.comm_lost_at >= limit:
                self.stop_reason = "COMM_ERROR"
                self.stop_requested.set()
        if self.stop_requested.is_set():
            raise JobStopped(self.stop_reason)


    # 기능: 완료점을 기록하고 Pause 시 대기한다. 재개 후 장비 상태를 재확인한다.
    #     step: 현재 동작이 끝난 완료점 이름. 재개 위치로 기록한다.
    def checkpoint(self, step):
        self.poll_control()
        if self.context is not None:
            self.context.resume_point = step
            self.context.current_sequence = step
        was_paused = self.pause_requested.is_set()
        if was_paused:
            self.state = SystemState.PAUSED
            self.notify("INFO", f"PAUSED: {step}")
        while self.pause_requested.is_set():
            self.pump()
            self.collect_results()
        self.poll_control()
        if was_paused:
            self._require(self.backend.check_robot_operability())
        if self.context is not None or self.state == SystemState.PAUSED:
            self.state = SystemState.RUNNING


    # 기능: 현재 원자 동작의 완료점에서 일시정지하도록 요청한다.
    #
    #     ------------------------------------------------------------
    #     반환: 요청 수락 여부를 담은 SequenceResult.
    def pause(self):
        if self.state not in {SystemState.RUNNING, SystemState.PAUSE_REQUEST}:
            return SequenceResult(False, "PAUSE_NOT_ALLOWED", "RUNNING 상태가 아닙니다.")
        self.pause_requested.set()
        self.state = SystemState.PAUSE_REQUEST
        return SequenceResult(True, "PAUSE_REQUESTED", "현재 원자 동작 완료점에서 일시정지합니다.")


    # 기능: 통신이 복구된 PAUSED 상태에서 보존된 위치의 실행을 재개한다.
    #
    #     ------------------------------------------------------------
    #     반환: 재개 요청 수락 여부를 담은 SequenceResult.
    def resume(self):
        if (self.state != SystemState.PAUSED or self.comm_lost_at is not None
                or not self.backend.hmi_available()):
            return SequenceResult(False, "RESUME_NOT_ALLOWED", "PAUSED 및 통신 복구 상태가 필요합니다.")
        self.pause_requested.clear()
        return SequenceResult(True, "RESUME_ACCEPTED", "보존된 Resume Point에서 계속합니다.")


    # 기능: 진행 중인 Job에 정지를 요청한다. 자동 Home 복귀는 요청하지 않는다.
    #
    #     ------------------------------------------------------------
    #     반환: 정지 요청 접수를 나타내는 SequenceResult.
    def stop(self):
        self.stop_reason = "STOP"
        self.stop_requested.set()
        return SequenceResult(True, "STOP_REQUESTED", "정지 요청. 자동 Home Return은 없습니다.")


    # 기능: 실행 중 통신 유실 시 복구 대기를 시작하고 Pause를 요청한다.
    def communication_lost(self):
        if self.state in {SystemState.RUNNING, SystemState.PAUSE_REQUEST, SystemState.PAUSED}:
            if self.comm_lost_at is None:
                self.comm_lost_at = time.monotonic()
            self.pause_requested.set()
            if self.state != SystemState.PAUSED:
                self.state = SystemState.PAUSE_REQUEST


    # 기능: 통신 복구 시각 상태를 해제한다. 재개에는 별도 RESUME이 필요하다.
    def communication_recovered(self):
        self.comm_lost_at = None  # Pause Event는 유지한다. 명시적인 RESUME만 해제한다.


    # 기능: 단계 실패를 예외로 전달해 이후 동작을 차단한다.
    #     result: 성공 여부, 사유 코드, 부가 정보를 담은 SequenceResult.
    #
    #     ------------------------------------------------------------
    #     반환: 성공한 입력 SequenceResult. 실패하면 RuntimeError.
    def _require(self, result):
        if not result.success:
            raise RuntimeError(f"{result.code}: {result.message}")
        return result


    # 기능: 포인트를 판정 대기 목록에 넣고 #06으로 요청한다.
    #     request: 포인트 식별자와 측정·판정 조건을 담은 JudgmentRequest.
    def submit_judgment(self, request):
        self.context.pending_judgments.add(request.point_id)
        self.judgment.submit(request)


    # 기능: 수신된 판정을 Job/Point 결과에 반영하고 결과 파일을 저장한다.
    def collect_results(self):
        if self.context is None or self.judgment is None:
            return
        for point_id, result in list(self.judgment.results.items()):
            runtime = self.context.point_runtime.get(point_id)
            if runtime is None:
                continue
            runtime.result = InspectionResult(result["result"])
            runtime.judgment_status = JudgmentStatus(result["judgment_status"])
            runtime.reason = result["reason"]
            self.context.pending_judgments.discard(point_id)
            if point_id in self.motion_results:
                self.motion_results[point_id] = replace(self.motion_results[point_id],
                    result=runtime.result, judgment_status=runtime.judgment_status,
                    sequence_status=SequenceStatus(result["sequence_status"]), reason=runtime.reason)
        self.save("judgment_results.json", self.judgment.results)
        self.save("inspection_results.json", {key: asdict(value) for key, value in self.motion_results.items()})
        self.backend.stream.flush()
        for point_id in self.judgment.results:
            if point_id in self.motion_results:
                self.context.point_runtime[point_id].log_saved = True


    # 기능: 포인트 모션 오류를 SYSTEM_ERROR 결과와 오류 파일로 남긴다.
    #     point: 현재 검사포인트 레시피. Pose(mm/deg), Grip 폭(mm)·힘(N), 이동 조건을 담는다.
    #     recipe: 실행 순서와 포인트별 조건을 담은 Inspection Recipe.
    #     error: 작업 중 발생한 예외. 중단 사유와 결과 기록에 사용한다.
    def record_point_error(self, point, recipe, error):
        # 정상 Pull 요청이 먼저 도착했어도 복귀 실패가 나면 SYSTEM_ERROR가 최종값이다.
        request = JudgmentRequest(
            run_id=self.run_id, recipe_id=recipe.recipe_id, recipe_version=recipe.recipe_version,
            point_id=point.point_id, point_name=point.point_name, connector_type=recipe.connector_type,
            peak_pull_force_n=0.0, pull_displacement_mm=0.0,
            termination_reason=PullTermination.MOTION_ERROR,
            required_force_n=point.pull_setting["force_limit_n"],
            normal_displacement_limit_mm=point.pull_setting["normal_displacement_limit_mm"],
            entry_task=point.entry_pose.task, entry_joint=point.entry_pose.joint,
            error_reason=f"{type(error).__name__}: {error}",
        )
        from cable_inspection.sequence.judgment_node import InspectionJudgmentNode, judge_pull
        result = InspectionJudgmentNode._result_message(request, judge_pull(
            termination=PullTermination.MOTION_ERROR, peak_force_n=0.0,
            displacement_mm=0.0, required_force_n=request.required_force_n))
        self.judgment.record_error(result)
        self.save("point_error.json", {"point_id": point.point_id, "reason": request.error_reason})


    # 기능: 로봇에 정지를 요청하고 정지 확인 실패는 로그로 남긴다.
    def _abort_motion(self):
        try:
            self.backend.request_motion_stop()
        except Exception as error:
            self.notify("ERROR", f"정지 확인 실패: {error}")


    # 기능: 대기/정지/오류 상태에서 사용자가 요청한 Home 복귀를 수행한다.
    #
    #     ------------------------------------------------------------
    #     반환: 복귀 성공 또는 거부/실패를 담은 SequenceResult.
    def request_home_return(self):
        if self.state not in {SystemState.SYSTEM_READY, SystemState.STOPPED, SystemState.ERROR}:
            return SequenceResult(False, "HOME_NOT_ALLOWED", "작업 실행 중에는 Home을 요청할 수 없습니다.")
        self.stop_requested.clear()
        self.pause_requested.clear()
        self.comm_lost_at = None
        self.state = SystemState.RUNNING
        try:
            self._require(self.backend.validate_system_recipe())
            result = self._require(self.home_return())
            self.context = None
            self.state = SystemState.SYSTEM_READY
            return result
        except Exception as error:
            self._abort_motion()
            self.last_error = str(error)
            self.state = SystemState.STOPPED if isinstance(error, JobStopped) else SystemState.ERROR
            return SequenceResult(False, "HOME_RETURN_FAILED", str(error))

    def work_initialize(self, recipe_id: str) -> SequenceResult:
        self.backend.phase = "SEQ_01_WORK_INITIALIZE"
        result = self.check_preconditions(recipe_id)
        if not result.success:
            return result

        enabled_points = self.backend.enabled_point_ids(recipe_id)
        if not enabled_points:
            return SequenceResult(
                False,
                "NO_ENABLED_POINT",
                "활성화된 검사포인트가 없습니다.",
            )

        rechecked = self.backend.check_robot_operability()
        if not rechecked.success:
            return rechecked

        return SequenceResult(
            True,
            "WORK_INITIALIZE_OK",
            "Work Initialize 조건을 모두 확인했습니다.",
            {"enabled_point_ids": enabled_points},
        )


    def check_preconditions(self, recipe_id):
        checks = (
            self.backend.check_robot_operability,
            self.backend.check_hmi_communication,
            self.backend.validate_system_recipe,
            lambda: self.backend.validate_inspection_recipe(recipe_id),
        )
        for check in checks:
            result = check()
            if not result.success:
                return result
        return result


    def home_return(self) -> SequenceResult:
        self.backend.phase = "SEQ_02_HOME_RETURN"
        operability = self.backend.check_robot_operability()
        if not operability.success:
            return operability

        tcp = self.backend.current_tcp()
        if len(tcp) < 3:
            return SequenceResult(False, "INVALID_TCP", "현재 TCP 값이 잘못되었습니다.")

        if self.backend.tcp_is_in_work_area(tcp):
            result = self.return_from_work_area()
            route = "WORK_ACCESS_HOME"
        else:
            result = self.return_from_outside()
            route = "SAFE_ROUTE_HOME"
        if not result.success:
            return result

        return SequenceResult(
            True,
            "HOME_RETURN_OK",
            "Home Return을 완료했습니다.",
            {"route": route, "start_tcp": tcp[:6]},
        )


    def return_from_work_area(self):
        result = self.backend.move_work_access_safe_pose()
        if not result.success:
            return result
        self.checkpoint("WORK_ACCESS_REACHED")
        return self.return_from_outside()


    def return_from_outside(self):
        result = self.backend.move_home_pose()
        if result.success:
            self.checkpoint("HOME_REACHED")
        return result


    def work_finish(self):
        controller = self
        controller.backend.phase = "SEQ_07_WORK_FINISH"
        context = controller.context
        context.current_sequence = "WORK_FINISH"
        deadline = time.monotonic() + controller.backend.system["judgment_timeout_s"]
        while True:
            controller.checkpoint("WORK_FINISH_WAIT")
            controller.collect_results()
            result = check_work_completion(context)
            if result.success:
                communication = controller.backend.check_hmi_communication()
                if not communication.success:
                    controller.communication_lost()
                    continue
                self.save_summary(result)
                return result
            if time.monotonic() >= deadline:
                controller.save("job_summary.json", {**result.data, "job_status": "NOT_COMPLETE"})
                return result
            controller.pump()


    def save_summary(self, result):
        controller = self
        context = controller.context
        context.end_time = controller.now()
        summary = {**result.data, "job_id": context.job_id, "recipe_id": context.recipe_id,
                   "point_total": len(context.enabled_point_ids),
                   "start_time": context.start_time.isoformat(),
                   "end_time": context.end_time.isoformat(), "job_status": "INSPECTION_COMPLETE"}
        controller.save("job_summary.json", summary)
        controller.notify("INFO", f"JOB_COMPLETE: {summary['counts']}")


class InspectionSequence:
    """Inspection Recipe 순서대로 각 검사포인트의 전체 Cycle을 수행한다."""

    # 기능: 검사 단계 객체와 포인트 선택·판정 요청 함수를 준비한다.
    #     hardware: 그리퍼 명령, 이동, 실측값 조회를 제공하는 장비 객체.
    #     should_run_point: (현재 순번, 전체 개수, point)를 받아 검사 여부를 반환하는 함수.
    #     submit_judgment: JudgmentRequest를 받아 #06에 비동기 판정을 요청하는 함수.
    #     run_id: 측정과 판정 결과를 연결하는 실행 식별자.
    #     checkpoint: 완료점 이름을 받아 Pause/STOP을 처리하는 함수. 생략하면 처리하지 않는다.
    def __init__(
        self,
        hardware,
        should_run_point=lambda _index, _total, _point: True,
        submit_judgment=lambda _request: None,
        run_id=0,
        checkpoint=lambda _step: None,
    ):
        self.hardware = hardware
        self.should_run_point = should_run_point
        self.submit_judgment = submit_judgment
        self.run_id = run_id
        self.recipe = None
        self.checkpoint = checkpoint


    # 기능: 레시피 순서로 활성 포인트를 선택하여 검사한다. 오류 시 정지·오류 판정을 요청한다.
    #     recipe: 실행 순서와 포인트별 조건을 담은 Inspection Recipe.
    #
    #     ------------------------------------------------------------
    #     반환: point_id별 InspectionPointResult를 담은 dict.
    def run(self, recipe):
        self.recipe = recipe
        points = [
            recipe.points[point_id]
            for point_id in recipe.execution_order
            if recipe.points[point_id].enabled
        ]
        results = {}
        for index, point in enumerate(points, start=1):
            if self.should_run_point(index, len(points), point):
                try:
                    results[point.point_id] = self.run_point(point)
                except Exception as error:
                    self.handle_point_error(point, error)
                    raise
        return results


    # 기능: 한 Point에서 #03 접근 → #04 파지 → #05 Pull/복귀를 수행한다.
    #     point: 현재 검사포인트 레시피. Pose(mm/deg), Grip 폭(mm)·힘(N), 이동 조건을 담는다.
    #
    #     ------------------------------------------------------------
    #     반환: 측정과 단계별 결과를 담은 InspectionPointResult. 판정은 비동기로 처리한다.
    def run_point(self, point):
        self.hardware.configure_point(point)

        # #03 접근 → #04 파지 → #05 Pull/복귀. 측정 직후 #06을 비동기로 요청한다.
        transition = self.point_transition(point)
        adaptive = self.adaptive_grip(point)
        pull = self.pull_inspection(
            point, on_measured=lambda data: self.submit_pull_result(point, adaptive, data),
        )
        return self.make_point_result(point, transition, adaptive, pull)


    # 기능: Pull 정지 직후 폭 차이를 계산해 #06 판정을 요청한다. 복귀와 병행한다.
    #     point: 현재 검사포인트 레시피. Pose(mm/deg), Grip 폭(mm)·힘(N), 이동 조건을 담는다.
    #     adaptive: Soft 기준 폭과 추가진입·Hard Grip 결과를 담은 AdaptiveGripResult.
    #     pull_data: Pull 종료 사유, 최대 힘(N), 실제 변위(mm), 최소 폭(mm)을 담은 dict.
    def submit_pull_result(self, point, adaptive, pull_data):
        pull_data["width_delta_mm"] = pull_data["pull_width_mm"] - adaptive.soft_width_mm
        termination = self._pull_termination(pull_data["stop_reason"])
        self.submit_judgment(JudgmentRequest(
            run_id=self.run_id,
            recipe_id=self.recipe.recipe_id,
            recipe_version=self.recipe.recipe_version,
            point_id=point.point_id,
            point_name=point.point_name,
            soft_width_mm=adaptive.soft_width_mm,
            pull_width_mm=pull_data["pull_width_mm"],
            connector_type=self.recipe.connector_type,
            peak_pull_force_n=float(pull_data["peak_pull_force_n"]),
            pull_displacement_mm=float(pull_data["pull_displacement_mm"]),
            termination_reason=termination,
            required_force_n=point.pull_setting["force_limit_n"],
            normal_displacement_limit_mm=(
                point.pull_setting["normal_displacement_limit_mm"]
            ),
            entry_task=point.entry_pose.task,
            entry_joint=point.entry_pose.joint,
        ))


    # 기능: 장비 종료 문자열을 시퀀스의 Pull 종료 Enum으로 변환한다.
    #     stop_reason: 장비가 반환한 Pull 종료 사유 문자열.
    #
    #     ------------------------------------------------------------
    #     반환: PullTermination. 미등록 종료 사유는 MOTION_ERROR.
    @staticmethod
    def _pull_termination(stop_reason):
        mapping = {
            "PULL_FORCE_LIMIT": PullTermination.FORCE_LIMIT,
            "PULL_MAX_DISTANCE": PullTermination.MAX_DISTANCE,
            "PULL_TIMEOUT": PullTermination.TIMEOUT,
        }
        return mapping.get(stop_reason, PullTermination.MOTION_ERROR)


    # 기능: 검사 모션을 중단하고 포인트 식별자와 오류 사유를 #06에 전달한다.
    #     point: 현재 검사포인트 레시피. Pose(mm/deg), Grip 폭(mm)·힘(N), 이동 조건을 담는다.
    #     error: 작업 중 발생한 예외. 중단 사유와 결과 기록에 사용한다.
    def handle_point_error(self, point, error):
        recipe = self.recipe
        # 하드웨어 오류에서는 후속 모션을 하지 않고 SYSTEM_ERROR를 전달한다.
        self.hardware.safe_abort()
        self.submit_judgment(JudgmentRequest(
            run_id=self.run_id, recipe_id=recipe.recipe_id,
            recipe_version=recipe.recipe_version, point_id=point.point_id,
            point_name=point.point_name, connector_type=recipe.connector_type,
            peak_pull_force_n=0.0, pull_displacement_mm=0.0,
            termination_reason=(PullTermination.TIMEOUT
                if isinstance(error, TimeoutError) else
                PullTermination.INVALID_DATA if isinstance(error, (ValueError, KeyError, TypeError))
                else PullTermination.MOTION_ERROR),
            required_force_n=point.pull_setting["force_limit_n"],
            normal_displacement_limit_mm=point.pull_setting["normal_displacement_limit_mm"],
            entry_task=point.entry_pose.task, entry_joint=point.entry_pose.joint,
            error_reason=f"{type(error).__name__}: {error}",
        ))


    # 기능: 접근·파지·Pull 결과를 한 Point 결과 객체로 묶는다.
    #     point: 현재 검사포인트 레시피. Pose(mm/deg), Grip 폭(mm)·힘(N), 이동 조건을 담는다.
    #     transition: #03의 그리퍼 개방 및 Ready/Entry 접근 결과.
    #     adaptive: Soft 기준 폭과 추가진입·Hard Grip 결과를 담은 AdaptiveGripResult.
    #     pull: #05의 Pull 측정, 그리퍼 개방, Entry/Ready 복귀 결과.
    #
    #     ------------------------------------------------------------
    #     반환: 판정 대기 상태의 InspectionPointResult.
    def make_point_result(self, point, transition, adaptive, pull):
        pull_data = pull["pull"]
        termination = self._pull_termination(pull_data["stop_reason"])
        return InspectionPointResult(
            point_id=point.point_id,
            transition=transition,
            adaptive_grip=adaptive,
            pull_inspection=pull,
            entry_displacement_mm=adaptive.entry.get("entry_displacement_mm"),
            peak_pull_force_n=float(pull_data["peak_pull_force_n"]),
            pull_displacement_mm=float(pull_data["pull_displacement_mm"]),
            termination_reason=termination,
            judgment_status=JudgmentStatus.PENDING,
            sequence_status=SequenceStatus.SUCCESS,
            result=None,
            reason="판정 요청을 등록했습니다.",
        )

    def point_transition(self, point):
        self.hardware.phase = "SEQ_03_POINT_TRANSITION"
        opened = self.open_gripper(point)
        ready = self.move_ready(point)
        entry = self.move_entry(point)
        return {"soft_open": opened, "ready": ready, "entry": entry}


    def open_gripper(self, point):
        return self.hardware.grip(
            point.grip_setting["soft_open_width_mm"],
            point.grip_setting["soft_force_n"],
            opening=True,
        )


    def move_ready(self, point):
        ready = self.hardware.move_joint(point.ready_pose)
        self.checkpoint("READY_REACHED")
        return ready


    def move_entry(self, point):
        entry = self.hardware.move_joint(point.entry_pose, allow_incomplete=True)
        self.checkpoint("ENTRY_REACHED")
        return entry


    def adaptive_grip(self, point):
        self.hardware.phase = "SEQ_04_ADAPTIVE_GRIP"

        # Soft Grip → 추가진입 → 기준 폭 측정 → Hard Grip 순서로 진행한다.
        self.soft_grip(point)
        entry = self.hardware.relative(
            point.normalized_entry_direction(),  # Entry ABC에서 계산한 Tool +Z의 BASE 방향.
            point.entry_setting["max_distance_mm"],
            entry_guard=True,  # 진입 힘 상한을 감시하고 도달하면 추가진입을 멈춘다.
        )
        # Soft 단계 종료 시점의 실제 폭. Hard 명령을 보내기 전에 확보한다.
        soft = self.hardware.wait_gripper_idle()
        hard = self.hard_grip(point)
        self.checkpoint("HARD_GRIP_DONE")
        return AdaptiveGripResult(
            entry=entry,
            hard_grip=hard,
            soft_width_mm=soft["width_mm"],
        )


    def soft_grip(self, point):
        return self.hardware.grip(
            point.grip_setting["soft_close_width_mm"],
            point.grip_setting["soft_force_n"],
        )


    def hard_grip(self, point):
        return self.hardware.grip(
            point.grip_setting["hard_width_mm"],
            point.grip_setting["hard_force_n"],
            wait_for_completion=True,  # Hard Grip 완료 확인 후 Pull 단계로 넘어간다.
        )


    def pull_inspection(self, point, on_measured=None):
        self.hardware.phase = "SEQ_05_PULL_INSPECTION"
        pull = self.pull(point)
        if on_measured is not None:
            on_measured(pull)  # 정지 직후 판정 요청. 해제/복귀와 병행한다.
        opened = self.open_gripper(point)
        entry = self.return_entry(point)
        ready = self.return_ready(point)
        return {"pull": pull, "soft_open": opened,
                "return_entry": entry, "return_ready": ready}


    def pull(self, point):
        # Entry ABC에서 구한 체결 방향의 반대로 당긴다.
        pull_direction = [-value for value in point.normalized_entry_direction()]
        return self.hardware.relative(
            pull_direction,
            point.pull_setting["max_distance_mm"],
            pull_guard=True,
        )


    def return_entry(self, point):
        return self.hardware.move_linear(point.entry_pose.task)


    def return_ready(self, point):
        ready = self.hardware.move_joint(point.ready_pose)
        self.checkpoint("POINT_READY_RETURNED")
        return ready


def check_work_completion(context):
    missing = []
    counts = {result.value: 0 for result in InspectionResult}
    for point_id in context.enabled_point_ids:
        point = context.point_runtime.get(point_id)
        if (point is None or point.motion_status != SequenceStatus.SUCCESS
                or point.result not in set(InspectionResult) or not point.log_saved):
            missing.append(point_id)
        else:
            counts[point.result] += 1
    complete = (context.current_point_index == len(context.enabled_point_ids)
                and not context.pending_judgments and not missing)
    return SequenceResult(complete, "WORK_FINISH_SUCCESS" if complete else "WORK_FINISH_NOT_COMPLETE",
                          "완료" if complete else "모션·판정·로그 완료 대기",
                          {"counts": counts, "missing_points": missing,
                           "pending_points": sorted(context.pending_judgments)})


# 기능: 명령행 설정을 읽어 장비·Job 제어·명령 수신 노드를 만들고 START를 기다린다.
#     argv: 명령행 인자 목록. None이면 실행 시 전달된 인자를 읽는다.
def main(argv=None):
    share = Path(get_package_share_directory("cable_inspection"))
    parser = argparse.ArgumentParser(description="CCCIS 전체 Job 실행")
    parser.add_argument("--system-recipe", type=Path, default=share / "config/system_recipe.json")
    parser.add_argument("--recipe", type=Path, action="append",
                        help="등록할 Inspection Recipe. 여러 번 지정할 수 있습니다.")
    parser.add_argument("--results-dir", type=Path, default=Path("results/inspection_sequence"))
    parser.add_argument("--robot-mode", choices=("real", "virtual"), default="real")
    parser.add_argument("--control-mode", choices=("hmi", "terminal"), default="hmi")
    # ros2 launch가 붙이는 --ros-args는 argparse에 넘기지 않는다.
    cli_args = remove_ros_args() if argv is None else remove_ros_args(args=["main_sequence", *argv])
    args = parser.parse_args(cli_args[1:])
    paths = args.recipe or ([] if args.control_mode == "hmi" else [share / "recipe/inspection/rcp_BMW_LWR_01.json"])
    recipes = {}
    for path in paths:
        raw = json.loads(path.read_text(encoding="utf-8"))
        if raw["recipe_id"] in recipes:
            raise ValueError(f"중복 Recipe ID: {raw['recipe_id']}")
        recipes[raw["recipe_id"]] = path
    # 좌표 미입력 상태에서도 노드는 실행된다. START의 Initialize가 상세 사유를 반환한다.
    system = json.loads(args.system_recipe.read_text(encoding="utf-8"))
    # Ctrl+C 때 통신부터 닫히지 않게 하고, Worker 정지 요청을 먼저 마친다.
    shutdown_requested = threading.Event()
    previous_signals = {sig: signal.getsignal(sig) for sig in (signal.SIGINT, signal.SIGTERM)}
    for sig in previous_signals:
        signal.signal(sig, lambda *_: shutdown_requested.set())
    rclpy.init(args=argv, signal_handler_options=SignalHandlerOptions.NO)
    robot = SequenceRobot(args.system_recipe, recipes, io.StringIO(), mode=args.robot_mode)
    node = MainSequenceNode(robot, args.results_dir, heartbeat_timeout_s=system["heartbeat_timeout_s"],
                        control_mode=args.control_mode)
    executor = SingleThreadedExecutor(context=node.context)
    executor.add_node(node)  # 장비 노드는 Worker에서만 spin한다.
    print(f"Main Work 대기 중 [{args.control_mode}]. START 전에는 검사 모션을 시작하지 않습니다.", flush=True)
    if args.control_mode == "terminal":
        print("별도 터미널: ros2 run cable_inspection sequence_console", flush=True)
    try:
        while rclpy.ok() and not shutdown_requested.is_set():
            executor.spin_once(timeout_sec=0.1)
    except KeyboardInterrupt:
        pass
    finally:
        node.close()
        executor.shutdown()
        node.destroy_node()
        robot.close()
        rclpy.try_shutdown()
        for sig, handler in previous_signals.items():
            signal.signal(sig, handler)


if __name__ == "__main__":
    main()
