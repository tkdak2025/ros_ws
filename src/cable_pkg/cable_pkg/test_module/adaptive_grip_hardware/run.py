"""선택한 검사포인트의 Adaptive Grip 실물 시퀀스를 Recipe 순서대로 실행한다."""

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

# `ros2 run`에서는 cable_pkg 패키지로 import된다.
# VS Code의 "Python 파일 실행"처럼 이 파일을 직접 실행하면 패키지 정보가 없으므로,
# cable_pkg가 들어 있는 패키지 루트(src/cable_pkg)를 Python 검색 경로에 추가한다.
if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from cable_pkg.test_module.adaptive_grip.sequence import ValidationStage
from cable_pkg.test_module.adaptive_grip_hardware.paths import RECIPE_PATH, RESULTS_DIR
from cable_pkg.test_module.adaptive_grip_hardware.recipe import load_recipe, load_trial
from cable_pkg.test_module.adaptive_grip_hardware.sequence import HardwareConfig, HardwareSequence

# 읽는 순서: main()의 설정 읽기 → 실행 확인 → 연결 → sequence.run() → 종료/저장.
# sequence.py는 단계 순서, robot.py는 실제 명령과 측정을 담당한다.

# ----------------------------------------------------------------------
# 단계 종료 시 작업자가 판단하는 공통 Gate 입력
# ----------------------------------------------------------------------
def confirm(stage, data):
    """단계 측정값을 보여주고 숫자로 Gate 결과를 입력받는다."""
    print(json.dumps(data, ensure_ascii=False, indent=2))
    print(f"{stage.value}: 해당 단계의 간섭·Slip·손상·파지/정렬 상태를 관찰하세요.")
    while True:
        print("1. 통과하고 다음 단계 진행")
        print("2. 실패 처리하고 시험 중단")
        choice = input("선택 [1/2]: ").strip()
        if choice == "1":
            return True
        if choice == "2":
            return False
        print("1 또는 2를 입력하세요.")


def should_inspect_point(order, total, point_id):
    """현재 Cycle의 검사포인트를 실행할지 숫자로 확인한다."""
    while True:
        print(f"\n[{order}/{total}] {point_id} 검사를 진행하시겠습니까?")
        print("1. 검사")
        print("2. 건너뛰기")
        choice = input("선택 [1/2]: ").strip()
        if choice == "1":
            return True
        if choice == "2":
            return False
        print("1 또는 2를 입력하세요.")


def execute_trial(sequence, config, point_id, hardware_type):
    """검사포인트 한 회차를 실행하고 해당 회차 폴더에 결과를 저장한다."""
    output = RESULTS_DIR / datetime.now().astimezone().strftime("%Y%m%d_%H%M%S_%f")
    output.mkdir(parents=True, exist_ok=False)
    snapshot = {"recipe": json.loads(RECIPE_PATH.read_text(encoding="utf-8")),
                "conditions": vars(config), "point": point_id, "stop_after": "V09"}
    (output / "inputs.json").write_text(
        json.dumps(snapshot, ensure_ascii=False, indent=2), encoding="utf-8")
    hardware = None
    status = {"completed": False, "error": None, "data_type": "adaptive_grip_hardware"}
    code = 1
    try:
        with (output / "samples.jsonl").open("w", encoding="utf-8") as stream:
            hardware = hardware_type(config, stream)
            hardware.axis = sequence.point.connector_axis[:]
            sequence.set_hardware(hardware)
            hardware.connect()
            results = sequence.run(ValidationStage.GRIP_PULL_LOGGING)
            final_data = results[-1].data
            status["inspection_result"] = final_data.get("judgment")
            status["completed"] = True
            code = 0
    except BaseException as error:
        if hardware is not None:
            hardware.safe_abort()
        status["error"] = f"{type(error).__name__}: {error}"
        status["interrupted_phase"] = getattr(hardware, "phase", "V01_RECIPE")
        print(f"시험 중단: {status['error']}")
        code = 130 if isinstance(error, (KeyboardInterrupt, EOFError)) else 1
    finally:
        if hardware is not None:
            hardware.close()
        sequence.save_results(output / "gates.json")
        (output / "status.json").write_text(
            json.dumps(status, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"시험 기록: {output.resolve()}")
    return code


def main(argv=None):
    # ------------------------------------------------------------------
    # 1. 실행 인자: 기본은 Recipe 전체 Cycle, 인자가 있으면 단일 포인트 시험이다.
    # ------------------------------------------------------------------
    parser = argparse.ArgumentParser(description="Adaptive Grip 실물 단계 시험")
    parser.add_argument("point", nargs="?", help="recipe.json의 검사포인트 ID")
    args = parser.parse_args(argv)
    # ------------------------------------------------------------------
    # 2. 파일 읽기와 정적 검증: 여기까지는 ROS 연결이나 로봇 명령이 없다.
    # ------------------------------------------------------------------
    try:
        recipe = load_recipe(RECIPE_PATH)
        enabled = [point.point_id for point in recipe.points.values() if point.enabled]
        point_ids = [args.point] if args.point is not None else enabled
        trials = []
        for point_id in point_ids:
            point_recipe, conditions = load_trial(RECIPE_PATH, point_id)
            config = HardwareConfig(**conditions)
            sequence = HardwareSequence(point_recipe, point_id, config, None, confirm)
            trials.append((point_id, config, sequence))
    except (KeyboardInterrupt, EOFError):
        return 130
    except (ValueError, TypeError, KeyError, OSError) as error:
        print(f"시험조건 오류(로봇 연결 전): {error}")
        return 2
    # ------------------------------------------------------------------
    # 3. 전체 V01~V09 조건 출력과 시작 확인
    # ------------------------------------------------------------------
    print(f"실물 시험: {recipe.recipe_id} / 활성 포인트 {len(trials)}개")
    for order, (point_id, _, _) in enumerate(trials, start=1):
        print(f"[{order}/{len(trials)}] {point_id}")
    print("순서: Entry 접근 → Soft Grip → Entry → Hard Grip → Pull → Entry → Ready")
    try:
        if input("시험 구역·경로와 조건 확인 후 START 입력: ").strip() != "START":
            print("취소했습니다.")
            return 0
    except (KeyboardInterrupt, EOFError):
        return 130

    # ROS 의존성은 실제 실행을 요청했을 때만 불러온다.
    import rclpy
    from cable_pkg.test_module.adaptive_grip_hardware.robot import HardwareRobot

    code = 1
    try:
        rclpy.init(args=[])
        code = 0
        for order, (point_id, config, sequence) in enumerate(trials, start=1):
            if args.point is None and not should_inspect_point(order, len(trials), point_id):
                print(f"[{order}/{len(trials)}] {point_id} 건너뛰기")
                continue
            print(
                f"[{order}/{len(trials)}] {point_id} 검사 시작: "
                f"Entry {config.search_mm:g} mm / Soft {config.soft_force_n:g} N / "
                f"Hard {config.hard_force_n:g} N / Pull {config.pull_force_limit_n:g} N, "
                f"최대 {config.pull_mm:g} mm, {config.pull_timeout_s:g} s"
            )
            code = execute_trial(sequence, config, point_id, HardwareRobot)
            if code != 0:
                break
    finally:
        if rclpy.ok():
            rclpy.shutdown()
    return code


if __name__ == "__main__":
    raise SystemExit(main())
