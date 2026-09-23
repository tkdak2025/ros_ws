"""운영 Inspection Recipe로 실제 #03~#05 Point Cycle을 실행한다."""

import argparse
import json
import time
from dataclasses import asdict, replace
from datetime import datetime
from pathlib import Path

from cable_pkg.recipe import OperatingInspectionRecipe
from cable_pkg.data_models.sequence_models import (
    InspectionResult,
    JudgmentStatus,
    SequenceStatus,
)


def _default_recipe_path() -> Path:
    from ament_index_python.packages import get_package_share_directory

    share = Path(get_package_share_directory("cable_pkg"))
    return share / "recipe" / "inspection" / "lan_inspection_recipe.json"


def _select_point(index, total, point) -> bool:
    """Recipe 순서대로 현재 포인트만 실행 여부를 확인한다."""
    while True:
        print(f"\n[{index}/{total}] {point.point_id} 검사를 진행하시겠습니까?")
        print("1. 검사")
        print("2. 건너뛰기")
        answer = input("선택 [1/2]: ").strip()
        if answer in {"1", "2"}:
            return answer == "1"
        print("1 또는 2를 입력하세요.")


def _save_json(path: Path, value) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )


def _complete_results(motion_results, judgment_results):
    """비동기 #06 결과를 Point 종합 결과에 반영한다."""
    completed = {}
    for point_id, motion in motion_results.items():
        judgment = judgment_results[point_id]
        product_result = judgment.get("result")
        completed[point_id] = replace(
            motion,
            judgment_status=JudgmentStatus(judgment["judgment_status"]),
            sequence_status=SequenceStatus(judgment["sequence_status"]),
            result=(InspectionResult(product_result) if product_result else None),
            reason=str(judgment["reason"]),
        )
    return completed


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="CCCIS 실제 검사 시퀀스")
    parser.add_argument("--recipe", type=Path, default=None)
    parser.add_argument("--results-dir", type=Path, default=Path("results/inspection_sequence"))
    args = parser.parse_args(argv)

    recipe_path = (args.recipe or _default_recipe_path()).resolve()
    try:
        recipe = OperatingInspectionRecipe.load_json(recipe_path)
    except (OSError, KeyError, TypeError, ValueError) as error:
        print(f"검사 Recipe 오류: {error}")
        return 2

    enabled = [point_id for point_id in recipe.execution_order
               if recipe.points[point_id].enabled]
    print(f"Recipe: {recipe.recipe_id}")
    print("검사 순서: " + " → ".join(enabled))
    print("Cycle: Ready → Entry → Soft Grip → 추가 진입 → Hard Grip → Pull → Entry → Ready")
    if input("작업영역과 케이블 상태 확인 후 START 입력: ").strip() != "START":
        print("검사를 시작하지 않았습니다.")
        return 0

    output = args.results_dir / datetime.now().astimezone().strftime("%Y%m%d_%H%M%S_%f")
    output.mkdir(parents=True, exist_ok=False)
    _save_json(output / "inputs.json", {
        "recipe_path": str(recipe_path),
        "recipe": json.loads(recipe_path.read_text(encoding="utf-8")),
    })

    import rclpy
    from cable_pkg.hardware.inspection_robot import HardwareRobot, RobotRuntimeConfig
    from cable_pkg.sequence.inspection.seq_00_inspection import InspectionSequence
    from cable_pkg.sequence.inspection.seq_06_inspection_judgment_node import (
        JudgmentClient,
    )

    robot = None
    judgment = None
    status = {"completed": False, "error": None, "executed_points": []}
    exit_code = 1
    try:
        rclpy.init(args=[])
        with (output / "samples.jsonl").open("w", encoding="utf-8") as stream:
            robot = HardwareRobot(RobotRuntimeConfig(), stream)
            judgment = JudgmentClient(robot.node)
            judgment.wait_for_subscriber()
            robot.connect()
            results = InspectionSequence(
                robot,
                _select_point,
                judgment.submit,
                run_id=int(time.time()),
            ).run(recipe)
            # 판정 응답이 늦거나 실패해도 측정 결과는 먼저 보존한다.
            status["executed_points"] = list(results)
            _save_json(output / "inspection_results.json", {
                point_id: asdict(result) for point_id, result in results.items()
            })
            judgment_results = judgment.wait_for_all()
            results = _complete_results(results, judgment_results)
            serializable = {
                point_id: asdict(result) for point_id, result in results.items()
            }
            _save_json(output / "inspection_results.json", serializable)
            _save_json(output / "judgment_results.json", judgment_results)
            status["executed_points"] = list(results)
            status["judgment_completed_points"] = list(judgment_results)
            status["completed"] = True
            exit_code = 0
    except (KeyboardInterrupt, EOFError) as error:
        status["error"] = type(error).__name__
        exit_code = 130
        if robot is not None:
            robot.safe_abort()
    except BaseException as error:
        status["error"] = f"{type(error).__name__}: {error}"
        status["interrupted_phase"] = getattr(robot, "phase", "PREFLIGHT")
        print(f"검사 중단: {status['error']}")
        if robot is not None:
            robot.safe_abort()
    finally:
        if judgment is not None:
            # 오류로 모션을 중단해도 이미 요청한 포인트의 판정은 파일에 보존한다.
            try:
                judgment.wait_for_all()
            except Exception as error:
                status["judgment_error"] = str(error)
            _save_json(output / "judgment_results.json", judgment.results)
            counts = {result.value: 0 for result in InspectionResult}
            for result in judgment.results.values():
                counts[result["result"]] += 1
            _save_json(output / "job_summary.json", {
                "counts": counts,
                "pending_points": [point for _, point in sorted(judgment.pending)],
                "all_requested_results_present": not judgment.pending,
            })
        if robot is not None:
            robot.close()
        if rclpy.ok():
            rclpy.shutdown()
        _save_json(output / "status.json", status)
        print(f"검사 기록: {output.resolve()}")
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
