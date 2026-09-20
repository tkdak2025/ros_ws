"""
rokey/move.py (simple_move) 의 비동기 버전.

자세·순서·속도는 원본과 같다. 다른 점은 모션을 amovej/amovel 로 걸고
"끝날 때까지 기다리기" 를 드라이버 안이 아니라 이 코드(wait_motion)에서 한다는 것뿐이다.
그래서 이동 중에도 두산 드라이버가 다른 서비스 요청(get_tool_force, get_current_posx ...)에
답할 수 있고, HMI 의 힘·위치·변위가 이동 중에도 갱신된다.

HMI 진행률: ProgressReporter 로 Cycle / 단계를 알려 주면 모니터 노드가 status 에 합쳐 HMI 에 표시한다.
다른 동작 코드에 옮길 때는 'progress.' 로 시작하는 줄만 가져가면 된다.

실행:  sod && source ~/ros_ws/install/setup.bash && python3 ~/ros_ws/move_async.py
먼저 sodvir(에뮬레이터)에서 모션이 겹치지 않고 하나씩 끝나는지 확인한 뒤 실제 로봇에서 돌릴 것.
"""

import time

from cable_hmi.hmi_progress import ProgressReporter
import DR_init
import rclpy

ROBOT_ID = "dsr01"
ROBOT_MODEL = "m0609"
VELOCITY, ACC = 30, 30
CYCLE = 3

MOTION_START_WAIT = 0.3   # amove 를 건 뒤 모션이 실제로 시작될 때까지 기다리는 시간 (s)
POLL_PERIOD = 0.05        # check_motion 을 다시 묻는 간격 (s)
DR_MV_RA_OVERRIDE = 1     # 진행 중인 모션을 버리고 새 모션으로 대체

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

    def wait_motion():
        """
        방금 건 비동기 모션이 끝날 때까지 기다린다.

        mwait() 를 쓰지 않는 이유: mwait 는 드라이버 안에서 붙잡는 호출이라 동기 모션과
        똑같이 다른 서비스를 막는다. check_motion 은 매번 바로 답이 오는 짧은 호출이다.
        주의: check_motion 은 '정상 도착' 과 'STOP/보호정지로 중간에 멈춤' 을 구분하지 못한다.
        """
        time.sleep(MOTION_START_WAIT)
        while check_motion() != 0:          # 0 = 정지 (1 = 계산 중, 2 = 동작 중)
            time.sleep(POLL_PERIOD)

    # HMI 진행률 보고: 전체 Point 수(여기서는 반복 횟수)와 Point 안의 단계 이름들.
    progress = ProgressReporter(
        node, points=CYCLE, steps=["관절 이동", "직선 이동 1", "직선 이동 2"])

    set_tool("ToolWeight")
    set_tcp("GripperDA_v1")

    homej = posj(0.0, 0.0, 90.0, 0.0, 90.0, 0.0)
    posj1 = posj(0.0, 0.0, 90.0, 0.0, 30.0, 0.0)

    posx1 = posx(350.0, 34.5, 350.0, 45.0, 180.0, 45.0)
    posx2 = posx(350.0, 34.5, 300.0, 45.0, 180.0, 45.0)

    progress.start()
    progress.step("홈 이동")               # steps 에 없는 이름: 글자만 표시, 퍼센트는 0 그대로
    amovej(homej, vel=VELOCITY, acc=ACC)
    wait_motion()

    try:
        for i in range(CYCLE):
            node.get_logger().info(f"Cycle {i+1}")
            progress.point(i, f"Cycle {i+1}")

            progress.step("관절 이동")
            node.get_logger().info(f"Moving to joint position: {posj1}")
            amovej(posj1, vel=VELOCITY, acc=ACC)
            wait_motion()

            progress.step("직선 이동 1")
            node.get_logger().info(f"Moving to task position: {posx1}")
            amovel(posx1, vel=VELOCITY, acc=ACC)
            wait_motion()

            progress.step("직선 이동 2")
            node.get_logger().info(f"Moving to task position: {posx2}")
            amovel(posx2, vel=VELOCITY, acc=ACC)
            wait_motion()

        progress.finish()                   # 100 %

    except KeyboardInterrupt:
        node.get_logger().info("Program Stopped")
        progress.abort("(Ctrl+C)")

    except Exception as e:
        node.get_logger().info(f"Robot Error: {e}")
        progress.abort(f"({e})")

    finally:
        # Ctrl+C 로 빠져나오면 앞 모션이 아직 진행 중일 수 있다. 기본값(DUPLICATE)이면
        # 홈 복귀가 그 위에 겹쳐지므로, OVERRIDE 로 진행 중인 모션을 대체한다.
        amovej(homej, vel=VELOCITY, acc=ACC, ra=DR_MV_RA_OVERRIDE)
        wait_motion()
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
