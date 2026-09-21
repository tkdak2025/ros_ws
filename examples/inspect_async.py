"""
검사 뼈대 (측정 없음): HMI 에서 고른 Recipe 의 Point 를 차례로 돌며 결과를 HMI 로 보고한다.

비동기 모션(amove* + check_motion)과 HMI 검사 시작 / 일시정지 / 이어하기 / STOP 연동에
'Recipe 읽기' 와 '결과 보고' 를 더한 것이다. sodvir(가상 로봇)에서 검사 흐름과 HMI 표시를 미리
맞춰 보기 위한 것으로, 아직 없는 것은 다음과 같다.

  - 측정·판정: judge() 가 자리만 잡고 있다. 힘·변위를 읽지 않으므로 모든 Point 를
    MISSING(유효 검사 미완료, 사유 '측정 미구현')으로 보고하고, 제품 판정은 '미검사 Point 있음' 이 된다.
    실제 로봇에서는 judge() 안에서 Pull 중의 힘·변위를 읽어 PASS / FAIL_* 를 돌려주면 된다.
  - 그리퍼: grip() / release() 가 자리만 잡고 있다(아무것도 잡지 않는다).

포인트 이동: 검사가 끝난 뒤 HMI 의 'FAIL 포인트 이동' / 'MISSING 포인트 이동' 을 누르면 그 Point 의
접근 자세(레시피의 joint)로 이동만 한다. 작업자가 그 자리에서 확인·재체결하기 위한 것이고 재검사는
하지 않는다. 이동 중에도 일시정지 / 이어하기 / STOP 이 된다. 티칭 안 된 Point 로는 가지 않는다.

Point 하나의 동작:  접근(레시피의 joint 로 관절 이동) -> 파지 -> Pull(툴 -Z 로 PULL_MM) -> 후퇴(제자리로)
좌표가 전부 0 인(티칭 안 된) Point 는 움직이지 않고 MISSING(사유 '미티칭')으로 보고한다.

위치는 레시피 JSON(RECIPE_DIR), 케이블·판정 기준은 DB(RECIPE_DB)에서 읽는다. HMI 와 같은 곳을 봐야
화면의 Recipe 목록과 어긋나지 않는다(hmi_monitor.launch.py 의 recipe_dir / recipe_db 기본값과 같다).

실행:
  sod && source ~/ros_ws/install/setup.bash
  python3 ~/ros_ws/examples/inspect_async.py --make-test-recipe   # (한 번만) 가상 로봇용 레시피 VIRTUAL_TEST 를 만든다
  python3 ~/ros_ws/examples/inspect_async.py                       # HMI 에서 Recipe 를 고르고 '검사 시작'
"""

import json
from pathlib import Path
import sys
import time

from cable_hmi import interface as itf
from cable_hmi import recipe_catalog, recipe_db
from cable_hmi.hmi_progress import HmiStop, ProgressReporter
import DR_init
from dsr_msgs2.srv import MovePause, MoveResume, SetCurrentTool
import rclpy

ROBOT_ID = "dsr01"
ROBOT_MODEL = "m0609"
VELOCITY, ACC = 30, 30
PULL_VELOCITY, PULL_ACC = 10, 10
PULL_MM = 10.0            # Pull 단계에서 툴 -Z 방향으로 물러나는 거리

RECIPE_DIR = Path("~/ros_ws/recipe_prototype/recipe/examples").expanduser()
RECIPE_DB = Path("~/ros_ws/results/inspection.db").expanduser()
STEPS = ["접근", "파지", "Pull", "후퇴"]

MOTION_START_WAIT = 0.3   # amove 를 건 뒤 모션이 실제로 시작될 때까지 기다리는 시간 (s)
POLL_PERIOD = 0.05        # check_motion 을 다시 묻는 간격 (s)
DR_MV_RA_OVERRIDE = 1     # 진행 중인 모션을 버리고 새 모션으로 대체
SERVICE_TIMEOUT = 3.0     # move_pause / move_resume 응답을 기다리는 시간 (s)
DRIVER_WAIT = 10.0        # 시작할 때 두산 드라이버가 보일 때까지 기다리는 시간 (s)

# --make-test-recipe 가 만드는 레시피: 가상 로봇에서 안전하게 오가는 자세의 관절각 (deg)
TEST_RECIPE_FILE = RECIPE_DIR / "virtual_test.json"
TEST_RECIPE_ID = "VIRTUAL_TEST"
TEST_POINTS = {
    "VT_P01": ("VIRTUAL_POINT_1", [0.0, 0.0, 90.0, 0.0, 30.0, 0.0]),
    "VT_P02": ("VIRTUAL_POINT_2", [20.0, 10.0, 80.0, 0.0, 60.0, 0.0]),
    "VT_P03": ("VIRTUAL_POINT_3", [-20.0, 10.0, 80.0, 0.0, 60.0, 0.0]),
}

