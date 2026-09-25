# Sequence #07 — Work Finish Sequence

버전: v4 · 기준일: 2026-09-25 · 범위: 검사파트와 HMI 통신 계약

[v4 문서 안내](../../00_문서안내_v4.md) · [변경 근거·확인 항목](../../01_commons/02_변경추적_및_확인항목_v4.md)

## 목적·진입

모든 활성 포인트의 동작 후 Work Access로 복귀하고 판정·기록의 완료를 확인한다. Home을 호출하지 않는다.

## 절차와 완료 조건

1. Main이 Work Access MoveJ를 수행하고 완료점을 기록한다. 실패하면 완료 처리하지 않는다.
2. 판정 결과를 수집하여 Recipe와 검사/판정 파일에 반영한다.
3. 활성 포인트가 있고, 전체 순회 수가 맞고, pending이 없고, 모든 포인트의 motion_status가 SUCCESS이며 유효 결과와 저장 완료가 있는지 확인한다.
4. HMI 통신 상태를 확인하고 결과별 개수와 시작/종료 시각을 요약한다.
5. Recipe 실행을 끝내고 completed=true, SYSTEM_READY를 기록한다. Access에서 다음 명령을 기다린다.

PASS·FAIL·SYSTEM_ERROR의 개수는 각각 집계한다. 복구 동작이 끝난 SYSTEM_ERROR 포인트가 포함될 수 있으며, Job 완료를 제품 전체 PASS라고 해석하지 않는다.

## 미완료 처리

judgment_timeout_s(현재 10초) 내 완료되지 않으면 NOT_COMPLETE 요약과 미완료/대기 포인트를 남기고 Pause한다. RESUME에서 다시 확인하고 STOP이면 종료한다. 저장 예외·Access 실패는 상위 Job 오류다.

HMI DB의 저장 완료를 기다리는 기능은 현재 없으며 로컬 로그 완료와 혼동하지 않는다. 최종 결과 발행/저장 및 화면 반영은 ID로 대조한다.

검증: G01~G03,H01~H03,E04. 구버전의 #07→#02 자동 Home 연결은 v4에서 적용하지 않는다.

## 구현 참조

[담당 소스](../../../../src/cable_inspection/cable_inspection/sequence/main/seq_main.py) · [공통 모션](../../../../src/cable_inspection/cable_inspection/sequence/common/motion.py) · [검증 체크리스트](../03_verification/01_기능검증_체크리스트_v4.md)
