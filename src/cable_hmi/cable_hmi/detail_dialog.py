"""'검사 결과 상세' 팝업. 선택한 결과 행에 따라 내용이 바뀐다."""

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QDialog, QFrame, QGridLayout, QHBoxLayout, QLabel, QVBoxLayout

from . import interface as itf
from .style import chip_style, MUTED_COLOR, OK_COLOR


def _role(widget, role: str):
    """main_window.ui 스타일시트의 [role="..."] 규칙을 적용받게 한다."""
    widget.setProperty('role', role)
    return widget


def _card(title: str):
    """제목 + 값으로 된 작은 카드를 만들고 (카드, 값 라벨)을 돌려준다."""
    card = _role(QFrame(), 'subPanel')
    lay = QVBoxLayout(card)
    lay.setContentsMargins(10, 6, 10, 6)
    lay.setSpacing(2)
    lay.addWidget(_role(QLabel(title), 'key'))
    value = _role(QLabel('-'), 'value')
    value.setTextInteractionFlags(Qt.TextSelectableByMouse)
    lay.addWidget(value)
    return card, value


class ResultDetailDialog(QDialog):
    """결과 1건의 상세 정보. 모달이 아니므로 떠 있어도 비상정지를 누를 수 있다."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle('검사 결과 상세')
        self.setModal(False)
        self.setMinimumWidth(540)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 12)
        root.setSpacing(10)
        root.addWidget(_role(QLabel('검사 결과 상세'), 'panelTitle'))

        body = QVBoxLayout()
        body.setContentsMargins(14, 0, 14, 0)
        body.setSpacing(10)
        root.addLayout(body)

        top = QHBoxLayout()
        recipe_card, self._recipe = _card('레시피명')
        top.addWidget(recipe_card, 2)
        self._badge = QLabel('-', alignment=Qt.AlignCenter)
        self._badge.setMinimumHeight(48)
        top.addWidget(self._badge, 1)
        body.addLayout(top)

        mid = QHBoxLayout()
        time_card, self._time = _card('검사 시간')
        place_card, self._place = _card('Place')
        cable_card, self._cable = _card('케이블 번호')
        for card in (time_card, place_card, cable_card):
            mid.addWidget(card)
        body.addLayout(mid)

        body.addWidget(_role(QLabel('상세 정보'), 'groupTitle'))
        info = _role(QFrame(), 'subPanel')
        grid = QGridLayout(info)
        grid.setContentsMargins(12, 10, 12, 10)
        grid.setHorizontalSpacing(16)
        grid.setVerticalSpacing(8)
        grid.setColumnStretch(1, 1)
        self._info = {}
        for row, key in enumerate(('결과 코드', '대표 측정값', '판정 사유', '처리')):
            grid.addWidget(_role(QLabel(key), 'key'), row, 0, Qt.AlignTop)
            value = _role(QLabel('-', wordWrap=True), 'value')
            value.setTextInteractionFlags(Qt.TextSelectableByMouse)
            grid.addWidget(value, row, 1)
            self._info[key] = value
        body.addWidget(info)

        bottom = QHBoxLayout()
        force_card, self._force_id = _card('Force 원본 ID')
        bottom.addWidget(force_card, 2)
        self._db = _role(QLabel('-', alignment=Qt.AlignCenter), 'value')
        bottom.addWidget(self._db, 1)
        body.addLayout(bottom)

    def show_result(self, result: itf.PointResult):
        """팝업 내용을 주어진 결과로 채운다."""
        category = itf.ResultCode.category(result.result)
        version = f' {result.recipe_version}' if result.recipe_version else ''
        self._recipe.setText(f'{result.recipe_id}{version}')
        self._badge.setText(category)
        self._badge.setStyleSheet(chip_style(category) + 'font-size: 18px;')
        self._time.setText(result.stamp.replace('T', ' ')[:19])
        self._place.setText(result.point_id)
        cable_type = f' ({result.cable_type})' if result.cable_type else ''
        self._cable.setText(f'{result.cable_id}{cable_type}')

        self._info['결과 코드'].setText(result.result)
        if result.result == itf.ResultCode.MISSING:
            self._info['대표 측정값'].setText('— (유효 검사 미완료)')
        else:
            self._info['대표 측정값'].setText(
                f'변위 {result.displacement_mm:.1f} / {result.displacement_limit_mm:.1f} mm'
                f'  ·  Pull Max {result.max_force_n:.1f} N (목표 {result.pull_force_n:.1f} N)')
        self._info['판정 사유'].setText(result.reason or '-')
        self._info['처리'].setText(result.action or '-')

        self._force_id.setText(result.force_data_id or '-')
        if result.db_saved:
            self._db.setText('● 저장 완료')
            self._db.setStyleSheet(f'color: {OK_COLOR};')
        else:
            self._db.setText('○ 저장 안 됨')
            self._db.setStyleSheet(f'color: {MUTED_COLOR};')
