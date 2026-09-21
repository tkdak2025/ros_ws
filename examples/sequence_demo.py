"""
설계 문서(CCCIS Sequence v0.2) 흐름으로 HMI 연동을 시험하는 예제. docs/HMI_연동_가이드.md 를 그대로 따른다.

sodvir(가상 로봇)에서 HMI 가 문서대로 동작하는지 눌러 보기 위한 것이다. 로봇 동작의 알맹이
(Adaptive Grip, Pull Inspection, 판정, Safe Escape ...)는 아직 팀 상세설계가 없으므로 자리만 있고,
모든 Point 는 MISSING('측정 미구현')으로 보고된다. inspect_async.py 와 다른 점은 다음과 같다.

  SYSTEM_READY -> START VALIDATION -> Work Initialize -> Home Return -> [Point Unit 반복]
               -> Work Finish -> Home Return -> SYSTEM_READY

  - 일시정지는 Safe Pause Point 방식: 누르면 HMI 가 '일시정지 요청', 하던 동작을 마친 뒤 '일시정지'.
  - HMI 통신 단절 감시: 검사 중에 HMI 가 HEARTBEAT_LOST_SEC 넘게 조용하면 안전 지점에서 멈추고,
    돌아와도 '이어하기' 를 눌러야 재개한다. COMM_TIMEOUT_SEC 안에 안 돌아오면 작업을 끝낸다.
  - HMI 'Home 이동' 을 이 코드의 home_return() 이 처리한다 (모니터 노드가 직접 움직이지 않는다).
  - STOP / ERROR / COMM_ERROR 는 작업만 끝내고 프로그램은 대기로 돌아간다. 자동 Home Return 은 없다.
    (inspect_async.py 는 STOP 이면 프로그램이 끝난다.)
  - 시작할 수 없으면 사유가 HMI 팝업으로 뜬다: 로봇이 움직이는 중(START 거부), 레시피를 못 읽음 /
    티칭된 Point 가 없음(INIT FAIL). 예제 레시피(좌표가 전부 0)를 골라 시작하면 INIT FAIL 을 볼 수 있다.

실행 (테스트 레시피 VIRTUAL_TEST 는 inspect_async.py --make-test-recipe 로 만들어 둔 것을 쓴다):
  sod && source ~/ros_ws/install/setup.bash && python3 ~/ros_ws/examples/sequence_demo.py

통신 단절 시험: HMI 프로세스를 얼렸다가 풀면 된다(창을 끄면 launch 가 같이 내려갈 수 있다).
  pkill -STOP -f "lib/cable_hmi/hmi "      # HMI 가 멈춘다 -> 3 초 뒤 로봇이 안전 지점에서 일시정지
  pkill -CONT -f "lib/cable_hmi/hmi "      # HMI 가 돌아온다 -> 팝업 확인 후 '이어하기'
"""

from pathlib import Path
import time

from cable_hmi import interface as itf
from cable_hmi import recipe_catalog, recipe_db
from cable_hmi.hmi_progress import HmiCommError, HmiStop, ProgressReporter
import DR_init
from dsr_msgs2.srv import SetCurrentTool
import rclpy

ROBOT_ID = "dsr01"
ROBOT_MODEL = "m0609"
VELOCITY, ACC = 30, 30
PULL_VELOCITY, PULL_ACC = 10, 10
PULL_MM = 10.0            # Pull 자리에서 툴 -Z 방향으로 물러나는 거리

RECIPE_DIR = Path("~/ros_ws/recipe_prototype/recipe/examples").expanduser()
RECIPE_DB = Path("~/ros_ws/results/inspection.db").expanduser()
STEPS = ["Transition", "Entry", "Grip", "Pull", "Judgment"]

HEARTBEAT_LOST_SEC = 3.0  # 문서에서 TBD. HMI 가 이 시간 넘게 조용하면 통신 단절로 본다
COMM_TIMEOUT_SEC = 30.0   # 문서에서 TBD. 이 시간 안에 복구되지 않으면 작업을 끝낸다 (COMM_ERROR)

