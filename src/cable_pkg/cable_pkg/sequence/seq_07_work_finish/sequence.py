"""#07 Work Finish: Work Access에서 검사 결과 처리가 끝났는지 확인한다.
1. 활성 Point 순회·모션·판정·로그 완료를 확인한다.
2. 판정이 남아 있으면 제한시간 동안 수신을 처리한다.
3. 완료되면 통신을 확인하고 검사 집계를 저장한다.
4. 미완료면 상태를 반환하고 Main Work에서 종료를 보류한다."""

import time

from cable_pkg.data_models.sequence_models import InspectionResult, SequenceStatus, SequenceResult


# 기능: 활성 Point의 순회·모션·판정·로그가 모두 완료되었는지 확인한다.
#     context: 활성 포인트 순서, 모션·판정·로그 상태를 담은 JobContext.
#
#     ------------------------------------------------------------
#     반환: 완료 여부, 결과별 개수, 누락/판정 대기 Point를 담은 SequenceResult.
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


class WorkFinishSequence:
    """Work Access에서 결과/기록 완료를 기다리고 Job 집계를 저장한다."""

    # 기능: 현재 Job의 완료 상태를 확인할 제어 객체를 연결한다.
    #     controller: 현재 Job 상태, 결과 저장, 제어 명령을 관리하는 SequenceController.
    def __init__(self, controller):
        self.controller = controller



    # 기능: Work Access에서 판정 수신을 기다리고 통신을 확인한 후 검사 집계를 저장한다.
    #
    #     ------------------------------------------------------------
    #     반환: 완료 또는 대기 만료 상태를 담은 SequenceResult.
    def run(self):
        controller = self.controller
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



    # 기능: Home 복귀 전 검사 집계와 시각을 저장하고 완료 로그를 보낸다.
    #     result: 성공 여부, 사유 코드, 부가 정보를 담은 SequenceResult.
    def save_summary(self, result):
        controller = self.controller
        context = controller.context
        context.end_time = controller.now()
        summary = {**result.data, "job_id": context.job_id, "recipe_id": context.recipe_id,
                   "point_total": len(context.enabled_point_ids),
                   "start_time": context.start_time.isoformat(),
                   "end_time": context.end_time.isoformat(), "job_status": "INSPECTION_COMPLETE"}
        controller.save("job_summary.json", summary)
        controller.notify("INFO", f"JOB_COMPLETE: {summary['counts']}")