DR_init.__dsr__id = ROBOT_ID
DR_init.__dsr__model = ROBOT_MODEL


def judge(point, info):
    """
    측정·판정 자리. (결과 코드, 사유, 측정값 dict) 를 돌려준다.

    아직 측정이 없으므로 '유효한 검사를 하지 못함' 으로 보고한다. 실제 로봇에서는 Pull 중에 읽은
    변위를 info.max_displacement_mm 와 비교해 PASS / FAIL_DISPLACEMENT / FAIL_DETACHED 를 돌려주고,
    측정값은 {'max_force_n': ..., 'displacement_mm': ...} 로 채운다.
    info.pull_force_limit_n 은 판정 기준이 아니라 Pull 을 멈추는 힘(안전 상한)이다 - 비교 대상이
    아니라 '여기까지만 당긴다' 는 조건이고, 상한에 닿아 멈췄다면 그 사실을 사유에 적는다.
    """
    return itf.ResultCode.MISSING, "측정 미구현 (동작 뼈대만 실행)", {}


def main(args=None):
    rclpy.init(args=args)
    node = rclpy.create_node("cable_inspect_async", namespace=ROBOT_ID)
    log = node.get_logger()

    DR_init.__dsr__node = node

    try:
        from DSR_ROBOT2 import (
            set_tool,
            set_tcp,
            amovej,
            amovel,
            check_motion,
            fkin,
            DR_TOOL,
            DR_MV_MOD_REL,
        )

        from DR_common2 import posx, posj

    except ImportError as e:
        log.info(f"Error importing DSR_ROBOT2 : {e}")
        return

    # 두산 라이브러리의 호출은 응답을 끝없이 기다린다. 드라이버가 안 떠 있거나 아직 연결되기 전에
    # 부르면 그대로 멈춰 버리므로, 서비스가 보이는지 먼저 확인한다.
    probe = node.create_client(SetCurrentTool, "dsr_controller2/tool/set_current_tool")
    if not probe.wait_for_service(timeout_sec=DRIVER_WAIT):
        log.error("두산 드라이버가 보이지 않음 - sodvir / sodreal 을 먼저 실행하세요")
        node.destroy_node()
        rclpy.shutdown()
        return
    node.destroy_client(probe)

    set_tool("ToolWeight")
    set_tcp("GripperDA_v1")

    if "--make-test-recipe" in sys.argv:
        make_test_recipe(fkin, posj, log)
        node.destroy_node()
        rclpy.shutdown()
        return

    # points 는 '검사 시작' 뒤에 Recipe 를 읽고 set_points() 로 맞춘다.
    progress = ProgressReporter(node, points=1, steps=STEPS, control=True)

    pause_client = node.create_client(MovePause, "dsr_controller2/motion/move_pause")
    resume_client = node.create_client(MoveResume, "dsr_controller2/motion/move_resume")

    def call(client, request, name):
        if not client.wait_for_service(timeout_sec=1.0):
            log.error(f"{name}: 서비스 없음")
            return False
        future = client.call_async(request)
        rclpy.spin_until_future_complete(node, future, timeout_sec=SERVICE_TIMEOUT)
        ok = future.done() and future.result() is not None and future.result().success
        log.info(f"{name}: {'성공' if ok else '실패'}")
        return ok

    def pause_motion():
        return call(pause_client, MovePause.Request(), "move_pause")

    def resume_motion():
        return call(resume_client, MoveResume.Request(), "move_resume")

    def wait_motion(allow_pause=True):
        """방금 건 비동기 모션이 끝날 때까지 기다린다."""
        time.sleep(MOTION_START_WAIT)
        while check_motion() != 0:          # 0 = 정지 (1 = 계산 중, 2 = 동작 중)
            if allow_pause and progress.check_pause(pause=pause_motion, resume=resume_motion):
                time.sleep(MOTION_START_WAIT)   # 이어 간 모션이 다시 움직이기 시작할 때까지
            time.sleep(POLL_PERIOD)
        if allow_pause:
            # 모션이 끝난 것이 HMI STOP 때문일 수 있다(모니터 노드의 move_stop). 그때는 여기서
            # HmiStop 이 나가 '도착' 으로 처리되지 않는다.
            progress.check_pause()

    def move(motion, target, **kwargs):
        """모션 하나: 단계 사이에서 눌린 일시정지 / STOP 을 먼저 확인하고, 걸고, 끝날 때까지 기다린다."""
        progress.check_pause()
        motion(target, **kwargs)
        wait_motion()

    def grip():
        """그리퍼 닫기 자리. 실제 로봇에서는 여기서 RG2 를 닫고 파지 성공을 확인한다."""
        progress.check_pause()
        time.sleep(0.5)

    def release():
        """그리퍼 열기 자리."""
        progress.check_pause()
        time.sleep(0.5)

    def load_recipe(recipe_id):
        """(레시피 JSON, DB 정보 또는 None). 레시피 JSON 이 없으면 ValueError."""
        recipes, problems = recipe_catalog.scan(RECIPE_DIR)
        for problem in problems:
            log.warn(f"레시피 파일: {problem}")
        if recipe_id not in recipes:
            raise ValueError(f"레시피 {recipe_id!r} 를 {RECIPE_DIR} 에서 찾지 못함")
        try:
            db_info = recipe_db.RecipeDb(RECIPE_DB).load_recipe(recipe_id)
        except recipe_db.RecipeDbError as e:
            log.warn(f"DB 없이 진행 (케이블·판정 기준 빈 칸): {e}")
            db_info = None
        return recipes[recipe_id], db_info

    def inspect_point(index, point, recipe, db_info):
        info = db_info.points.get(point.point_id) if db_info else None
        info = info or recipe_db.PointInfo(point.point_id)
        progress.point(index, point.point_id, criteria=itf.Criteria(
            info.max_displacement_mm, info.pull_force_limit_n, info.repeat_count,
            info.grip_width_mm))
        result = itf.PointResult(
            recipe_id=recipe.recipe_id, recipe_version=recipe.recipe_version,
            product_id=db_info.product_id if db_info else "",
            point_id=point.point_id, point_name=info.point_name or point.point_name,
            cable_id=info.cable_id, cable_type=info.cable_type,
            pull_force_limit_n=info.pull_force_limit_n,
            displacement_limit_mm=info.max_displacement_mm,
            repeat_count=info.repeat_count, grip_width_mm=info.grip_width_mm,
            task=list(point.task), joint=list(point.joint))

        if not point.taught:
            # 좌표가 전부 0 인 자리표시자다. 그대로 보내면 팔을 곧게 편 기계 원점으로 간다.
            log.warn(f"{point.point_id}: 티칭 안 됨 - 건너뜀")
            result.result = itf.ResultCode.MISSING
            result.reason = "미티칭 (레시피 좌표가 전부 0)"
            result.action = "이동하지 않고 다음 Point 진행"
            progress.report_result(result)
            return

        log.info(f"{point.point_id}: 접근 {point.joint}")
        progress.step("접근")
        move(amovej, posj(*point.joint), vel=VELOCITY, acc=ACC)

        progress.step("파지")
        grip()

        progress.step("Pull")
        move(amovel, posx(0.0, 0.0, -PULL_MM, 0.0, 0.0, 0.0),
             vel=PULL_VELOCITY, acc=PULL_ACC, ref=DR_TOOL, mod=DR_MV_MOD_REL)
        code, reason, measured = judge(point, info)

        progress.step("후퇴")
        move(amovel, posx(0.0, 0.0, PULL_MM, 0.0, 0.0, 0.0),
             vel=PULL_VELOCITY, acc=PULL_ACC, ref=DR_TOOL, mod=DR_MV_MOD_REL)
        release()

        result.result = code
        result.reason = reason
        result.action = "결과 기록" if code != itf.ResultCode.MISSING else "다음 Point 진행"
        result.max_force_n = float(measured.get("max_force_n", 0.0))
        result.displacement_mm = float(measured.get("displacement_mm", 0.0))
        progress.report_result(result)
        log.info(f"{point.point_id}: {code} ({reason})")

    def find_point(point_id, last_recipe):
        """이동할 Point 를 찾는다: 마지막으로 검사한 레시피에서, 없으면 레시피 폴더 전체에서."""
        recipes = [last_recipe] if last_recipe else list(recipe_catalog.scan(RECIPE_DIR)[0].values())
        found = [p for r in recipes for p in r.points if p.point_id == point_id]
        return found[0] if len(found) == 1 else None

    def move_to_point(point_id, last_recipe):
        """HMI 의 FAIL / MISSING 포인트 이동: 그 Point 의 접근 자세로 가기만 한다. 움직였으면 True."""
        point = find_point(point_id, last_recipe)
        if point is None:
            log.warn(f"포인트 이동 거부 - {point_id!r} 를 레시피에서 찾지 못함")
            progress.note(f"포인트 이동 거부 - {point_id} 를 레시피에서 찾지 못함")
            return False
        if not point.taught:
            log.warn(f"포인트 이동 거부 - {point_id} 는 티칭 안 됨 (좌표가 전부 0)")
            progress.note(f"포인트 이동 거부 - {point_id} 는 티칭 안 됨")
            return False
        log.info(f"포인트 이동: {point_id} {point.joint}")
        progress.moving(point_id)
        move(amovej, posj(*point.joint), vel=VELOCITY, acc=ACC)
        progress.moved()
        return True

    homej = posj(0.0, 0.0, 90.0, 0.0, 90.0, 0.0)
    moved = False           # 한 번도 안 움직였으면 끝낼 때 홈 복귀도 하지 않는다
    go_home = True
    last_recipe = None      # 포인트 이동은 마지막으로 검사한 레시피의 좌표를 쓴다
    try:
        while True:
            log.info("HMI 에서 Recipe 를 고르고 '검사 시작' 을 누르세요 (끝내려면 Ctrl+C)")
            command, start_args = progress.wait_for_command()
            if command == itf.CommandName.MOVE_TO_POINT:
                moved = move_to_point(str(start_args.get("point_id", "")), last_recipe) or moved
                continue
            recipe_id = str(start_args.get("recipe_id", ""))
            try:
                recipe, db_info = load_recipe(recipe_id)
            except ValueError as e:
                log.error(str(e))
                progress.abort(f"({e})")
                continue
            last_recipe = recipe
            progress.set_points(len(recipe.points))
            log.info(f"검사 시작: {recipe.recipe_id} {recipe.recipe_version}, "
                     f"Point {len(recipe.points)}개")

            moved = True
            progress.step("홈 이동")       # steps 에 없는 이름: 글자만 표시, 퍼센트는 0 그대로
            move(amovej, homej, vel=VELOCITY, acc=ACC)

            for index, point in enumerate(recipe.points):
                inspect_point(index, point, recipe, db_info)

            progress.step("홈 이동")
            move(amovej, homej, vel=VELOCITY, acc=ACC)
            progress.finish()               # 100 %, HMI '검사 완료' + 제품 판정

    except HmiStop:
        # 로봇은 모니터 노드가 move_stop 으로 이미 멈췄다. STOP 뒤에 스스로 움직이면 안 된다.
        log.warn("HMI STOP - 홈 복귀 없이 종료")
        progress.abort("(HMI STOP)")
        go_home = False

    except KeyboardInterrupt:
        log.info("Program Stopped")
        progress.abort("(Ctrl+C)")

    except Exception as e:
        log.info(f"Robot Error: {e}")
        progress.abort(f"({e})")

    finally:
        progress.close()
        if moved and go_home and rclpy.ok():
            # 앞 모션이 아직 진행 중일 수 있으므로 OVERRIDE 로 대체한다.
            amovej(homej, vel=VELOCITY, acc=ACC, ra=DR_MV_RA_OVERRIDE)
            wait_motion(allow_pause=False)
        elif moved and go_home:
            # Ctrl+C 는 ROS 연결부터 닫는다. 그 뒤에는 로봇에 명령을 보낼 수 없다.
            print("Ctrl+C 로 ROS 연결이 닫혀 홈 복귀를 하지 못함 - 걸려 있던 모션 하나는 끝까지 간다")
        node.destroy_node()
        rclpy.try_shutdown()


