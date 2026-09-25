# Concept 04 — Recipe

버전: v4 · 기준일: 2026-09-25 · 범위: 검사파트와 HMI 통신 계약

[v4 문서 안내](../../00_문서안내_v4.md) · [변경 근거·확인 항목](../../01_commons/02_변경추적_및_확인항목_v4.md)

## 소유권과 생명주기

HMI는 원본 레시피 파일과 버전을 관리한다. 검사측 HmiNode가 ROS2 `StartInspection`으로 전체 레시피를 받고 RecipeNode에 전달한다. Recipe는 검증한 실행 복사본을 고정하여 활성 포인트를 순회하고 현황·결과를 관리한다. Main은 `next_point()`로 한 포인트를 받아 검사하고 결과를 돌려준다.

수신 `points` 배열의 순서가 실행 순서이며 `enabled=false`는 실행에서 제외한다. 비활성 포인트도 구조 검증 대상이다. 현재 파일 로더는 과거 points 객체와 execution_order 형식도 경계에서 변환한다. 이를 새로운 ROS 메시지의 독립 실행 순서 필드로 해석하지 않는다.

실행 중 새 레시피로 현재 조건을 바꾸지 않는다. Main의 중복 START는 거절하고 snapshot은 원본 변경과 분리한다. 별도의 OperatingInspectionRecipe/OperatingInspectionPoint 계층은 필요하지 않다.

## 좌표와 방향

Ready/Entry pose는 각각 task `[X,Y,Z,A,B,C]`와 joint `[J1..J6]`를 저장한다. task는 BASE 기준 mm·ZYZ deg, joint는 deg다. 두 값은 같은 교시 자세의 한 쌍이다. 검사 측이 포인트 하나를 찍으면 Ready/Entry를 자동 교시·생성하는 기능은 제공하지 않는다.

Entry task의 자세각으로 `Rz(A)·Ry(B)·Rz(C)·[0,0,1]`을 계산한다. 이 BASE 방향 벡터가 접촉 진입 방향이며 Pull은 반대다. 독립 entry_direction을 ROS로 전달하지 않는다. 실제 케이블 방향에 Tool +Z가 맞도록 교시하는 책임이 남는다.

## 설정 분리

| 설정 | 소유/내용 |
|---|---|
| Inspection Recipe | HMI 원본. ID/version/frame/type, points, Ready/Entry, Entry/Grip/Pull 조건 |
| System Recipe | 검사 측. Home/Access, work_area, tool_approach_axis, Escape, 통신/판정 timeout, Home 경로 |
| Runtime config | 장비 운전·계측 공통값. 속도/가속도/주기/허용오차/Tool·TCP 이름 |

형식 검증은 교시 자세의 도달 가능성, 충돌 없음, task/joint의 물리적 일치를 보증하지 않는다.

## 2026-09-25 저장값

| Recipe/Point | Open / Soft close / Hard (mm) | Soft / Hard (N) | Entry 거리 (mm) | Pull 힘 / 최대거리 / 허용변위 |
|---|---|---|---|---|
| BMW HARNESS_01 | 29 / 24 / 19 | 10 / 20 | 5 | 15 N / 25 mm / 5 mm |
| BMW HARNESS_02 | 28 / 23 / 18 | 10 / 20 | 5 | 15 N / 25 mm / 5 mm |
| BMW HARNESS_03 | 28 / 23 / 18 | 10 / 20 | 5 | 15 N / 25 mm / 5 mm |
| LAN LAN_L2 | 25 / 22 / 16 | 10 / 20 | 5 | 15 N / 25 mm / 5 mm |
| LAN LAN_L5 | 25 / 22 / 16 | 10 / 20 | 6 | 15 N / 25 mm / 5 mm |

현재 두 파일 모두 Entry force_guard 5 N, Entry/Pull timeout 각 10초, Pull speed 10 mm/s다. LAN 15 N은 기존값 유지 결정이다. 이 표는 교시/실험 설정의 스냅샷이며 제품 공통 검증 기준이 아니다.

Safe Escape의 Open 25 mm는 포인트별 Open 폭과 별도 시스템 설정이다. Home은 joint 전부 0°, safe_home_route는 현재 Home 한 점이다. Escape 축은 Tool `[0,0,1]`의 반대, 후퇴 거리는 30 mm다.

근거: [Recipe 코드](../../../../src/cable_inspection/cable_inspection/recipe/recipe.py) · [시스템 설정](../../../../src/cable_inspection/config/system_recipe.json) · [검사 레시피 파일](../../../../src/cable_inspection/cable_inspection/recipe/inspection) · [전송 필드와 검증 조건](../../02_HMI/01_HMI_검사측_통신인터페이스_v4.md).
