"""
상세 팝업 두 가지. 선택한 행에 따라 내용이 바뀐다.

  ResultDetailDialog   '현재 검사 결과' 표의 결과 1건       배치: result_detail_dialog.ui
  LookupDetailDialog   '통합 조회' 표의 레시피 포인트 1개   배치: lookup_detail_dialog.ui

배치·글자·색은 .ui 에 있다 (Qt Designer 로 편집). 이 파일이 의존하는 것은 값을 써 넣는 라벨의
objectName 뿐이다(각 클래스의 _load 참고). Designer 에서 그 라벨을 지우거나 이름을 바꾸면 그
항목만 창에서 빠지고 창은 그대로 뜨며, 빠진 이름은 터미널에 경고로 나온다. 제목 라벨, 카드,
레이아웃은 자유롭게 바꿔도 된다.

두 창은 같은 구성이다: 레시피 + 배지 / 이름 · Point · 케이블 / 검사 결과 / 판정 기준 / 위치 / 아래 줄.
같은 뜻의 라벨은 두 .ui 에서 objectName 도 같다.

코드에 남아 있는 것은 상황에 따라 바뀌는 것뿐이다: 값, 배지 색(PASS / FAIL / MISSING),
'저장 완료' 색.
"""

from pathlib import Path
import sys

from PyQt5 import uic
from PyQt5.QtWidgets import QDialog, QLabel, QWidget

from . import interface as itf
from .style import chip_style, MUTED_COLOR, OK_COLOR, RESULT_COLORS

UI_DIR = Path(__file__).parent


class _UiDialog(QDialog):
    """.ui 를 읽어 만드는 비모달 대화상자."""

    UI_FILE = ''

    def __init__(self, parent=None):
        super().__init__(parent)
        uic.loadUi(str(UI_DIR / self.UI_FILE), self)
        # 모달이면 떠 있는 동안 STOP 을 누를 수 없다. Designer 에서 modal 을 켜도 여기서 끈다.
        self.setModal(False)
        self._attic = QWidget(self)
        self._attic.hide()
        self.missing_widgets = []
        self._load()
        if self.missing_widgets:
            print(f'[cable_hmi] {self.UI_FILE} 에 없는 위젯: {", ".join(self.missing_widgets)}',
                  file=sys.stderr)

    def _load(self):
        raise NotImplementedError

    def _label(self, name: str) -> QLabel:
        """라벨을 objectName 으로 찾는다. Designer 에서 지워졌으면 숨겨진 대역을 돌려준다."""
        found = self.findChild(QLabel, name)
        if found is not None:
            return found
        self.missing_widgets.append(name)
        return QLabel(self._attic)


def _pose_text(values, names, units) -> str:
    """좌표 6개를 'X 1.0  Y 2.0 ...' 로. units = (앞 3개 단위, 뒤 3개 단위)."""
    if len(values) != 6:
        return '—'
    parts = [f'{name} {value:.2f}' for name, value in zip(names, values)]
    if units[0] == units[1]:
        return f'{"   ".join(parts)}  {units[0]}'
    return f'{"   ".join(parts[:3])}  {units[0]}\n{"   ".join(parts[3:])}  {units[1]}'


RESULT_LABELS = {'결과 코드': 'resultCodeValue', '검사 시간': 'timeValue',
                 '대표 측정값': 'measuredValue', '판정 사유': 'reasonValue', '처리': 'actionValue'}
CRITERIA_LABELS = {'허용 변위': 'limitValue', 'Pull 정지 상한': 'pullForceValue',
                   '반복 횟수': 'repeatValue', '파지 폭': 'gripWidthValue'}


def _fill_result(labels, result):
    """'검사 결과' 패널을 채운다. result 가 None 이면 검사 이력이 없는 것이다."""
    if result is None:
        for label in labels.values():
            label.setText('—')
        labels['결과 코드'].setText('— (저장된 검사 결과 없음)')
        labels['결과 코드'].setStyleSheet('')
        return
    category = itf.ResultCode.category(result.result)
    labels['결과 코드'].setText(result.result)
    labels['결과 코드'].setStyleSheet(f'color: {RESULT_COLORS[category][0]};')
    labels['검사 시간'].setText(result.stamp.replace('T', ' ')[:19] or '-')
    if result.result == itf.ResultCode.MISSING:
        labels['대표 측정값'].setText('— (유효 검사 미완료)')
    else:
        labels['대표 측정값'].setText(
            f'변위 {result.displacement_mm:.1f} mm  ·  Pull Max {result.max_force_n:.1f} N')
    labels['판정 사유'].setText(result.reason or '-')
    labels['처리'].setText(result.action or '-')


def _fill_pose(labels, task, joint, missing_text='—'):
    """'위치' 패널을 채운다. 좌표가 없으면 missing_text, 전부 0 이면 '미티칭' 을 덧붙인다."""
    if len(task) != 6 or len(joint) != 6:
        for label in labels.values():
            label.setText(missing_text)
        return
    untaught = not (any(v != 0.0 for v in task) and any(v != 0.0 for v in joint))
    labels['Task'].setText(
        _pose_text(task, ('X', 'Y', 'Z', 'A', 'B', 'C'), ('mm', 'deg'))
        + ('\n(미티칭 - 좌표가 전부 0)' if untaught else ''))
    labels['Joint'].setText(
        _pose_text(joint, ('J1', 'J2', 'J3', 'J4', 'J5', 'J6'), ('deg', 'deg')))


