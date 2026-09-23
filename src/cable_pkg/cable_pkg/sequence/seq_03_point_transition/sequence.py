"""#03 Point Transition: 검사포인트의 Entry Pose까지 접근한다.
1. 레시피의 Soft Open 폭으로 그리퍼를 개방한다.
2. Ready Pose로 이동하고 완료를 확인한다.
3. Entry Pose로 이동하고 도달 여부를 기록한다.
4. 하드웨어 오류가 없으면 #04 Adaptive Grip으로 넘어간다."""

class PointTransitionSequence:
    """Ready/Entry 접근을 담당한다. 장비 호출은 hardware에 맡긴다."""

    # 기능: 접근 동작을 수행할 장비와 완료점 처리 함수를 준비한다.
    #     hardware: 그리퍼 명령, 이동, 실측값 조회를 제공하는 장비 객체.
    #     checkpoint: 완료점 이름을 받아 Pause/STOP을 처리하는 함수. 생략하면 처리하지 않는다.
    def __init__(self, hardware, checkpoint=lambda _step: None):
        self.hardware = hardware
        self.checkpoint = checkpoint



    # 기능: 레시피 Open → Ready Pose → Entry Pose 순서로 접근한다.
    #     point: 현재 검사포인트 레시피. Pose(mm/deg), Grip 폭(mm)·힘(N), 이동 조건을 담는다.
    #
    #     ------------------------------------------------------------
    #     반환: 개방, Ready, Entry 결과를 담은 dict.
    def run(self, point):
        self.hardware.phase = "SEQ_03_POINT_TRANSITION"
        opened = self.open_gripper(point)
        ready = self.move_ready(point)
        entry = self.move_entry(point)
        return {"soft_open": opened, "ready": ready, "entry": entry}



    # 기능: 레시피의 Soft Open 폭(mm)·Soft 힘(N)으로 개방하고 폭 도달을 확인한다.
    #     point: 현재 검사포인트 레시피. Pose(mm/deg), Grip 폭(mm)·힘(N), 이동 조건을 담는다.
    #
    #     ------------------------------------------------------------
    #     반환: 개방 명령값과 실측 상태를 담은 dict.
    def open_gripper(self, point):
        return self.hardware.grip(
            point.grip_setting["soft_open_width_mm"],
            point.grip_setting["soft_force_n"],
            opening=True,
        )



    # 기능: Ready Pose의 JOINT 좌표로 이동하고 완료점을 확인한다.
    #     point: 현재 검사포인트 레시피. Pose(mm/deg), Grip 폭(mm)·힘(N), 이동 조건을 담는다.
    #
    #     ------------------------------------------------------------
    #     반환: Ready 이동 결과 dict.
    def move_ready(self, point):
        ready = self.hardware.move_joint(point.ready_pose)
        self.checkpoint("READY_REACHED")
        return ready



    # 기능: Entry Pose로 이동한다. 미도달 여부를 기록하고 하드웨어 오류가 없으면 진행한다.
    #     point: 현재 검사포인트 레시피. Pose(mm/deg), Grip 폭(mm)·힘(N), 이동 조건을 담는다.
    #
    #     ------------------------------------------------------------
    #     반환: Entry 이동 및 도달 여부를 담은 dict.
    def move_entry(self, point):
        entry = self.hardware.move_joint(point.entry_pose, allow_incomplete=True)
        self.checkpoint("ENTRY_REACHED")
        return entry
