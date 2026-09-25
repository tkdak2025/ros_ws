# Sequence #00 — Main Work Sequence

버전: v4 · 기준일: 2026-09-25 · 범위: 검사파트와 HMI 통신 계약

[v4 문서 안내](../../00_문서안내_v4.md) · [변경 근거·확인 항목](../../01_commons/02_변경추적_및_확인항목_v4.md)

## 목적·책임

Main이 #01, #03~#05, #07을 순서대로 호출하고 #06의 비동기 결과를 집계한다. #02는 HOME 명령 경로이며 정상 START/완료 흐름에 자동 삽입하지 않는다.

## 입력과 시작 조건

검증된 Recipe ID/실행 복사본과 run_id를 받는다. SYSTEM_READY/STOPPED/ERROR에서 활성 context와 Worker가 없을 때 새 START를 받는다. 상태 이름만 바꾸어 장비 점검을 우회하지 않는다. 접수 성공은 Job 성공이 아니다.

## 절차

1. 새 실행 문맥·기록·판정 세대를 준비한다.
2. #01 장비·통신·설정을 점검하고 레시피 순회를 준비한다.
3. 현재 자세를 검사하여 Work Access를 확보한다.
4. Recipe.next_point()로 활성 포인트를 받아 #03→#04→#05를 수행한다. #06은 병행한다.
5. 포인트 수행·판정 결과를 Recipe와 기록에 반영한다. 남은 포인트가 있으면 반복한다.
6. 마지막 포인트 뒤 Work Access로 복귀한다.
7. #07에서 결과·로그 완료를 확인한다. SYSTEM_READY로 대기하며 자동 Home은 없다.

## 실패와 제어

Hard 완료 timeout은 포인트 복구 성공 시 다음 포인트로 진행한다. STOP은 정지 처리·문맥 폐기, 통신/모션/복구 오류는 Job 오류로 처리한다. 어느 경우도 임의 자동 Home을 추가하지 않는다. Pause는 완료점에서 문맥을 유지한다.

## 수용 기준

C01~C07, F01~F05, G01~G03. 실행권은 Main 한 곳에 있어야 하며 Home과 Inspection을 동시에 수행하지 않는다.

## 구현 참조

[담당 소스](../../../../src/cable_inspection/cable_inspection/sequence/main/seq_main.py) · [공통 모션](../../../../src/cable_inspection/cable_inspection/sequence/common/motion.py) · [검증 체크리스트](../03_verification/01_기능검증_체크리스트_v4.md)
