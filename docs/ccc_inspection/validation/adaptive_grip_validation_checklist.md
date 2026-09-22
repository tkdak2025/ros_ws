# Adaptive Grip 작업검증 체크리스트

- 기준 문서: `CCCIS Adaptive Grip 작업검증계획서 v0.1`
- 대응 코드: `src/cable_pkg/cable_pkg/adaptive_grip/sequence.py`
- 상태 표기: `미착수 / 진행 중 / 통과 / 실패 / 보류`
- 작성 원칙: 측정하지 않은 항목은 추정값을 쓰지 않고 `TBD`로 남긴다.

## 1. 시험 식별 정보

| 항목 | 기록값 |
| --- | --- |
| 시험 일시 | TBD |
| 작업자 | TBD |
| Recipe ID | TBD |
| Inspection Point ID | TBD |
| Point Name | TBD |
| 시편 ID | TBD |
| 시험 회차 | TBD |
| 로봇 / 제어기 | M0609 / `192.168.1.100` |
| TCP / Tool | `GripperDA_v1` / `ToolWeight` |
| 결과 폴더 | TBD |

## 2. 공통 사전조건

- [ ] ROS 2 bringup이 `mode:=real`, `host:=192.168.1.100`으로 실행됐다.
- [ ] DART와 ROS에서 조회한 현재 TASK·JOINT가 일치한다.
- [ ] 활성 TCP가 `GripperDA_v1`이다.
- [ ] 활성 Tool이 `ToolWeight`다.
- [ ] RG2 Open/Close 및 파지력 제어가 정상이다.
- [ ] Fixture와 시편이 움직이지 않도록 고정됐다.
- [ ] 비상정지 수단과 작업자 위치를 확인했다.
- [ ] 이동·Force 제한값이 시험 전에 정의됐다.
- [ ] Tool Force와 TCP Pose를 읽고 저장할 수 있다.
- [ ] 로봇, 그리퍼, 케이블과 주변 구조물의 간섭 가능성을 확인했다.

## 3. 레시피 입력값

| 항목 | 값 | 확인 |
| --- | --- | --- |
| Nominal TASK `[X,Y,Z,A,B,C]` | TBD | [ ] |
| Connector Axis `[dx,dy,dz]` | TBD | [ ] |
| Ready JOINT `[J1..J6]` | TBD | [ ] |
| Entry TASK `[X,Y,Z,A,B,C]` | TBD | [ ] |
| Depth Offset | TBD mm | [ ] |
| Search Range | TBD mm | [ ] |
| Workspace Boundary | TBD | [ ] |

## 4. 단계별 검증

### V01 — Recipe / Inspection Point

- [ ] Recipe ID와 Point ID가 존재한다.
- [ ] 동일 Point ID를 다시 읽어도 동일한 값이 나온다.
- [ ] Nominal TASK, Connector Axis, Ready JOINT와 Entry TASK가 유효하다.
- [ ] Connector Axis가 0 벡터가 아니며 단위벡터로 변환된다.
- [ ] 잘못된 Point ID에서는 로봇 동작 전에 중단된다.

| 상태 | Gate 판정 | 근거 파일 / 메모 |
| --- | --- | --- |
| 미착수 | G1 전제정보 확인: TBD | TBD |

### V02 — Ready → Entry 접근

- [ ] 그리퍼 Open 상태를 확인했다.
- [ ] Ready Pose까지 MoveJ 경로를 검토했다.
- [ ] Ready에서 Entry까지 이동 방식을 확정했다.
- [ ] 반복 접근 중 주변 구조물 간섭이 없다.
- [ ] TCP·JOINT와 Entry 도달 오차를 기록했다.
- [ ] 반복 접근 시 Entry Pose가 재현된다.

| 반복 횟수 | 위치 오차 | 방향 오차 | 간섭 | 메모 |
| ---: | ---: | ---: | --- | --- |
| TBD | TBD mm | TBD deg | TBD | TBD |

