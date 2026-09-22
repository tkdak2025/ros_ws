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
   └─ seq_06_inspection_judgment.py
```

`seq_00_inspection.py`는 ROS 노드가 아니다. `InspectionSequence` 클래스 하나가
Inspection Recipe의 `execution_order` 순회와 각 포인트의 모션을 제어한다.

```text
Point Transition → Adaptive Grip → Pull Inspection
Ready → Entry → Soft Grip → 추가 진입 → Hard Grip → Pull → Entry → Ready
```

실제 실행 명령은 다음과 같다.

```bash
ros2 run cable_pkg inspection_sequence
```
