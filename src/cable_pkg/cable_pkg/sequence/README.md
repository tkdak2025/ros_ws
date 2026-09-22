# 확정 시퀀스 코드

현재 설계가 확정된 공통 흐름만 구현한다.

- `models.py`: 시스템 상태, Job Context, 공통 결과
- `backend.py`: 로봇·HMI·레시피 구현체와의 인터페이스
- `work_initialize.py`: Sequence #1 Work Initialize
- `home_return.py`: Sequence #2 Home Return과 Work Area 분기
- `controller.py`: Main 상태 전이와 Context 수명
- `node.py`: HMI command/status/log 토픽과 Controller 연결

구현된 정책:

- START는 `SYSTEM_READY`에서만 허용한다.
- START마다 장비·HMI·System Recipe·Inspection Recipe를 다시 확인한다.
- 활성 검사포인트가 하나도 없으면 시작하지 않는다.
- 작업영역 내부 Home Return은 Grip 완화, Safe Escape, Work Access, Home 순이다.
- STOP/ERROR는 자동 Home Return하지 않는다.
- PAUSE만 Job Context를 보존한다.
- HMI 통신 복구 후 사용자가 RESUME하기 전에는 움직이지 않는다.

아직 상세설계되지 않은 Point Transition, Adaptive Grip, Pull Inspection과 판정은
`InspectionPointExecutor` 인터페이스로만 정의했다. 기본 구현은 명시적인
`POINT_SEQUENCE_NOT_IMPLEMENTED` 결과를 반환하며 로봇을 움직이지 않는다.

`SequenceBackend`의 실물 DSR/RG2 구현과 System Recipe 좌표가 연결되기 전에는
이 모듈을 실물 동작 노드로 실행하지 않는다.

HMI heartbeat timeout은 아직 설계값이 확정되지 않아 기본적으로 비활성화한다.
실물 Backend 조립 코드가 확정값을 `heartbeat_timeout_s`로 전달해야 활성화된다.

## HMI 동작시험

한 명령으로 HMI와 Sequence Mock 노드를 실행한다.

```bash
ros2 launch cable_pkg sequence_hmi_test.launch.py
```

개별 실행이 필요하면 두 터미널을 사용한다. 기존 `mock_inspection_node`와 동시에
실행하면 status가 섞이므로 HMI launch의 mock을 반드시 끈다.

```bash
# Terminal 1
ros2 launch cable_hmi hmi.launch.py mock:=false

# Terminal 2
ros2 run cable_pkg sequence_test_node
```

HMI에서 `SEQUENCE_TEST_USB` 또는 `SEQUENCE_TEST_LAN`을 선택하고 시작한다.
Mock 노드는 실제 로봇·그리퍼 서비스를 호출하지 않는다. 각 포인트는 화면 확인을
위해 `READY_POSE → ENTRY_POSE → INSPECTION_PLACEHOLDER → READY_POSE_RETURN`으로
표시된다. `INSPECTION_PLACEHOLDER`는 실제 Adaptive Grip/Pull 구현이 아니다.
