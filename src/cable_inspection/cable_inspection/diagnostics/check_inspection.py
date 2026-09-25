#!/usr/bin/env python3
"""검사 체크리스트를 재현하고 정량 비교 결과를 Markdown으로 저장한다.
기존 회귀 테스트와 가상 피드백 시험을 실행한다. 메뉴 2는 가상 장비에 모션 명령을 보낸다.
운영 코드에서 이 파일을 참조하지 않으며 검사 패키지의 test/를 재사용한다.
"""

import argparse
import contextlib
import hashlib
import importlib.util
import io
import json
import math
import os
from pathlib import Path
import shlex
import subprocess
import sys
import time
import traceback
import xml.etree.ElementTree as ET
from datetime import datetime

WORKSPACE = Path(__file__).resolve().parents[4]
PACKAGE = WORKSPACE / 'src/cable_inspection'
TESTS = PACKAGE / 'test'

# 검증 기준은 이 코드에서 관리한다. docs 문서를 읽거나 파일명·위치에 의존하지 않는다.
# CHECKLIST: 항목 ID → (보고서에 표시할 확인 내용, 연결할 pytest 이름 접두사 목록).
# 테스트 실행 목록이 아니며, 빈 목록인 실물 항목은 자동 통과로 처리하지 않는다.
# pytest는 각 시험을 한 번 실행한다. A01·A02처럼 같은 시험을 여러 ID의 근거로 공유할 수 있다.
# 접두사로 연결하므로 파라미터별 시험 결과도 포함한다. 미연결·미실행 항목은 통과로 보지 않는다.
# 아래 주석은 항목별 확인 목적이며, 자동 시험이 확인한 범위는 보고서에서 '자동 부분 통과'로 표시한다.
CHECKLIST = {

    # A. 노드·장비 준비

    # A01: 기동 상태: 필요한 노드가 생성되고 START 전 대기하는지 확인.
    'A01': ('검사 launch 후 START 없이 관찰',
            ['test_standalone_launches_and_services']),

    # A02: 통신 소유권: 외부 서비스·토픽이 HMI 노드에 있는지 확인. A01과 같은 시험 결과를 공유.
    'A02': ('ROS 그래프에서 서비스·토픽 소유자 확인',
            ['test_standalone_launches_and_services']),

    # A03: 연속 Job에서 장비 초기화와 판정 연결 재사용 확인.
    'A03': ('두 장비 준비 완료 후 연속 Job 실행',
            ['test_robot_preparation_runs_once', 'test_two_jobs_reuse_judgment']),

    # A04: 장비 준비 실패·그리퍼 제공자 불일치 시 실행 차단 확인.
    'A04': ('로봇/그리퍼 미연결·모드 불일치·부적합 Robot 상태를 각각 모의',
            ['test_prepare_failure', 'test_rg2_wrong_provider']),

    # A05: 잘못된 좌표·수치·시스템 설정 거절 확인.
    'A05': ('Tool/TCP 불일치·잘못된 관절/TCP 측정값을 모의',
            ['test_invalid_vectors', 'test_system_recipe_without_coordinates']),

    # B. HMI 통신·Recipe

    # B01: HMI START 접수·실행 식별자·Snapshot 연결 확인.
    'B01': ('hmi 모드에서 전체 Recipe로 StartInspection 호출',
            ['test_hmi_gateway_routes_requests']),

    # B02: 같은 요청의 중복 실행 방지와 변경된 요청 충돌 처리 확인.
    'B02': ('같은 request_id·같은 Recipe 재전송, 이후 같은 ID·다른 Recipe 전송',
            ['test_duplicate_start', 'test_duplicate_ack']),

    # B03: 잘못된 Recipe·운전 조건에 대한 START 거절 확인.
    'B03': ('빈 ID·잘못된 좌표/검사조건·활성 포인트 없음·Heartbeat 없음 요청',
            ['test_specific_rejection_code', 'test_nonfinite_recipe']),

    # B04: HMI 서비스와 터미널 명령의 입력 경로 구분 확인.
    'B04': ('terminal 모드와 hmi 모드의 입력 경로 확인',
            ['test_terminal_mode_rejects', 'test_hmi_gateway_routes_requests']),

    # B05: 레시피 배열 순서 유지와 비활성 포인트 제외 확인.
    'B05': ('포인트 순서를 바꾸고 일부 enabled=false로 실행',
            ['test_array_order_disabled_skip']),

    # B06: 실행 중 Recipe 변경 격리와 중복 START 거절 확인.
    'B06': ('Job 도중 다음 Recipe 입력/원본 수정을 모의',
            ['test_received_updates_do_not_change', 'test_terminal_start_does_not_launch']),

    # B07: 외부 토픽 소유권과 결과 직렬화 계약 확인.
    'B07': ('work_status·execution_snapshot·robot_status·judgment_result·log 수신',
            ['test_standalone_launches_and_services', 'test_custom_result_serialization']),

    # C. START·Work Access 준비

    # C01: Home에서 START할 때 Work Access를 거쳐 시작하는지 확인.
    'C01': ('Home에서 START',
            ['test_start_uses_current_pose_to_reach_work_access[home']),

    # C02: 이미 Work Access이면 불필요한 준비 이동을 생략하는지 확인.
    'C02': ('이미 Work Access에 있는 상태에서 START',
            ['test_start_uses_current_pose_to_reach_work_access[access']),

    # C03: 작업영역 내부에서 Open·Tool 역방향 후퇴·Access 준비 확인.
    'C03': ('작업영역 내부에서 START',
            ['test_start_uses_current_pose_to_reach_work_access[work', 'test_escape_moves_30mm']),

    # C04: STOPPED 상태에서 별도 Home 없이 새 Job 시작 확인.
    'C04': ('STOP 후 새 START',
            ['test_new_job_from_idle_states', 'test_terminal_start_accepts_stopped']),

    # C05: ERROR 후 새 시작 허용과 장비 준비 실패 시 차단 확인.
    'C05': ('ERROR 원인이 해소된 경우와 남은 경우에 새 START',
            ['test_new_job_from_idle_states', 'test_prepare_failure']),

    # C06: 작업 중 새 실행을 거절해 중복 Worker 생성을 방지하는지 확인.
    'C06': ('실행·일시정지·정지 처리 중 START/HOME 반복 입력',
            ['test_terminal_start_does_not_launch', 'test_specific_rejection_code']),

    # C07: Open·후퇴·Access 준비 실패 시 검사 시작 차단 확인.
    'C07': ('Open 실패·후퇴 미도달·Access 미도달을 각각 모의',
            ['test_failed_start_preparation']),

    # D. 포인트 검사 동작

    # D01: Open → Ready MoveJ → Entry pose MoveJ 접근 순서 확인.
    'D01': ('첫 포인트 및 다음 포인트 접근 관찰',
            ['test_recipe_iterates_point_transition', 'test_approach_miss_blocks_grip',
             'test_approach_failure_stops_job']),

    # D02: Entry pose의 ABC로 Tool 진입 방향을 계산하는지 확인.
    'D02': ('Entry pose의 A/B/C가 다른 포인트 실행',
            ['test_entry_direction_comes_from_entry_abc']),

    # D03: Soft Grip·진입·실측 폭·Hard Grip·Pull의 순서와 측정 확인.
    'D03': ('파지·진입 단계 로그 확인',
            ['test_recipe_iterates_point_transition', 'test_real_sequence_with_synthetic_feedback']),

    # D04: Soft 폭 미도달·busy가 진입을 제한하지 않는지 확인.
    'D04': ('Soft 목표 폭 미도달 및 busy=true 데이터 입력',
            ['test_soft_width_snapshot_ignores_busy', 'test_real_sequence_with_synthetic_feedback']),

    # D05: Hard 목표 폭 도달 또는 폭 안정화로 파지 완료 판단 확인.
    'D05': ('Hard 목표 폭 도달 / 목표 미도달이나 폭 안정화 데이터를 각각 입력',
            ['test_hard_grip_accepts_recorded_normal_width', 'test_hard_grip_uses_stable_width']),

    # D06: 파지 시간 초과 시 Pull 생략·복구·다음 포인트 진행 확인.
    'D06': ('Hard 폭이 안정화되지 않아 완료 제한시간을 넘기는 데이터 입력',
            ['test_grip_timeout_recovers_to_next_point']),

    # D07: 파지 실패 복구 중 오류를 숨기지 않는지 확인. D06과 같은 시험군을 공유.
    'D07': ('파지 실패 복구 중 Open·복귀 실패 또는 STOP 입력',
            ['test_grip_timeout_recovers_to_next_point']),

    # D08: 접촉 이동의 힘·거리·미도달·시간 초과 종료 처리 확인.
    'D08': ('Entry/Pull의 힘 제한·거리 도달·미도달·시간 초과를 각각 입력',
            ['test_real_sequence_with_synthetic_feedback', 'test_contact_motion_stopped_short']),

    # D09: 감속 구간까지 포함한 최대 힘·최소 폭 측정 확인.
    'D09': ('감속 중 더 큰 힘·더 작은 폭이 발생하는 데이터 입력',
            ['test_peak_includes_deceleration_samples']),

    # D10: Pull 후 Open·Entry 복귀·Ready 복귀와 다음 포인트 진행 확인.
    'D10': ('Pull 후 복귀 관찰',
            ['test_recipe_iterates_point_transition', 'test_00_job_order_delayed_results']),

    # D11: 포인트 속도 설정이 다음 포인트나 공통 이동에 남지 않는지 확인.
    'D11': ('서로 다른 검사 속도의 포인트를 연속 실행',
            ['test_point_speed_does_not_change_common_home_speed']),

    # E. 판정·비동기 결과

    # E01: 힘·변위 조건에 맞는 PASS와 판정 경계 확인.
    'E01': ('FORCE_LIMIT, 기준 힘 이상, 최소 폭 16 mm 이상, 변위 허용 이내 입력',
            ['test_force_limit_with_small_displacement', 'test_v03_policy']),

    # E02: 변위 초과·최대 거리·파지 폭 조건의 FAIL 판정 확인.
    'E02': ('유효한 FORCE_LIMIT에서 변위 초과 / 유효한 최대거리 도달 / 최소 폭 16 mm 미만 입력',
            ['test_pull_width_failure_threshold', 'test_max_distance_without_slip', 'test_force_limit_after_large']),

    # E03: 미도달·시간 초과·잘못된 입력의 SYSTEM_ERROR 구분 확인.
    'E03': ('Pull 미도달·시간 초과·잘못된 수치·종료 사유와 힘 불일치 입력',
            ['test_timeout_is_incomplete', 'test_v03_policy', 'test_identifiable_invalid_request']),

    # E04: 비동기 판정과 모션 병행, 최종 결과 대기 확인.
    'E04': ('판정을 늦추고 다음 포인트 진행 관찰',
            ['test_00_job_order_delayed_results', 'test_early_and_late_judgments']),

    # E05: 이전 실행·중복·늦은 판정이 확정 결과를 덮어쓰지 않는지 확인.
    'E05': ('이전 run_id의 늦은 판정·중복 요청·복귀 오류 후 늦은 정상 판정 입력',
            ['test_old_inflight_judgment', 'test_stale_unknown_and_duplicate']),

    # F. Pause·Resume·STOP·통신 유실

    # F01: Pause 시 문맥 보존과 Resume 후 실행 재개 확인.
    'F01': ('검사 중 PAUSE 후 RESUME',
            ['test_pause_resume_preserves_context']),

    # F02: STOP 감시·정지 처리·응답 대기 중 모니터링과 종료 확인.
    'F02': ('이동·서비스 응답 대기 중 STOP, PAUSED 중 STOP',
            ['test_monitoring_and_shutdown_stop', 'test_rg2_control_interrupt', 'test_00_job_order_delayed_results', 'test_stop_failure_restores']),

    # F03: 통신 복구만으로 자동 재개하지 않고 RESUME을 기다리는지 확인.
    'F03': ('Heartbeat 중단 후 제한시간 내 복구',
            ['test_communication_recovery_requires_explicit_resume', 'test_hmi_gateway_routes_requests']),

    # F04: 통신 복구 제한시간 초과 시 Job 중단 확인.
    'F04': ('Heartbeat 복구 제한시간 초과',
            ['test_communication_timeout_requests_stop']),

    # F05: 완료·STOP 후 새 Job에서 실행 상태 초기화와 연결 재사용 확인.
    'F05': ('완료·STOP 후 같은 노드로 새 Job 실행',
            ['test_two_jobs_reuse_judgment', 'test_stop_preserves_last_progress']),

    # G. 작업 완료·수동 Home

    # G01: 작업 완료 시 Work Access 대기와 자동 Home 미실행 확인.
    'G01': ('전체 포인트 정상 완료',
            ['test_00_job_order_delayed_results', 'test_new_job_from_idle_states']),

    # G02: Access 복귀·판정·기록 미완료를 작업 완료로 처리하지 않는지 확인.
    'G02': ('최종 Access 복귀 실패 / 판정·기록 미완료를 각각 모의',
            ['test_finish_access_failure', 'test_07_incomplete_conditions']),

    # G03: 완료 후 Work Access에서 다음 Job 시작 확인.
    'G03': ('완료한 자리에서 다시 START',
            ['test_two_jobs_reuse_judgment', 'test_start_uses_current_pose_to_reach_work_access[access']),

    # G04: 작업영역 안의 수동 Home에서 Safe Escape·Access 경로 확인.
    'G04': ('작업영역 안에서 별도 HOME 명령',
            ['test_home_sequence_uses_shared_runtime', 'test_02_home_routes',
             'test_manual_home_command_selects_route']),

    # G05: 작업영역 밖의 수동 Home에서 설정 경로와 도달 확인.
    'G05': ('작업영역 밖에서 별도 HOME 명령',
            ['test_home_uses_single_move', 'test_home_route_uses_only_given_waypoints']),

    # G06: Home 단계 실패 처리와 실행 요청 중복 방지 확인.
    'G06': ('수동 HOME 실패 / HOME 중 START 입력',
            ['test_home_stops_at_first_failed_step', 'test_home_clears_only_current_request']),

    # H. 결과 파일·상태 표시

    # H01: Job별 입력 Snapshot·결과 기록 분리 확인.
    'H01': ('실행별 결과 폴더와 inputs.json 확인',
            ['test_00_job_order_delayed_results', 'test_two_jobs_reuse_judgment']),

    # H02: Entry·Pull 구간의 실제 측정값 기록 확인.
    'H02': ('samples.jsonl의 Entry/Pull 구간 확인',
            ['test_real_sequence_with_synthetic_feedback']),

    # H03: 실행 결과·판정·완료 상태 기록의 일관성 확인.
    'H03': ('inspection_results.json·judgment_results.json·job_summary.json·status.json 대조',
            ['test_00_job_order_delayed_results', 'test_grip_timeout_recovers_to_next_point']),

    # H04: 장비·포인트 상태의 유효성·만료·오류와 비동기 갱신 확인.
    'H04': ('비활성·다른 포인트·오래된 측정값 및 연결 끊김 표시 확인',
            ['test_monitoring_and_shutdown_stop', 'test_gripper_feedback_validity', 'test_robot_monitor_keeps_one', 'test_robot_snapshot_expiry', 'test_work_uses_matching_point_sample']),


    # R. 실물 확인

    # R01~R05: 실물에서 별도 확인한다. 자동 시험 연결이 없으므로 보고서에는 미검증으로 남긴다.
    'R01': ('각 포인트의 Ready/Entry 자세와 Tool +Z 접근 방향이 실제 케이블 방향에 맞는가.', []),
    'R02': ('Open 25 mm가 실제 파지를 해제하며 인접 케이블과 간섭하지 않는가.', []),
    'R03': ('Tool 반대 방향 30 mm 후퇴와 이후 Work Access 이동이 실제 접촉을 해제하고 간섭을 피하는가.', []),
    'R04': ('Soft/Hard 폭·힘 및 안정화 조건이 정상 파지를 놓치거나 잘못된 파지를 정상으로 보지 않는가.', []),
    'R05': ('정상체결·체결불량 실물 데이터에서 힘·변위·폭 판정 기준이 적절한가. LAN 기준 힘은 현재 15 N이다.', []),
}



