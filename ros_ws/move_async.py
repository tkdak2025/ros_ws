"""
rokey/move.py (simple_move) 의 비동기 버전.

자세·순서·속도는 원본과 같다. 다른 점은 모션을 amovej/amovel 로 걸고
"끝날 때까지 기다리기" 를 드라이버 안이 아니라 이 코드(wait_motion)에서 한다는 것뿐이다.
그래서 이동 중에도 두산 드라이버가 다른 서비스 요청(get_tool_force, get_current_posx ...)에
답할 수 있고, HMI 의 힘·위치·변위가 이동 중에도 갱신된다.

HMI 진행률: ProgressReporter 로 Cycle / 단계를 알려 주면 모니터 노드가 status 에 합쳐 HMI 에 표시한다.
다른 동작 코드에 옮길 때는 'progress.' 로 시작하는 줄만 가져가면 된다.

HMI 버튼 (hmi_monitor.launch.py 로 HMI 를 띄운 상태에서):
  - 실행하면 로봇은 가만히 있고 HMI 가 '대기' 가 된다. Recipe 를 고르고 '검사 시작' 을 누르면 움직인다.
    끝나면 '검사 완료' 가 되고 '검사 시작' 을 다시 누를 수 있다. 프로그램을 끝내려면 Ctrl+C.
  - '일시정지': 이동 중이면 그 자리에서 멈추고(motion/move_pause), '이어하기' 를 누르면 가던 길을
    마저 간다(motion/move_resume). 단계 사이에서 눌렀으면 다음 모션을 걸지 않고 기다린다.
  - 'STOP': 로봇은 모니터 노드가 멈추고(move_stop), 이 프로그램은 홈 복귀 없이 바로 끝난다.
  두산 파이썬 라이브러리에는 move_pause / move_resume 함수가 없어서 서비스를 직접 부른다.

실행:  sod && source ~/ros_ws/install/setup.bash && python3 ~/ros_ws/move_async.py
먼저 sodvir(에뮬레이터)에서 모션이 겹치지 않고 하나씩 끝나는지 확인한 뒤 실제 로봇에서 돌릴 것.
"""

import time

from cable_hmi.hmi_progress import HmiStop, ProgressReporter
import DR_init
from dsr_msgs2.srv import MovePause, MoveResume
import rclpy

ROBOT_ID = "dsr01"
ROBOT_MODEL = "m0609"
VELOCITY, ACC = 30, 30
CYCLE = 3

MOTION_START_WAIT = 0.3   # amove 를 건 뒤 모션이 실제로 시작될 때까지 기다리는 시간 (s)
POLL_PERIOD = 0.05        # check_motion 을 다시 묻는 간격 (s)
DR_MV_RA_OVERRIDE = 1     # 진행 중인 모션을 버리고 새 모션으로 대체
SERVICE_TIMEOUT = 3.0     # move_pause / move_resume 응답을 기다리는 시간 (s)

DR_init.__dsr__id = ROBOT_ID
DR_init.__dsr__model = ROBOT_MODEL


