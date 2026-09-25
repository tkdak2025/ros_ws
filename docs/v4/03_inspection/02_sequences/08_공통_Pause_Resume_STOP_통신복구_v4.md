# 공통 시퀀스 — Pause/Resume/STOP/통신복구

버전: v4 · 기준일: 2026-09-25 · 범위: 검사파트와 HMI 통신 계약

[v4 문서 안내](../../00_문서안내_v4.md) · [변경 근거·확인 항목](../../01_commons/02_변경추적_및_확인항목_v4.md)

## Pause와 Resume

PAUSE는 현재 원자 동작의 완료점에서 멈추도록 요청한다. 포인트·단계·실행 복사본 문맥을 유지한다. RESUME은 PAUSED이며 제어 통신이 유효할 때 명시적으로 요청하고 장비 운전 가능 상태를 재확인한 뒤 이어간다. 통신이 복구됐다는 이유만으로 자동 재개하지 않는다.

## STOP

STOP은 완료점 Pause와 다르다. 제어 감시에서 정지를 요청하고 실제 모션 종료를 확인한 뒤 Job을 끝내며 문맥을 폐기한다. 통신 서비스 응답 대기 중에도 정지 요청을 확인하도록 한다. 자동 Home은 없다. 정리가 끝난 STOPPED/ERROR의 새 START는 새 run_id와 Access 준비부터 시작한다.

## Heartbeat 유실

| 사건 | 처리 |
|---|---|
| heartbeat 만료(현재 2초) | Safe Pause 요청 |
| 복구 제한 안에 heartbeat 회복 | 통신 회복 기록, 사용자 RESUME 대기 |
| 복구 제한 초과(현재 30초) | COMM_ERROR·STOP 처리 |

hmi/terminal은 각 제어 모드 heartbeat를 사용한다. 다른 모드의 명령 채널을 동시에 활성화하지 않는다. Robot 상태 stale 표시는 운전 명령으로 오인하지 않는다.

## 실패와 종료 수명

장비 통신·Open·일반 이동·복귀 실패를 파지 timeout의 국소 복구와 구분한다. 종료 시 새 명령 접수를 막고 STOP을 요청한 뒤 Worker가 끝날 때까지 executor 응답 처리를 유지한다. 상태 수집은 모션 응답 대기와 독립적으로 진행되어야 한다.

검증: A02,A03,F01~F05,G06,H04. 소프트웨어 STOP/상태 표시는 하드웨어 E-STOP이나 제조사 보호정지 기능을 대신하지 않는다.

## 구현 참조

[담당 소스](../../../../src/cable_inspection/cable_inspection/sequence/main/seq_main.py) · [공통 모션](../../../../src/cable_inspection/cable_inspection/sequence/common/motion.py) · [검증 체크리스트](../03_verification/01_기능검증_체크리스트_v4.md)
