# Sequence #01 — Work Initialize Sequence

버전: v4 · 기준일: 2026-09-25 · 범위: 검사파트와 HMI 통신 계약

[v4 문서 안내](../../00_문서안내_v4.md) · [변경 근거·확인 항목](../../01_commons/02_변경추적_및_확인항목_v4.md)

## 목적·입력

선택/수신한 레시피와 현재 장비 상태를 점검하여 포인트 검사를 시작할 수 있는 상태를 만든다. 이미 Home인지 여부는 필수조건이 아니다.

## 준비 절차

1. Robot/RG2 연결, 장비 모드·운전 가능 상태, Tool/TCP를 점검한다.
2. 제어 모드에 맞는 heartbeat를 확인한다.
3. System Recipe의 BASE 좌표·경로·축·허용 범위를 검증한다.
4. Inspection Recipe를 검증하고 실행 복사본·순회를 시작한다.
5. 활성 포인트가 있는지 확인하고 장비 상태를 다시 확인한다.

연결은 재사용하되 운전 가능 상태는 실행마다 재확인한다. 누락 좌표·잘못된 조건은 임의 기본 자세로 대체하지 않는다.

## Work Access 확보

| 현재 위치 | 동작 |
|---|---|
| 이미 Access | 자세 도달 확인만 수행; Open/후퇴/재이동 없음 |
| Access 외의 work_area 내부 | Open 25 mm 확인→현재 Tool −Z 30 mm 확인→Access MoveJ |
| work_area 외부, Home 포함 | Access MoveJ |

Access 여부를 work_area 포함 여부보다 먼저 확인한다. Access가 work_area 안에 있어도 불필요한 Escape를 하지 않기 위해서다. Access 도달 확인 실패는 첫 포인트 실행을 막는다.

## 완료·실패

장비 준비 성공과 Access 확인 후 #03으로 넘긴다. Open/후퇴/Access 실패, 모드/Tool/TCP 불일치는 검사 미시작과 오류 보고로 처리한다. Work Access는 경로 계획기가 아니며 실제 무간섭성은 교시·실물 검증 대상이다.

검증: A03~A05, C01~C07.

## 구현 참조

[담당 소스](../../../../src/cable_inspection/cable_inspection/sequence/main/seq_main.py) · [공통 모션](../../../../src/cable_inspection/cable_inspection/sequence/common/motion.py) · [검증 체크리스트](../03_verification/01_기능검증_체크리스트_v4.md)
