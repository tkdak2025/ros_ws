"""실물 M0609의 BASE Y 방향 MoveL 동작을 확인하는 최소 프로그램.

현재 TCP 위치를 읽고 BASE Y+ 방향으로 10 mm 이동한다. 이동 후 사용자가
RETURN을 입력하면 최초 위치로 복귀한다. TCP/Tool/그리퍼 설정은 변경하지 않는다.
"""

import time

import rclpy
from dsr_msgs2.srv import GetCurrentPosx, MoveLine, MoveStop
from rclpy.executors import ExternalShutdownException


class SimpleMoveLCheck:
    """현재 위치 기준으로 Y+ 지정 거리 MoveL과 원위치 복귀를 수행한다."""

    SERVICE_PREFIX = "/dsr01/dsr_controller2"
    MOVE_DISTANCE_MM = 100.0       # BASE Y+ 방향 이동 거리 [mm].
    LINEAR_VELOCITY_MM_S = 30.0   # MoveL 병진 속도 [mm/s].
    LINEAR_ACCELERATION_MM_S2 = 60.0  # MoveL 병진 가속도 [mm/s²].
    SERVICE_TIMEOUT_S = 3.0       # 위치 조회 등 일반 서비스 응답 제한시간 [s].
    MOVE_TIMEOUT_S = 30.0         # 동기 MoveL 완료 응답 제한시간 [s].

    def __init__(self):
        """ROS 노드와 현재 위치·MoveL·정지 서비스 클라이언트를 생성한다."""
        self.node = rclpy.create_node("simple_movel_check")
        prefix = self.SERVICE_PREFIX
        self.position_client = self.node.create_client(
            GetCurrentPosx, prefix + "/aux_control/get_current_posx"
        )
        self.move_client = self.node.create_client(
            MoveLine, prefix + "/motion/move_line"
        )
        self.stop_client = self.node.create_client(
            MoveStop, prefix + "/motion/move_stop"
        )
        self.motion_requested = False

    def call(self, client, request, timeout=None):
        """서비스를 호출하고 시간 초과 또는 실패 응답을 예외로 처리한다."""
        future = client.call_async(request)
        rclpy.spin_until_future_complete(
            self.node,
            future,
            timeout_sec=self.SERVICE_TIMEOUT_S if timeout is None else timeout,
        )
        if not future.done():
            future.cancel()
            raise TimeoutError(f"서비스 응답 시간 초과: {client.srv_name}")
        response = future.result()
        if response is None or not response.success:
            raise RuntimeError(f"서비스 호출 실패: {client.srv_name}")
        return response

    def current_task_position(self):
        """BASE 기준 현재 TCP [X, Y, Z, A, B, C]를 반환한다."""
        request = GetCurrentPosx.Request()
        request.ref = 0  # DR_BASE
        response = self.call(self.position_client, request)
        if not response.task_pos_info:
            raise RuntimeError("현재 TCP 응답이 비어 있습니다.")
        values = list(response.task_pos_info[0].data)
        if len(values) < 6:
            raise RuntimeError("현재 TCP 응답 길이가 잘못되었습니다.")
        return values[:6]

    def movel(self, target):
        """BASE 절대좌표 target으로 동기 MoveL을 실행하고 소요시간을 반환한다."""
        request = MoveLine.Request()
        request.pos = [float(value) for value in target]
        request.vel = [self.LINEAR_VELOCITY_MM_S, -10000.0]
        request.acc = [self.LINEAR_ACCELERATION_MM_S2, -10000.0]
        request.time = 0.0
        request.radius = 0.0
        request.ref = 0        # DR_BASE
        request.mode = 0       # DR_MV_MOD_ABS
        request.blend_type = 0
        request.sync_type = 0  # 동기 이동: 도착 후 서비스 응답
        self.motion_requested = True
        # 동기 MoveL 서비스는 로봇이 목표 위치에 도착해야 응답하므로
        # 일반 상태 조회와 분리된 긴 제한시간을 사용한다.
        started = time.monotonic()
        self.call(self.move_client, request, timeout=self.MOVE_TIMEOUT_S)
        return time.monotonic() - started

    def stop(self):
        """MoveL 오류나 사용자 중단 시 Stop Category 2 정지를 요청한다."""
        request = MoveStop.Request()
        request.stop_mode = 1  # DR_QSTOP
        try:
            self.call(self.stop_client, request, timeout=1.0)
        except Exception as error:
            print(f"정지 서비스 호출 실패: {error}")

    def run(self):
        """서비스 확인 → Y+ 지정 거리 이동 → 현재 위치 확인 → 원위치 복귀."""
        for client in (
            self.position_client,
            self.move_client,
            self.stop_client,
        ):
            if not client.wait_for_service(timeout_sec=3.0):
                raise RuntimeError(f"서비스를 찾지 못했습니다: {client.srv_name}")

        start = self.current_task_position()
        target = start[:]
        target[1] += self.MOVE_DISTANCE_MM

        print("시작 TCP [X,Y,Z,A,B,C]:", [round(value, 3) for value in start])
        print("목표 TCP [X,Y,Z,A,B,C]:", [round(value, 3) for value in target])
        confirmation = input(
            f"BASE Y+ {self.MOVE_DISTANCE_MM:.0f} mm 이동 경로를 확인했으면 MOVE 입력: "
        ).strip()
        if confirmation != "MOVE":
            print("이동을 취소했습니다.")
            return

        try:
            print(f"Y+ {self.MOVE_DISTANCE_MM:.0f} mm MoveL 시작")
            move_elapsed = self.movel(target)
            time.sleep(0.5)
            reached = self.current_task_position()
            move_distance = abs(reached[1] - start[1])
            print("이동 후 TCP:", [round(value, 3) for value in reached])
            print(f"실제 Y 변화량: {reached[1] - start[1]:+.3f} mm")
            print(f"MOVE 완료시간: {move_elapsed:.3f} s, "
                  f"평균 Y 속도: {move_distance / move_elapsed:.3f} mm/s")

            confirmation = input("원래 위치로 복귀하려면 RETURN 입력: ").strip()
            if confirmation != "RETURN":
                print("복귀하지 않고 프로그램을 종료합니다.")
                return

            print("원위치 MoveL 시작")
            return_elapsed = self.movel(start)
            time.sleep(0.5)
            returned = self.current_task_position()
            return_distance = abs(returned[1] - reached[1])
            print("복귀 후 TCP:", [round(value, 3) for value in returned])
            print(f"시작점 대비 Y 오차: {returned[1] - start[1]:+.3f} mm")
            print(f"RETURN 완료시간: {return_elapsed:.3f} s, "
                  f"평균 Y 속도: {return_distance / return_elapsed:.3f} mm/s")
        except (KeyboardInterrupt, ExternalShutdownException):
            self.stop()
            raise
        except Exception:
            if self.motion_requested:
                self.stop()
            raise


def main():
    """ROS 2 초기화, 이동 확인 실행, 노드 종료를 관리한다."""
    rclpy.init(args=[])
    checker = None
    try:
        checker = SimpleMoveLCheck()
        checker.run()
    except (KeyboardInterrupt, ExternalShutdownException):
        print("사용자가 프로그램을 중단했습니다.")
    except Exception as error:
        print(f"프로그램 실행 중단: {error}")
        return 1
    finally:
        if checker is not None:
            checker.node.destroy_node()
        rclpy.try_shutdown()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
