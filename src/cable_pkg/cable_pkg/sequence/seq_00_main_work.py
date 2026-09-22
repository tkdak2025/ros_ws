"""확정된 공통 시퀀스의 상태 전이와 Context 수명을 관리한다."""

from cable_pkg.interfaces.sequence_backend import InspectionPointExecutor, SequenceBackend
from .seq_02_home_return import HomeReturnSequence
from cable_pkg.data_models.sequence_models import JobContext, SequenceResult, SystemState
from .seq_01_work_initialize import WorkInitializeSequence


class SequenceController:
    """START, PAUSE, RESUME, STOP, HOME_RETURN 정책을 시행한다."""

    def __init__(
        self,
        backend: SequenceBackend,
        point_executor: InspectionPointExecutor,
        max_escape_distance_mm: float,
    ) -> None:
        self.backend = backend
        self.point_executor = point_executor
        self.work_initialize = WorkInitializeSequence(backend)
        self.home_return = HomeReturnSequence(backend, max_escape_distance_mm)
        self.state = SystemState.SYSTEM_READY
        self.context: JobContext | None = None
        self.last_error = ""

    def start(self, recipe_id: str) -> SequenceResult:
        """SYSTEM_READY에서 새 Job Context를 만들고 확정된 시작 절차를 수행한다."""
        if self.state != SystemState.SYSTEM_READY:
            return self._reject("START_NOT_ALLOWED", "SYSTEM_READY에서만 START할 수 있습니다.")
        if not recipe_id.strip():
            return self._reject("RECIPE_ID_REQUIRED", "recipe_id가 필요합니다.")

        self.context = None
        self.last_error = ""
        self.state = SystemState.RUNNING

        initialized = self.work_initialize.run(recipe_id)
        if not initialized.success:
            return self._fail(initialized)

        points = list(initialized.data["enabled_point_ids"])
        self.context = JobContext(recipe_id=recipe_id, enabled_point_ids=points)

        self.context.current_sequence = "HOME_RETURN"
        returned = self.home_return.run()
        if not returned.success:
            return self._fail(returned)

        self.context.current_sequence = "WORK_ACCESS"
        accessed = self.backend.move_work_access_safe_pose()
        if not accessed.success:
            return self._fail(accessed)

        self.context.current_sequence = "POINT_LOOP"
        return SequenceResult(
            True,
            "START_SEQUENCE_OK",
            "확정된 START 절차를 완료했고 Point Loop 시작 조건이 준비됐습니다.",
            {"enabled_point_ids": points},
        )

    def execute_current_point(self) -> SequenceResult:
        """상세설계된 Point Executor가 있을 때만 현재 포인트를 실행한다."""
        if self.state != SystemState.RUNNING or self.context is None:
            return self._reject("POINT_NOT_ALLOWED", "RUNNING Job이 없습니다.")
        result = self.point_executor.execute(self.context)
        if not result.success:
            return self._fail(result)
        self.context.current_point_index += 1
        return result

    def pause(self) -> SequenceResult:
        """Pause Safe 처리 후 Context를 보존한 채 PAUSED로 전환한다."""
        if self.state != SystemState.RUNNING or self.context is None:
            return self._reject("PAUSE_NOT_ALLOWED", "RUNNING 상태에서만 PAUSE할 수 있습니다.")
        self.state = SystemState.PAUSE_REQUEST
        result = self.backend.request_pause_safe(self.context)
        if not result.success:
            return self._fail(result)
        self.state = SystemState.PAUSED
        return SequenceResult(True, "PAUSED", "Pause Safe 처리를 완료했습니다.")

    def resume(self) -> SequenceResult:
        """보존된 Resume Point를 사용해 명시적인 RESUME 요청을 처리한다."""
        if self.state != SystemState.PAUSED or self.context is None:
            return self._reject("RESUME_NOT_ALLOWED", "PAUSED Job이 없습니다.")
        result = self.backend.resume_from(self.context)
        if not result.success:
            return self._fail(result)
        self.state = SystemState.RUNNING
        return SequenceResult(True, "RESUMED", "Job 실행을 재개했습니다.")

    def stop(self) -> SequenceResult:
        """현재 Job을 종료하고 Context를 폐기하며 자동 Home Return은 하지 않는다."""
        result = self.backend.request_motion_stop()
        self.context = None
        self.state = SystemState.STOPPED
        if not result.success:
            self.last_error = result.message
            return result
        return SequenceResult(True, "STOPPED", "Job을 종료했습니다. Home Return은 수행하지 않았습니다.")

    def request_home_return(self) -> SequenceResult:
        """STOPPED/ERROR/SYSTEM_READY에서 사용자가 요청한 Home Return을 수행한다."""
        if self.state not in {
            SystemState.SYSTEM_READY,
            SystemState.STOPPED,
            SystemState.ERROR,
        }:
            return self._reject("HOME_RETURN_NOT_ALLOWED", "현재 상태에서는 Home Return할 수 없습니다.")
        result = self.home_return.run()
        if result.success:
            self.context = None
            self.last_error = ""
            self.state = SystemState.SYSTEM_READY
        else:
            self._fail(result)
        return result

    def complete(self) -> SequenceResult:
        """정상 작업 완료 후 Home Return하고 SYSTEM_READY로 돌아간다."""
        if self.state != SystemState.RUNNING:
            return self._reject("COMPLETE_NOT_ALLOWED", "RUNNING 상태가 아닙니다.")
        result = self.home_return.run()
        self.context = None
        if result.success:
            self.state = SystemState.SYSTEM_READY
            return SequenceResult(True, "JOB_COMPLETE", "작업 완료와 Home Return을 마쳤습니다.")
        return self._fail(result)

    def communication_lost(self) -> SequenceResult:
        """통신 유실 시 Pause Safe를 수행하고 자동 재개하지 않는다."""
        if self.state != SystemState.RUNNING:
            return self._reject("COMM_LOST_IGNORED", "실행 중인 Job이 없습니다.")
        result = self.pause()
        if result.success:
            return SequenceResult(True, "PAUSED_COMM_LOST", "HMI 통신 유실로 일시정지했습니다.")
        return result

    def communication_recovered(self) -> SequenceResult:
        """통신 복구를 기록하되 사용자의 RESUME 전에는 PAUSED를 유지한다."""
        if self.state != SystemState.PAUSED:
            return self._reject("COMM_RECOVERY_NOT_PAUSED", "통신 복구 대기 상태가 아닙니다.")
        return SequenceResult(True, "COMM_RECOVERED", "통신이 복구됐습니다. RESUME 입력을 기다립니다.")

    def _fail(self, result: SequenceResult) -> SequenceResult:
        self.last_error = result.message
        self.context = None
        self.state = SystemState.ERROR
        return result

    @staticmethod
    def _reject(code: str, message: str) -> SequenceResult:
        return SequenceResult(False, code, message)