def main(args=None):
    rclpy.init(args=args)
    node = rclpy.create_node("rokey_move_async", namespace=ROBOT_ID)

    DR_init.__dsr__node = node

    try:
        from DSR_ROBOT2 import (
            set_tool,
            set_tcp,
            amovej,
            amovel,
            check_motion,
        )

        from DR_common2 import posx, posj

    except ImportError as e:
        node.get_logger().info(f"Error importing DSR_ROBOT2 : {e}")
        return

    # HMI 진행률 보고: 전체 Point 수(여기서는 반복 횟수)와 Point 안의 단계 이름들.
    # control=True: HMI 의 검사 시작 / 일시정지 / 이어하기 / STOP 도 받는다.
    progress = ProgressReporter(
        node, points=CYCLE, steps=["관절 이동", "직선 이동 1", "직선 이동 2"], control=True)

    # 두산 라이브러리(DSR_ROBOT2)와 같은 방식으로 서비스를 부른다: 같은 노드, 같은 스레드.
    pause_client = node.create_client(MovePause, "dsr_controller2/motion/move_pause")
    resume_client = node.create_client(MoveResume, "dsr_controller2/motion/move_resume")

    def call(client, request, name):
        if not client.wait_for_service(timeout_sec=1.0):
            node.get_logger().error(f"{name}: 서비스 없음")
            return False
        future = client.call_async(request)
        rclpy.spin_until_future_complete(node, future, timeout_sec=SERVICE_TIMEOUT)
        ok = future.done() and future.result() is not None and future.result().success
        node.get_logger().info(f"{name}: {'성공' if ok else '실패'}")
        return ok

    def pause_motion():
        return call(pause_client, MovePause.Request(), "move_pause")

    def resume_motion():
        return call(resume_client, MoveResume.Request(), "move_resume")

    def wait_motion(allow_pause=True):
        """
        방금 건 비동기 모션이 끝날 때까지 기다린다.

        mwait() 를 쓰지 않는 이유: mwait 는 드라이버 안에서 붙잡는 호출이라 동기 모션과
        똑같이 다른 서비스를 막는다. check_motion 은 매번 바로 답이 오는 짧은 호출이다.
        주의: check_motion 은 '정상 도착' 과 'STOP/보호정지로 중간에 멈춤' 을 구분하지 못한다.

        일시정지: check_motion 이 '움직이는 중' 이라고 답한 직후에만 move_pause 를 보낸다. 멈춰 있는
        동안에는 check_motion 을 묻지 않으므로(그 값이 무엇이든) 다음 단계로 넘어가지 않는다.
        """
        time.sleep(MOTION_START_WAIT)
        while check_motion() != 0:          # 0 = 정지 (1 = 계산 중, 2 = 동작 중)
            if allow_pause and progress.check_pause(pause=pause_motion, resume=resume_motion):
                time.sleep(MOTION_START_WAIT)   # 이어 간 모션이 다시 움직이기 시작할 때까지
            time.sleep(POLL_PERIOD)
        if allow_pause:
            # 모션이 끝난 것이 HMI STOP 때문일 수 있다(모니터 노드의 move_stop). 그때는 여기서
            # HmiStop 이 나가 '도착' 으로 처리되지 않는다.
            progress.check_pause()

    def move(motion, target):
        """모션 하나: 단계 사이에서 눌린 일시정지 / STOP 을 먼저 확인하고, 걸고, 끝날 때까지 기다린다."""
        progress.check_pause()
        motion(target, vel=VELOCITY, acc=ACC)
        wait_motion()

    set_tool("ToolWeight")
    set_tcp("GripperDA_v1")

    homej = posj(0.0, 0.0, 90.0, 0.0, 90.0, 0.0)
    posj1 = posj(0.0, 0.0, 90.0, 0.0, 30.0, 0.0)

    posx1 = posx(350.0, 34.5, 350.0, 45.0, 180.0, 45.0)
    posx2 = posx(350.0, 34.5, 300.0, 45.0, 180.0, 45.0)

    moved = False           # 한 번도 안 움직였으면 끝낼 때 홈 복귀도 하지 않는다
    go_home = True
    try:
        while True:
            node.get_logger().info("HMI 의 '검사 시작' 을 기다리는 중 (끝내려면 Ctrl+C)")
            progress.wait_for_start()
            moved = True

            progress.step("홈 이동")       # steps 에 없는 이름: 글자만 표시, 퍼센트는 0 그대로
            move(amovej, homej)

            for i in range(CYCLE):
                node.get_logger().info(f"Cycle {i+1}")
                progress.point(i, f"Cycle {i+1}")

                progress.step("관절 이동")
                node.get_logger().info(f"Moving to joint position: {posj1}")
                move(amovej, posj1)

                progress.step("직선 이동 1")
                node.get_logger().info(f"Moving to task position: {posx1}")
                move(amovel, posx1)

                progress.step("직선 이동 2")
                node.get_logger().info(f"Moving to task position: {posx2}")
                move(amovel, posx2)

            progress.finish()               # 100 %, HMI '검사 완료'

    except HmiStop:
        # 로봇은 모니터 노드가 move_stop 으로 이미 멈췄다. STOP 뒤에 스스로 움직이면 안 된다.
        node.get_logger().warn("HMI STOP - 홈 복귀 없이 종료")
        progress.abort("(HMI STOP)")
        go_home = False

    except KeyboardInterrupt:
        node.get_logger().info("Program Stopped")
        progress.abort("(Ctrl+C)")

    except Exception as e:
        node.get_logger().info(f"Robot Error: {e}")
        progress.abort(f"({e})")

    finally:
        progress.close()
        if moved and go_home and rclpy.ok():
            # 앞 모션이 아직 진행 중일 수 있다. 기본값(DUPLICATE)이면 홈 복귀가 그 위에 겹쳐지므로,
            # OVERRIDE 로 진행 중인 모션을 대체한다.
            amovej(homej, vel=VELOCITY, acc=ACC, ra=DR_MV_RA_OVERRIDE)
            wait_motion(allow_pause=False)
        elif moved and go_home:
            # Ctrl+C 는 ROS 연결부터 닫는다. 그 뒤에는 로봇에 명령을 보낼 수 없다.
            print("Ctrl+C 로 ROS 연결이 닫혀 홈 복귀를 하지 못함 - 걸려 있던 모션 하나는 끝까지 간다")
        node.destroy_node()
        rclpy.try_shutdown()


if __name__ == "__main__":
    main()
