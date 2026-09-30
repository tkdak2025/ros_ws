# Sequence #02 — Home Return Sequence

버전: v4 · 기준일: 2026-09-30 · 현재 코드 기준

[v4 문서 안내](../../00_문서안내_v4.md)

## 실행권과 위치 분류

HOME_RETURN/MOVE_HOME은 Main의 단일 Worker에서 수행한다. START·검사와 동시에 실행하지 않는다. 마지막 포인트 기록 대신 BASE 기준 실측 TCP의 XYZ로 전체 작업영역 및 세부 영역을 판별한다. 이미 Home이면 정지와 절대 관절각으로 확인하고 이동 없이 완료한다.

| 현재 위치 | HOME 동작 |
|---|---|
| 이미 Home | ALREADY_HOME, 이동 없이 완료 |
| upper_work_area | Open 30 mm/10 N 확인 → safe_escape_region_upper MoveJ → Home MoveJ |
| lower_side_work_area | Open 30 mm/10 N 확인 → safe_escape_region_midlower MoveJ → Home MoveJ |
| 전체/세부 작업영역 밖 | HOME_OUTSIDE_REGIONS, 자동 이동 차단·수동 복구 안내 |

전체 X는 -330~924.84 mm, 상부 X는 -330~100 mm, 하부·측면 X는 100~924.84 mm다. Y는 -654.63~265.79 mm, Z는 60~800 mm로 공통이다. X=100 경계는 상부 우선이다. safe_escape_region_*는 영역 경계가 아니라 이동 목표의 task/joint 한 쌍이다.

## 개방·경유점·완료

그리퍼 개방 폭은 system_recipe의 relax_width_mm=30, relax_force_n=10을 사용한다. 실측 폭 허용오차는 5 mm이며, 개방 확인이 실제 케이블 해제를 보증하지는 않는다. 경유점에 이미 도달했다면 중복 이동을 생략한다. 경유점과 Home의 MoveJ는 motion_status=0 및 각 관절의 절대 오차 0.1° 이하로 판정한다. 360° 차이를 같은 관절각으로 취급하지 않는다. 개방·이동·도달 확인 실패 시 다음 이동을 차단한다.

현재 HOME run()은 선택한 경유점에서 home_pose로 직접 MoveJ하며, 30 mm MoveL과 safe_home_route 배열 순회를 사용하지 않는다. safe_home_route 설정과 기존 helper는 남아 있지만 현재 HOME 분기에는 연결되지 않는다. 검사 완료 후에는 Work Access에서 대기하며 자동 HOME은 실행하지 않는다.

## START와의 차이

START 준비는 기존 경로를 유지한다. Access가 아닌 작업영역 내부에서는 Open 30 mm → 현재 Tool 접근축 반대로 30 mm MoveL → Work Access다. HOME 변경이 START의 NOT REACHABLE을 해결한 것은 아니다.

## 진단·검증

HOME_RETURN 로그는 영역과 경유 목표를, HOME_ESCAPE_REACHED는 실측 TCP와 저장 task의 XYZ 오차를, HOME_MOVE_REQUEST는 Home 관절 목표를 기록한다. HOME에서는 TCP 오차를 진단값으로 남기고 관절 기준으로 완료 판단한다. 일반 검사 MoveJ는 기존 실물 TCP 완료 판정을 유지한다.

영역 포함 여부와 자동시험 통과는 충돌 없는 경로를 보장하지 않는다. 영역 안의 여러 시작 자세에서 경유점까지 및 Home까지의 실물 검증이 필요하다.

구현: `sequence/home_return/seq_home_return.py`, `sequence/common/motion.py`. 회귀시험: `test_home_regions.py`, `test_start_work_access.py`.