| 상태 | Gate 판정 | 근거 파일 / 메모 |
| --- | --- | --- |
| 미착수 | G1 Entry: TBD | TBD |

### V03 — Depth Compensation

- [ ] Search 방향이 Connector Axis와 일치한다.
- [ ] Search Range와 속도를 정의했다.
- [ ] Force Detection 조건과 최대 힘을 정의했다.
- [ ] Contact 발생 시 즉시 정지 또는 다음 상태로 전환된다.
- [ ] Contact TCP와 기준점 대비 깊이 보정량을 기록했다.
- [ ] 반복 측정에서 보정량이 재현된다.

| Search Range | 속도 | Force 조건 | Contact 위치 | 보정량 |
| ---: | ---: | ---: | --- | ---: |
| TBD mm | TBD | TBD N | TBD | TBD mm |

| 상태 | Gate 판정 | 근거 파일 / 메모 |
| --- | --- | --- |
| 미착수 | G2 Adaptive Entry: TBD | TBD |

### V04 — Soft Grip

- [ ] Soft Grip Force와 Width 후보를 기록했다.
- [ ] 파지 깊이와 Tool Orientation을 기록했다.
- [ ] 케이블이 빠지지 않는다.
- [ ] 케이블이 과구속되지 않는다.
- [ ] Micro-Wiggle을 수행할 수 있다.
- [ ] 파지 전후 Tool Force와 케이블 손상 여부를 확인했다.

| Grip Force | Grip Width | 파지 깊이 | Slip | 과구속/손상 |
| ---: | ---: | ---: | --- | --- |
| TBD | TBD | TBD mm | TBD | TBD |

| 상태 | Gate 판정 | 근거 파일 / 메모 |
| --- | --- | --- |
| 미착수 | G3 Soft Grip: TBD | TBD |

### V05 — Micro-Wiggle

- [ ] Connector Axis에 수직인 시험 방향을 정의했다.
- [ ] +방향 이동 거리·속도와 Force Response를 기록했다.
- [ ] 기준 위치로 복귀한 TCP 오차를 기록했다.
- [ ] -방향 이동 거리·속도와 Force Response를 기록했다.
- [ ] 양방향 Peak Force와 Force 차이를 기록했다.
- [ ] Wiggle 중 Slip과 케이블 위치 변화를 확인했다.

| 방향 | 이동 거리 | 속도 | Peak Force | 복귀 오차 | Slip |
| --- | ---: | ---: | ---: | ---: | --- |
| + | TBD mm | TBD | TBD N | TBD mm | TBD |
| - | TBD mm | TBD | TBD N | TBD mm | TBD |

| 상태 | Gate 판정 | 근거 파일 / 메모 |
| --- | --- | --- |
| 미착수 | G4 Alignment 입력 확보: TBD | TBD |

### V06 — Fine Alignment

- [ ] 사용할 Feature를 명시했다: Force Difference / Ratio / Position 등.
- [ ] 보정 방향 결정 근거를 기록했다.
- [ ] 1회 보정 거리와 최대 보정 횟수를 정의했다.
- [ ] 보정 전후 Force Response를 비교했다.
- [ ] 최종 TCP와 보정 횟수를 기록했다.
- [ ] 조건 미충족 시 재보정 또는 실패로 종료된다.
- [ ] 반복시험에서 최종 Grip 위치가 재현된다.

| Feature | 보정 방향/거리 | 보정 횟수 | 보정 전 | 보정 후 | 결과 |
| --- | --- | ---: | ---: | ---: | --- |
| TBD | TBD | TBD | TBD | TBD | TBD |

| 상태 | Gate 판정 | 근거 파일 / 메모 |
| --- | --- | --- |
| 미착수 | G4 Alignment: TBD | TBD |

### V07 — Hard Grip

