# 2-Stage Approach·Grip-Pull Recipe

`grip_pull_recipe.template.json`은 `grip_stability_test.py` 전용 템플릿이다.
일반 검사 레시피와 Y/Z 오차 검증 레시피와 분리해 관리한다.

실물 시험 전에 다음 값을 같은 자세에서 Teaching한 값으로 교체한다.

- `ready_pose.task`: Ready 위치의 BASE TASK
- `ready_pose.joint`: Ready 위치의 JOINT
- `entry_pose.task`: Depth 직선 진입을 시작할 BASE TASK
- `entry_direction`: 해당 Point의 BASE 기준 Depth 진입 단위방향
- `entry_depth_mm`: Entry에서 Soft Grip 구간으로 진입할 거리

`null`은 미입력 표시이며 그대로는 시험 Recipe로 사용할 수 없다. 실제 값을
입력한 뒤 파일명을 `grip_pull_recipe.json`으로 저장해 사용한다.

진입 방향은 검사포인트마다 Recipe에 저장한다. Pull 방향은 코드에서 해당
`entry_direction`의 반대방향으로 계산한다.

## 실행 옵션과 코드 읽는 순서

`--point`는 JSON의 `points` 안에서 사용할 검사포인트 ID를 선택한다.
예를 들어 `--point TEST_P01`은 해당 포인트의 Ready·Entry 좌표, 진입 방향,
진입 깊이를 사용한다. 기본값도 `TEST_P01`이므로 현재 포인트만 시험할 때는 생략한다.

```bash
/usr/bin/python3 src/grip_stability/grip_stability_test.py --mode virtual --trials 1
```

`--mode`는 bringup과 동일하게 지정한다. 기본값은 `real`이다.
가상모드는 `config/tcp.json`, `config/tool.json`을 읽어 적용하며,
실물모드는 제어기에 활성화된 TCP·Tool을 사용한다.

코드는 다음 세 파일로 나눈다.

| 파일 | 역할 / 수정할 내용 |
| --- | --- |
| `src/grip_stability/grip_stability_test.py` | 실행 옵션, 연속 시험 순서, Entry/Pull 측정 루프 |
| `src/grip_stability/grip_stability_data.py` | 레시피 읽기, `GripPullConfig` 시험조건, CSV/JSON 저장 |
| `src/grip_stability/grip_stability_robot.py` | ROS2 서비스, 실물 RG2 명령, 가상 설정·그리퍼 변환 |

처음에는 `main()` → `run()` → `run_trial()` 순서로 읽는다.
`run_trial()`의 1~4단계 주석이 전체 동작을 설명한다.
힘·속도·시간 조건은 `GripPullConfig`, 검사 위치는 레시피 JSON에서 수정한다.
가상 그리퍼의 5 mm 요청은 모델의 닫힘 한계 약 7.07 mm로 제한되며,
가상 시험으로 실제 파지력이나 미끄러짐을 평가하지 않는다.

## 실물 Grip 안정성 반복시험

각 검사포인트의 `cable_condition`에는 검사 전 기준정보인 커넥터 종류, 케이블 종류,
정상 기대상태 및 체결 방향을 기록한다. 시험 중 확인한 Cable 이탈·Slip·판정 결과는
레시피를 수정하지 않고 결과 JSON에 저장한다. 검사포인트별 Soft Open/Close 및 Hard
폭은 `grip_setting`에 정의한다.

`mode:=real` bringup이 실행 중인 터미널과 동일한 ROS 환경에서 실행한다.
USB-A 초기 시험값은 Soft Grip Open 22 mm·Close 18 mm·명령 힘 10 N이며,
Hard Grip은 목표 폭 5 mm·명령 힘 20 N이다. 다른 케이블은 동일 시험으로 적정 폭과
힘을 별도로 확인한다.
Soft Grip 진입 중 측정한 Tool Force를 CSV에 기록해 후속 조건 결정에 사용한다.

Entry Pose에서는 Soft Grip Close 명령을 먼저 내린다. 그리퍼 실측 폭이 Open 폭인
22 mm 이하가 되면 25 mm Entry MoveL을 시작하여 18 mm까지 닫히는 동작과 로봇
진입을 겹쳐 수행한다.
20초 안에 해당 폭에 도달하지 않거나 폭 피드백이 없으면 로봇은 진입하지 않고
시험을 중단한다.

여기서 Grip의 `force_n`은 RG2에 내리는 파지력 명령값이다. CSV의 Base/Tool
Force는 로봇 플랜지 힘/토크 센서가 측정한 외력과 초기 기준값 대비 변화량이므로 두
값을 같은 힘으로 해석하지 않는다.

CSV의 `grip_event` 열은 그립 시점을 다음과 같이 구분한다.

