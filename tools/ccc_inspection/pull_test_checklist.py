"""케이블 Pull 시험 기능 요구사항 수동 점검표.

실행 예: python3 pull_test_checklist.py
결과 경로 지정: python3 pull_test_checklist.py --output-dir ./check_results

Python 표준 라이브러리만 사용한다. ROS 연결, 로봇 동작, 측정은 수행하지
않으며 사용자가 확인한 시험 결과와 근거를 기록한다. '통과'는 자동 검증
결과가 아니다. 미확인/실패 항목이 하나라도 있으면 전체 통과로 표시하지 않는다.
입력 중 Ctrl+C 또는 EOF가 발생하면 입력된 내용까지 중간 저장한다.
"""

import argparse
import json
from datetime import datetime
from pathlib import Path
from uuid import uuid4


REQUIREMENTS = (
    ("test_info", "시험 정보", (
        "케이블 종류, 시편 ID, 시험 회차가 시험 결과에 기록되는가?",
    )),
    ("baseline", "기준값 확보", (
        "파지 후 Pull 직전에 기준값을 측정하는가?",
        "기준 힘과 기준 TCP 위치를 저장하는가?",
    )),
    ("continuous_measurement", "연속 측정", (
        "시간, 힘, TCP 위치를 연속 저장하는가?",
        "기준 위치 대비 Pull 방향 변위를 저장하는가?",
        "힘·위치·변위의 단위와 기준 좌표계, Pull 방향을 식별할 수 있는가?",
    )),
    ("phases", "단계 구분", (
        "기준 측정 → Pull → 유지 → 하중 해제 단계가 구분되는가?",
        "각 측정값이 어느 단계에서 수집되었는지 확인할 수 있는가?",
    )),
    ("termination", "종료 조건", (
        "설정한 힘 제한에 도달하면 Pull을 종료하는가?",
        "설정한 이동량 제한에 도달하면 Pull을 종료하는가?",
        "설정한 시간 제한에 도달하면 Pull을 종료하는가?",
    )),
    ("results", "결과 저장", (
        "원본 측정값을 CSV로 저장하는가?",
        "힘–시간 그래프를 생성하는가?",
        "변위–시간 그래프를 생성하는가?",
        "힘–변위 그래프를 생성하는가?",
    )),
    ("observations", "수동 관찰 입력", (
        "미끄러짐 여부를 수동 입력하고 저장할 수 있는가?",
        "이탈 여부를 수동 입력하고 저장할 수 있는가?",
        "관찰 메모를 입력하고 저장할 수 있는가?",
    )),
)

STATUS_LABELS = {"pass": "통과", "fail": "실패", "unchecked": "미확인"}


class GripPullChecker:
    """시험 정보와 요구사항 점검 상태를 관리하고 결과를 저장한다."""

    def __init__(self, output_dir):
        self.output_dir = Path(output_dir)
        self.report = {
            "schema_version": 1,
            "assessment_method": "manual_checklist",
            "started_at": datetime.now().astimezone().isoformat(timespec="seconds"),
            "completed": False,
            "test_info": {},
            "requirements": [
                {
                    "id": key,
                    "name": name,
                    "checks": [
                        {"question": question, "status": "unchecked", "evidence": ""}
                        for question in questions
                    ],
                }
                for key, name, questions in REQUIREMENTS
            ],
        }

    @staticmethod
    def _required_input(prompt):
        while True:
            value = input(prompt).strip()
            if value:
                return value
            print("값을 입력해 주세요.")

    @staticmethod
    def _aggregate(statuses):
        if "fail" in statuses:
            return "fail"
        if statuses and all(status == "pass" for status in statuses):
            return "pass"
        return "unchecked"

    def collect(self):
        info = self.report["test_info"]
        info["cable_type"] = self._required_input("케이블 종류: ")
        info["specimen_id"] = self._required_input("시편 ID: ")
        while True:
            value = input("시험 회차 (1 이상의 정수): ").strip()
            try:
                cycle = int(value)
            except ValueError:
                print("1 이상의 정수를 입력해 주세요.")
                continue
            if cycle >= 1:
                info["test_cycle"] = cycle
                break
            print("1 이상의 정수를 입력해 주세요.")
        info["reviewer"] = input("점검자 (선택): ").strip()
        print("\n상태: p=통과, f=실패, u=미확인, Enter=미확인")
        print("통과/실패 선택 시 확인 근거를 입력하세요. 실제 시험은 별도로 수행해야 합니다.")
        for index, requirement in enumerate(self.report["requirements"], start=1):
            print(f"\n[{index}/7] {requirement['name']}")
            for check in requirement["checks"]:
                print(f"  {check['question']}")
                while True:
                    choice = input("  상태 [p/f/u]: ").strip().lower()
                    if choice in ("p", "f", "u", ""):
                        break
                    print("  p, f, u 중 하나를 입력해 주세요.")
                status = {"p": "pass", "f": "fail", "u": "unchecked", "": "unchecked"}[choice]
                # 근거 입력이 끝나기 전에 중단되면 기존 '미확인' 상태를 유지한다.
                if status in ("pass", "fail"):
                    evidence = self._required_input("  근거 (파일 경로, 로그, 관찰 결과 등): ")
                else:
                    evidence = input("  미확인 사유/메모 (선택): ").strip()
                check.update(status=status, evidence=evidence, checked_at=datetime.now().astimezone().isoformat(timespec="seconds"))
        self.report["notes"] = input("\n전체 점검 메모 (선택): ").strip()
        self.report["completed"] = True

    def save_report(self):
        all_statuses = []
        for requirement in self.report["requirements"]:
            statuses = [check["status"] for check in requirement["checks"]]
            requirement["status"] = self._aggregate(statuses)
            all_statuses.extend(statuses)
        self.report["overall_status"] = self._aggregate(all_statuses)
        self.report["saved_at"] = datetime.now().astimezone().isoformat(timespec="seconds")
        self.output_dir.mkdir(parents=True, exist_ok=True)
        filename = f"pull_checklist_{datetime.now():%Y%m%d_%H%M%S}_{uuid4().hex[:8]}.json"
        path = self.output_dir / filename
        # 기존 점검 결과를 덮어쓰지 않는다.
        with path.open("x", encoding="utf-8") as stream:
            json.dump(self.report, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
        return path


def main():
    parser = argparse.ArgumentParser(description="케이블 Pull 시험 요구사항 수동 점검표")
    parser.add_argument(
        "--output-dir", type=Path,
        default=Path(__file__).resolve().parent.parent / "check_results",
        help="JSON 저장 폴더 (기본: PRJT_prototype/check_results)",
    )
    args = parser.parse_args()
    checker = GripPullChecker(args.output_dir)
    print("케이블 Pull 시험 기능 요구사항 점검 — 로봇 제어/자동 검증 없음")
    try:
        checker.collect()
    except (KeyboardInterrupt, EOFError):
        print("\n입력이 중단되었습니다. 현재까지의 점검 내용을 저장합니다.")
    try:
        path = checker.save_report()
    except OSError as error:
        print(f"저장 실패: {error}")
        print("복구용 점검 내용:")
        print(json.dumps(checker.report, ensure_ascii=False, indent=2))
        return 2
    print("\n점검 결과")
    for requirement in checker.report["requirements"]:
        print(f"- {requirement['name']}: {STATUS_LABELS[requirement['status']]}")
    print(f"전체 상태: {STATUS_LABELS[checker.report['overall_status']]}")
    print(f"입력 완료: {'예' if checker.report['completed'] else '아니오 (중간 저장)'}")
    print(f"저장 파일: {path.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
