"""#00 Main Work: START 한 번으로 전체 Job을 수행한다.
1. #01 초기화 후 #02 Home을 거쳐 Work Access로 이동한다.
2. 레시피의 활성 Point마다 #03→#04→#05를 실행하고 #06을 비동기로 요청한다.
3. Work Access에서 #07 결과 완료를 확인하고 Home으로 복귀한다.
4. 완료점에서 Pause/Resume을 처리하며 STOP 시 Job을 중단한다."""

import copy
import json
import threading
import time
from dataclasses import asdict, replace
from datetime import datetime
from pathlib import Path

import rclpy

from cable_pkg.data_models.sequence_models import (
    InspectionResult, JudgmentStatus, JobContext, PointRuntime, PullTermination,
    SequenceResult, SequenceStatus, SystemState,
)
from cable_pkg.data_models.inspection_models import JudgmentRequest
from cable_pkg.sequence.inspection.inspection import InspectionSequence
from cable_pkg.sequence.seq_06_inspection_judgment.node import JudgmentClient
from cable_pkg.sequence.seq_01_work_initialize.sequence import WorkInitializeSequence
from cable_pkg.sequence.seq_02_home_return.sequence import HomeReturnSequence
from cable_pkg.sequence.seq_07_work_finish.sequence import WorkFinishSequence


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
    def run(self, recipe_id):
        if self.state != SystemState.SYSTEM_READY or self.context is not None:
            return SequenceResult(False, "START_NOT_ALLOWED", "SYSTEM_READY에서만 시작할 수 있습니다.")
        stream, previous_stream = self.prepare_job()
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
    def prepare_job(self):
        self.stop_requested.clear()
        self.pause_requested.clear()
        self.comm_lost_at = None
        self.last_error = ""
        self.last_summary = {}
        self.motion_results = {}
        self.state = SystemState.RUNNING
        self.run_id = time.time_ns() // 1000
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
        initialized = WorkInitializeSequence(self.backend).run(recipe_id)
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
            finish = WorkFinishSequence(self).run()
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
        from cable_pkg.sequence.seq_06_inspection_judgment.node import InspectionJudgmentNode, judge_pull
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



    # 기능: #02 Home Return을 현재 장비와 완료점 처리 함수로 실행한다.
    #
    #     ------------------------------------------------------------
    #     반환: Home 복귀 결과를 담은 SequenceResult.
    def home_return(self):
        return HomeReturnSequence(self.backend, checkpoint=self.checkpoint).run()



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
