# Concept 04 — Recipe

버전: v4 · 기준일: 2026-09-30 · 범위: 검사파트와 HMI 통신 계약

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

## 현재 파일 구성과 설정 (2026-09-30)

| 파일 | 실행 순서 |
|---|---|
| `rcp_01_BMW_HARNESS_LWR_RH.json` | HARNESS_01 → HARNESS_02 → HARNESS_03 |
| `rcp_02_BMW_HARNESS_UPR_RH.json` | LAN_L2 → LAN_L5 → LAN_MONITOR_ARM_01 |
| `rcp_03_BMW_HARNESS_UPR_RH.json` | HARNESS_03 → LAN_MONITOR_ARM_01 |
| `rcp_04_BMW_HARNESS_LWR_RH.json` | HARNESS_01 → HARNESS_02 → LAN_L2 → LAN_L5 |

파일명과 recipe_id는 rcp_번호_BMW_HARNESS_위치_RH 형식이다. 03·04는 하네스와 LAN을 묶어 connector_type=WIRING_HARNESS_RJ45_LAN을 사용한다. 원래 01·02는 유지한다. rcp_TEST는 이전 별도 시험 좌표이므로 운영 모니터암 좌표와 혼동하지 않는다.

모든 현재 소스 레시피의 soft_open_width_mm는 soft_close_width_mm + 5 mm다. HARNESS_01은 29/24/19 mm, HARNESS_02·03은 28/23/18 mm, LAN은 27/22/16 mm(Open/Soft/Hard)이며 파지력은 10/20 N이다. Entry 힘 기준 5 N, Entry/Pull timeout 10초, Pull 15 N·최대거리 25 mm·허용변위 5 mm·속도 10 mm/s다. 이는 현재 저장값이며 모든 제품에 검증된 기준을 뜻하지 않는다.

시스템은 전체 work_area와 upper_work_area/lower_side_work_area를 별도로 보관한다. safe_escape_region_upper/midlower는 HOME 경유 자세이며, relax_width_mm=30과 relax_force_n=10은 포인트 Open과 별개다. HOME 경로는 #02, START 준비는 #01 문서를 따른다.

## 최신 교시 좌표 스냅샷

Task는 BASE [X,Y,Z,A,B,C](mm/deg), Joint는 [J1~J6](deg)다. 아래는 현재 소스에서 추출한 값이며 변경 시 JSON 원본을 우선 확인한다.

### LAN_MONITOR_ARM_01

```json
{
  "ready_pose": {
    "task": [
      -138.99,
      155.74,
      702.3,
      9.05,
      -1.05,
      64.53
    ],
    "joint": [
      -231.39,
      -18.39,
      132.47,
      -1.0,
      -113.56,
      -55.43
    ]
  },
  "entry_pose": {
    "task": [
      -307.12,
      202.19,
      780.28,
      139.83,
      -0.75,
      -49.75
    ],
    "joint": [
      -214.39,
      2.33,
      102.27,
      -0.09,
      -105.34,
      -55.55
    ]
  }
}
```

### HARNESS_01

```json
{
  "ready_pose": {
    "task": [
      467.69,
      63.87,
      393.67,
      172.19,
      -180.0,
      172.19
    ],
    "joint": [
      7.05,
      25.25,
      28.8,
      -180.02,
      -125.95,
      -172.96
    ]
  },
  "entry_pose": {
    "task": [
      384.61,
      20.02,
      96.98,
      92.52,
      -180.0,
      -178.09
    ],
    "joint": [
      2.07,
      5.18,
      103.56,
      -180.02,
      -71.26,
      -88.53
    ]
  }
}
```

### HARNESS_02

```json
{
  "ready_pose": {
    "task": [
      467.69,
      63.87,
      393.67,
      172.19,
      -180.0,
      172.19
    ],
    "joint": [
      7.05,
      25.25,
      28.8,
      -180.02,
      -125.95,
      -172.96
    ]
  },
  "entry_pose": {
    "task": [
      340.64,
      18.02,
      96.98,
      27.56,
      -180.0,
      116.95
    ],
    "joint": [
      2.0,
      -0.9,
      109.9,
      -180.02,
      -70.99,
      -88.6
    ]
  }
}
```

모니터암 Ready는 02·03 및 시스템 상부 경유점에 동일하게 반영했다. J5는 -113.56°이며 이전 -111.56°는 잘못된 저장값이다. 정정 관절각의 컨트롤러 FK와 직접 확인한 task의 XYZ 차이는 약 0.006 mm였다. HARNESS_01·02 Entry 변경은 01·04에 함께 반영했다.

소스 수정 후 colcon build --packages-select cable_inspection 및 source install/setup.bash로 설치본을 갱신한다. 실행 중 Python 코드 변경은 검사 프로그램 재시작이 필요하다. HMI가 보유한 레시피는 다시 불러와 선택하고 실행 Snapshot으로 확인한다. 빌드만으로 이미 접수된 실행 복사본은 바뀌지 않는다.
