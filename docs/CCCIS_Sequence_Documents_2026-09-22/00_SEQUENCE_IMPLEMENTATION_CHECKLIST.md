# CCCIS 시퀀스 구현 체크리스트

기준 문서: `CCCIS_Sequence_Documents_2026-09-22`

관리 원칙: 이 문서는 사용자 요청이 있을 때만 갱신한다.

상태 표기:

- `[x]` 구현 및 자동 테스트 완료
- `[ ]` 미구현 또는 검증 필요
- `코드`는 소프트웨어 구현 상태, `실물`은 로봇 검증 상태

## 공통 기반

- [x] 상태·판정·Pull 종료 Enum 정의
- [x] `JobContext`, `PointRuntime` 기본 구조 정의
- [ ] Recipe Snapshot을 Job 시작 시 고정
- [ ] Sequence 결과 코드와 오류 전달 규칙 통일
- [ ] HMI 상태·결과 메시지 계약 연결

## #00 Main Work

- [ ] Recipe 1회 실행을 Job 1개로 관리하는 상위 상태 머신 완성
- [ ] `START → Initialize → Home → Work Access → Point Loop` 자동 전이
- [ ] 검사포인트를 Recipe 순서대로 순회
- [ ] 각 Point의 `#03 → #04 → #05` 자동 전이
- [ ] #06 비동기 판정 등록 후 다음 Point 진행
- [ ] 마지막 Point 이후 #07 Work Finish 자동 호출
- [ ] #07 완료 후 #02 Home Return 자동 호출
- [ ] Job 시작·종료 시간과 최종 상태 저장
- [ ] 코드 단위 테스트
- [ ] 실물 전체 Cycle 검증

## #01 Work Initialize

- [x] Robot/HMI/System Recipe/Inspection Recipe 검사 호출 구조
- [x] 활성 검사포인트 목록 생성
- [ ] Recipe Snapshot 생성 및 JobContext 저장
- [ ] Point 순서 보존과 disabled Point 제외 검증
- [ ] Validation reason code 구조화
- [ ] START 이후 Recipe 원본 변경 격리 테스트
- [ ] 실물 시작 조건 검증

## #02 Home Return

- [x] 작업영역 내부/외부 복귀 경로 분기 구조
- [x] Grip Relax, Safe Escape, Work Access, Home 호출 구조
- [ ] Tool approach axis 역방향 Safe Escape 계산 검증
- [ ] Home 도달 tolerance 파라미터화
- [ ] 완료 후 Operating Stop/SYSTEM_READY 전이 검증
- [ ] 실물 내부·외부 작업영역 복귀 검증

## #03 Point Transition — Inspection Sequence

- [ ] `adaptive_grip_hardware`에서 Point Transition 책임 분리
- [ ] 첫 Point: `work_Access_safe_pose → ready_pose → entry_pose`
- [ ] 다음 Point: 이전 `ready_pose → 다음 ready_pose → entry_pose`
- [ ] Ready 이동 완료 확인
- [ ] Entry 도달 여부 확인 및 기록
- [ ] Entry 도달 여부 자체로 시퀀스 중단 금지
- [ ] 하드웨어 충돌·제어기·서비스 오류만 중단
- [ ] Pose frame과 Tool/TCP 설정 일관성 검사
- [ ] 코드 단위 테스트
- [ ] L2·L5 실물 검증

## #04 Adaptive Grip

- [x] Soft Grip 명령
- [x] Soft Grip 상태 추가 진입
- [x] 진입 힘·실제 이동량 Raw Data 기록
- [x] 진입 힘 상한/거리/시간 종료 후 다음 단계 연결
- [x] Hard Grip 20 N 명령 및 완료 확인
- [x] Hard Grip 직후 `grip_width_hard` 취득
- [x] Entry Motion Guard와 제품 판정 분리
- [ ] Point Transition 제거 후 Soft Grip부터 시작하도록 정리
- [ ] Soft/Hard Grip Wrapper 인터페이스 분리
- [x] 코드 단위 테스트
- [ ] L2·L5 실물 검증

## #05 Pull Inspection

- [x] Motion 기반 MoveL Pull
- [x] Recipe의 방향·속도·힘·최대거리·시간 사용
- [x] Force/TCP/RG2 Width Raw Data 기록
- [x] Pull 실제 이동량과 Pull Force 계산
- [x] 요구 힘 도달 시 Soft Stop
- [x] 최대 25 mm 및 10초 Timeout 종료
- [x] 5 mm를 Motion Stop 조건에서 제외
- [x] Pull 종료 사유 모델 정의
- [x] Soft Open → Entry → Ready 복귀
- [ ] 측정 결과를 #06 비동기 Queue로 전달
- [ ] Queue 전달 실패를 Point Runtime Error로 기록
- [x] 코드 단위 테스트
- [ ] L2·L5 실물 검증

## #06 Inspection Judgment & Work Monitoring

- [x] PASS/FAIL/MISSING 순수 판정 규칙
- [x] TIMEOUT/MOTION_ERROR를 제품 결과로 강제 변환하지 않음
- [x] 판정 Reason 생성 및 PointRuntime 필드 정의
- [ ] Slip Width 임계값 확정 및 자동 검출
- [ ] 비동기 Judgment Worker 구현
- [ ] `pending_judgments` 등록·완료·오류 관리
- [ ] 판정 결과를 PointRuntime에 반영
- [ ] Raw Log 저장 완료 상태 관리
- [ ] HMI에 Point 결과 전송
- [x] 순수 판정 함수 단위 테스트
- [ ] 비동기 처리 및 다음 Point 비차단 테스트

## #07 Work Finish

- [ ] 마지막 Point 이후 `work_Access_safe_pose` 이동
- [ ] 모든 Point Motion 완료 확인
- [ ] Pending Judgment 없음 확인
- [ ] 모든 Judgment COMPLETED 확인
- [ ] 모든 Point Result 및 Log 저장 확인
- [ ] FAIL/MISSING이 있어도 처리 완료 시 Job SUCCESS 허용
- [ ] INCOMPLETE/ERROR 시 정상 종료 보류
- [ ] 성공 후 #02 Home Return 내부 전이
- [ ] 완료조건 단위 테스트
- [ ] 실물 Job 종료 검증

## Common #01 Pause / Resume / HMI Recovery

- [x] PAUSE 요청과 Context 보존 구조
- [x] 명시적 RESUME 전 자동 재개 금지
- [x] STOP 시 Context 폐기
- [x] HMI 통신 유실 시 Pause 구조
- [ ] HMI Heartbeat Monitor 구현
- [ ] 하위 Sequence별 Safe Pause Point 정의
- [ ] `resume_point` 저장과 단계별 재개 구현
- [ ] Pending Judgment 포함 Context 보존 검증
- [ ] 통신 유실·복구 통합 테스트

## 현재 미확정 파라미터

- [ ] Slip Width Threshold
- [ ] RG2 Width 정상 변동 범위
- [ ] Home Reached Tolerance
- [ ] HMI Heartbeat/Timeout
- [ ] 각 Sequence Safe Pause/Resume Point