def _fill_criteria(labels, limit, force, repeat, grip):
    """'검사 조건' 패널을 채운다. 0 은 '값이 없음' 이다."""
    labels['허용 변위'].setText(f'{limit:g} mm' if limit > 0 else '—')
    labels['Pull 정지 상한'].setText(f'{force:g} N' if force > 0 else '—')
    labels['반복 횟수'].setText(f'{repeat} 회' if repeat > 0 else '—')
    labels['파지 폭'].setText(f'{grip:g} mm' if grip > 0 else '—')


class ResultDetailDialog(_UiDialog):
    """
    결과 1건의 상세 정보. 모달이 아니므로 떠 있어도 비상정지를 누를 수 있다.

    판정 기준은 DB 의 현재 값이 아니라 결과에 실려 온 '검사 당시' 값이다.
    """

    UI_FILE = 'result_detail_dialog.ui'

    def _load(self):
        w = self._label
        self._recipe, self._badge = w('recipeValue'), w('badge')
        self._point, self._name, self._cable = w('pointValue'), w('nameValue'), w('cableValue')
        self._info = {key: w(name) for key, name in RESULT_LABELS.items()}
        self._criteria = {key: w(name) for key, name in CRITERIA_LABELS.items()}
        self._pose = {'Task': w('taskValue'), 'Joint': w('jointValue')}
        self._product, self._force_id, self._db = (
            w('productValue'), w('forceIdValue'), w('dbSaved'))

    def show_result(self, result: itf.PointResult):
        """팝업 내용을 주어진 결과로 채운다."""
        category = itf.ResultCode.category(result.result)
        version = f' {result.recipe_version}' if result.recipe_version else ''
        self._recipe.setText(f'{result.recipe_id}{version}')
        self._badge.setText(category)
        self._badge.setStyleSheet(chip_style(category) + 'font-size: 18px;')
        self._point.setText(result.point_id or '-')
        self._name.setText(result.point_name or '-')
        cable_type = f' ({result.cable_type})' if result.cable_type else ''
        self._cable.setText(f'{result.cable_id}{cable_type}' or '-')

        _fill_result(self._info, result)
        # 결과에 실려 온 값이다. 0 은 '기준이 실려 오지 않음' (DB 에 이 포인트가 없을 때 등).
        _fill_criteria(self._criteria, result.displacement_limit_mm, result.pull_force_limit_n,
                       result.repeat_count, result.grip_width_mm)
        _fill_pose(self._pose, result.task, result.joint, '— (결과에 위치가 실려 오지 않음)')

        self._product.setText(result.product_id or '-')
        self._force_id.setText(result.force_data_id or '-')
        if result.db_saved:
            self._db.setText('● 저장 완료')
            self._db.setStyleSheet(f'color: {OK_COLOR};')
        else:
            self._db.setText('○ 저장 안 됨')
            self._db.setStyleSheet(f'color: {MUTED_COLOR};')


class LookupDetailDialog(_UiDialog):
    """
    통합 조회 표에서 고른 레시피 포인트 1개의 상세 정보.

    '지금 DB·레시피 파일에 들어 있는 내용' 이다: 레시피 정보 + DB 에 저장된 가장 최근 검사 결과.
    모달이 아니므로 떠 있어도 비상정지를 누를 수 있다.
    """

    UI_FILE = 'lookup_detail_dialog.ui'

    def _load(self):
        w = self._label
        self._recipe, self._badge = w('recipeValue'), w('badge')
        self._point, self._name, self._cable = w('pointValue'), w('nameValue'), w('cableValue')
        self._info = {key: w(name) for key, name in RESULT_LABELS.items()}
        self._criteria = {key: w(name) for key, name in CRITERIA_LABELS.items()}
        self._pose = {'Task': w('taskValue'), 'Joint': w('jointValue')}
        self._product, self._force_id, self._source = (
            w('productValue'), w('forceIdValue'), w('source'))

    def show_row(self, row):
        """팝업 내용을 주어진 lookup_tab.LookupRow 로 채운다."""
        version = f' {row.recipe_version}' if row.recipe_version else ''
        self._recipe.setText(f'{row.recipe_id}{version}')
        text, category = row.badge
        self._badge.setText(text)
        self._badge.setStyleSheet(chip_style(category) + 'font-size: 18px;')
        self._point.setText(row.point_id)
        self._name.setText(row.point_name or '-')
        cable_type = f' ({row.cable_type})' if row.cable_type else ''
        self._cable.setText(f'{row.cable_id}{cable_type}' if row.in_db else '-')

        _fill_result(self._info, row.result)
        if row.in_db:
            _fill_criteria(self._criteria, row.max_displacement_mm, row.pull_force_limit_n,
                           row.repeat_count, row.grip_width_mm)
        else:
            for label in self._criteria.values():
                label.setText('— (DB 에 없는 포인트)')

        _fill_pose(self._pose, row.task if row.in_json else [], row.joint if row.in_json else [],
                   f'— ({row.position})')

        self._product.setText(row.product_id or '-')
        self._force_id.setText((row.result.force_data_id if row.result else '') or '-')
        marks = [('DB', row.in_db), ('JSON', row.in_json)]
        self._source.setText('   '.join(f'{"●" if on else "○"} {name}' for name, on in marks))
        self._source.setStyleSheet(
            f'color: {OK_COLOR if row.in_db and row.in_json else MUTED_COLOR};')
