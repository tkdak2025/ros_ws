"""HMI 없는 운전 메뉴: Main Sequence에 숫자 명령을 보낸다.
1. 상태를 수신하고 터미널 전용 Heartbeat를 주기적으로 보낸다.
2. START/Pause/Resume/STOP/Home/레시피 선택을 요청한다.
3. 종료할 때 STOP을 요청한다. 로봇 서비스는 직접 호출하지 않는다."""

import json
import select
import sys
import time
import rclpy
from rclpy.node import Node
from rclpy.qos import QoSProfile, DurabilityPolicy, ReliabilityPolicy
from rclpy.signals import SignalHandlerOptions
from std_msgs.msg import Empty, String



class SequenceConsole(Node):
    # 기능: 터미널 전용 명령·Heartbeat와 공통 상태·로그를 연결한다.
    def __init__(self):
        super().__init__("sequence_console")
        self.status = {}
        self.status_received_at = 0.0
        self.recipe_choices = None
        self.commands = self.create_publisher(String, "cable_inspection/terminal_command", 10)
        self.heartbeat = self.create_publisher(Empty, "cable_inspection/terminal_heartbeat", 10)
        self.create_subscription(
            String, "cable_inspection/work_status", self.receive_status,
            QoSProfile(depth=1, reliability=ReliabilityPolicy.RELIABLE,
                       durability=DurabilityPolicy.TRANSIENT_LOCAL))
        self.create_subscription(String, "cable_inspection/log", self.receive_log, 50)
        self.create_timer(0.5, lambda: self.heartbeat.publish(Empty()))

        # 대기 중 work_status는 주기 발행하지 않는다. 콘솔은 SYNC로 생존을 확인한다.
        self.create_timer(1.0, lambda: self.commands.publish(
            String(data=json.dumps({"name": "SYNC", "args": {}}))))



    # 기능: 상태를 보관하고 상태/Point가 바뀌었을 때만 표시한다.
    #     message: Main Sequence가 발행한 상태 JSON.
    def receive_status(self, message):
        status = json.loads(message.data)
        keys = ("control_mode", "run_state", "current_point", "selected_recipe_id")
        changed = any(status.get(key) != self.status.get(key) for key in keys)
        self.status = status
        self.status_received_at = time.monotonic()

        if changed:
            print(f"\n[{status.get('control_mode')}] {status.get('run_state')} | "
                  f"Recipe={status.get('selected_recipe_id')} | Point={status.get('current_point')}", flush=True)



    # 기능: Main/판정 노드의 요청 처리 결과와 오류를 출력한다.
    #     message: level/text를 담은 로그 JSON.
    def receive_log(self, message):
        log = json.loads(message.data)
        print(f"\n[{log.get('level')}] {log.get('text')}", flush=True)



    # 기능: 활성 terminal 모드에 명령을 전송한다. 실제 허용 상태는 Main에서 판단한다.
    #     name: START/PAUSE/RESUME/STOP/HOME_RETURN/SELECT_RECIPE/SYNC.
    #     args: 레시피 ID 등 명령 인자. 생략하면 빈 객체.
    def send(self, name, args=None):
        if name != "STOP" and (self.status.get("control_mode") != "terminal"
                or time.monotonic() - self.status_received_at > 2.0):
            print("terminal 모드 Main의 최신 상태를 기다리세요.", flush=True)
            return

        self.commands.publish(String(data=json.dumps({"name": name, "args": args or {}})))
        print(f"요청: {name}", flush=True)



    # 기능: 숫자 메뉴와 등록된 레시피 선택 입력을 처리한다.
    #     text: 터미널에서 읽은 한 줄. Q는 종료 요청.
    #
    #     ------------------------------------------------------------
    #     반환: 계속 운전하면 True, 종료 선택이면 False.
    def handle_input(self, text):
        choice = text.strip().upper()

        if choice == "Q":
            return False

        if self.recipe_choices is not None:
            if choice.isdigit() and 1 <= int(choice) <= len(self.recipe_choices):
                self.send("SELECT_RECIPE", {"recipe_id": self.recipe_choices[int(choice) - 1]})

            elif choice != "0":
                print("레시피 선택 번호가 잘못되었습니다.", flush=True)

            self.recipe_choices = None
            self.show_menu()
            return True

        commands = {"1": "START", "2": "PAUSE", "3": "RESUME", "4": "STOP", "5": "HOME_RETURN"}

        if choice in commands:
            self.send(commands[choice])

        elif choice == "6":
            recipes = self.status.get("available_recipes", [])

            if recipes:
                self.recipe_choices = list(recipes)

                for index, recipe in enumerate(recipes, 1):
                    print(f"{index}. {recipe}", flush=True)

                print("레시피 번호 입력 (0: 취소):", flush=True)

            else:
                print("등록된 레시피 상태를 아직 받지 못했습니다.", flush=True)

        elif choice == "7":
            print(json.dumps(self.status, ensure_ascii=False, indent=2), flush=True)
            self.send("SYNC")

        else:
            self.show_menu()

        return True



    # 기능: 실물 모션을 시작하는 메뉴와 제어 메뉴를 안내한다.
    @staticmethod
    def show_menu():
        print("\n1. 전체 Job 시작  2. Pause  3. Resume  4. STOP\n"
              "5. Home 복귀  6. 레시피 선택  7. 상태 조회  Q. STOP 요청 후 종료\n"
              "작업 중에도 번호 입력 후 Enter: 2=Pause 요청, 3=PAUSED에서 Resume, 4=STOP, 7=상태\n"
              "1/5는 실제 로봇이 움직일 수 있습니다. 번호 입력 후 Enter:", flush=True)



# 기능: 입력 대기 중에도 상태 수신과 Heartbeat를 처리하고 종료 시 STOP을 보낸다.
#     args: ROS 인자. None이면 명령행에서 읽는다.
def main(args=None):
    rclpy.init(args=args, signal_handler_options=SignalHandlerOptions.NO)
    node = SequenceConsole()
    node.show_menu()

    try:
        while rclpy.ok():
            rclpy.spin_once(node, timeout_sec=0.1)

            if select.select([sys.stdin], [], [], 0)[0]:
                line = sys.stdin.readline()

                if not line or not node.handle_input(line):
                    break

    except KeyboardInterrupt:
        pass

    finally:
        node.send("STOP")

        # DDS 전송 기회를 주고 종료한다. 접수/정지 완료는 Main 쪽 상태로 확인한다.
        rclpy.spin_once(node, timeout_sec=0.2)
        node.destroy_node()
        rclpy.try_shutdown()



if __name__ == "__main__":
    main()
