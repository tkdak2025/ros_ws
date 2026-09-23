"""#04 Adaptive Grip: Entry Pose에서 케이블을 파지하고 Pull을 준비한다.
1. 레시피의 Soft 폭·힘으로 파지한다.
2. Soft Grip 상태로 진입축을 따라 추가진입한다(힘 또는 거리 상한까지).
3. Soft 동작 완료 후 실측 폭을 기준값으로 기록한다.
4. Hard 폭·힘으로 파지하고 동작 완료를 확인해 #05 Pull Inspection으로 넘긴다."""

from cable_pkg.data_models.inspection_models import AdaptiveGripResult


class AdaptiveGripSequence:
    """Soft 추가진입과 Hard Grip을 담당한다. 장비 호출은 hardware에 맡긴다."""

    # 기능: Adaptive Grip에 사용할 장비와 완료점 처리 함수를 받는다.
    #     hardware: 그리퍼 명령, 상대이동, 실측값 조회를 제공하는 장비 객체.
    #     checkpoint: 단계명 문자열을 받아 Pause/STOP 등을 처리하는 함수.
    #                 Hard Grip 완료 후 호출하며, 생략하면 아무 작업도 하지 않는다.
    def __init__(self, hardware, checkpoint=lambda _step: None):
        self.hardware = hardware
        self.checkpoint = checkpoint



    # 기능: Soft Grip 상태로 추가 진입한 뒤 Hard Grip한다.
    #     point: 현재 검사포인트의 OperatingInspectionPoint 레시피 객체.
    #            BASE 진입 방향, 추가진입 거리(mm), Grip 폭(mm)·힘(N)을 사용한다.
    #
    #     ------------------------------------------------------------
    #     반환: 추가진입 결과, Hard Grip 결과, Soft 실측 폭을 담은 AdaptiveGripResult.
    def run(self, point):
        self.hardware.phase = "SEQ_04_ADAPTIVE_GRIP"

        # Soft Grip → 추가진입 → 기준 폭 측정 → Hard Grip 순서로 진행한다.
        self.soft_grip(point)
        entry = self.hardware.relative(
            point.normalized_entry_direction(),  # Entry ABC에서 계산한 Tool +Z의 BASE 방향.
            point.entry_setting["max_distance_mm"],
            entry_guard=True,  # 진입 힘 상한을 감시하고 도달하면 추가진입을 멈춘다.
        )
        # Soft 단계 종료 시점의 실제 폭. Hard 명령을 보내기 전에 확보한다.
        soft = self.hardware.wait_gripper_idle()
        hard = self.hard_grip(point)
        self.checkpoint("HARD_GRIP_DONE")
        return AdaptiveGripResult(
            entry=entry,
            hard_grip=hard,
            soft_width_mm=soft["width_mm"],
        )



    # 기능: Soft 파지 명령을 보낸다. 완료 대기는 추가진입 후 run()에서 수행한다.
    #     point: 검사포인트 레시피. grip_setting의 soft_close_width_mm(mm),
    #            soft_force_n(N)을 사용한다.
    #
    #     ------------------------------------------------------------
    #     반환: 명령한 폭·힘과 현재 실측 상태를 담은 dict.
    def soft_grip(self, point):
        return self.hardware.grip(
            point.grip_setting["soft_close_width_mm"],
            point.grip_setting["soft_force_n"],
        )



    # 기능: Hard 파지 명령을 보내고 그리퍼 동작이 끝난 뒤 반환한다.
    #     point: 검사포인트 레시피. grip_setting의 hard_width_mm(mm),
    #            hard_force_n(N)을 사용한다.
    #
    #     ------------------------------------------------------------
    #     반환: 명령한 폭·힘, 완료 사유와 완료 시 실측 상태를 담은 dict.
    def hard_grip(self, point):
        return self.hardware.grip(
            point.grip_setting["hard_width_mm"],
            point.grip_setting["hard_force_n"],
            wait_for_completion=True,  # Hard Grip 완료 확인 후 Pull 단계로 넘어간다.
        )
