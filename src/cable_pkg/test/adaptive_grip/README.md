# Adaptive Grip 단위테스트

대상: `cable_pkg/adaptive_grip/sequence.py`의 `AdaptiveGripPoint`와
`AdaptiveGripSequence`. 기준은 `ros_ws/docs/ccc_inspection/validation/`
`adaptive_grip_validation_checklist.md`의 V01~V09 순서입니다.

## 실행

워크스페이스 루트(`PRJT_CCCIS`)에서:

```bash
python3 -m pytest -q ros_ws/src/cable_pkg/test/adaptive_grip
```

`ros_ws/src/cable_pkg`에서 실행할 때:

```bash
python3 -m pytest -v test/adaptive_grip
```

Python 3.10 이상과 pytest가 필요합니다. ROS bringup, colcon 빌드,
로봇 및 그리퍼 연결은 필요하지 않습니다. `conftest.py`가 현재 패키지의
소스를 import하도록 경로를 설정합니다.

JUnit 결과 파일이 필요한 경우 워크스페이스 루트에서:

```bash
python3 -m pytest -q ros_ws/src/cable_pkg/test/adaptive_grip \
  --junitxml=/tmp/adaptive_grip_unit_tests.xml
```

## 구성과 검증 범위

| 파일 | 검증 내용 |
| --- | --- |
| `conftest.py` | 테스트 전용 검사포인트 fixture와 소스 import 설정 |
| `test_recipe.py` | V01 필수 문자열, 벡터 길이·유한성, 영벡터, 축 정규화, 깊이·탐색 범위, JSON 로딩 및 반복성 |
| `test_sequence.py` | V01~V09 순서, 각 단계 종료, 각 Gate 실패 후 후속 단계 차단, 예외 전파, 재실행 초기화, JSON 결과 저장 |

현재 실제 구현은 V01까지입니다. V02~V09는 `NotImplementedError`를
발생시키므로, 전체 흐름 테스트에서는 monkeypatch로 단계별 응답을 대체하고
**실제 `run()`의 제어 흐름**을 검증합니다. 별도 테스트는 미구현 단계가 명시적으로
예외를 내는지, 실제 시퀀스가 V01 기록 후 V02에서 중단되는지도 확인합니다.
V08 실패 시 V09가 호출되지 않는 경우는 각 Gate 실패 매개변수 테스트에 포함됩니다.

성공·실패 결과 JSON은 pytest의 `tmp_path`에 저장하고 메타데이터, 단계 이력,
판정 및 데이터를 다시 읽어 검증합니다. 이 데이터는 실물 측정 결과가 아닙니다.
fixture의 위치·힘 관련 숫자는 테스트 입력이며 실물 운전용 레시피가 아닙니다.

실물의 접촉 감지, Soft/Hard Grip 힘·폭, Wiggle 응답, 정렬 판정,
Slip, Force/TCP 동기 측정은 이 테스트의 통과로 검증되지 않습니다.
해당 기능이 구현되면 테스트 대역 기반 흐름 검증은 유지하고 실제 단계 로직의
입력·출력 및 실패 조건 테스트를 추가해야 합니다. 미구현 예외 테스트는 그때
구현된 단계에 맞게 수정합니다. 현재 Point ID 검증 범위는 빈 값 여부이며,
등록된 레시피 목록과의 존재 여부 대조 기능은 구현되어 있지 않습니다.