MOTION_START_WAIT = 0.3   # amove 를 건 뒤 모션이 실제로 시작될 때까지 기다리는 시간 (s)
POLL_PERIOD = 0.05        # check_motion 을 다시 묻는 간격 (s)
DRIVER_WAIT = 10.0        # 시작할 때 두산 드라이버가 보일 때까지 기다리는 시간 (s)

DR_init.__dsr__id = ROBOT_ID
DR_init.__dsr__model = ROBOT_MODEL


class SequenceError(Exception):
    """시퀀스가 더 진행할 수 없다. 메시지는 HMI 에 그대로 보여 줄 사유다."""


def main(args=None):
    rclpy.init(args=args)
    node = rclpy.create_node("cable_sequence_demo", namespace=ROBOT_ID)
    log = node.get_logger()

    DR_init.__dsr__node = node

    try:
        from DSR_ROBOT2 import (
            set_tool,
            set_tcp,
            amovej,
            amovel,
            check_motion,
            DR_TOOL,
            DR_MV_MOD_REL,
        )

        from DR_common2 import posx, posj

    except ImportError as e:
        log.info(f"Error importing DSR_ROBOT2 : {e}")
        return

    # 두산 라이브러리의 호출은 응답을 끝없이 기다린다. 드라이버가 떠 있는지 먼저 확인한다.
    probe = node.create_client(SetCurrentTool, "dsr_controller2/tool/set_current_tool")
    if not probe.wait_for_service(timeout_sec=DRIVER_WAIT):
        log.error("두산 드라이버가 보이지 않음 - sodvir / sodreal 을 먼저 실행하세요")
        node.destroy_node()
        rclpy.shutdown()
        return
    node.destroy_client(probe)

    set_tool("ToolWeight")
    set_tcp("GripperDA_v1")

    progress = ProgressReporter(
        node, points=1, steps=STEPS, control=True,
        watch_heartbeat=True, heartbeat_lost_sec=HEARTBEAT_LOST_SEC,
        comm_timeout_sec=COMM_TIMEOUT_SEC, handles_home=True)

    homej = posj(0.0, 0.0, 90.0, 0.0, 90.0, 0.0)

    # ------------------------------------------------------------ 원자 동작 / Safe Pause Point
    def safe_point():
        """Safe Pause Point: 일시정지가 요청돼 있으면 여기서 멈춘다. STOP 이면 HmiStop 이 올라온다."""
        progress.check_pause()

    def atomic(motion, target, **kwargs):
        """
        원자 동작 하나. 도중에는 일시정지하지 않고, 끝난 뒤(안전 지점)에 일시정지 / STOP 을 본다.

        모션은 비동기로 걸고 check_motion 으로 기다린다. 동기 모션이어도 연동은 되지만, 그러면 도는
        동안 드라이버가 다른 요청에 답하지 못해 HMI 의 힘·위치 값이 멈춘다.
        STOP 은 모니터 노드가 move_stop 으로 로봇을 멈추므로 이 루프가 끝나고, 아래 safe_point() 에서
        HmiStop 이 올라와 '도착' 으로 처리되지 않는다.
        """
        safe_point()
        motion(target, **kwargs)
        time.sleep(MOTION_START_WAIT)
        while check_motion() != 0:          # 0 = 정지 (1 = 계산 중, 2 = 동작 중)
            time.sleep(POLL_PERIOD)
        safe_point()

    def wait_atomic(seconds):
        """모션이 아닌 원자 동작(그리퍼 등)의 자리."""
        safe_point()
        time.sleep(seconds)
        safe_point()

    # ------------------------------------------------------------ Sequence #0: START VALIDATION
    def start_denied(start_args) -> str:
        """시작을 거부할 사유. 받아도 되면 ''. (SYSTEM_READY 확인은 부품이 이미 했다.)"""
        if check_motion() != 0:
            return "다른 Robot Motion 이 실행 중"
        if not str(start_args.get("recipe_id", "")):
            return "Recipe 가 선택되지 않음"
        return ""

    # ------------------------------------------------------------ Sequence #1: Work Initialize
    def work_initialize(recipe_id):
        """(레시피, DB 정보, 검사할 Point 목록). 시작할 수 없으면 SequenceError(사유)."""
        # Robot Operability Check: 팀 상세설계(M0609 상태값 매핑) 후 채울 자리.
        # HMI Communication Check: START 를 방금 받았고 heartbeat 감시가 켜져 있으므로 생략.
        # System Recipe Validation (home_pose, work_Access_safe_pose, Work Area): 형식이 정해지면 채울 자리.
        recipes, problems = recipe_catalog.scan(RECIPE_DIR)
        for problem in problems:
            log.warn(f"레시피 파일: {problem}")
        if recipe_id not in recipes:                                # Inspection Recipe Validation
            raise SequenceError(f"레시피 {recipe_id} 를 읽을 수 없음")
        recipe = recipes[recipe_id]
        try:
            db_info = recipe_db.RecipeDb(RECIPE_DB).load_recipe(recipe_id)
        except recipe_db.RecipeDbError as e:
            log.warn(f"DB 없이 진행 (케이블·판정 기준 빈 칸): {e}")
            db_info = None
        # Enabled Point Check (>= 1). 레시피에 enabled 필드가 아직 없어 '티칭된 Point' 를 대신 쓴다.
        points = [p for p in recipe.points if p.taught]
        skipped = [p.point_id for p in recipe.points if not p.taught]
        if skipped:
            log.warn(f"티칭 안 된 Point 는 검사하지 않음: {', '.join(skipped)}")
        if not points:
            raise SequenceError("검사할 수 있는(티칭된) Point 가 없음")
        return recipe, db_info, points

    # ------------------------------------------------------------ Sequence #2: Home Return
    def home_return():
        """(성공 여부, 실패 사유). 호출한 쪽이 다음 상태를 정한다 (Context-neutral)."""
        # Robot Operability Check                       : 채울 자리
        # Work Area Boundary Check -> INSIDE 면
        #   Grip Relaxation -> Safe Escape(<= 30 mm) -> work_Access_safe_pose : 경계·동작이 정해지면 채울 자리
        progress.step("Safe Home Route")
        atomic(amovej, homej, vel=VELOCITY, acc=ACC)
        # Home Reached Verification                     : 허용오차가 정해지면 채울 자리
        return True, ""

    # ------------------------------------------------------------ Point Unit
    def point_unit(index, point, recipe, db_info):
        info = db_info.points.get(point.point_id) if db_info else None
        info = info or recipe_db.PointInfo(point.point_id)
        progress.sequence("Point Unit")
        progress.point(index, point.point_id, criteria=itf.Criteria(
            info.max_displacement_mm, info.pull_force_limit_n, info.repeat_count, info.grip_width_mm))

        progress.step("Transition")             # Point Transition: ready_pose 로 (지금 레시피의 joint)
        atomic(amovej, posj(*point.joint), vel=VELOCITY, acc=ACC)

        progress.step("Entry")                  # entry_pose: 레시피에 생기면 채울 자리
        wait_atomic(0.3)

        progress.step("Grip")                   # Adaptive Grip: 상세설계 후 채울 자리
        wait_atomic(0.5)

        progress.step("Pull")                   # Pull Inspection: 지금은 허공에서 물러났다 돌아오기만 한다
        atomic(amovel, posx(0.0, 0.0, -PULL_MM, 0.0, 0.0, 0.0),
               vel=PULL_VELOCITY, acc=PULL_ACC, ref=DR_TOOL, mod=DR_MV_MOD_REL)
        atomic(amovel, posx(0.0, 0.0, PULL_MM, 0.0, 0.0, 0.0),
               vel=PULL_VELOCITY, acc=PULL_ACC, ref=DR_TOOL, mod=DR_MV_MOD_REL)

        progress.step("Judgment")               # Inspection Judgment: 측정이 없으므로 '유효 검사 미완료'
        progress.report_result(itf.PointResult(
            recipe_id=recipe.recipe_id, recipe_version=recipe.recipe_version,
            product_id=db_info.product_id if db_info else "",
            point_id=point.point_id, point_name=info.point_name or point.point_name,
            cable_id=info.cable_id, cable_type=info.cable_type,
            pull_force_limit_n=info.pull_force_limit_n, displacement_limit_mm=info.max_displacement_mm,
            repeat_count=info.repeat_count, grip_width_mm=info.grip_width_mm,
            task=list(point.task), joint=list(point.joint),
            result=itf.ResultCode.MISSING, reason="측정 미구현 (시퀀스 시험)",
            action="다음 Point 진행"))
        # Point Unit 은 ready_pose 에서 끝난다. 위 동작이 전부 제자리로 돌아오므로 이미 ready_pose 다.

    # ------------------------------------------------------------ Main Work
    last_recipe = None
    try:
        while True:                                                     # SYSTEM_READY
            log.info("SYSTEM_READY - HMI 의 '검사 시작' / 'Home 이동' 을 기다리는 중 (끝내려면 Ctrl+C)")
            command, cmd_args = progress.wait_for_command(auto_start=False)
            try:
                if command == itf.CommandName.MOVE_HOME:                # HMI 'Home 이동'
                    progress.moving("HOME")
                    progress.sequence("Home Return")
                    ok, reason = home_return()
                    progress.home_done(ok, reason)
                    continue

                if command == itf.CommandName.MOVE_TO_POINT:            # 문서에는 없는 HMI 기능
                    point_id = str(cmd_args.get("point_id", ""))
                    found = [p for p in (last_recipe.points if last_recipe else [])
                             if p.point_id == point_id and p.taught]
                    if not found:
                        progress.note(f"포인트 이동 거부 - {point_id} 를 찾지 못했거나 티칭 안 됨")
                        continue
                    progress.moving(point_id)
                    atomic(amovej, posj(*found[0].joint), vel=VELOCITY, acc=ACC)
                    progress.moved()
                    continue

                reason = start_denied(cmd_args)                         # START VALIDATION
                if reason:
                    log.warn(f"START 거부: {reason}")
                    progress.reject(reason)
                    continue
                progress.start()                                        # ACCEPT

                progress.sequence("Work Initialize")
                try:
                    recipe, db_info, points = work_initialize(str(cmd_args["recipe_id"]))
                except SequenceError as e:
                    log.warn(f"INIT FAIL: {e}")
                    progress.fail(str(e))
                    continue
                last_recipe = recipe
                progress.set_points(len(points))
                log.info(f"검사 시작: {recipe.recipe_id} {recipe.recipe_version}, Point {len(points)}개")

                progress.sequence("Home Return")
                ok, reason = home_return()
                if not ok:
                    raise SequenceError(f"Home Return 실패 - {reason}")
                # work_Access_safe_pose: System Recipe 에 정해지면 여기서 경유한다.

                for index, point in enumerate(points):                  # INSPECTION POINT LOOP
                    point_unit(index, point, recipe, db_info)

                progress.sequence("Work Finish")                        # Completion Processing
                progress.step("")
                progress.sequence("Home Return")
                ok, reason = home_return()
                if not ok:
                    raise SequenceError(f"Home Return 실패 - {reason}")
                progress.finish()                                       # -> SYSTEM_READY (HMI '검사 완료')

            except HmiCommError:
                log.error("HMI 통신 Timeout - 작업 종료 (COMM_ERROR)")
                progress.abort("(COMM_ERROR)", itf.EndReason.COMM_ERROR)
            except HmiStop:
                # 로봇은 모니터 노드가 이미 멈췄다. 자동 Home Return 은 하지 않는다 - 사용자가 Home 을 누른다.
                log.warn("HMI STOP - 작업 종료, 자동 Home Return 없음")
                progress.abort("(HMI STOP)", itf.EndReason.STOP)
            except SequenceError as e:
                log.error(f"ERROR: {e}")
                progress.error(str(e))

    except KeyboardInterrupt:
        log.info("Program Stopped")
        progress.abort("(Ctrl+C)")

    finally:
        progress.close()
        node.destroy_node()
        rclpy.try_shutdown()


if __name__ == "__main__":
    main()
