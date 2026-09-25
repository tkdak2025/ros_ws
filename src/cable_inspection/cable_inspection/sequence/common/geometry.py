"""시퀀스의 자세 오차와 Tool 방향 계산. 장비·레시피 통신에 의존하지 않는다."""

import math



# 기능: ZYZ Euler 각을 회전행렬로 바꿔 실제 자세 차이를 계산한다.
#     actual_abc: 현재 TCP의 [A, B, C] 자세각(deg).
#     target_abc: 목표 TCP의 [A, B, C] 자세각(deg).
#
#     ------------------------------------------------------------
#     반환: 두 자세 사이의 최소 회전각(deg, 0~180). 동등한 Euler 표현은 0이다.
def orientation_error_deg(actual_abc, target_abc):
    # 기능: Rz(A) × Ry(B) × Rz(C) 회전행렬을 만든다.
    def rotation_matrix(abc):
        a, b, c = map(math.radians, abc)
        ca, sa = math.cos(a), math.sin(a)
        cb, sb = math.cos(b), math.sin(b)
        cc, sc = math.cos(c), math.sin(c)

        return (
            (ca*cb*cc - sa*sc, -ca*cb*sc - sa*cc, ca*sb),
            (sa*cb*cc + ca*sc, -sa*cb*sc + ca*cc, sa*sb),
            (-sb*cc, sb*sc, cb),
        )



    actual = rotation_matrix(actual_abc)
    target = rotation_matrix(target_abc)

    # trace(R_actual.T × R_target) = 1 + 2*cos(자세 차이).
    trace = sum(actual[i][j] * target[i][j] for i in range(3) for j in range(3))
    cosine = max(-1.0, min(1.0, (trace - 1.0) / 2.0))

    return math.degrees(math.acos(cosine))



def reverse_tool_axis(abc, tool_axis):
    """ZYZ: Rz(A) Ry(B) Rz(C). 반환값은 BASE 기준 단위 이탈벡터다."""

    if (not isinstance(tool_axis, (list, tuple)) or len(tool_axis) != 3
            or not all(isinstance(v, (int, float)) and math.isfinite(v) for v in tool_axis)
            or math.hypot(*tool_axis) == 0):
        raise ValueError("유효한 Tool 접근축이 필요합니다.")

    a, b, c = map(math.radians, abc)
    x, y, z = tool_axis
    x, y = math.cos(c)*x - math.sin(c)*y, math.sin(c)*x + math.cos(c)*y
    x, z = math.cos(b)*x + math.sin(b)*z, -math.sin(b)*x + math.cos(b)*z
    x, y = math.cos(a)*x - math.sin(a)*y, math.sin(a)*x + math.cos(a)*y
    length = math.hypot(x, y, z)

    return [0.0 if abs(value / length) < 1e-12 else -value / length for value in (x, y, z)]

