# Sequence #04 — Adaptive Grip

갱신: 2026-09-23. [05 반영 결과](../05_시퀀스_보류항목_반영결과_2026-09-23.md)와 현재 후속 파지 규칙을 적용한다. 기존 PDF는 갱신 전 보존본이다.

## 목적과 진입 조건

#03 Entry MoveL 목표 도달 확인 뒤 Soft Grip과 추가 진입을 수행하고 Hard Grip 완료 후 Pull을 허용한다. 케이블 체결 판정은 이 단계에서 하지 않는다.

## 실행 순서

1. 레시피 Soft Grip 명령.
2. Entry task의 ZYZ 자세로 구한 Tool +Z 방향으로 추가 직선 진입.
3. 거리/힘 Guard/timeout 중 먼저 도달한 조건에서 감속 정지.
4. Soft 동작 종료 확인 후 실측 `soft_width_mm` 기록.
5. 레시피 Hard Grip 명령 및 그리퍼 동작 완료 확인.
6. `HARD_GRIP_DONE` 완료점 확인 후 #05 Pull.

추가 진입이 짧았다는 이유로 제품 FAIL로 판단하지 않는다. 별도 고정 settling delay는 없다. Soft 동작 종료 확인은 폭 측정의 유효성을 위한 것이다. Hard 목표 폭과 실제 폭의 일치로 케이블 파지 성공을 추정하지 않는다.

## 조건과 예외

Entry 거리 상한 25 mm, timeout 상한 10 s. force_guard_n과 Soft/Hard 목표 폭·힘은 레시피의 유한한 양수다. 설정 상한 위반은 전송/초기화 검증에서 거절한다. 실제 그리퍼/모션 오류는 상위에 전달하고 Pull을 시작하지 않는다.

## 후속 합의

옛 Hard 직후 폭 기준은 Soft 종료 기준 폭으로 대체한다. 별도 entry_direction 전송 대신 Entry ABC로 방향을 정한다. 폭 차이는 기록용이고 Pull 중 최소 폭 16 mm 미만 판정은 #06에서 수행한다. 이 합의로 인해 구형 PDF의 Hard 폭/Slip 설명은 사용하지 않는다.
