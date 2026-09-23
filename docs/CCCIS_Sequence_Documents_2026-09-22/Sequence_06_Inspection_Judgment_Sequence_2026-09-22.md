# Sequence #06 — Inspection Judgment & Work Monitoring

갱신: 2026-09-23. [05 반영 결과](../05_시퀀스_보류항목_반영결과_2026-09-23.md)가 기준이며 기존 PDF는 이전 설계 보존본이다.

## 역할

Pull 측정 요약을 비동기 Queue/Worker로 처리한다. 다음 포인트 이동을 기다리게 하지 않으며, 포인트 결과와 사유 및 처리 상태를 발행하고 #07 완료 게이트에 전달한다.

## 판정 순서

1. 측정/기준 누락·비유한 값·Robot/Tool/Motion 오류·TIMEOUT 등 유효하지 않은 종료는 SYSTEM_ERROR / judgment_status=ERROR / sequence_status=INCOMPLETE.
2. 정상 FORCE_LIMIT 또는 MAX_DISTANCE 검사에서 Pull 전체 구간 최소 실측 폭이 16 mm 미만이면 FAIL_GRIP_WIDTH.
3. MAX_DISTANCE이면 FAIL_MAX_DISTANCE.
4. FORCE_LIMIT인데 실제 최대 힘이 기준 미만이면 SYSTEM_ERROR.
5. 기준 힘 도달 및 변위 허용치 이내면 PASS_FORCE_DISPLACEMENT_OK, 변위 초과면 FAIL_DISPLACEMENT_LIMIT.

PASS/FAIL은 판단 완료를 뜻하며 judgment_status=COMPLETED, sequence_status=SUCCESS다. SYSTEM_ERROR는 제품 불량이 아니라 검사 미완료이며 #07 정상 종료를 허용하지 않는다. 결과 문자열이 존재한다고 판정 완료로 보지 않는다.

## 기준과 출력

- 기준 힘: LAN 15 N 유지(사용자 확정), USB는 해당 레시피 값. 전송된 snapshot 기준을 판정에 사용한다.
- 변위 기본 5 mm는 판정 기준이며 모션 정지 조건이 아니다.
- Soft 종료 기준 폭, Pull 전체 최소 폭, 두 값의 부호 있는 차이를 기록한다. 차이로 Slip을 별도 판정하지 않는다.
- 옛 MISSING/미정 Slip threshold 정책은 후속 FAIL_GRIP_WIDTH/SYSTEM_ERROR 정책으로 대체한다.
- `InspectionResult`로 run_id/recipe/point 식별, 판정·사유·종료 사유, 힘·변위·폭·당시 기준, force_data_id를 발행한다.
- 원시 기록은 검사 PC의 samples.jsonl과 point_id로 연결한다. HMI DB 저장 여부는 검사 로컬 저장과 별개다.
- 통신 복구는 자동 판정 변경이나 자동 모션 재개의 근거가 아니다.
