# Sequence #03 — Point Transition Sequence

버전: v4 · 기준일: 2026-09-25 · 범위: 검사파트와 HMI 통신 계약

[v4 문서 안내](../../00_문서안내_v4.md) · [변경 근거·확인 항목](../../01_commons/02_변경추적_및_확인항목_v4.md)

## 목적·입력

포인트의 ready_pose와 entry_pose로 접근한다. 케이블을 따라 들어가는 접촉 진입은 #04다.

## 명령 순서

1. 포인트 soft_open_width_mm/soft_force_n으로 Open한다.
2. ready_pose로 MoveJ하고 READY_REACHED를 기록한다.
3. entry_pose로 MoveJ하고 ENTRY_REACHED 체크포인트를 기록한다.
4. #04 Soft Grip/진입으로 넘긴다.

접근을 MoveL로 변경하지 않는다. task/joint는 교시된 같은 자세의 한 쌍이다. virtual의 MoveJ 확인은 관절 기준, real은 공통 모션의 TCP 위치·자세 기준을 사용한다.

## 도달 확인과 실패 처리 — U02 반영 완료

Ready/Entry 접근은 공통 MoveJ의 기본 도달 확인을 사용한다. Entry 접근의 `allow_incomplete=True`를 제거했다. real은 TCP 위치·자세, virtual은 관절 기준으로 확인하며 성공한 이동만 READY_REACHED/ENTRY_REACHED를 기록한다.

목표 확인 제한시간 내 도달하지 못하면 TimeoutError를 Main에 전달한다. Main은 정지 처리·포인트 오류·Job 오류를 기록하고 후속 Soft Grip·접촉 진입·Pull 및 다음 포인트를 실행하지 않는다. 잘못된 위치에서 케이블 접촉 검사를 시작하지 않기 위한 조건이다.

Entry pose 이후의 접촉 진입/Pull은 별도 정책이다. 저항으로 목표거리를 못 간 경우 실제 변위와 종료 사유를 기록하고 판정·복귀하므로, 일반 접근의 도달 필수조건을 접촉 이동에 적용하지 않는다.

검증: D01/D10, real·virtual Ready/Entry 미도달 차단 시험, Main 정지·오류 기록 시험. 단순 명령 인자 확인에 더해 실제 공통 모션과 검사 시퀀스를 가상 피드백으로 실행했다.

## 구현 참조

[담당 소스](../../../../src/cable_inspection/cable_inspection/sequence/inspection/seq_inspection.py) · [공통 모션](../../../../src/cable_inspection/cable_inspection/sequence/common/motion.py) · [검증 체크리스트](../03_verification/01_기능검증_체크리스트_v4.md)
