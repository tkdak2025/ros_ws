"""Job 상태, 단일 모션 실행, 기록과 완료 판정을 담당한다."""

import copy
import json
import threading
import time
import weakref
from dataclasses import asdict
from datetime import datetime
from pathlib import Path

from cable_inspection.sequence.main.data_models.system_state import SystemState
from cable_inspection.sequence.main.data_models.job_context import JobContext
from cable_inspection.sequence.common.data_models.sequence_result import SequenceResult
from cable_inspection.sequence.common.data_models.sequence_status import SequenceStatus
from cable_inspection.sequence.inspection.seq_inspection import InspectionSequence
from cable_inspection.sequence.home_return.seq_home_return import HomeReturnSequence
from cable_inspection.sequence import JobStopped
from cable_inspection.recipe.recipe import Recipe, RobotPose



class MainSequence:
    """#00·#01·#07과 작업 제어를 소유하고 Inspection·Home Return을 순서대로 실행한다."""



    # 기능: Job 제어 상태와 기록 경로를 준비한다.
    def __init__(self, backend, results_dir="results/inspection_sequence",
                 home_return_sequence=HomeReturnSequence, inspection=None, recipes=None):
        self.backend = backend
        self.recipes = recipes if recipes is not None else Recipe()
        self.system = None
        self.hmi_available = lambda: False
        self.home_return_sequence = home_return_sequence
        self.inspection = inspection if inspection is not None else InspectionSequence(backend)
        self.inspection.on_pending = self.recipes.mark_pending
        self.results_dir = Path(results_dir)
        self.state = SystemState.SYSTEM_READY
        self.context = None
        self.last_error = ""
        self.last_summary = {}
        self.run_id = 0
        self.snapshot_notify = lambda run_id, recipe: None
        self.output = None
        self.pause_requested = threading.Event()
        self.stop_requested = threading.Event()
        self.comm_lost_at = None
        self.stop_reason = "STOP"
        self.notify = lambda level, text: print(f"[{level}] {text}", flush=True)
        controller_ref = weakref.ref(self)



        # 기능: Main 수명 안에서만 장비 대기의 STOP·통신 만료 감시를 실행한다.
        def poll_control():
            controller = controller_ref()

            if controller is None:
                raise RuntimeError("Job Controller가 종료되어 장비 명령을 중단합니다.")

            controller.poll_control()



        # 기능: Inspection 완료점은 Main의 Pause/STOP 정책으로 처리한다.
        def checkpoint(step):
            controller = controller_ref()

            if controller is None:
                raise RuntimeError("Main 시퀀스가 종료되었습니다.")

            controller.checkpoint(step)



        self.inspection.checkpoint = checkpoint
        self.backend.control_poll = poll_control



    # 기능: 두 장비의 준비 순서를 관리한다. 각 장비는 자신의 최초 초기화 여부를 소유한다.
    def check_devices(self):
        robot, gripper = self.backend.robot, self.backend.gripper

        if robot.mode != gripper.mode:
            raise ValueError("Robot과 GripperTool의 운전 모드가 다릅니다.")

        robot.check_ready()
        gripper.check_ready()
        robot.initialize(self.backend.config)
        gripper.initialize()
        robot.check_operability(self.backend.config)
        self.backend.sample()
        return SequenceResult(True, "ROBOT_OPERABLE", "ROBOT_OPERABLE")



    # 기능: Main의 제어 연결이 유효한지 확인한다.
    def check_hmi_communication(self):
        if not self.hmi_available():
            return SequenceResult(False, "HMI_COMM_LOST", "HMI Heartbeat가 없습니다.")

        return SequenceResult(True, "HMI_CONNECTED", "HMI_CONNECTED")



    # 기능: 시스템 레시피를 검증하고 공통 관절 속도를 적용한다.
    def validate_system_recipe(self):
        self.system = self.recipes.system_recipe()
        self.backend.config.joint_speed_deg_s = self.system["joint_speed_deg_s"]

        return SequenceResult(True, "SYSTEM_RECIPE_VALID", "SYSTEM_RECIPE_VALID")



    # 기능: Recipe가 선택한 검사 배열을 이번 실행에 고정하도록 요청한다.
    def validate_inspection_recipe(self, recipe_id):
        self.recipes.begin(recipe_id, self.run_id)
        return SequenceResult(True, "INSPECTION_RECIPE_VALID", "INSPECTION_RECIPE_VALID")



    # 기능: 장비 운전 가능 상태를 확인한 뒤 현재 위치에 맞는 #02 복귀 절차를 호출한다.
    #     인자: 없음. 연결된 장비와 검증된 시스템 설정을 사용한다.
    #     반환: 장비 준비 실패 또는 Home Return의 SequenceResult.
    def home_return(self):
        ready = self.check_devices()

        if not ready.success:
            return ready

        return self.home_return_sequence(
            self.backend, checkpoint=self.checkpoint, poll_control=self.poll_control, system=self.system,
        ).run()



    # 기능: 별도 Home 명령의 허용 상태와 실패 처리를 담당한다.
    def request_home_return(self):
        if self.state not in {SystemState.SYSTEM_READY, SystemState.STOPPED, SystemState.ERROR}:
            return SequenceResult(False, "HOME_NOT_ALLOWED", "작업 실행 중에는 Home을 요청할 수 없습니다.")

        self.stop_requested.clear()
        self.pause_requested.clear()
        self.comm_lost_at = None
        self.state = SystemState.RUNNING

        try:
            self._require(self.validate_system_recipe())
            result = self._require(self.home_return())
            self.context = None
            self.state = SystemState.SYSTEM_READY

            return result

        except Exception as error:
            self._abort_motion()
            self.last_error = str(error)
            self.state = SystemState.STOPPED if isinstance(error, JobStopped) else SystemState.ERROR

            return SequenceResult(False, "HOME_RETURN_FAILED", str(error))



    # 기능: 초기화 → Work Access 준비 → 검사 → Work Access 복귀·완료 확인 후 대기한다.
    #     recipe_id: 실행할 검사 레시피 식별자.
    #     run_id: 외부 접수 실행 ID. None이면 새 ID를 생성한다.
    #     반환: Job 완료·중단·오류 정보를 담은 SequenceResult.
    def run(self, recipe_id, run_id=None):
        if self.state not in {SystemState.SYSTEM_READY, SystemState.STOPPED, SystemState.ERROR} or self.context is not None:
            return SequenceResult(False, "START_NOT_ALLOWED", "진행 중인 작업이 없는 대기·정지·오류 상태에서 시작할 수 있습니다.")

        stream, previous_stream = self.prepare_job(run_id)
        motion_started = False

        try:
            # #01 초기화 후 Work Access 도달을 확인해야 포인트 검사를 시작한다.
            self.initialize_job(recipe_id)
            motion_started = True
            self.prepare_work_access()

            # 활성 Point마다 #03 → #04 → #05 실행, #06은 비동기 판정
            self.inspect_points()

            # Work Access 복귀 → #07 결과 완료 확인 → 다음 START 대기
            self.move_work_access("WORK_ACCESS_FINISH")
            finish = self.wait_for_completion()
            self.last_summary = finish.data

            return self.complete_job()

        except JobStopped as error:
            return self.stop_job(error)

        except Exception as error:
            return self.fail_job(error, motion_started)

        finally:
            self.close_recording(stream, previous_stream)



    # 기능: 새 Job 상태와 측정 스트림을 준비하고 기존 판정 연결의 결과 목록을 초기화한다.
    def prepare_job(self, run_id=None):
        self.stop_requested.clear()
        self.pause_requested.clear()
        self.comm_lost_at = None
        self.last_error = ""
        self.last_summary = {}
        self.state = SystemState.RUNNING
        self.run_id = run_id if run_id is not None else time.time_ns() // 1000
        self.output = self.results_dir / self.now().strftime("%Y%m%d_%H%M%S_%f")
        self.output.mkdir(parents=True, exist_ok=False)
        stream = (self.output / "samples.jsonl").open("w", encoding="utf-8")
        previous_stream, self.backend.stream = self.backend.stream, stream
        self.inspection.begin(self.run_id)
        return stream, previous_stream



    # 기능: #01 및 판정 노드 준비를 확인하고 실행할 레시피 Snapshot을 고정한다.
    def initialize_job(self, recipe_id):
        initialized = self.work_initialize(recipe_id)
        self._require(initialized)
        recipe = self.recipes.snapshot()
        self.inspection.prepare(recipe["recipe_id"], recipe["recipe_version"],
                                recipe["connector_type"], self.poll_control)
        self.context = JobContext(
            recipe_id=recipe_id, job_id=str(self.run_id), start_time=self.now(),
            state=SequenceStatus.RUNNING,
        )
        self.save("inputs.json", {"recipe": recipe,
                                  "system_recipe": copy.deepcopy(self.system)})
        self.snapshot_notify(self.run_id, recipe)
        self.checkpoint("INITIALIZE_DONE")
        return recipe



    # 기능: 현재 위치에 맞춰 Work Access를 확보하고 검사 시작 조건을 확인한다.
    #     인자: 없음. 초기화에서 검증한 시스템 설정과 현재 장비 자세를 사용한다.
    #     반환: 없음. Open·Safe Escape·Access 도달 실패는 예외로 전달하여 검사를 막는다.
    def prepare_work_access(self):
        self.backend.phase = "WORK_ACCESS_PREPARE"
        route = self.home_return_sequence(
            self.backend, checkpoint=self.checkpoint, poll_control=self.poll_control, system=self.system)
        self.poll_control()
        tcp = route.current_tcp()
        RobotPose(task=tcp, joint=[0.0] * 6).validate("현재 TCP")

        # Access도 work_area 안에 있으므로 이미 도달했는지를 먼저 확인한다.
        if route.tcp_is_at_work_access(tcp):
            self.checkpoint("WORK_ACCESS_REACHED")
            return

        if route.tcp_is_in_work_area(tcp):
            self._require(route.escape_work_area())

        # Home 등 작업영역 밖에서는 Home을 경유하지 않고 Access로 이동한다.
        self.poll_control()
        self.backend.move_joint(RobotPose(**self.system["work_Access_safe_pose"]))

        if not route.tcp_is_at_work_access(route.current_tcp()):
            raise RuntimeError("검사 시작 전 Work Access 도달 확인 실패")

        self.checkpoint("WORK_ACCESS_REACHED")



    # 기능: 공통 Work Access Safe Pose로 이동하고 완료점을 확인한다.
    def move_work_access(self, checkpoint_name):
        self.backend.phase = "WORK_ACCESS"
        self.backend.move_joint(RobotPose(**self.system["work_Access_safe_pose"]))
        self.checkpoint(checkpoint_name)



    # 기능: 활성 Point마다 #03~#05를 실행하고 측정·판정 수신 결과를 기록한다.
    def inspect_points(self):
        while True:
            self.checkpoint("POINT_START")
            point = self.recipes.next_point()

            if point is None:
                break

            try:
                result = self.inspection.run_point(point)

            except JobStopped:
                raise

            except Exception as error:
                self._abort_motion()
                self.inspection.record_error(point, error)
                self.save("point_error.json", {"point_id": point["point_id"],
                          "reason": f"{type(error).__name__}: {error}"})
                self.collect_results()
                raise

            self.recipes.complete_point(self.run_id, result)

            if not result.adaptive_grip["adaptive_grip_done"]:
                self.notify("WARN", f"{point['point_id']}: {result.reason}; Open/복귀 완료, 다음 포인트 진행")

            self.collect_results()



    # 기능: #07 완료를 확인한다. 미완료면 Pause 후 RESUME에서 재확인한다.
    def wait_for_completion(self):
        while True:
            finish = self.work_finish()

            if finish.success:
                break

            self.notify("WARN", f"WORK_FINISH_NOT_COMPLETE: {finish.data}")
            self.pause_requested.set()
            self.checkpoint("WORK_FINISH_RETRY")  # RESUME 후 재확인, STOP이면 종료

        return finish



    # 기능: Work Access 복귀와 #07 완료 확인 후 성공 상태를 기록하고 대기한다.
    #     인자: 없음. 완료된 Job Context와 검사 요약을 사용한다.
    #     반환: Work Access 대기 상태와 검사 요약을 담은 SequenceResult.
    def complete_job(self):
        self.context.state = SequenceStatus.SUCCESS
        self.recipes.end(self.run_id)
        self.save("status.json", {"completed": True, "state": "SYSTEM_READY", "run_id": self.run_id})
        self.context = None
        self.state = SystemState.SYSTEM_READY

        return SequenceResult(True, "JOB_COMPLETE", "검사를 완료하고 Work Access에서 대기합니다.", self.last_summary)



    # 기능: 정지 요청을 처리하고 상태를 기록한 뒤 재개 Context를 폐기한다.
    def stop_job(self, error):
        self._abort_motion()
        self.recipes.end(self.run_id)
        self.state = SystemState.STOPPED if self.stop_reason == "STOP" else SystemState.ERROR
        self.last_error = str(error)
        self.save("status.json", {"completed": False, "state": self.state.value,
            "error": self.last_error, "phase": self.backend.phase,
            "context": asdict(self.context) if self.context else None,
            "recipe_progress": self.recipes.progress()})
        self.context = None  # STOP은 Resume 불가. 기록만 보존한다.

        return SequenceResult(False, self.stop_reason, self.last_error)



    # 기능: 초기화/모션 오류를 기록하고 해당 단계에 맞는 종료 상태로 전환한다.
    def fail_job(self, error, motion_started):
        if motion_started:
            self._abort_motion()

        self.recipes.end(self.run_id)
        self.last_error = f"{type(error).__name__}: {error}"
        self.state = SystemState.ERROR if motion_started else SystemState.SYSTEM_READY
        self.save("status.json", {"completed": False, "state": self.state.value,
            "error": self.last_error, "phase": self.backend.phase,
            "context": asdict(self.context) if self.context else None,
            "recipe_progress": self.recipes.progress()})
        self.context = None

        return SequenceResult(False, "JOB_ERROR" if motion_started else "INIT_FAIL", self.last_error)



    # 기능: 판정 기록과 계측 스트림을 정리한다. 판정 통신 연결은 다음 Job에도 유지한다.
    def close_recording(self, stream, previous_stream):
        try:
            self.save("judgment_results.json", self.inspection.results())

        finally:
            stream.close()
            self.backend.stream = previous_stream



    # 기능: 현재 지역 시간과 시간대를 읽는다.
    @staticmethod
    def now():
        return datetime.now().astimezone()



    # 기능: 실행 폴더에 JSON을 임시 파일로 쓴 뒤 교체한다.
    def save(self, name, data):
        self.output.mkdir(parents=True, exist_ok=True)
        target = self.output / name
        temporary = target.with_suffix(target.suffix + ".tmp")
        temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
        temporary.replace(target)



    # 기능: STOP/통신 만료를 확인하며 비동기 결과나 RESUME을 짧게 기다린다.
    def pump(self):
        self.poll_control()
        time.sleep(0.05)  # ROS 수신은 실행 노드의 Executor가 처리한다.



    # 기능: 서비스 대기 중에도 STOP과 통신 복구시간 만료를 감시한다. 요청 시 JobStopped를 발생시킨다.
    def poll_control(self):
        if self.comm_lost_at is not None:
            limit = (self.system or {}).get("communication_recovery_timeout_s", 30.0)

            if time.monotonic() - self.comm_lost_at >= limit:
                self.stop_reason = "COMM_ERROR"
                self.stop_requested.set()

        if self.stop_requested.is_set():
            raise JobStopped(self.stop_reason)



    # 기능: 완료점을 기록하고 Pause 시 대기한다. 재개 후 장비 상태를 재확인한다.
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
            self._require(self.check_devices())

        if self.context is not None or self.state == SystemState.PAUSED:
            self.state = SystemState.RUNNING



    # 기능: 현재 원자 동작의 완료점에서 일시정지하도록 요청한다.
    def pause(self):
        if self.state not in {SystemState.RUNNING, SystemState.PAUSE_REQUEST}:
            return SequenceResult(False, "PAUSE_NOT_ALLOWED", "RUNNING 상태가 아닙니다.")

        self.pause_requested.set()
        self.state = SystemState.PAUSE_REQUEST

        return SequenceResult(True, "PAUSE_REQUESTED", "현재 원자 동작 완료점에서 일시정지합니다.")



    # 기능: 통신이 복구된 PAUSED 상태에서 보존된 위치의 실행을 재개한다.
    def resume(self):
        if (self.state != SystemState.PAUSED or self.comm_lost_at is not None
                or not self.hmi_available()):
            return SequenceResult(False, "RESUME_NOT_ALLOWED", "PAUSED 및 통신 복구 상태가 필요합니다.")

        self.pause_requested.clear()
        return SequenceResult(True, "RESUME_ACCEPTED", "보존된 Resume Point에서 계속합니다.")



    # 기능: 진행 중인 Job에 정지를 요청한다. 자동 Home 복귀는 요청하지 않는다.
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
    def _require(self, result):
        if not result.success:
            raise RuntimeError(f"{result.code}: {result.message}")

        return result



    # 기능: 수신된 판정을 Job/Point 결과에 반영하고 결과 파일을 저장한다.
    def collect_results(self):
        if self.context is None:
            return

        results = self.inspection.results()
        self.recipes.apply_judgments(self.run_id, results)
        self.save("judgment_results.json", results)
        self.save("inspection_results.json", self.recipes.inspection_results())
        self.backend.stream.flush()
        self.recipes.mark_logs_saved(self.run_id, results)



    # 기능: 로봇에 정지를 요청하고 정지 확인 실패는 로그로 남긴다.
    def _abort_motion(self):
        try:
            self.backend.request_motion_stop()

        except Exception as error:
            self.notify("ERROR", f"정지 확인 실패: {error}")



    # 기능: #01 통신·장비·레시피와 활성 검사포인트 존재 여부를 확인한다.
    def work_initialize(self, recipe_id: str) -> SequenceResult:
        self.backend.phase = "SEQ_01_WORK_INITIALIZE"
        result = self.check_preconditions(recipe_id)

        if not result.success:
            return result

        total_points = self.recipes.progress()["total_points"]

        if not total_points:
            return SequenceResult(
                False,
                "NO_ENABLED_POINT",
                "활성화된 검사포인트가 없습니다.",
            )

        rechecked = self.check_devices()

        if not rechecked.success:
            return rechecked

        return SequenceResult(
            True,
            "WORK_INITIALIZE_OK",
            "Work Initialize 조건을 모두 확인했습니다.",
            {"total_points": total_points},
        )



    # 기능: 장비, HMI 연결, 시스템 설정, 검사 레시피 순서로 사전 조건을 확인한다.
    def check_preconditions(self, recipe_id):
        checks = (
            self.check_devices,
            self.check_hmi_communication,
            self.validate_system_recipe,
            lambda: self.validate_inspection_recipe(recipe_id),
        )

        for check in checks:
            result = check()

            if not result.success:
                return result

        return result



    # 기능: #07 판정·로그 완료를 기다리고 통신 상태와 결과 집계를 확인한다.
    def work_finish(self):
        self.backend.phase = "SEQ_07_WORK_FINISH"
        context = self.context
        context.current_sequence = "WORK_FINISH"
        deadline = time.monotonic() + self.system["judgment_timeout_s"]

        while True:
            self.checkpoint("WORK_FINISH_WAIT")
            self.collect_results()
            result = self.recipes.completion()

            if result.success:
                communication = self.check_hmi_communication()

                if not communication.success:
                    self.communication_lost()
                    continue

                self.save_summary(result)
                return result

            if time.monotonic() >= deadline:
                self.save("job_summary.json", {**result.data, "job_status": "NOT_COMPLETE"})
                return result

            self.pump()



    # 기능: 완료 시각과 판정 집계를 실행 폴더에 기록한다.
    def save_summary(self, result):
        context = self.context
        context.end_time = self.now()
        summary = {**result.data, "job_id": context.job_id, "recipe_id": context.recipe_id,
                   "point_total": self.recipes.progress()["total_points"],
                   "start_time": context.start_time.isoformat(),
                   "end_time": context.end_time.isoformat(), "job_status": "INSPECTION_COMPLETE"}
        self.save("job_summary.json", summary)
        self.notify("INFO", f"JOB_COMPLETE: {summary['counts']}")


