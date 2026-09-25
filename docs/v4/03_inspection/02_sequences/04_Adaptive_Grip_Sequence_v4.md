# Sequence #04 — Adaptive Grip Sequence

버전: v4 · 기준일: 2026-09-25 · 범위: 검사파트와 HMI 통신 계약

[v4 문서 안내](../../00_문서안내_v4.md) · [변경 근거·확인 항목](../../01_commons/02_변경추적_및_확인항목_v4.md)

## 목적·입력

포인트의 grip_setting, entry_setting과 Entry task의 자세를 사용한다. Tool 축 접촉 진입으로 파지를 안정화하고 Pull 전 Hard Grip을 완료한다.

## 절차

1. soft_close_width_mm/soft_force_n으로 Soft Grip 명령을 보낸다.
2. 명령 성공 후 Tool +Z 방향 접촉 진입을 시작한다. Soft 목표폭·busy 해제를 기다리지 않는다.
3. 힘 변화 크기, 실제 이동거리, 모션 종료, 포인트 timeout을 관찰한다. 종료 사유와 실측값을 기록한다.
4. Entry가 끝난 뒤 새 폭 피드백을 읽어 soft_width_mm으로 기록한다.
5. hard_width_mm/hard_force_n으로 Hard Grip한다.
6. 목표폭 오차 2.5 mm 이내 또는 약 1.5초(최소 1.45초) 폭 변화 범위 0.2 mm 이내이면 완료한다.
7. HARD_GRIP_DONE 이후 #05로 진행한다.

## 실패·복구

Hard 완료 20초 제한을 넘겨 GripCompletionTimeout이 발생하면 해당 포인트 Pull을 생략한다. TIMEOUT/SYSTEM_ERROR 판정을 요청하고 Open→Entry task MoveL→Ready MoveJ로 복구한 후 다음 포인트로 간다.

Open 폭 확인·복귀·서비스 통신 실패는 이 복구 성공으로 간주하지 않는다. STOP도 계속 진행하지 않는다. busy는 어느 단계의 완료 조건도 아니다. Entry 접촉 미도달 자체는 전체 Job 예외 조건이 아니지만 장비 통신이나 공통 모션 제한 실패는 별개다.

## 출력·검증

Entry 종료·변위, 실측 Soft 폭, Hard 측정 결과, adaptive_grip_done을 남긴다. 검증: D03~D09,R04. 안정 폭은 접촉 완료를 추정하는 기준이며 실제 케이블 파지 성공을 절대적으로 보증하지 않는다.

## 구현 참조

[담당 소스](../../../../src/cable_inspection/cable_inspection/sequence/inspection/seq_inspection.py) · [공통 모션](../../../../src/cable_inspection/cable_inspection/sequence/common/motion.py) · [검증 체크리스트](../03_verification/01_기능검증_체크리스트_v4.md)
