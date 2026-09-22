# Grip 안정성 시험 코드

| 파일 | 역할 |
| --- | --- |
| `grip_stability_test.py` | 실행 옵션과 Grip/Pull 시험 순서 |
| `grip_stability_robot.py` | 실물·가상 로봇 및 그리퍼 연결 |
| `grip_stability_data.py` | 레시피·시험조건·결과 저장 |

워크스페이스를 빌드하고 source한 뒤 실행한다.

```bash
ros2 run cable_pkg grip_stability_test
```

실행 메뉴에서 USB 또는 LAN 레시피와 real 모드를 선택한다. 포인트는 선택한
레시피의 `enabled` 순서대로 실행하며, 시작 전 `START` 입력을 요구한다.
검사 레시피는 `cable_pkg/recipe/grip_stability/`, Tool·TCP 설정은 `config/`,
결과는 `measurement_results/`에 둔다. 경로는 코드 위치를 기준으로 찾는다.
레시피 파일과 결과 기본 경로는 실행 코드 상단의 `RECIPE_PATH`, `OUTPUT_DIR`로
고정한다. 가상 결과는 `measurement_results/virtual/`에 저장한다.

툴 하중 기준은 DART에 등록된 `ToolWeight`이며, 질량은 `1.470 kg`, 무게중심은
플랜지 기준 `XYZ = [1.490, 85.380, 15.620] mm`다. 실물 시험에서는 제어기에
활성화된 `ToolWeight`를 사용하고, `config/tool.json`은 같은 값의 기록과 설정
검증에 사용한다. 관성값은 확인되지 않아 `null`로 유지한다.

실물과 가상은 같은 시험 순서·MoveJ/MoveL 명령·이동 완료 판단을 사용한다.
MoveJ는 중간 목표를 자동 추가하지 않고 완료 응답을 기다린다.
Entry/Pull의 MoveL은 목표 위치까지 남은 거리가 0.5 mm 이하면 완료로 본다.
모드별 차이는 연결 확인, TCP·Tool 설정, 그리퍼 명령 변환과 수동 관찰 여부다.

로봇 연결 클래스는 `GripPullRobot` 하나다.
실행 코드에서 `GripPullRobot(mode=args.mode)`로 생성하고,
설정·그리퍼 처리에서만 `self.mode`에 따라 분기한다.
선택한 모드와 제어기의 모드가 다르면 이동·그리퍼 명령을 차단한다.

## 코드 작성 기준

- 기교보다 단순하고 직관적으로 작성한다.
- 함수 이름과 실행 순서만 읽어도 무엇을 하는지 알 수 있게 한다.
- 불필요한 추상화·분기를 피하고 필요한 역할만 분리한다.
- 한글 주석은 동작의 목적, 단위, 중요한 조건을 설명한다.
