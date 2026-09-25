> 이 문서는 이전 설계·작업 기록입니다. 현재 기준은 [v4 문서 안내](../../v4/00_문서안내_v4.md)이며, 이후 변경 내용은 [최종결론](../../작업내역/18_최종결론_2026-09-25.md)을 참고하세요. 아래 본문은 이력으로 보존합니다.

# CCCIS Sequence Document Index - 2026-09-22

갱신 안내 (2026-09-25): 이 폴더의 Markdown은 후속 정책 변경을 반영했으며 같은 이름의 PDF는 갱신 전 보존본입니다. 최신 용어는 Ready→Entry pose **접근**, Entry pose에서 Tool +Z Soft Grip 이동 **진입**, 반대 방향 **Pull**입니다. RG2 busy는 기록만 하고 완료 조건으로 사용하지 않습니다. [시퀀스 작업내역](<../시퀀스 작업내역.md>), [Home Return 정책](../../작업내역/10_Home_Return_정책_검토_2026-09-25.md)을 함께 확인합니다.

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
