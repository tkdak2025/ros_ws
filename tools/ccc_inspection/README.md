# ETC

현재 레시피 기반 검사 및 로봇 오차 시험의 필수 실행 경로에서 제외한 보조
코드를 보관한다.

| 파일 | 용도 |
| --- | --- |
| `move.py` | 초기 이동 확인 코드 |
| `pose_range_observer.py` | 수동 이동 중 좌표 관찰 코드 |
| `simple_movel_check.py` | MoveL 서비스 단독 확인 코드 |
| `pull_test_checklist.py` | 초기 수동 체크리스트 |

이 폴더의 코드는 `src`의 필수 실행 코드에서 import하지 않는다. 다시 사용할
경우 현재 레시피 구조와 ROS 환경에 맞는지 먼저 검토한다.