def make_test_recipe(fkin, posj, log):
    """
    가상 로봇용 레시피 JSON 을 만든다. 로봇은 움직이지 않는다.

    task 좌표는 손으로 적지 않고 드라이버의 정기구학(fkin)으로 joint 에서 계산한다. 그래야 현재
    Tool/TCP 기준으로 joint 와 task 가 같은 자세를 가리킨다.
    """
    if TEST_RECIPE_FILE.exists():
        log.error(f"이미 있음 - 덮어쓰지 않음: {TEST_RECIPE_FILE}")
        return
    points = {}
    for point_id, (name, joint) in TEST_POINTS.items():
        task = fkin(posj(*joint))
        if task is None or isinstance(task, int) or len(task) != 6:
            log.error(f"{point_id}: fkin 실패 ({task!r}) - 파일을 만들지 않음")
            return
        points[point_id] = {
            "point_id": point_id, "point_name": name,
            "task": [round(float(v), 3) for v in task], "joint": joint,
            "coordinate_frame": "BASE"}
    data = {"recipe_id": TEST_RECIPE_ID, "recipe_version": "0.1.0", "points": points}
    TEST_RECIPE_FILE.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    log.info(f"만듦: {TEST_RECIPE_FILE}  (HMI 의 Recipe 목록에 {TEST_RECIPE_ID} 가 5 초 안에 나타난다)")


if __name__ == "__main__":
    main()
