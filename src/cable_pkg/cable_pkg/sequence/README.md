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