| 값 | 의미 |
| --- | --- |
| `INITIAL_SOFT_GRIP_OPEN_COMMAND` | 시험 시작 시 완전 개방 대신 Soft Open 22 mm를 명령한 시점 |
| `INITIAL_SOFT_GRIP_OPEN_REACHED` | 실측 폭 22 ±0.5 mm 확인 후 Ready 이동을 허용한 시점 |
| `SOFT_GRIP_COMMAND` | Close 18 mm / 10 N Soft Grip 명령 응답 시점 |
| `ENTRY_MOTION_START_WIDTH_REACHED` | 실측 폭 22 mm 이하 도달 및 Entry MoveL 시작 직전 |
| `SOFT_GRIP_STABILIZATION_END` | Entry 완료 후 Soft Grip 안정화 대기 종료 |
| `HARD_GRIP_COMMAND` | 5 mm / 20 N Hard Grip 명령 응답 시점 |
| `HARD_GRIP_STABILIZATION_END` | Hard Grip 안정화 대기 종료 및 Pull 준비 시점 |
| `RETURN_SOFT_GRIP_COMMAND` | Pull 종료 후 기존 파지력을 변경하지 않고 Open 22 mm 폭 명령을 보낸 시점 |
| `RETURN_SOFT_GRIP_OPEN_REACHED` | 실측 폭이 목표 22 mm의 ±0.5 mm 범위에 들어온 뒤 Soft 힘을 적용하고 Ready 이동을 허용한 시점 |

연속 Entry/Pull 측정 행에서는 `grip_event`가 빈 문자열이며 `state`로 구간을
구분한다. 각 이벤트 행에도 TCP, Base/Tool Force 및 실측 그리퍼 폭을 함께 저장한다.

## 체결 이상 자동 판정 실험

`grip_stability_evaluator.py`는 Pull 측정값에서 힘의 최고점과 마지막 5개 측정값의
중앙값을 비교한다. 최고 힘이 8 N 이상이고, 이후 힘이 8 N 이상 감소하면서 마지막
힘이 최고 힘의 45% 이하이면 `pull_force_peak_then_drop` 체결 이상 후보로 판정한다.
또한 Pull 최대 거리의 90% 이상 이동했고 그리퍼 폭이 2 mm 이상 변했는데 힘 제한에는
도달하지 못한 경우를 점진적 미끄러짐 또는 이탈로 판정한다. 현재 USB-A 단위시험용
`force_release_and_slip_v0.2` 규칙이며 최종 검사 기준은 아니다.

시험자는 자동 판정을 보기 전에 Cable 이탈, Grip Slip, Fixture 이동을 입력한다.
이후 프로그램이 자동 판정과 Peak·안정구간 힘·감소량을 보여주고 판정이 맞았는지
`y/n/u`로 받아 `trial_summaries.json`에 함께 저장한다.

`Cable 이탈 여부 = y`이면 측정 기반 힘 곡선 판정과 관계없이 `불량 후보`를
제안한다. 이 결과는 최종 정답이 아니며, 프로그램은 힘 곡선 수치와 관찰 입력을
`judgement_basis`에 모두 기록하고 시험자에게 제안이 맞았는지 확인한다.

고정 반복 횟수는 사용하지 않는다. 각 시험의 판정 입력이 끝나면 현재 Soft/Hard
Grip 힘을 표시하고 `현재 힘으로 계속`, `힘 조정 후 계속`, `시험 종료` 중 하나를
선택한다. 조정값은 RG2 사양에 맞춰 0~40 N 범위의 2.5 N 단위만 허용하며 Hard
힘은 Soft 힘 이상이어야 한다. 각 Trial의 `soft_grip_setting`과
`hard_grip_setting`에는 해당 시험에 실제 사용한 값을 저장하므로 실행 중 설정을
바꿔도 결과를 구분할 수 있다.

관찰 결과를 입력하면 다음 시험의 Soft/Hard Grip 힘과 Pull 정지 힘을 추천한다.
Grip Slip이면 Hard Grip을 2.5 N 높이고, 케이블이 빠졌다면
측정 Peak의 70%를 2.5 N 단위로 내림한 값 이하로 Pull 제한을 낮춘다. Fixture가
움직였다면 Pull 5 N 이하를 추천한다. Pull 최대거리는 추천 로직에서 변경하지 않는다.
추천값은 자동 적용하지 않으며 실행 메뉴의 `추천 설정 적용 후 계속`을 선택했을 때만
다음 시험에 반영한다. 추천 근거와 값은 결과 JSON에도 저장한다.

먼저 1회 시험으로 동작을 확인한다.

```bash
/usr/bin/python3 src/grip_stability/grip_stability_test.py \
  --mode real \
  --point TEST_P01 \
  --trials 1
```

1회 검증 후 정규 10회 반복은 `--trials 10`으로 실행한다. 프로그램이 Recipe와
시험조건을 출력한 후 `START`를 입력해야 실제 이동을 시작한다. 실행 중
`Ctrl+C`를 누르면 Quick Stop을 요청하고 종료한다.
