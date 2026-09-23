"""#05 Pull Inspection: Hard Grip 후 당기며 측정하고 검사 시작 위치로 복귀한다.
1. 진입축 반대 방향으로 Pull하며 힘·거리·시간 조건을 감시한다.
2. 정지 후 측정값을 #06에 전달하고 그리퍼를 개방한다.
3. Entry Pose → Ready Pose 순서로 복귀한다.
4. 복귀 완료점을 확인하고 측정·동작 결과를 반환한다."""

class PullInspectionSequence:
    """Pull 측정과 Entry/Ready 복귀를 담당한다. 장비 호출은 hardware에 맡긴다."""

    # 기능: Pull/복귀 장비와 완료점 처리 함수를 준비한다.
    #     hardware: 그리퍼 명령, 이동, 실측값 조회를 제공하는 장비 객체.
    #     checkpoint: 완료점 이름을 받아 Pause/STOP을 처리하는 함수. 생략하면 처리하지 않는다.
    def __init__(self, hardware, checkpoint=lambda _step: None):
        self.hardware = hardware
        self.checkpoint = checkpoint



    # 기능: Pull 측정 → 결과 전달 → 그리퍼 Open → Entry → Ready 순서로 수행한다.
    #     point: 현재 검사포인트 레시피. Pose(mm/deg), Grip 폭(mm)·힘(N), 이동 조건을 담는다.
    #     on_measured: Pull 정지 직후 측정 dict를 받는 함수. 지정하면 복귀 전에 호출한다.
    #
    #     ------------------------------------------------------------
    #     반환: Pull 측정·개방·복귀 결과를 담은 dict.
    def run(self, point, on_measured=None):
        self.hardware.phase = "SEQ_05_PULL_INSPECTION"
        pull = self.pull(point)
        if on_measured is not None:
            on_measured(pull)  # 정지 직후 판정 요청. 해제/복귀와 병행한다.
        opened = self.open_gripper(point)
        entry = self.return_entry(point)
        ready = self.return_ready(point)
        return {"pull": pull, "soft_open": opened,
                "return_entry": entry, "return_ready": ready}



    # 기능: 진입축 반대 방향으로 Pull하며 레시피 힘·거리·시간 조건과 실측값을 감시한다.
    #     point: 현재 검사포인트 레시피. Pose(mm/deg), Grip 폭(mm)·힘(N), 이동 조건을 담는다.
    #
    #     ------------------------------------------------------------
    #     반환: 최대 힘(N), 실제 변위(mm), 최소 폭(mm), 종료 사유를 담은 dict.
    def pull(self, point):
        # Entry ABC에서 구한 체결 방향의 반대로 당긴다.
        pull_direction = [-value for value in point.normalized_entry_direction()]
        return self.hardware.relative(
            pull_direction,
            point.pull_setting["max_distance_mm"],
            pull_guard=True,
        )



    # 기능: 복귀 전에 Soft Open 폭(mm)·Soft 힘(N)으로 그리퍼를 개방한다.
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



    # 기능: 그리퍼 개방 후 Entry TASK 좌표로 직선 복귀한다.
    #     point: 현재 검사포인트 레시피. Pose(mm/deg), Grip 폭(mm)·힘(N), 이동 조건을 담는다.
    #
    #     ------------------------------------------------------------
    #     반환: Entry 복귀 결과 dict.
    def return_entry(self, point):
        return self.hardware.move_linear(point.entry_pose.task)



    # 기능: Ready JOINT 좌표로 복귀하고 포인트 완료점을 확인한다.
    #     point: 현재 검사포인트 레시피. Pose(mm/deg), Grip 폭(mm)·힘(N), 이동 조건을 담는다.
    #
    #     ------------------------------------------------------------
    #     반환: Ready 복귀 결과 dict.
    def return_ready(self, point):
        ready = self.hardware.move_joint(point.ready_pose)
        self.checkpoint("POINT_READY_RETURNED")
        return ready
