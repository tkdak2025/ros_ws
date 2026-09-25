# Concept 03 — Adaptive Grip

버전: v4 · 기준일: 2026-09-25 · 범위: 검사파트와 HMI 통신 계약

[v4 문서 안내](../../00_문서안내_v4.md) · [변경 근거·확인 항목](../../01_commons/02_변경추적_및_확인항목_v4.md)

## 현재 의미

현재 Adaptive Grip은 Soft Grip 상태로 Tool 축을 따라 진입하여 파지를 안정화한 후 Hard Grip을 수행하는 절차다. 초기 구상의 Micro-Wiggle/Fine Alignment를 모두 구현했다는 명칭이 아니다.

Soft 명령→Tool +Z 접촉 진입→새 실측 Soft 폭 기록→Hard Grip 순서다. Soft 목표폭에 도달하지 않거나 busy=true라고 진입을 막지 않는다. 통신 성공과 사용할 피드백의 유효성은 별도 조건이다.

## Hard Grip 완료와 실패

목표폭 허용오차 안에 들어오거나, 최근 약 1.5초 폭이 0.2 mm 범위에서 안정되면 완료로 처리한다. 목표폭과 일치하지 않더라도 케이블 접촉으로 폭이 안정될 수 있기 때문이다. 현재 공통 폭 허용오차는 2.5 mm, 파지 완료 제한시간은 20초다.

안정화 창의 실제 샘플 포함 시간은 최소 1.45초를 요구한다. 이 값은 센서 정밀도 인증값이 아니라 구현상 완료 확인 조건이다. Hard 명령의 힘은 RG2 명령 설정이며, 이 완료 로직이 그립 힘 실측 도달을 확인한다는 뜻은 아니다.

Hard 완료 timeout만 포인트 복구 대상으로 삼는다. Pull을 생략하고 SYSTEM_ERROR 판정을 요청한 후 Open→Entry 직선 복귀→Ready 관절 복귀한다. 복구가 성공하면 다음 포인트, Open·복귀·통신이 실패하면 Job 오류다. 타임아웃을 모두 없애거나 장비 실패를 무조건 무시하는 정책은 아니다.

## 레시피 폭과 허용오차

BMW에서 ±5 mm로 바꾼 것은 Soft close를 기준으로 Open/Hard 목표폭의 간격이다. 공통 목표폭 도달 허용오차를 ±5 mm로 변경한 것이 아니다. 실제 목표값은 [Recipe 컨셉](04_Recipe_컨셉_v4.md)에 기록한다.

busy는 관측 정보다. 폭·힘·변위와 단계명으로 동작을 추적하되 busy에 따라 정지·재개하지 않는다. 안정화 조건의 실제 파지 적합성은 R04로 확인한다.

근거: [검사 시퀀스](../../../../src/cable_inspection/cable_inspection/sequence/inspection/seq_inspection.py) · [#04 상세 설계](../02_sequences/04_Adaptive_Grip_Sequence_v4.md).
