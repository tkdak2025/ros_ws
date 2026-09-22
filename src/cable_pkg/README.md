# cable_pkg 기능 구조

M0609와 RG2를 사용하는 CCCIS 로봇 제어·검증 기능을 관리하는 ROS 2 Python
패키지다. 실제 검사 기능과 개발 중 검증 도구를 기능별 패키지로 분리한다.

```text
cable_pkg/
├── adaptive_grip/       # Adaptive Grip 단계/Gate (현재 V01만 구현)
├── diagnostics/         # 실물 로봇 상태 수동 조회
├── error_validation/    # Y/Z 위치 오차 측정
├── grip_stability/      # Soft/Hard Grip 및 Pull 반복시험
├── recipe/              # 검사포인트와 시험 레시피
├── safety/              # 작업영역 및 금지영역 판정
├── sequence/            # 실제 운전 시퀀스
└── test_module/         # 기능·실물 검증용 코드
```

## 실행 명령

워크스페이스를 빌드하고 `install/setup.bash`를 source한 뒤 실행한다.

```bash
ros2 run cable_pkg manual_check
ros2 run cable_pkg pose_range_test --recipe /path/to/y_pose_range_recipe.json
ros2 run cable_pkg pose_range_observer
ros2 run cable_pkg grip_stability_test
ros2 run cable_pkg adaptive_grip_validate
ros2 run cable_pkg sequence_test_node
```

`adaptive_grip_validate`는 V01 레시피 정적 검증까지만 구현되어 있다. 미확정된
V02~V09 로봇 동작은 임의로 실행하지 않는다.

레시피 JSON과 TCP/Tool 설정 파일은 빌드 시 `share/cable_pkg`에 설치된다.
실물 동작 전에는 bringup 모드, 활성 TCP/Tool, 이동 경로와 주변 간섭을 확인한다.
