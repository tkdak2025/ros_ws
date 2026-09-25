# Sequence #04 - Adaptive Grip Sequence

**프로젝트:** CCCIS (Contact-based Cable Connection Inspection System)  
**환경:** Doosan M0609 + OnRobot RG2 / No-Vision Phase  
**작업 단위:** Recipe 1회 실행 = Job 1개  
**외부 Trigger:** HMI 통신 기반 START / PAUSE / RESUME / STOP / HOME_RETURN  
**작성 기준일:** 2026-09-22


## 1. 목적

`entry_pose`에서 Recipe 기반 Soft Grip 상태로 Cable 진입을 수행한 후 Hard Grip으로 전환하여 Pull Inspection을 시작할 수 있는 상태를 만든다.

## 2. 설계 의도

- Adaptive Grip은 특정 Connector에 종속되지 않는 공통 Sequence다.
- Cable 형상/위치 편차를 Soft Grip + Entry Motion으로 흡수한다.
- 실제 진입거리가 목표 Depth보다 짧다고 실패로 판단하지 않는다.
- Soft Grip 자체에 성공/실패 판정을 두지 않는다.
- Hard Grip은 Recipe Command 실행 여부만 확인하며 Cable을 잘 잡았다고 추론하지 않는다.
- Pull Slip 판별을 위해 Hard Grip 완료 직후 실제 RG2 Width를 기준값으로 저장한다.

## 3. 진입 조건

- #03 Point Transition 완료
- Robot이 대상 Point `entry_pose`에 위치
- Point Recipe의 `entry_direction`, Soft/Hard Grip 설정 유효

## 4. Sequence Flow

```text
entry_pose
    |
    v
Soft Grip Command
- Width = Recipe
- Force = Recipe
    |
    v
Entry movel
- Direction = entry_direction
- Max Distance = min(Point entry limit, 25 mm)
- Timeout = 10 s
- Force Guard = 5 N candidate
    |
    v
Entry Motion Termination
    |
    v
Immediately Hard Grip Command
- Width = Recipe
- Force = Recipe
    |
    v
Hard Grip Operation Check
    |
    +-- tool/action abnormal --> System Tool/Grip Error
    |
    v
Measure RG2 Width
- grip_width_hard
- timestamp
    |
    v
ADAPTIVE_GRIP_DONE
    |
    v
#05 Pull Inspection
```

## 5. Flow 용어 설명

| 용어 | 설명 |
|---|---|
| Soft Grip | Cable 진입 중 유연한 정렬을 허용하기 위한 Recipe 기반 파지 상태 |
| Entry Motion | `entry_direction`으로 진행하는 `movel` 진입 |
| Force Guard | 진입 중 과도한 접촉을 막는 Motion Guard, Grip 성공 기준이 아님 |
| Hard Grip | Pull 직전 Recipe 기반 최종 파지 |
| grip_width_hard | Hard Grip 직후 측정한 RG2 실제 Width. Pull 중 Width 변화의 기준값 |

## 6. 세부 동작 및 판단 조건

- Entry 최대 이동: 25 mm 상한
- Entry Timeout: 10 s
- Entry Force Guard: 5 N 후보, 검증 필요
- Entry는 Distance/Force Guard/Timeout 중 Guard 조건으로 종료될 수 있음
- 실제 이동거리가 짧아도 Grip 실패로 간주하지 않음
- Entry 종료 즉시 Hard Grip, 별도 Settling Delay 없음
- `actual_width == Recipe width`를 성공조건으로 사용하지 않음
- `grip_width_hard`는 측정/Logging 값이지 성공 판정값이 아님

현재 별도 예외/Test Case:
- Adjacent Cable Interference
- Tip Contact + Periodic Motion

위 항목은 Normal Flow에 포함하지 않는다.

## 7. 정상 종료 조건

- Hard Grip Command/Action 정상 수행
- `grip_width_hard` + Timestamp 기록
- Robot/Tool Error 없음

## 8. 비정상 / 예외 처리

- RG2 Command/Action 자체 실패 -> System Tool/Grip Error
- Cable 체결 정상/불량은 이 Sequence에서 판단하지 않음
- Slip 여부도 이 단계에서 판정하지 않고 #05/#06에서 판단

## 9. 상위·하위 Sequence Interface

**입력:** Point Recipe grip/entry settings  
**출력:** `grip_width_hard`, timestamp, adaptive_grip_done  
**다음:** #05 Pull Inspection

## 10. 코드 구현 포인트

- Hard Grip 완료 시 RG2 실제 Width 읽기 API 검증 필요
- Soft/Hard Grip Command Wrapper 분리
- Entry Motion Guard는 제품 판정 로직과 분리
