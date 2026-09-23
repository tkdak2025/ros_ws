"""검사 단독 실행부: 전체 Job 대신 Inspection 구간을 실행한다.
1. 레시피와 실행 조건을 읽고 사용자 시작 확인을 받는다.
2. 장비·판정 클라이언트를 준비하고 활성 Point를 순서대로 검사한다.
3. 판정 완료를 기다린 뒤 측정·판정·종료 상태를 파일로 저장한다."""

import argparse
import json
import time
from dataclasses import asdict, replace
from datetime import datetime
from pathlib import Path

from cable_pkg.recipe import OperatingInspectionRecipe
from cable_pkg.recipe.system_recipe import joint_speed_from_system
from cable_pkg.data_models.sequence_models import (
    InspectionResult,
    JudgmentStatus,
    SequenceStatus,
)


# 기능: 설치된 cable_pkg의 기본 BMW 레시피 경로를 찾는다.
#
#     ------------------------------------------------------------
#     반환: 기본 레시피 파일의 Path.
def _default_recipe_path() -> Path:
    from ament_index_python.packages import get_package_share_directory

    share = Path(get_package_share_directory("cable_pkg"))
    return share / "recipe" / "inspection" / "rcp_BMW_LWR_01.json"


# 기능: 현재 포인트의 검사/건너뛰기 선택을 숫자로 받는다.
#     index: 현재 활성 포인트 순번. 1부터 시작한다.
#     total: 검사 대상 활성 포인트 수.
#     point: 현재 검사포인트 레시피. Pose(mm/deg), Grip 폭(mm)·힘(N), 이동 조건을 담는다.
#
#     ------------------------------------------------------------
#     반환: 검사 선택이면 True, 건너뛰기면 False.
def _select_point(index, total, point) -> bool:
    while True:
        print(f"\n[{index}/{total}] {point.point_id} 검사를 진행하시겠습니까?")
        print("1. 검사")
        print("2. 건너뛰기")
        answer = input("선택 [1/2]: ").strip()
        if answer in {"1", "2"}:
            return answer == "1"
        print("1 또는 2를 입력하세요.")


# 기능: 측정/판정 데이터를 UTF-8 JSON 파일로 저장한다.
#     path: 저장할 JSON 파일 경로.
#     value: JSON으로 기록할 값.
def _save_json(path: Path, value) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )


# 기능: Point 모션 결과에 비동기 판정 결과를 합친다.
#     motion_results: point_id별 검사 모션·측정 결과.
#     judgment_results: point_id별 비동기 판정 결과.
#
#     ------------------------------------------------------------
#     반환: point_id별 최종 InspectionPointResult를 담은 dict.
def _complete_results(motion_results, judgment_results):
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


# 기능: 레시피를 읽고 검사 모션·비동기 판정을 실행한 뒤 결과를 저장한다.
#     argv: 명령행 인자 목록. None이면 실행 시 전달된 인자를 읽는다.
#
#     ------------------------------------------------------------
#     반환: 성공 0, 입력 오류 2, 검사 오류 1, 사용자 중단 130.
def main(argv=None) -> int:
    from ament_index_python.packages import get_package_share_directory

    share = Path(get_package_share_directory("cable_pkg"))
    parser = argparse.ArgumentParser(description="CCCIS 실제 검사 시퀀스")
    parser.add_argument("--recipe", type=Path, default=None)
    parser.add_argument("--system-recipe", type=Path, default=share / "config/system_recipe.json")
    parser.add_argument("--results-dir", type=Path, default=Path("results/inspection_sequence"))
    args = parser.parse_args(argv)

    recipe_path = (args.recipe or _default_recipe_path()).resolve()
    try:
        recipe = OperatingInspectionRecipe.load_json(recipe_path)
        system = json.loads(args.system_recipe.read_text(encoding="utf-8"))
        joint_speed = joint_speed_from_system(system)
    except (OSError, KeyError, TypeError, ValueError) as error:
        print(f"검사 Recipe 오류: {error}")
        return 2

    enabled = [point_id for point_id in recipe.execution_order
               if recipe.points[point_id].enabled]
    print(f"Recipe: {recipe.recipe_id}")
    print(f"Joint 속도: {joint_speed:g} deg/s (System Recipe)")
    print("검사 순서: " + " → ".join(enabled))
    for point_id in enabled:
        direction = recipe.points[point_id].normalized_entry_direction()
        pull_direction = [-value if value else 0.0 for value in direction]
        print(f"  {point_id}: 추가진입(BASE)={direction}, Pull(BASE)={pull_direction}")
    print("Cycle: Ready → Entry → Soft Grip → 추가 진입 → Hard Grip → Pull → Entry → Ready")
    if input("작업영역과 케이블 상태 확인 후 START 입력: ").strip() != "START":
        print("검사를 시작하지 않았습니다.")
        return 0

    output = args.results_dir / datetime.now().astimezone().strftime("%Y%m%d_%H%M%S_%f")
    output.mkdir(parents=True, exist_ok=False)
    _save_json(output / "inputs.json", {
        "system_recipe_path": str(args.system_recipe.resolve()),
        "system_recipe": system,
        "recipe_path": str(recipe_path),
        "recipe": json.loads(recipe_path.read_text(encoding="utf-8")),
    })

    import rclpy
    from cable_pkg.hardware.inspection_robot import HardwareRobot, RobotRuntimeConfig
    from cable_pkg.sequence.inspection.inspection import InspectionSequence
    from cable_pkg.sequence.seq_06_inspection_judgment.node import (
        JudgmentClient,
    )

    robot = None
    judgment = None
    status = {"completed": False, "error": None, "executed_points": []}
    exit_code = 1
    try:
        rclpy.init(args=[])
        with (output / "samples.jsonl").open("w", encoding="utf-8") as stream:
            robot = HardwareRobot(RobotRuntimeConfig(joint_speed_deg_s=joint_speed), stream)
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
