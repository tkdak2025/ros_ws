"""
D1 baseline 측정 노드.

커넥터를 파지한 뒤 당김력을 단계적으로 올리면서 힘(get_tool_force)과
TCP 변위(get_current_posx)를 CSV로 기록한다. 목적은 PASS/FAIL 판정이
아니라 '몇 N에서 빠지는가'를 실측해 검사 임계값을 정하는 것이다.
"""

import csv
from datetime import datetime
import math
import os
import time

import DR_init
import rclpy

ROBOT_ID = 'dsr01'
ROBOT_MODEL = 'm0609'

DR_init.__dsr__id = ROBOT_ID
DR_init.__dsr__model = ROBOT_MODEL

ON, OFF = 1, 0

# 당김 힘 램프 (N). F_MAX 는 안전 상한이자 램프의 끝.
F_START = 2.0
F_MAX = 25.0
F_STEP = 1.0
STEP_DWELL = 0.7        # 각 단계에서 힘이 안정될 때까지 대기 (s)
SAMPLE_PERIOD = 0.05    # 단계 내 샘플링 주기 (s)

# 변위 판정 (mm). D_SEP 를 넘으면 '빠졌다'로 보고 그 때의 힘을 기록.
D_SEP = 5.0
D_ABORT = 25.0          # 이 이상 움직이면 뭔가 잘못된 것 -> 즉시 중단

# 컴플라이언스 강성 [N/mm x3, Nm/rad x3].
# 당김 축 강성을 낮춰 커넥터가 빠질 때 로봇이 따라가도록 한다.
STIFFNESS = [500.0, 500.0, 500.0, 100.0, 100.0, 100.0]

# 당김 방향: [x, y, z, rx, ry, rz] 중 1 인 축에 힘을 가한다.
PULL_DIR = [0, 0, 1, 0, 0, 0]
PULL_SIGN = 1.0         # +1 이면 +축, -1 이면 -축

TRIALS = 5
LABEL = 'normal'        # normal | half | unlatched | none

OUT_DIR = os.path.expanduser('~/ros_ws/results')

CSV_HEADER = [
    'timestamp', 'label', 'trial', 'fd_cmd',
    'fx', 'fy', 'fz', 'tx', 'ty', 'tz',
    'x', 'y', 'z', 'rx', 'ry', 'rz',
    'disp_mm', 'event',
]


def _dist(a, b):
    """두 posx 의 위치 성분(mm) 사이 거리."""
    return math.sqrt(sum((a[i] - b[i]) ** 2 for i in range(3)))


