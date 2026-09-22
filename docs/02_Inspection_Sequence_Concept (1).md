# 02. Inspection Sequence Concept
## M0609 케이블 커넥터 체결이상 검사 - 검사 시퀀스 정의

### 1. 문서 목적
본 문서는 M0609 기반 케이블 커넥터 체결이상 검사에서 **검사 포인트(Inspection Point)마다 반복 수행되는 표준 검사 시퀀스(Inspection Sequence)**의 개념을 정의한다.

본 단계에서는 세부 모션 파라미터나 Force 판정 임계값을 확정하지 않고, 팀원 간 개발 기준이 될 **검사 순서와 각 단계의 역할**을 우선 정리한다.

> 문서 체계상 본 문서는 검사결과/시편에 대한 컨셉 정리에 이은 **두 번째 컨셉 문서**로 정의한다.

---

### 2. 핵심 개념

#### 2.1 Inspection Point
실제 제품에서 로봇이 체결 상태를 검사해야 하는 개별 검사 위치를 의미한다.

제품에 여러 검사 포인트가 존재하는 경우 각 포인트로 이동한 뒤 동일한 Inspection Sequence를 반복 수행한다.

#### 2.2 Inspection Sequence
하나의 Inspection Point에서 수행되는 표준 검사 절차이다.

```text
Inspection Task
 ├─ Inspection Point 1
 │    └─ Inspection Sequence
 ├─ Inspection Point 2
 │    └─ Inspection Sequence
 └─ Inspection Point N
      └─ Inspection Sequence
```

---

### 3. 기본 검사 시퀀스

```text
InspectionPointApproach
        ↓
ToolPosAlign
        ↓
Connector Approach
        ↓
Contact Search
        ↓
Connector Grip
        ↓
Push / Pull × 2~3
        ↓
Connector Force Check
        ↓
Cable Search / Approach
        ↓
Cable Grip
        ↓
Push / Pull × 2~3
        ↓
Cable Force Check
        ↓
Inspection Result
```

---

### 4. 단계별 정의

| 단계 | 정의 | 주요 목적 |
|---|---|---|
| InspectionPointApproach | 해당 검사 포인트의 작업 가능 영역/Ready Pose로 로봇을 이동 | 검사 포인트 진입 |
| ToolPosAlign | 케이블/커넥터 파지 전에 TCP의 진입 위치와 자세를 정렬 | 접촉 탐색 및 파지를 위한 기준 자세 확보 |
| Connector Approach | 예상 커넥터 위치 방향으로 접근 | 접촉 탐색 시작 위치 확보 |
| Contact Search | 접촉식 탐색으로 실제 커넥터 위치를 탐지 | 위치 오차 보정 및 적절한 파지 위치 탐색 |
| Connector Grip | 탐색 결과를 기준으로 커넥터를 파지 | 커넥터 체결검사 준비 |
| Connector Push/Pull | 커넥터를 파지한 상태에서 2~3회 밀고 당김 | 체결 상태에 따른 Force 응답 취득 |
| Connector Force Check | Push/Pull 중 측정된 힘 데이터를 검사 | 커넥터 체결이상 판단용 데이터 확보 |
| Cable Search / Approach | 케이블 검사 위치를 탐색하고 접근 | 케이블 파지 위치 확보 |
| Cable Grip | 케이블을 검사 가능한 위치에서 파지 | 케이블 체결검사 준비 |
| Cable Push/Pull | 케이블을 파지한 상태에서 2~3회 밀고 당김 | 케이블 측 Force 응답 취득 |
| Cable Force Check | Push/Pull 중 측정된 힘 데이터를 검사 | 케이블 측 체결이상 판단용 데이터 확보 |
| Inspection Result | 커넥터 및 케이블 검사 결과를 종합 | 해당 Inspection Point의 최종 검사 결과 생성 |

---

### 5. ToolPosAlign 정의

**ToolPosAlign**은 케이블 또는 커넥터를 파지하기 직전에 툴/그리퍼 TCP를 검사에 적합한 진입 위치와 자세로 정렬하는 단계이다.

개념적으로 다음과 같이 구분한다.