class InspectionCheck:
    """시험 실행·수치 비교·MD 기록만 담당하는 검증용 클래스."""



    # 기능: 실행 경로와 결과 목록을 준비한다.
    #     output: 새 실행의 결과를 기록할 폴더. 기존 폴더는 덮어쓰지 않는다.
    #     반환: 없음.
    def __init__(self, output):
        self.output = output.resolve()
        self.output.mkdir(parents=True, exist_ok=False)

        self.started = datetime.now().astimezone().isoformat(timespec='seconds')
        self.tests = []
        self.metrics = []
        self.errors = []
        self.virtual_result = None



    # 기능: 필요한 테스트 모듈을 불러와 이미 사용하는 가상 입력을 재사용한다.
    #     filename: test/ 내부 Python 파일명.
    #     반환: 로드한 모듈. 불러오기 실패는 호출자에게 전달한다.
    def load_fixture(self, filename):
        path = TESTS / filename
        spec = importlib.util.spec_from_file_location(path.stem, path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        return module



    # 기능: 기대값과 관측값을 비교하고 정량 결과 한 행을 저장한다.
    #     scenario: 재현 시나리오 이름. ids: 연결된 체크리스트 ID.
    #     name: 비교 지표. expected/actual: 기준값/관측값. unit: 단위.
    #     tolerance: 수치 절대 허용오차. 문자는 정확히 일치해야 한다.
    #     반환: 비교 통과 여부.
    def compare(self, scenario, ids, name, expected, actual, unit='', tolerance=0.):
        numeric = (type(expected) in (int, float) and type(actual) in (int, float))
        delta = abs(actual - expected) if numeric else None
        passed = (math.isfinite(actual) and delta <= tolerance) if numeric else actual == expected

        self.metrics.append(dict(
            scenario=scenario, ids=ids, metric=name,
            expected=expected, actual=actual, unit=unit,
            tolerance=tolerance if numeric else '정확히 일치',
            error=delta, result='PASS' if passed else 'FAIL',
        ))

        return passed



    # 기능: 실제 검사 코드를 가상 힘·폭·위치 데이터로 실행해 종료와 계측값을 대조한다.
    #     인자: 없음. test_motion_feedback의 결정적 가상 장비를 사용한다.
    #     반환: 없음. 원시 접촉 샘플과 명령 목록은 evidence/에 저장한다.
    def measure_inspection(self):
        fixture = self.load_fixture('test_motion_feedback.py')
        from cable_inspection.sequence.inspection.node_inspection import InspectionJudgmentNode

        # 시나리오별 기대 종료 사유·힘·변위·폭·판정을 준비한다.
        scenarios = {
            'force': ('FORCE_LIMIT', 25., 4., 18.4, 'PASS'),
            'short': ('STOPPED_SHORT', 1., 2., 18.4, 'SYSTEM_ERROR'),
            'distance': ('MAX_DISTANCE', 1., 25., 18.4, 'FAIL'),
            'timeout': ('TIMEOUT', 25., 4., 18.4, 'SYSTEM_ERROR'),
            'stable': ('FORCE_LIMIT', 25., 4., 18.8, 'PASS'),
            'grip_timeout': ('TIMEOUT', 0., 0., None, 'SYSTEM_ERROR'),
        }

        # 재현 입력과 측정 증거의 저장 위치를 준비한다.
        evidence = self.output / 'evidence'
        evidence.mkdir(exist_ok=True)
        (evidence/'synthetic_point.json').write_text(json.dumps(fixture.point, ensure_ascii=False, indent=2))

        # 각 시나리오를 실행하고 계측 결과와 명령 순서를 대조한다.
        for case, (termination, force, distance, width, judgment) in scenarios.items():
            try:
                events, requests, result, samples = fixture.run(case)
                (evidence/f'{case}.json').write_text(json.dumps(
                    {'commands':events, 'contact_samples':samples}, ensure_ascii=False, indent=2))

                # 판정 요청과 실제 힘·변위·폭을 검증한다.
                ids = 'D03,D05,D06,D08,D09,E01,E02,E03'
                self.compare(case, ids, '판정 요청 수', 1, len(requests), '건')
                request = requests[0]
                self.compare(case, ids, 'Pull 종료 사유', termination, result.termination_reason.value)
                self.compare(case, ids, '최대 Pull 힘', force, request.peak_pull_force_n, 'N', 1e-6)
                self.compare(case, ids, '실제 Pull 변위', distance, request.pull_displacement_mm, 'mm', 1e-6)
                self.compare(case, ids, 'Pull 최소 폭', width, request.pull_width_mm, 'mm', 1e-6)
                self.compare(case, ids, '제품/시스템 판정', judgment,
                             InspectionJudgmentNode.judge_request(request).result.value)

                # 복귀 명령 수와 실패 포인트의 Pull 생략 여부를 검증한다.
                self.compare(case, 'D01,D10', 'MoveJ 명령 수', 3,
                             sum(event[0]=='movej' for event in events), '회')
                self.compare(case, 'D06,D10', 'MoveL 명령 수', 2 if case=='grip_timeout' else 3,
                             sum(event[0]=='movel' for event in events), '회')
                self.compare(case, 'D06', 'Pull 생략', case=='grip_timeout',
                             bool(result.pull_inspection.get('skipped', False)))

            except Exception:
                self.errors.append(f'가상 계측 {case}\n{traceback.format_exc()}')
                self.compare(case, 'D03,D08', '시나리오 실행', '완료', 'ERROR')



    # 기능: START 위치와 준비 실패를 재현해 명령 수·후퇴량·완료점을 측정한다.
    #     인자: 없음. 실제 Main 준비 코드와 Home의 Safe Escape 코드를 사용한다.
    #     반환: 없음. 준비 동작만 실행하고 실제 장비를 생성하지 않는다.
    def measure_start(self):
        fixture = self.load_fixture('test_start_work_access.py')

        # 정상 준비: 시작 위치에 따른 명령 수와 Access 도달을 확인한다.
        for location, count in [('home', 1), ('access', 0), ('work', 3)]:
            main, events, checkpoints = fixture.setup_route(location)
            main.prepare_work_access()

            self.compare(location, 'C01,C02,C03', '준비 명령 수', count, len(events), '회')
            self.compare(location, 'C01,C02,C03', 'Home 도달 완료점 수', 0, checkpoints.count('HOME_REACHED'), '회')
            self.compare(location, 'C01,C02,C03', 'Access 도달 완료점 수', 1, checkpoints.count('WORK_ACCESS_REACHED'), '회')

            if location == 'work':
                target = events[1][1]
                self.compare(location, 'C03', 'Tool −Z 후퇴량', 30., 300.-target[2], 'mm', 1e-6)

        # 준비 실패: 오류가 감지되고 Access 완료점이 남지 않는지 확인한다.
        for failure in ['open', 'escape', 'move', 'arrival']:
            main, events, checkpoints = fixture.setup_route('work',failure)
            error = None

            try:
                main.prepare_work_access()

            except (RuntimeError, TimeoutError) as caught:
                error = caught

            self.compare(failure, 'C07', '준비 오류 감지', True, error is not None)
            self.compare(failure, 'C07', '잘못된 Access 완료점 수', 0, checkpoints.count('WORK_ACCESS_REACHED'), '회')



    # 기능: 실행 중인 가상 장비에 실제 검사 Main을 연결해 한 Job의 완료를 확인한다.
    #     인자: 없음. 현재 ROS 도메인과 LOCALHOST discovery를 사용한다.
    #     반환: 없음. 가상 결과와 검사 원본은 이번 출력 폴더에 저장한다.
    def run_virtual(self):
        from cable_inspection.diagnostics.check_virtual import VirtualInspectionCheck

        self.virtual_result = VirtualInspectionCheck(self.output).run()



    # 기능: pytest를 자식 프로세스에서 실행하고 개별 결과·시간·실패 근거를 수집한다.
    #     ros: True이면 현재 ROS 도메인에서 LOCALHOST 통합 시험을 추가한다.
    #     반환: 없음. 시험 실패·수집 오류·시간 초과는 보고서와 종료 코드에 반영한다.
    def run_tests(self, ros=False):
        label = 'ros' if ros else 'offline'
        xml = self.output/f'{label}.xml'
        command = [sys.executable, '-m', 'pytest', '-q', str(TESTS/'test_standalone_ros.py') if ros else str(TESTS),
                   f'--junitxml={xml}', '--tb=short']

        # 시험 프로세스의 공통 환경을 구성한다.
        env = os.environ.copy()
        env['PYTEST_DISABLE_PLUGIN_AUTOLOAD'] = '1'
        env['PYTHONPATH'] = str(PACKAGE)+os.pathsep+env.get('PYTHONPATH','')

        if ros:
            # 현재 ROS 도메인을 유지하고 LOCALHOST에서 HMI 없는 설치 환경을 재현한다.
            for key in ['PYTHONPATH','AMENT_PREFIX_PATH','COLCON_PREFIX_PATH','CMAKE_PREFIX_PATH',
                        'LD_LIBRARY_PATH','ROS_DISCOVERY_SERVER','CYCLONEDDS_URI','FASTRTPS_DEFAULT_PROFILES_FILE']:
                env.pop(key,None)

            env.update(CCCIS_STANDALONE_TEST='1', ROS_AUTOMATIC_DISCOVERY_RANGE='LOCALHOST')
            setup = Path('/home/rokey/ws_cobot_pjt/ws_dsr/install/local_setup.bash')

            if not setup.exists():
                raise FileNotFoundError(f'ROS 모의시험용 드라이버 인터페이스 환경이 없습니다: {setup}')

            boot = f'source /opt/ros/jazzy/setup.bash && source {shlex.quote(str(setup))} && '
            boot += 'export AMENT_PREFIX_PATH="$PWD/install/cable_inspection:$PWD/install/cable_interfaces:$AMENT_PREFIX_PATH" && '
            boot += 'export PYTHONPATH="$PWD/build/cable_inspection:$PWD/install/cable_interfaces/lib/python3.12/site-packages:$PYTHONPATH" && '
            boot += 'export LD_LIBRARY_PATH="$PWD/install/cable_interfaces/lib:$LD_LIBRARY_PATH" && '
            command = ['/bin/bash','--noprofile','--norc','-c',boot+shlex.join(command)]

        else:
            command += ['--ignore='+str(TESTS/'test_standalone_ros.py')]

        # pytest 실행과 로그 저장. 실패해도 가능한 결과를 보고서에 수집한다.
        try:
            result = subprocess.run(command, cwd=WORKSPACE, env=env, stdout=subprocess.PIPE,
                                    stderr=subprocess.STDOUT, text=True, timeout=180)
            (self.output/f'{label}.log').write_text(result.stdout)

            if result.returncode:
                self.errors.append(f'{label}: pytest 종료 코드 {result.returncode}. {label}.log 확인')

        except subprocess.TimeoutExpired as error:
            (self.output/f'{label}.log').write_text(str(error))
            self.errors.append(f'{label}: 180초 제한시간 초과')

        # 실행 결과 XML을 읽어 개별 시험 결과를 등록한다.
        if not xml.exists():
            self.errors.append(f'{label}: 결과 XML 미생성')
            return

        for case in ET.parse(xml).iter('testcase'):
            issue = next((child for child in case if child.tag in {'failure','error','skipped'}), None)
            state = 'PASS' if issue is None else 'SKIP' if issue.tag=='skipped' else 'FAIL'

            self.tests.append(dict(
                suite=label, name=case.get('name', ''), source=case.get('classname', ''),
                status=state, seconds=float(case.get('time', 0)),
                detail='' if issue is None else issue.text or issue.get('message', ''),
            ))



    # 기능: 표 셀의 구분 문자와 줄바꿈을 이스케이프한다.
    #     value: 표에 기록할 수치·문자·None.
    #     반환: Markdown 표에 넣을 문자열. None은 미측정으로 표시한다.
    @staticmethod
    def cell(value):
        return ('미측정' if value is None else str(value)).replace('|','\\|').replace('\n','<br>')



    # 기능: 테스트 통계·수치 비교·체크리스트 근거를 MD 보고서로 저장한다.
    #     인자: 없음. 이번 실행에서 수집한 결과만 사용한다.
    #     반환: 생성한 보고서 경로.
    def write_report(self):
        # 실행에 사용한 소스 버전을 기록한다.
        digest = hashlib.sha256()

        # 실행기는 패키지 소스에 이미 포함된다. 같은 파일을 두 번 해시하지 않는다.
        paths = sorted({*(PACKAGE/'cable_inspection').rglob('*.py'), *TESTS.glob('*.py')})

        for path in paths:
            digest.update(str(path.relative_to(WORKSPACE)).encode())
            digest.update(path.read_bytes())

        # 자동 시험과 수치 비교의 통과·실패 수를 집계한다.
        passed = sum(t['status']=='PASS' for t in self.tests)
        failed = sum(t['status']=='FAIL' for t in self.tests)
        skipped = sum(t['status']=='SKIP' for t in self.tests)
        metric_pass = sum(m['result']=='PASS' for m in self.metrics)

        # 보고서 머리말·실행 요약과 수치 비교 표를 작성한다.
        lines = ['# 검사파트 재현·정량 검증 결과', '', f'- 실행 시각: {self.started}',
            f'- Python: `{sys.executable}`', f'- 검증 기준: 실행기 내부 CHECKLIST 정의 ({len(CHECKLIST)}개 항목)',
            '- 환경: 합성 입력 회귀시험과 선택한 가상 에뮬레이터 Job을 실행. 실물 로봇 운전과 접촉 검증은 하지 않음.',
            f'- 코드 해시(SHA256): `{digest.hexdigest()}`', '', '## 실행 요약', '',
            '| 구분 | 통과 | 실패 | 미실행/건너뜀 |', '|---|---:|---:|---:|',
            f'| 자동 테스트 | {passed} | {failed} | {skipped} |',
            f'| 정량 비교 | {metric_pass} | {len(self.metrics)-metric_pass} | 0 |',
            f'| 실행/환경 오류 | — | {len(self.errors)} | — |', '',
            '**주의:** 여기서 PASS는 코드 검증의 기대 결과와 일치한다는 뜻이다. 제품 판정 FAIL/SYSTEM_ERROR를 기대한 시험도 정확히 재현되면 검증 PASS다.',
            '자동 시험 통과율은 실물 적합성이나 체크리스트 전체 완료율이 아니다.', '',
            '## 수치·명령 비교', '',
            '힘·폭·위치는 합성 입력이다. 허용오차 0.000001은 계산 결과 비교용이며 실제 장비 정밀도 기준이 아니다.',
            'force/short/distance/timeout/stable/grip_timeout 입력과 접촉 샘플은 evidence/에 저장했다.', '',
            '| 시나리오 | 항목 ID | 지표 | 기대값 | 관측값 | 단위 | 절대오차 | 허용오차 | 검증 |',
            '|---|---|---|---|---|---|---|---|---|']

        for m in self.metrics:
            lines.append('| '+' | '.join(self.cell(m[k]) for k in
                ('scenario','ids','metric','expected','actual','unit','error','tolerance','result'))+' |')

        # 체크리스트마다 기존 시험 결과를 연결해 확인 범위를 표시한다.
        lines += ['', '## 체크리스트별 자동 검증 범위', '',
            '자동 부분 통과는 해당 항목의 아래 테스트 범위만 확인한 것이다. 모든 현장 시나리오를 확인한 뜻이 아니다.',
            'A04/A05의 모든 장비 상태 조합, F02의 모든 모션 시점, G06의 모든 HOME 중 명령 조합 등은 추가 확인이 필요하다.',
            'V(가상 로봇 실제 운전)·R(실물) 항목의 현장 확인란은 직접 실행 후 작성한다.', '',
            '| ID | 확인 내용 | 자동 결과 | 통과/대상 | 시험 근거 | 현장 확인 |',
            '|---|---|---|---:|---|---|']

        for ident, (title, prefixes) in CHECKLIST.items():
            # 이미 수집한 결과를 ID별로 연결한다. 다른 ID가 같은 시험을 참조해도 재실행하지 않는다.
            hits = [t for t in self.tests if any(t['name'].startswith(p) for p in prefixes)]
            ok = sum(t['status']=='PASS' for t in hits)
            missing = [p for p in prefixes if not any(t['name'].startswith(p) for t in hits)]

            state = ('자동 실패' if any(t['status']=='FAIL' for t in hits) else
                     '자동 부분 통과' if hits and ok==len(hits) and not missing else
                     '일부 미실행' if hits else '미검증')

            refs = ', '.join(sorted({t['source']+'.'+t['name'].split('[')[0] for t in hits})) or '자동 시험 연결 없음'

            if missing:
                refs += '; 미실행: ' + ', '.join(missing)

            lines.append('| ' + ' | '.join(self.cell(v) for v in (
                ident, title, state, f'{ok}/{len(hits)}', refs, '[ ] 확인자/날짜/증거',
            )) + ' |')

        # 개별 시험 결과와 실패 근거를 기록한다.
        lines += ['', '## 개별 자동 시험', '', '| 종류 | 시험 | 결과 | 소요시간(s) |', '|---|---|---|---:|']

        for t in self.tests:
            lines.append(f"| {t['suite']} | {self.cell(t['source']+'.'+t['name'])} | {t['status']} | {t['seconds']:.6f} |")

        lines += ['', '## 오류·실패 상세', '']
        lines += ['```text\n'+e+'\n```' for e in self.errors]

        for t in self.tests:
            if t['status'] != 'PASS':
                lines += [f"### {t['name']}", '```text\n' + t['detail'] + '\n```']

        if not self.errors and not failed and not skipped and metric_pass == len(self.metrics):
            lines.append('실행한 자동 시험에서 오류·실패·건너뜀 없음.')

        if self.virtual_result is not None:
            result = self.virtual_result
            lines += ['', '## 가상 에뮬레이터 전체 Job', '',
                f"- 실행 ID: `{result['run_id']}`",
                f"- 레시피: `{result['recipe_id']}` / 포인트 {result['point_total']}개",
                f"- 판정 집계: `{json.dumps(result['counts'], ensure_ascii=False)}`",
                f"- 실행 데이터: `{result['result_dir']}`",
                '- 완료 기준: 검사 Main이 SYSTEM_READY로 복귀하고 job_summary.json에 INSPECTION_COMPLETE 기록.',
                '- 제품 판정 PASS 개수는 가상 케이블 저항의 적합성 지표가 아니다.']

        # 자동 검증 밖의 확인 사항을 덧붙이고 파일을 저장한다.
        lines += ['', '## 적용 정책과 실물 확인 범위', '',
            '- 수동 HOME은 현재 Work Access 도달을 확인하면 직접 설정 Home 경로로 이동한다. Access 이외 작업영역 내부에서는 Open·후퇴·Access를 거친다.',
            '- Ready/Entry 접근 미도달은 후속 파지·접촉 이동을 차단한다. 접촉 Entry/Pull의 미도달 기록·판정 정책과 구분한다.',
            '- 실제 접근 방향·Open 25 mm·후퇴 30 mm·케이블 간섭·판정 임계값 적합성은 R01~R05 실물 확인 대상이다.',
            '- 메뉴 2 또는 `--with-virtual`은 미리 실행한 virtual bringup을 확인하고 실제 가상 Job을 수행한다. 현재 ROS 도메인과 LOCALHOST만 사용한다.']

        report = self.output / 'report.md'
        report.write_text('\n'.join(lines)+'\n', encoding='utf-8')

        return report



# 기능: 검증을 실행하고 MD 보고서 위치와 종료 코드를 반환한다.
#     인자: --output 결과 폴더, --with-virtual 가상 Job, --with-ros 기존 모의 통합시험.
#     반환: 모두 통과하면 0, 실패·미실행 자동 시험·환경 오류가 있으면 1.
def main():
    parser = argparse.ArgumentParser(description='검사파트 재현·정량 검증 및 MD 보고서 생성')
    parser.add_argument(
        '--output', type=Path,
        default=WORKSPACE / 'results/checklist' / datetime.now().strftime('%Y%m%d_%H%M%S_%f'),
    )
    parser.add_argument('--with-virtual', action='store_true', help='메뉴 없이 가상 에뮬레이터 Job 실행')
    parser.add_argument('--with-ros', action='store_true', help='기존 모의 ROS 통합시험 추가')
    args = parser.parse_args()

    # 터미널에서는 실행할 검증 범위를 고른다. 자동 실행은 입력을 기다리지 않는다.
    include_virtual_test = args.with_virtual

    if not include_virtual_test and not args.with_ros and sys.stdin.isatty():
        print('검사파트 검증 범위를 선택하세요.')
        print('1. 실물 장비 없는 회귀시험 + 정량 비교 (ROS 2 환경 필요)')
        print('2. 위 검증 + 에뮬레이터 virtual 전체 Job (가상 bringup 실행 필요)')

        while True:
            try:
                choice = input('선택 [1/2, 기본 1]: ').strip()

            except EOFError:
                choice = '1'

            if choice in ('', '1', '2'):
                include_virtual_test = choice == '2'
                break

            print('1 또는 2를 입력하세요.')

    # 실행 환경과 필수·선택 검증 단계를 준비한다.
    runner = InspectionCheck(args.output)
    sys.path.insert(0,str(PACKAGE))
    started = time.monotonic()
    steps = [('가상 계측', runner.measure_inspection, ()),
             ('START 준비', runner.measure_start, ()),
             ('오프라인 회귀', runner.run_tests, ())]

    if args.with_ros:
        steps.append(('LOCALHOST ROS 통합', runner.run_tests, (True,)))

    if include_virtual_test:
        steps.append(('에뮬레이터 virtual Job', runner.run_virtual, ()))

    # 단계별 오류를 수집하면서 나머지 검증을 계속한다.
    for label, action, call_args in steps:
        print(f'[실행] {label}', flush=True)

        try:
            with contextlib.redirect_stdout(io.StringIO()):
                action(*call_args)

        except Exception:
            runner.errors.append(label+'\n'+traceback.format_exc())

    # 보고서 저장 후 전체 결과와 종료 코드를 출력한다.
    report = runner.write_report()
    success = (bool(runner.tests) and bool(runner.metrics) and not runner.errors
               and all(t['status']=='PASS' for t in runner.tests)
               and all(m['result']=='PASS' for m in runner.metrics))

    print(f"[{'PASS' if success else 'FAIL'}] 테스트 {len(runner.tests)}건 / 정량 비교 {len(runner.metrics)}건 / {time.monotonic()-started:.2f}s")

    if runner.virtual_result is not None:
        virtual = runner.virtual_result
        print(f"[VIRTUAL] {virtual['recipe_id']} / {virtual['point_total']}포인트 / 판정 {virtual['counts']}")

    print(report)

    return 0 if success else 1



if __name__ == '__main__':
    raise SystemExit(main())
