"""사용자가 직접 호출하는 시퀀스별 확인 함수.

controller는 실제 SequenceController, backend는 실제 SequenceRobot이다.
모션 함수는 실제 로봇을 움직인다. 호출 전 대상 Pose와 주변 상태를 확인한다.
운영 코드의 의존성은 없으므로 이 파일을 통째로 삭제해도 운영에 영향이 없다.
한 번에 한 함수만 장비 Worker에서 실행한다. 검사 중 병렬 호출하지 않는다.
"""


def check_00_main_work(controller, recipe_id):
    """전체 Job: Init → Home → Access → 활성 Point 순회 → Finish → Home."""
    print("기대: 실행목록 순회, 3종 결과 집계, 마지막 Home 도달 후 SYSTEM_READY")
    result = controller.run(recipe_id)
    print("실제:", result, "상태:", controller.state, "결과 폴더:", controller.output)
    return result


def check_01_initialize(backend, recipe_id):
    """정상 입력은 SUCCESS, 좌표 미입력/Heartbeat 없음은 시작 거부. 이동하지 않는다."""
    from cable_pkg.sequence.seq_01_work_initialize.sequence import WorkInitializeSequence
    try:
        result = WorkInitializeSequence(backend).run(recipe_id)
    except Exception as error:
        print("INIT FAIL:", error)
        return {"success": False, "reason": str(error)}
    print("실제:", result)
    return result


def check_02_home_return(controller):
    """영역 안: Relax→Escape→Access→Home / 밖: Safe Route→Home. 실제 이동한다."""
    controller.backend.validate_system_recipe()
    tcp = controller.backend.current_tcp()
    print("현재 TCP:", tcp, "영역 내부:", controller.backend.tcp_is_in_work_area(tcp))
    result = controller.request_home_return()
    print("실제:", result, "최종 TCP:", controller.backend.current_tcp())
    return result


def check_03_point_transition(inspection, point):
    """실제 Open → Ready → Entry. 입력받은 inspection은 이미 연결된 장비를 사용한다."""
    inspection.hardware.configure_point(point)
    print("기대: Recipe Open 폭 확인 → Ready → Entry")
    result = inspection.point_transition.run(point)
    print("실제:", result)
    return result


def check_04_adaptive_grip(inspection, point):
    """Entry에 위치시킨 후 호출. 완료 후 파지를 유지하므로 다음 동작을 직접 선택한다."""
    inspection.hardware.configure_point(point)
    print("기대: Soft+추가진입 → Soft 폭 기록 → Hard 동작 종료 확인")
    result = inspection.adaptive_grip.run(point)
    print("Soft 기준 폭:", result.soft_width_mm, "Hard 상태:", result.hard_grip)
    return result


def check_05_pull_inspection(inspection, point):
    """Hard Grip 완료 상태에서 호출. Pull 측정 → Open → Entry → Ready로 실제 이동한다."""
    inspection.hardware.configure_point(point)
    print("기대: 힘/최대거리 도달 시 정지, 실제 변위·최소 폭 기록, Entry→Ready 복귀")
    result = inspection.pull_inspection.run(point)
    print("실제 Pull:", result["pull"])
    return result


def check_06_judgment():
    """로봇/노드 실행 없이 판정함수만 호출한다. PASS/FAIL/파지실패/오류/경계값."""
    from cable_pkg.data_models.sequence_models import PullTermination
    from cable_pkg.sequence.seq_06_inspection_judgment.node import judge_pull
    cases = [
        ("정상", "FORCE_LIMIT", 16.0, 4.0, 17.0, "PASS"),
        ("5 mm 경계", "FORCE_LIMIT", 16.0, 5.0, 16.0, "PASS"),
        ("변위 초과", "FORCE_LIMIT", 16.0, 5.1, 17.0, "FAIL"),
        ("최대거리", "MAX_DISTANCE", 8.0, 25.0, 17.0, "FAIL"),
        ("파지 실패", "FORCE_LIMIT", 16.0, 4.0, 15.9, "FAIL"),
        ("시간 초과", "TIMEOUT", 8.0, 3.0, 17.0, "SYSTEM_ERROR"),
        ("데이터 누락", "FORCE_LIMIT", 16.0, 4.0, None, "SYSTEM_ERROR"),
    ]
    results = []
    for name, termination, force, distance, width, expected in cases:
        result = judge_pull(termination=PullTermination(termination), peak_force_n=force,
                            displacement_mm=distance, required_force_n=15.0,
                            soft_width_mm=22.0, pull_width_mm=width)
        print(f"{name}: 기대={expected}, 실제={result.result.value}, 사유={result.reason}")
        results.append(result)
    return results


def check_07_work_finish(context):
    """사용자가 만든 JobContext로 결과 누락/Pending/로그 미저장/3종 결과 완료 확인."""
    from cable_pkg.sequence.seq_07_work_finish.sequence import check_work_completion
    result = check_work_completion(context)
    print("기대: 모든 활성 Point 모션·결과·저장 완료일 때만 성공. FAIL도 종료 가능")
    print("실제:", result)
    return result


def check_common_command(controller, command):
    """전체 Job Worker 실행 중 제어 스레드에서 한 명령씩 호출한다.

    PAUSE→완료점에서 PAUSED / RESUME→재개 / COMM_LOST→PAUSED /
    COMM_RECOVERED→PAUSED 유지 / STOP→종료, 자동 Home 없음.
    COMM_LOST 뒤 복구를 보내지 않으면 설정 시간 뒤 COMM_ERROR가 된다.
    """
    actions = {"PAUSE": controller.pause, "RESUME": controller.resume,
               "STOP": controller.stop, "COMM_LOST": controller.communication_lost,
               "COMM_RECOVERED": controller.communication_recovered}
    result = actions[command]()
    print("요청:", command, "현재 상태:", controller.state, "응답:", result)
    return result
