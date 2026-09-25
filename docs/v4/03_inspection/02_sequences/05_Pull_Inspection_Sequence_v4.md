# Sequence #05 — Pull Inspection Sequence

버전: v4 · 기준일: 2026-09-25 · 범위: 검사파트와 HMI 통신 계약

[v4 문서 안내](../../00_문서안내_v4.md) · [변경 근거·확인 항목](../../01_commons/02_변경추적_및_확인항목_v4.md)

## 목적·입력

Hard Grip 이후 Entry에서 계산한 축의 반대로 Pull하여 힘·변위·폭을 계측한다. pull_setting의 force_limit_n, max_distance_mm, timeout_s, speed_mm_s를 사용한다.

## 절차

1. Pull 시작의 실제 TCP·힘을 기준으로 삼는다.
2. Tool −Z 방향 상대 목표로 이동하면서 실제 축방향 변위와 힘 변화를 측정한다.
3. 힘 제한을 우선 검사한다. 이어 모션 종료 시 거리 도달/미도달, 포인트 timeout을 구분한다.
4. 필요한 정지를 요청하고 감속 구간까지 샘플을 수집한다.
5. 최대 힘, 실제 최종 변위, Pull 최소 폭과 종료 사유를 확정한다.
6. #06 판정 요청을 먼저 등록한다.
7. Open→Entry task MoveL(포인트 속도)→Ready MoveJ를 수행한다.

## 출력과 실패

FORCE_LIMIT/MAX_DISTANCE/STOPPED_SHORT/TIMEOUT을 구분한다. 목표거리를 실제 이동값으로 대체하지 않는다. 접촉 미도달·포인트 timeout은 판정 입력으로 남기고 복귀한다. STOP·장비 통신·복귀 실패는 Main의 Job 중단/오류 대상이다. 공통 모션 제한시간도 남아 있으므로 모든 timeout을 계속 진행한다고 해석하지 않는다.

width_delta_mm = pull_width_mm − soft_width_mm이며 기록용이다. 기준 힘 유지 hold나 별도 slip delta 임계값 판정은 구현되어 있지 않다. 복귀 오류가 나면 이미 요청한 정상 판정이 나중에 오류 결과를 덮지 않도록 한다.

검증: D08~D11,E01~E05. real/virtual 모두 같은 상위 순서지만 가상 드라이버에 실제 접촉 힘이 자동 생성되는 것은 아니다.

## 구현 참조

[담당 소스](../../../../src/cable_inspection/cable_inspection/sequence/inspection/seq_inspection.py) · [공통 모션](../../../../src/cable_inspection/cable_inspection/sequence/common/motion.py) · [검증 체크리스트](../03_verification/01_기능검증_체크리스트_v4.md)
