# 운영 시퀀스 코드

`sequence/`는 실제 프로젝트의 작업 흐름을 코드로 제어한다. ROS 서비스의 구체적인
호출과 측정은 `hardware/`가 담당하며, 시퀀스는 동작 순서와 단계 간 데이터 전달만
담당한다.

```text
sequence/
├─ common/
│  ├─ seq_00_main_work.py       # 전체 작업 상태와 Job Context
│  ├─ seq_00_hmi_interface.py   # HMI 명령 연결
│  ├─ seq_01_work_initialize.py # 작업 시작 조건 확인
│  └─ seq_02_home_return.py     # Home Return
└─ inspection/
   ├─ seq_00_inspection_run.py  # 실제 검사를 시작하는 CLI 진입점
   ├─ seq_00_inspection.py      # 포인트 반복과 #03→#05 검사 모션
   └─ seq_06_inspection_judgment_node.py # Queue + Worker 비동기 판정
```

`seq_00_inspection.py`는 ROS 노드가 아니다. `InspectionSequence` 클래스 하나가
Inspection Recipe의 `execution_order` 순회와 각 포인트의 모션을 제어한다.

```text
Point Transition → Adaptive Grip → Pull Inspection
Ready → Entry → Soft Grip → 추가 진입 → Hard Grip → Pull → Entry → Ready
```

실제 실행 명령은 다음과 같다.

```bash
# 터미널 1: 비동기 판정 노드
ros2 run cable_pkg inspection_judgment
# 터미널 2: 실제 검사 모션
ros2 run cable_pkg inspection_sequence
```

각 Point 측정 후 판정 요청을 발행하고 다음 Point를 진행한다. 판정 노드는
`cable_inspection/judgment_result`로 `cable_interfaces/msg/InspectionResult`를 전달하며, 전체 모션 종료 후 CLI가 결과를 모아
`inspection_results.json`과 `judgment_results.json`에 저장한다.

v03 판정은 `PASS / FAIL / SYSTEM_ERROR`이다. `FORCE_LIMIT` 종료 시 실제 변위가
레시피 허용값 이하면 PASS, 초과면 FAIL이다. `MAX_DISTANCE`는 FAIL,
TIMEOUT·하드웨어 오류·유효하지 않은 데이터는 SYSTEM_ERROR다. Slip과 RG2 폭 변화는
판정에 사용하지 않는다. 그리퍼 Open/Hard Grip 완료 확인에 필요한 폭 피드백은 유지한다.

기본 결과 경로는 실행 디렉터리의 `results/inspection_sequence/<실행시각>/`이다.
`--results-dir`로 변경할 수 있다. `samples.jsonl`은 원시 측정,
`inspection_results.json`은 모션과 판정 종합 결과, `judgment_results.json`은 비동기 판정,
`job_summary.json`은 결과별 개수와 미수신 포인트를 기록한다.


커스텀 결과 메시지는 `cable_interfaces/msg/InspectionResult.msg`에 정의한다.
판정 노드의 `_result_message()`가 식별정보·판정·측정값·기준값을 채운다.
`JudgmentClient`는 이 타입을 구독해 실행/포인트를 대조한 뒤 JSON 저장용 dict로 변환한다.
요청 토픽은 기존 `std_msgs/String` JSON 형식이며, HMI 패키지는 변경하지 않는다.
기존 HMI의 `cable_inspection/result` JSON 토픽과 새 결과 토픽은 별개다.

인터페이스를 처음 추가하거나 `.msg`를 변경했을 때는 빌드와 환경 로딩이 필요하다.

```bash
colcon build --symlink-install --packages-up-to cable_pkg
source install/setup.bash
ros2 interface show cable_interfaces/msg/InspectionResult
ros2 topic echo /cable_inspection/judgment_result cable_interfaces/msg/InspectionResult
```


파지 검증 추가: Soft 단계 종료 후 Hard 명령 직전에 실측 폭을 저장한다.
Hard 동작이 멈춘 뒤 Pull을 시작하고, 정지 대기를 포함한 Pull 구간의 최소 실측 폭을
`pull_width_mm`으로 기록한다. `width_delta_mm = pull_width_mm - soft_width_mm`이며
차이는 기록용이다. Pull 폭이 **16 mm 미만**이면 `FAIL_GRIP_WIDTH`로 FAIL 처리한다.
TIMEOUT 등 시스템 오류는 SYSTEM_ERROR를 우선하며, 폭으로 Pull 정지 조건을 변경하지 않는다.