```text
InspectionPointApproach
= 검사 포인트 작업 영역까지의 거시적 이동

ToolPosAlign
= 실제 접촉 탐색/파지를 위한 TCP 위치 및 자세 정렬
```

ToolPosAlign 완료 후에는 접촉식 Connector Search를 수행할 수 있는 기준 자세가 확보되어야 한다.

---

### 6. 검사 원리

검사는 크게 두 구간으로 구성한다.

#### A. Connector 체결검사
1. 커넥터 위치를 접촉식으로 탐색한다.
2. 파지하기 적절한 위치를 결정한다.
3. 커넥터를 Grip한다.
4. Push/Pull을 2~3회 반복한다.
5. 이 과정에서 로봇/툴에 작용하는 Force 데이터를 취득한다.

#### B. Cable 체결검사
1. 케이블 검사 위치로 이동 또는 탐색한다.
2. 케이블을 Grip한다.
3. Push/Pull을 2~3회 반복한다.
4. Force 데이터를 취득한다.
5. Connector 검사 결과와 함께 최종 체결 상태 판단에 사용한다.

---

### 7. Force 기반 판정에 대한 현재 원칙

현재 검사 컨셉에서는 **그리퍼/툴에 작용하는 힘을 체결이상 판단의 주요 신호로 사용**한다.

다만 현재 단계에서 정상/이상 판정 Threshold는 확정하지 않는다.

기존 수동 시험에서 Pull 시 약 10 N 수준의 최대 차이가 관찰된 사례가 있으나, 이는 2~3회 수준의 수동 측정 결과이며 반복성 검증을 거친 판정 기준이 아니다.

따라서 다음 항목을 반복시험으로 확인한 뒤 판정 범위를 결정해야 한다.

- 정상 시편 Force 분포
- 이상 시편 Force 분포
- 반복시험 간 편차
- Push와 Pull 각각의 특성
- 최대 Force, 평균 Force, Force 변화량 등 유효 Feature
- 정상/이상 데이터의 분리 가능성
- 로봇 자세, Grip 위치, 속도 등에 따른 측정 편차

**현재 확정 범위:** Push/Pull 과정에서 Force 데이터를 취득한다.  
**추후 검증 범위:** 어떤 Force Feature와 Threshold가 신뢰성 있는 이상 판정 기준인지 결정한다.

---

### 8. 검사 포인트 반복 구조

제품에 N개의 검사 포인트가 있다면 다음 구조로 운용한다.

```text
for each Inspection Point:
    InspectionPointApproach
    ToolPosAlign
    Connector Inspection
    Cable Inspection
    Inspection Result
```

따라서 Inspection Sequence 자체는 공통 로직으로 구성하고, 검사 포인트별로 필요한 위치/자세 및 탐색 관련 파라미터를 변경하는 구조를 기본 컨셉으로 한다.

---

### 9. 현재 확정사항과 미확정사항

#### 확정사항
- 검사 포인트마다 동일한 Inspection Sequence를 수행한다.
- ToolPosAlign 전에 InspectionPointApproach 단계를 둔다.
- ToolPosAlign은 파지 전 TCP 진입 위치/자세 정렬 단계이다.
- 커넥터는 접촉식으로 탐색하여 파지 위치를 결정한다.
- 커넥터 Grip 후 Push/Pull을 2~3회 수행한다.
- 이후 케이블도 동일한 개념으로 검사한다.
- 검사 중 Force 데이터를 취득하여 체결이상 판정에 활용한다.

#### 추후 검증사항
- Contact Search의 구체적인 탐색 패턴
- Connector/Cable의 정확한 Grip 위치
- Push/Pull 이동 거리 및 속도
- 반복 횟수 최종 확정
- Force 측정 축 및 Feature 선정
- 정상/이상 Threshold
- 측정 반복성 및 재현성
- 최종 검사결과 판정 로직

---

### 10. 한 줄 정의

> **Inspection Sequence는 각 Inspection Point에 진입한 뒤 ToolPosAlign, 접촉식 위치 탐색, Connector/Cable Grip-Push/Pull 및 Force 측정을 순차 수행하여 체결이상 여부를 판단하기 위한 반복 검사 단위이다.**
