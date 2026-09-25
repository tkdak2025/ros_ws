# CCCIS Sequence Document Index - 2026-09-22

## Current Sequence Set

1. Sequence #00 - Main Work
2. Sequence #01 - Work Initialize
3. Sequence #02 - Home Return
4. Sequence #03 - Point Transition
5. Sequence #04 - Adaptive Grip
6. Sequence #05 - Pull Inspection
7. Sequence #06 - Inspection Judgment & Work Monitoring
8. Sequence #07 - Work Finish
9. Common Sequence #01 - Pause / Resume & HMI Communication Recovery
10. Code Implementation Handoff

## Current scope assumptions

- Recipe 1회 실행 = Job 1개
- Scheduler / Recipe Queue 제외
- 외부 작업 Trigger는 HMI 통신 기반
- 내부 Sequence Transition은 자동
- Inspection Judgment는 Point 간 Robot Motion을 Blocking하지 않음
- Work Finish는 모든 Judgment/Result/Log 완료를 확인한 후 Home Return 허용
- No-Vision Phase
