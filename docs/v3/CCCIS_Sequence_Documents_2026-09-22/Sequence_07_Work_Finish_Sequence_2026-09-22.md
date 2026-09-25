# Sequence #07 - Work Finish Sequence

**프로젝트:** CCCIS (Contact-based Cable Connection Inspection System)  
**환경:** Doosan M0609 + OnRobot RG2 / No-Vision Phase  
**작업 단위:** Recipe 1회 실행 = Job 1개  
**외부 Trigger:** HMI 통신 기반 START / PAUSE / RESUME / STOP / HOME_RETURN  
**작성 기준일:** 2026-09-22


## 1. 목적

Recipe 단위 Job의 모든 검사 동작이 끝난 후 Robot을 `work_Access_safe_pose`에 위치시키고, #06 Inspection Judgment/Work Monitoring 상태를 기준으로 검사 완료 여부를 검증한다. 모든 마무리 조건이 만족되면 Home Return을 허용하고 Job을 정상 종료한다.

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
    +-- Every Point has PASS/FAIL/MISSING ?
    +-- No Point INCOMPLETE/ERROR ?
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
| Job Summary | PASS/FAIL/MISSING 수량 및 Job 수행상태 요약 |
| NOT COMPLETE | 검사 결과가 나쁘다는 뜻이 아니라 Job 종료 조건이 충족되지 않은 상태 |

## 6. 세부 동작 및 판단 조건

체크 항목:

1. Execution List 전체 순회 완료
2. 모든 enabled Point Robot Motion 완료
3. 모든 #06 Judgment 완료
4. 모든 Point에 `PASS / FAIL / MISSING` 중 하나의 Result 존재
5. Point Incomplete/Error 없음
6. 검사 Result 및 필요한 Log 저장 완료
7. HMI에 완료 상태를 전달할 수 있는 통신 상태

중요:

- Point Result에 FAIL이 있어도 Work Finish는 SUCCESS 가능
- Point Result에 MISSING이 있어도 Judgment 자체가 정상 완료되었다면 Work Finish는 SUCCESS 가능
- Judgment Pending, Result 누락, Sequence Error가 있으면 NOT COMPLETE

## 7. 정상 종료 조건

- 모든 Completion Check PASS
- Job Summary 생성/저장
- HMI에 Job Complete 상태 전달
- #02 Home Return SUCCESS
- home_pose 도달
- Robot Operating Stop

## 8. 비정상 / 예외 처리

- Pending Judgment 존재 -> 안전 위치에서 완료 대기
- Point Incomplete/Error -> Job 정상완료 금지, HMI Reason 전달
- HMI Comm Loss -> Common #01 정책 적용
- Work Finish 중 Robot Error -> ERROR, 자동 Home Return 강제 금지

## 9. 상위·하위 Sequence Interface

**상위:** #00 Main Work  
**참조:** #06 Work Monitoring Runtime State  
**다음:** #02 Home Return

Job Summary 예시:

```text
job_id
recipe_id
point_total
pass_count
fail_count
missing_count
start_time
end_time
job_status
```

## 10. 코드 구현 포인트

- `check_work_completion(job_context)`는 Robot Motion과 분리된 순수 상태 검사 함수로 구현 가능
- #07 자체에서 Point Result를 재계산하지 않음
- `work_Access_safe_pose`에서만 Completion 대기하도록 상태를 단순화
- Completion 성공 후 내부 전이로 Home Return 수행; 별도 Scheduler/Next Job 자동실행 없음
