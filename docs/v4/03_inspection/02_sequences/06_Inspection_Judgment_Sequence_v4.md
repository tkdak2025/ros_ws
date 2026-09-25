# Sequence #06 — Inspection Judgment Sequence

버전: v4 · 기준일: 2026-09-25 · 범위: 검사파트와 HMI 통신 계약

[v4 문서 안내](../../00_문서안내_v4.md) · [변경 근거·확인 항목](../../01_commons/02_변경추적_및_확인항목_v4.md)

## 책임·입력

InspectionJudgmentNode의 Queue Worker가 실행한다. 입력은 run_id/recipe/point 식별 정보, Pull 종료 사유, 최대 힘, 실제 변위, 요구 힘·허용 변위, Soft 폭·Pull 최소 폭이다. 모션 실행과 독립한다.

## 판정 우선순위 — 현재 코드 순서

아래 표를 위에서부터 적용한다. 겹치는 경우 먼저 해당한 결과를 반환한다.

| 순서 | 조건 | 결과 / 사유 |
|---|---|---|
| 1 | 힘·변위·기준값이 bool/비수치/비유한, 음수 또는 요구 힘≤0 | SYSTEM_ERROR |
| 2 | STOPPED_SHORT | SYSTEM_ERROR: 힘/최대거리 전에 모션 종료 |
| 3 | FORCE_LIMIT/MAX_DISTANCE 외 종료(TIMEOUT 등) | SYSTEM_ERROR |
| 4 | Soft/Pull 폭이 비유한·비수치·음수 | SYSTEM_ERROR |
| 5 | Pull 최소 폭 <16 mm | FAIL / FAIL_GRIP_WIDTH |
| 6 | MAX_DISTANCE | FAIL / FAIL_MAX_DISTANCE |
| 7 | FORCE_LIMIT인데 peak force < required force | SYSTEM_ERROR: 종료 사유/계측 불일치 |
| 8 | FORCE_LIMIT, actual displacement ≤ normal limit | PASS / PASS_FORCE_DISPLACEMENT_OK |
| 9 | FORCE_LIMIT, actual displacement > normal limit | FAIL / FAIL_DISPLACEMENT_LIMIT |

폭 16 mm는 폭 실패가 아니며 허용 변위와 같은 값은 PASS 경계다. 폭 실패는 힘 불일치 확인보다 먼저 적용된다. Soft/Pull 폭 차이는 결과에 기록하지만 이 표의 독립 기준은 아니다.

16 mm는 현재 판정 코드의 고정값이다. 레시피의 hard_width_mm과 동일 개념이 아니며 모든 케이블에 검증된 물리 기준이라고 확정하지 않는다(R05).

## 비동기·결과 보호

pending 등록 후 제출한다. run_id와 내부 세대가 다른 결과는 버리고 중복 포인트 요청은 재판정하지 않는다. 복귀 오류로 확정된 결과는 늦은 정상 결과로 덮지 않는다. 결과 송신은 HMI 노드의 콜백 경로를 사용한다.

## 검증

E01~E05: 동등 경계, FORCE/MAX/TIMEOUT/SHORT, 비정상 수치·폭, 중복/이전 실행, 복귀 오류 후 늦은 결과를 확인한다. MISSING/DETACHED는 현 확정 결과에 추가하지 않는다.

## 구현 참조

[담당 소스](../../../../src/cable_inspection/cable_inspection/sequence/inspection/node_inspection.py) · [공통 모션](../../../../src/cable_inspection/cable_inspection/sequence/common/motion.py) · [검증 체크리스트](../03_verification/01_기능검증_체크리스트_v4.md)