- [ ] Hard Grip Force와 Width를 기록했다.
- [ ] 파지 위치와 Pull 전 초기 Tool Force를 기록했다.
- [ ] Pull 중 Cable Slip이 없다.
- [ ] 반복 파지 후 위치 변화가 허용범위 안이다.
- [ ] 케이블 손상과 Force 신호 이상이 없다.

| Grip Force | Grip Width | 초기 Force | Slip | 손상 |
| ---: | ---: | ---: | --- | --- |
| TBD | TBD | TBD N | TBD | TBD |

| 상태 | Gate 판정 | 근거 파일 / 메모 |
| --- | --- | --- |
| 미착수 | G5 Hard Grip: TBD | TBD |

### V08 — Grip Stability Check

- [ ] Gripper Width 변화량을 기록했다.
- [ ] TCP Position 변화량을 기록했다.
- [ ] 초기 Tool Force를 기록했다.
- [ ] 짧은 사전 하중의 Force/Displacement 반응을 기록했다.
- [ ] Gripper-Cable 파지상태만 판정하고 체결상태와 혼용하지 않는다.
- [ ] 불안정하면 Grip-Pull 단계로 진행하지 않는다.

| Width 변화 | TCP 변화 | 초기 Force | 사전 하중 반응 | 결과 |
| ---: | ---: | ---: | --- | --- |
| TBD | TBD mm | TBD N | TBD | TBD |

| 상태 | 검사 진행 가능 여부 | 근거 파일 / 메모 |
| --- | --- | --- |
| 미착수 | TBD | TBD |

### V09 — Grip-Pull Logging

- [ ] Timestamp, Recipe ID, Point ID와 Trial Number를 기록한다.
- [ ] Test Phase와 Grip State를 기록한다.
- [ ] TCP Pose와 기준 대비 TCP Displacement를 기록한다.
- [ ] Tool Force `Fx,Fy,Fz`를 동기화해 기록한다.
- [ ] Connector Axis와 Axial Force를 기록한다.
- [ ] Pull Distance와 Pull Speed를 기록한다.
- [ ] Connector 이탈 여부와 Manual Label을 기록한다.
- [ ] 데이터 누락과 샘플 시간 불연속을 확인한다.
- [ ] Adaptive Grip 데이터와 체결검사 데이터를 분리해 저장한다.

| 상태 | Gate 판정 | 결과 폴더 / 메모 |
| --- | --- | --- |
| 미착수 | G6 Logging: TBD | TBD |

## 5. Gate 현황

| Gate | 통과 조건 | 상태 | 근거 |
| --- | --- | --- | --- |
| G1 Entry | Ready→Entry 반복 가능, 간섭 없음 | 미착수 | TBD |
| G2 Adaptive Entry | Depth 보정 방식 결정 | 미착수 | TBD |
| G3 Soft Grip | Micro-Wiggle 가능한 파지 조건 확보 | 미착수 | TBD |
| G4 Alignment | 위치 편차에 따른 반응과 보정 가능 | 미착수 | TBD |
| G5 Hard Grip | Pull 중 Slip 없는 조건 확보 | 미착수 | TBD |
| G6 Logging | Force/TCP 동기 기록 확인 | 미착수 | TBD |
| G7 Repeat Test | 정상·이상 시편 반복 데이터 확보 | 미착수 | TBD |
| G8 Judgment | Feature와 Threshold 후보 도출 | 미착수 | TBD |

앞 Gate가 통과하지 않으면 이후 단계의 결과를 판정 기준 확정에 사용하지 않는다.

## 6. 수동 관찰 및 최종 메모

| 항목 | 기록 |
| --- | --- |
| Cable Slip | TBD |
| Connector 이탈 | TBD |
| Cable 손상 | TBD |
| 구조물 간섭 | TBD |
| 비정상 소음·진동 | TBD |
| 시험 중단 단계·사유 | TBD |
| 추가 메모 | TBD |

