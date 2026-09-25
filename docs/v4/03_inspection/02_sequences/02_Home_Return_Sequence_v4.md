# Sequence #02 — Home Return Sequence

버전: v4 · 기준일: 2026-09-25 · 범위: 검사파트와 HMI 통신 계약

[v4 문서 안내](../../00_문서안내_v4.md) · [변경 근거·확인 항목](../../01_commons/02_변경추적_및_확인항목_v4.md)

## 목적·실행권

별도 HOME 요청으로 설정된 Home 자세에 복귀한다. Main의 단일 모션 실행권 안에서만 수행한다. 새 START·검사와 동시에 실행하지 않는다.

## 현재 경로

| 현재 위치 | 처리 |
|---|---|
| Work Access 도달 확인 | 설정 Home 경로로 직접 이동 |
| Access 이외의 work_area 내부 | Open 25 mm/10 N 확인→현재 Tool 접근축 반대로 30 mm→Access MoveJ→설정 Home 경로 |
| work_area 외부 | 설정 Home 경로 |

HomeReturnSequence가 현재 Access 도달 여부를 먼저 확인한다. real은 위치 0.5 mm/자세 1° 공통 허용오차, virtual은 현재 관절 0.1° 기준이다. Access도 작업영역 내부이므로 영역 판정보다 먼저 확인하여 중복 Open·후퇴·Access 재이동을 생략한다.

호출자가 전달하던 at_verified_access 인자는 Main과 Home Return에서 제거했다. HOME_RETURN/MOVE_HOME 모두 같은 현재 위치 판단을 사용한다. Access를 벗어났다면 현재 영역에 맞는 경로를 선택하며 과거 Access 도달 상태를 신뢰하지 않는다. U01 반영 완료.

## Safe Escape 상세

현재 TCP의 XYZ와 ZYZ 자세를 읽는다. 설정 tool_approach_axis=[0,0,1]을 현재 회전으로 BASE 방향으로 바꾸고 반대로 30 mm 목표를 만든다. 자세각은 유지하며 MoveL 후 목표 도달을 확인한다.

Open은 실측 폭이 설정 폭 허용오차 이내여야 한다. 후퇴 거리 입력은 0 초과 30 mm 이하만 허용한다. 후퇴 미도달이면 Access로 계속 가지 않는다. 여기서 30 mm는 현재 구현의 지정 거리/상한이며, work_area 밖까지 반복 이동하거나 contact_area 이탈을 계산하지 않는다.

## Home 경로와 완료

safe_home_route의 마지막 점은 home_pose와 같아야 한다. 현재 경로는 전 관절 0° Home 한 점이다. 추가 교시 경유점이 없으면 직접 MoveJ한다. 도달 관절값과 home_joint_tolerance_deg=0.1°를 확인한다. 실패 시 임의 우회 경로나 추가 후퇴를 생성하지 않는다.

검사 종료의 자동 Home은 삭제되었다. 이 문서의 Home 동작을 #07 뒤에 자동 연결하지 않는다. 검증: G04~G06, R02~R03, U01.

## 구현 참조

[담당 소스](../../../../src/cable_inspection/cable_inspection/sequence/home_return/seq_home_return.py) · [공통 모션](../../../../src/cable_inspection/cable_inspection/sequence/common/motion.py) · [검증 체크리스트](../03_verification/01_기능검증_체크리스트_v4.md)
