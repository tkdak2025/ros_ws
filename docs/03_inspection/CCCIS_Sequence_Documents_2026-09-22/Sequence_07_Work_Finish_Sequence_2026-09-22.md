> 이 문서는 이전 설계·작업 기록입니다. 현재 기준은 [v4 문서 안내](../../v4/00_문서안내_v4.md)이며, 이후 변경 내용은 [최종결론](../../작업내역/18_최종결론_2026-09-25.md)을 참고하세요. 아래 본문은 이력으로 보존합니다.

> 2026-09-23 설계·구현 정합성 갱신: [05 보류항목 반영 결과](../../작업내역/05_시퀀스_보류항목_반영결과_2026-09-23.md)를 함께 적용한다. 같은 이름의 기존 PDF는 갱신 전 보존본이다.

# Sequence #07 - Work Finish Sequence

**프로젝트:** CCCIS (Contact-based Cable Connection Inspection System)  
**환경:** Doosan M0609 + OnRobot RG2 / No-Vision Phase  
**작업 단위:** Recipe 1회 실행 = Job 1개  
**외부 Trigger:** HMI 통신 기반 START / PAUSE / RESUME / STOP / HOME_RETURN  
**작성 기준일:** 2026-09-22


## 1. 목적

Recipe 단위 Job의 모든 검사 동작이 끝난 후 Robot을 `work_Access_safe_pose`에 위치시키고, #06 Inspection Judgment/Work Monitoring 상태를 기준으로 검사 완료 여부를 검증한다. 모든 마무리 조건이 만족되면 Work Access에 머무른 채 Job을 정상 종료한다.

## 2. 설계 의도

#01 Work Initialize가 '작업을 시작해도 되는가'를 확인하는 Gate라면, #07 Work Finish는 '이 Job을 종료해도 되는가'를 확인하는 Completion Gate다.

Work Finish는 Point의 PASS/FAIL을 다시 판정하지 않는다. #06이 생성/관리한 결과와 진행 상태를 확인한다.

## 3. 진입 조건

- Execution List의 마지막 Point Robot Motion 완료
- 마지막 Point의 ready_pose 복귀 완료
- Robot이 `work_Access_safe_pose`로 복귀 가능

## 4. Sequence Flow

```text
LAST POINT MOTION DONE
    |
    v
ready_pose
    |
    v
Move to work_Access_safe_pose
    |
    v
WORK_FINISH_CHECK
    |
    +-- Execution List all executed ?
    +-- All enabled Points motion completed ?
    +-- pending_judgments == 0 ?
    +-- Every Point has PASS/FAIL/SYSTEM_ERROR ?
    +-- Result/Log saved ?
    +-- HMI communication available ?
    |
    v
ALL COMPLETE ?
  +-- NO --> WORK_FINISH_NOT_COMPLETE
  |          -> HMI status/reason
  |          -> remain safe at work_Access_safe_pose
  |
  +-- YES
        |
        v
Aggregate Job Summary
        |
        v
HMI JOB_COMPLETE Status
        |
        v
WORK_FINISH_SUCCESS
        |
        v
#02 HOME RETURN
        |
        v
home_pose
        |
        v
Operating Stop / SYSTEM_READY
```

## 5. Flow 용어 설명

| 용어 | 설명 |
|---|---|
| Completion Gate | Job을 종료해도 되는지 확인하는 최종 상태 검증 |
| pending_judgments | 비동기 #06 처리 중 아직 완료되지 않은 Point 수/목록 |
| Job Summary | PASS/FAIL/SYSTEM_ERROR 수량 및 Job 수행상태 요약 |
| NOT COMPLETE | 검사 결과가 나쁘다는 뜻이 아니라 Job 종료 조건이 충족되지 않은 상태 |

## 6. 세부 동작 및 판단 조건

체크 항목:

1. Execution List 전체 순회 완료
2. 모든 enabled Point Robot Motion 완료
3. pending_judgments 없음
4. 모든 Point에 `PASS / FAIL / SYSTEM_ERROR` 중 하나의 Result 존재
5. 각 Point motion_status=SUCCESS 확인
6. 검사 Result 및 필요한 Log 저장 완료
7. HMI에 완료 상태를 전달할 수 있는 통신 상태

중요:

- Point Result에 FAIL이 있어도 Work Finish는 SUCCESS 가능
- SYSTEM_ERROR도 다른 완료 조건이 만족되면 Job 종료 가능
- Judgment Pending, Result 누락, Sequence Error가 있으면 NOT COMPLETE

## 7. 정상 종료 조건

- 모든 Completion Check PASS
- Job Summary 생성/저장
- HMI에 Job Complete 상태 전달
- work_Access_safe_pose 도달 확인
- #07 검사 결과·기록 완료
- Robot Operating Stop

## 8. 비정상 / 예외 처리

- Pending Judgment 존재 -> 안전 위치에서 완료 대기
- motion_status 실패 또는 결과/로그 누락 -> 완료 보류
- HMI Comm Loss -> Common #01 정책 적용
- Work Finish 중 Robot Error -> ERROR, 자동 Home Return 강제 금지

## 9. 상위·하위 Sequence Interface

**상위:** #00 Main Work  
**참조:** #06 Work Monitoring Runtime State  
**다음:** Work Access에서 SYSTEM_READY 대기

Job Summary 예시:

```text
job_id
recipe_id
point_total
pass_count
fail_count
system_error_count
start_time
end_time
job_status
```

## 10. 코드 구현 포인트

- `check_work_completion(job_context)`는 Robot Motion과 분리된 순수 상태 검사 함수로 구현 가능
- #07 자체에서 Point Result를 재계산하지 않음
- `work_Access_safe_pose`에서만 Completion 대기하도록 상태를 단순화
- Completion 성공 후 Work Access에서 대기; 별도 Scheduler/Next Job 자동실행 없음

## 11. 사용자 확정 PR #9 완료 정책

전체 포인트 순회 완료, pending_judgments 없음, 각 포인트 motion_status=SUCCESS, 유효한 PASS/FAIL/SYSTEM_ERROR 결과 및 log_saved=true가 완료 조건이다. adaptive_grip_status/pull_status/judgment_status는 별도 완료 게이트로 검사하지 않는다. SYSTEM_ERROR도 이 조건을 만족하면 Job 종료와 Work Access 대기가 가능하다.

기록·자원 정리·force_data_id 처리도 PR #9로 복원했다. 최종 Home 이후 summary를 다시 쓰는 PR #10 보완은 적용하지 않는다.

## 완료 위치 변경 (2026-09-25 사용자 확정)

검사 완료 후 자동 Home 복귀를 제거했다. 마지막 포인트 → Work Access → 판정·기록 완료 확인 → SYSTEM_READY 순서로 종료한다. Access 복귀 또는 완료 조건이 실패하면 성공으로 처리하지 않는다. 수동 HOME_RETURN은 별도 명령으로 유지한다.
