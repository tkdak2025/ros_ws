# Concept 05 — Pull Inspection

버전: v4 · 기준일: 2026-09-25 · 범위: 검사파트와 HMI 통신 계약

[v4 문서 안내](../../00_문서안내_v4.md) · [변경 근거·확인 항목](../../01_commons/02_변경추적_및_확인항목_v4.md)

## 방향과 기준

Pull은 Entry task에서 계산한 Tool +Z의 반대로 수행한다. Safe Escape는 현재 TCP 자세에서 계산하므로 둘의 기준 자세가 다를 수 있다. Tool −Z는 BASE −Z와 같지 않다.

Pull 시작 위치·힘을 기준으로 실제 변위와 힘 변화를 측정한다. 이동거리는 목표 명령값이 아니라 이동 방향에 투영한 실제 TCP 변위를 사용한다. Pull 힘은 축 방향 힘 변화의 크기, Entry guard는 힘 변화 벡터의 크기로 계산한다.

## 종료 사유

| 관측 | Pull 종료 | 후속 처리 |
|---|---|---|
| 기준 힘 도달 | FORCE_LIMIT | 정지 후 계측 확정, 판정 요청 |
| 목표거리 도달 | MAX_DISTANCE | 실제 이동값 기록, 판정 요청 |
| 힘·거리 전 모션 종료 | STOPPED_SHORT | Job 예외로 단정하지 않고 SYSTEM_ERROR 판정 |
| 포인트 제한시간 | TIMEOUT | 정지·계측·SYSTEM_ERROR 판정 |
| STOP/통신·공통 모션 이상 | 제어 중단/오류 | Main 중단 또는 오류 처리 |

같은 관측에서 힘 기준을 우선 확인한다. 정지 요청 뒤 감속 구간도 계측하여 최대 힘과 최소 폭을 포함한다. 설정 힘과 실제 peak가 같다고 가정하지 않는다.

## 판정과 복귀 병행

측정 확정→판정 Queue 제출→Open→Entry task MoveL→Ready MoveJ 순서다. 매 포인트에서 판정 완료를 기다리지 않는다. 최종 Work Finish는 모든 결과·기록을 기다린다.

현 구현에 기준 힘을 유지하는 별도 hold 시험은 없다. 폭 차이는 기록하지만 독립 합격 임계값으로 사용하지 않는다. 힘·폭·변위 기준의 실물 적합성은 정상/불량 데이터 분포로 검증한다.

근거: [#05 상세 설계](../02_sequences/05_Pull_Inspection_Sequence_v4.md) · [#06 판정 순서](../02_sequences/06_Inspection_Judgment_Sequence_v4.md).
