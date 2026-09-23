"""
기준선이 있는 막대 게이지.

값을 막대로 채우고, 기준(목표 힘, 허용 변위, 파지 실패 폭 ...)을 막대 위의 세로선으로 그린다.
작업자가 숫자를 비교하지 않고 '막대가 선을 넘었는가' 만 보면 되게 하려는 것이다.
막대 아래에는 기준선 이름과 눈금 끝 값을 작게 쓴다.

main_window.ui 에는 같은 자리에 QProgressBar 가 자리표시로 있고, main_window 가 실행할 때
이 위젯으로 바꿔 끼운다(Designer 에서 배치는 그대로 옮길 수 있다).
"""

from typing import List, Optional, Tuple

from PyQt5.QtCore import QRectF, Qt
from PyQt5.QtGui import QColor, QFont, QPainter
from PyQt5.QtWidgets import QSizePolicy, QWidget

from .style import MUTED_COLOR

TRACK_COLOR = '#E8EDF2'
MARK_COLOR = '#2B3440'
BAR_HEIGHT = 8
TEXT_GAP = 2
# 게이지 아래 빈칸. 다음 줄(다른 값의 이름)과 떨어뜨려 이 게이지가 위 줄의 것임을 보이게 한다.
BOTTOM_PAD = 12


class LimitGauge(QWidget):
    """set_state() 로 값·눈금·기준선을 한 번에 바꾼다. 값이 None 이면 빈 막대."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._value: Optional[float] = None
        self._scale = 0.0
        self._scale_text = ''
        self._marks: List[Tuple[float, str]] = []
        self._color = MUTED_COLOR
        font = QFont(self.font())
        font.setPixelSize(11)
        self._label_font = font
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setFixedHeight(BAR_HEIGHT + TEXT_GAP + 14 + BOTTOM_PAD)

    def set_state(self, value: Optional[float], scale: float, color: str,
                  marks: List[Tuple[float, str]] = (), scale_text: str = ''):
        """
        value: 막대 값 (None = 모름, 빈 막대). scale: 막대 오른쪽 끝의 값 (0 이하면 빈 막대).

        marks: [(기준값, 이름)] - 세로선과 그 아래 이름. scale_text: 오른쪽 끝 아래 글자.
        """
        state = (value, scale, color, list(marks), scale_text)
        if state == (self._value, self._scale, self._color, self._marks, self._scale_text):
            return                      # 10 Hz 로 불리므로 바뀐 것이 없으면 다시 그리지 않는다
        self._value, self._scale, self._color, self._marks, self._scale_text = state
        self.update()

    def _x(self, value: float, width: float) -> float:
        return min(1.0, max(0.0, value / self._scale)) * width if self._scale > 0 else 0.0

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        width = float(self.width())
        track = QRectF(0, 1, width, BAR_HEIGHT)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(TRACK_COLOR))
        p.drawRoundedRect(track, 3, 3)
        if self._value is not None and self._scale > 0:
            p.setBrush(QColor(self._color))
            p.drawRoundedRect(QRectF(0, 1, self._x(self._value, width), BAR_HEIGHT), 3, 3)

        p.setFont(self._label_font)
        metrics = p.fontMetrics()
        text_top = BAR_HEIGHT + TEXT_GAP + 1
        text_h = self.height() - text_top - BOTTOM_PAD
        taken = []                      # 이미 쓴 글자 범위 - 겹치면 뒤의 것을 쓰지 않는다

        def put(text, lefts, color):
            """후보 자리(lefts) 중 이미 쓴 글자와 겹치지 않는 첫 자리에 쓴다. 다 겹치면 쓰지 않는다."""
            label_w = metrics.horizontalAdvance(text)
            for left in lefts:
                left = min(width - label_w, max(0.0, left))
                right = left + label_w
                if not any(left < b + 4 and a < right + 4 for a, b in taken):
                    taken.append((left, right))
                    p.setPen(QColor(color))
                    p.drawText(QRectF(left, text_top, label_w + 1, text_h),
                               Qt.AlignLeft | Qt.AlignTop, text)
                    return

        for value, text in self._marks:
            if self._scale <= 0 or value <= 0:
                continue
            x = min(width - 1, max(1, self._x(value, width)))
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(MARK_COLOR))
            p.drawRect(QRectF(x - 1, 0, 2, BAR_HEIGHT + 2))
            label_w = metrics.horizontalAdvance(text)
            # 선 가운데 → 선 오른쪽 → 선 왼쪽 순서로 빈 자리를 찾는다.
            put(text, [x - label_w / 2, x + 3, x - label_w - 3], MARK_COLOR)
        if self._scale_text:            # 끝 눈금은 덜 중요하다 - 기준선 이름과 겹치면 쓰지 않는다
            put(self._scale_text, [width], MUTED_COLOR)
        p.end()