def main(args=None):
    """파지 -> 힘 램프 -> 로그 -> 복귀를 TRIALS 회 반복한다."""
    rclpy.init(args=args)
    node = rclpy.create_node('pull_test_logger', namespace=ROBOT_ID)

    DR_init.__dsr__node = node

    try:
        from DSR_ROBOT2 import (
            DR_BASE,
            DR_FC_MOD_ABS,
            DR_MV_MOD_ABS,
            get_current_posx,
            get_tool_force,
            movel,
            release_compliance_ctrl,
            release_force,
            set_desired_force,
            set_digital_output,
            set_tcp,
            set_tool,
            task_compliance_ctrl,
        )
    except ImportError as e:
        node.get_logger().error(f'Error importing DSR_ROBOT2 : {e}')
        rclpy.shutdown()
        return

    set_tool('Tool Weight_1')
    set_tcp('GripperDA_v1')

    log = node.get_logger()

    def grip():
        set_digital_output(1, OFF)
        set_digital_output(2, OFF)
        set_digital_output(1, ON)
        set_digital_output(2, OFF)
        time.sleep(1.0)

    def release():
        set_digital_output(1, OFF)
        set_digital_output(2, OFF)
        set_digital_output(1, OFF)
        set_digital_output(2, ON)
        time.sleep(1.0)

    def sample(writer, trial, fd_cmd, origin, event=''):
        """현재 힘/자세를 한 줄 기록하고 변위(mm)를 돌려준다."""
        f = get_tool_force(DR_BASE)
        p, _sol = get_current_posx(DR_BASE)
        if not isinstance(f, list) or p is None:
            log.warn('force/pose 읽기 실패 - 샘플 건너뜀')
            return None
        disp = _dist(p, origin)
        writer.writerow([
            datetime.now().isoformat(timespec='milliseconds'),
            LABEL, trial, round(fd_cmd, 2),
            *[round(v, 3) for v in f],
            *[round(v, 3) for v in p],
            round(disp, 3), event,
        ])
        return disp

    os.makedirs(OUT_DIR, exist_ok=True)
    stamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    csv_path = os.path.join(OUT_DIR, f'pull_baseline_{LABEL}_{stamp}.csv')

    # 시작 자세 = 현재 자세. 이 노드는 큰 이동을 스스로 만들지 않는다.
    # 커넥터를 잡을 수 있는 위치까지는 미리 티칭으로 옮겨 둘 것.
    origin, _sol = get_current_posx(DR_BASE)
    if origin is None:
        log.error('시작 자세를 읽지 못했습니다. 로봇 연결을 확인하세요.')
        node.destroy_node()
        rclpy.shutdown()
        return
    log.info(f'시작 자세: {[round(v, 1) for v in origin]}')
    log.info(f'기록 파일: {csv_path}')

    separation_forces = []

    with open(csv_path, 'w', newline='') as fp:
        writer = csv.writer(fp)
        writer.writerow(CSV_HEADER)

        for trial in range(1, TRIALS + 1):
            log.info(f'=== trial {trial}/{TRIALS} ({LABEL}) ===')
            sep_force = None

            grip()
            sample(writer, trial, 0.0, origin, 'grip')

            task_compliance_ctrl(STIFFNESS, time=0.5)
            time.sleep(0.5)

            try:
                fd_cmd = F_START
                while fd_cmd <= F_MAX:
                    fd = [0.0] * 6
                    for i, active in enumerate(PULL_DIR):
                        if active:
                            fd[i] = PULL_SIGN * fd_cmd

                    set_desired_force(fd, PULL_DIR, time=0.3,
                                      mod=DR_FC_MOD_ABS)

                    elapsed = 0.0
                    while elapsed < STEP_DWELL:
                        disp = sample(writer, trial, fd_cmd, origin)
                        time.sleep(SAMPLE_PERIOD)
                        elapsed += SAMPLE_PERIOD

                        if disp is None:
                            continue
                        if disp >= D_ABORT:
                            sample(writer, trial, fd_cmd, origin, 'abort_disp')
                            log.error(f'변위 {disp:.1f}mm > {D_ABORT}mm - 중단')
                            raise RuntimeError('displacement abort')
                        if sep_force is None and disp >= D_SEP:
                            sep_force = fd_cmd
                            sample(writer, trial, fd_cmd, origin, 'separated')
                            log.info(f'분리 감지: {fd_cmd:.1f}N '
                                     f'(변위 {disp:.1f}mm)')
                            break

                    if sep_force is not None:
                        break
                    fd_cmd += F_STEP

                if sep_force is None:
                    sample(writer, trial, F_MAX, origin, 'held')
                    log.info(f'{F_MAX}N 까지 버팀 - 분리 없음')

            except RuntimeError:
                pass
            except KeyboardInterrupt:
                log.warn('사용자 중단')
                break
            finally:
                # 힘 제어는 어떤 경로로 빠져나가든 반드시 해제한다.
                release_force(time=0.3)
                time.sleep(0.3)
                release_compliance_ctrl()
                time.sleep(0.3)

            separation_forces.append(sep_force)
            fp.flush()

            # 원위치 복귀 후 재삽입은 수동. 다음 시행 전에 대기.
            movel(origin, vel=20, acc=20, mod=DR_MV_MOD_ABS, ref=DR_BASE)
            release()
            if trial < TRIALS:
                input(f'[{trial}/{TRIALS}] 커넥터 재삽입 후 Enter: ')

    measured = [f for f in separation_forces if f is not None]
    if measured:
        log.info(f'분리력 n={len(measured)} '
                 f'min={min(measured):.1f} max={max(measured):.1f} '
                 f'mean={sum(measured) / len(measured):.1f} N')
    else:
        log.info(f'분리 없음 - 전 시행 {F_MAX}N 유지')
    log.info(f'저장 완료: {csv_path}')

    node.destroy_node()
    rclpy.shutdown()


if __name__ == '__main__':
    main()
