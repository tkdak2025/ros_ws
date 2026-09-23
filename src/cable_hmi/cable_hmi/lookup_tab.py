"""
'통합 조회' 탭: 검사 레시피(v0.1 JSON)의 Point 와 DB 에 저장된 검사 결과를 한 표에서 검색한다.

이 탭은 '지금 레시피 파일과 결과 DB 에 들어 있는 내용' 을 보여 준다. 그래서 HMI 의
다른 부분과 달리 파일·DB 를 직접 읽는다. 대신 다음을 지킨다.
  - 읽기 전용이다. 값을 고치는 기능은 없다.
  - 조회는 별도 스레드에서 한다. DB 가 잠겨 있어도 화면과 STOP 버튼이 멈추지 않는다.
  - 검사에 쓰는 기준은 여전히 검사 시작 때 보낸 레시피와 노드가 보낸 값이다. 이 탭의 값은
    검사에 아무 영향을 주지 않는다.

포인트 1개가 1행이다. 레시피는 검사 시작에 쓰는 것과 같은 폴더(inspection_recipe_dir)에서 읽고,
결과 DB(result_db.py, result_recorder_node 가 씀)에서 포인트별 가장 최근 결과를 recipe_id +
point_id 로 붙인다. 레시피에 없는 결과(레시피를 지우거나 이름을 바꾼 경우)도 버리지 않고 따로 보여 준다.
표에는 '현재 검사 결과' 표와 같은 열만 둔다(검사 시간 / Point / 종류 / 결과 / 상세).
판정 기준, 좌표 같은 나머지는 행을 누르면 뜨는 상세 팝업에 있다.

2026-09-23 이전에는 레시피 DB 뷰(v_recipe_point)와 프로토타입 JSON 을 읽었다. 새 레시피가
v0.1 JSON 으로 바뀌어 그 둘은 이 탭에서 더 읽지 않는다.

'결과 파일 저장' 은 DB 에 쌓인 검사 결과 전체를 새 파일 둘(.db + .csv)로 내보낸다.
'검사' 탭의 같은 이름 버튼이 이번 검사 1회분만 담는 것과 다르다. 화면 필터는 적용하지 않고,
공용 DB 는 읽기만 한다.
"""

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Tuple

from PyQt5.QtCore import pyqtSignal, QObject, QRunnable, Qt, QThreadPool
from PyQt5.QtGui import QBrush, QColor
from PyQt5.QtWidgets import (
    QAbstractItemView, QComboBox, QHBoxLayout, QHeaderView, QLabel, QLineEdit, QMessageBox,
    QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from . import inspection_recipe
from . import interface as itf
from . import result_db
from .detail_dialog import LookupDetailDialog
from .style import RESULT_COLORS

ALL_RECIPES = '전체'

# '현재 검사 결과' 표(main_window.RESULT_HEADERS)와 같은 열 + 맨 앞의 Recipe.
# 나머지 정보(판정 기준, 좌표 ...)는 상세 팝업에 있다.
COLUMNS = ('Recipe', '검사 시간', 'Point', '종류', '결과', '상세')
COLUMN_TIPS = {'검사 시간': 'DB 에 저장된 가장 최근 검사의 시각 (월-일 시:분)',
               '결과': 'DB 에 저장된 가장 최근 검사 결과', '상세': '누르면 상세 팝업'}
FIXED_WIDTHS = {'Recipe': 150, '검사 시간': 110, '종류': 90, '결과': 180, '상세': 50}
COL_RESULT = COLUMNS.index('결과')


@dataclass
class LookupRow:
    """표의 1행 = 포인트 1개."""

    recipe_id: str
    point_id: str
    recipe_version: str = ''
    point_name: str = ''
    cable_type: str = ''        # 레시피의 connector_type (결과의 cable_type 과 같은 값)
    enabled: bool = True        # False 면 검사 때 건너뛰는 Point
    # 검사 조건. 레시피 Point 는 pull_setting / grip_setting 에서, 레시피에 없는 결과는 결과에서.
    max_displacement_mm: float = 0.0
    required_pull_force_n: float = 0.0
    pull_max_distance_mm: float = 0.0
    grip_width_mm: float = 0.0  # grip_setting.hard_width_mm (지시 폭)
    in_recipe: bool = True      # False = 결과만 있고 지금 레시피 파일에는 없는 Point
    task: List[float] = field(default_factory=list)     # entry_pose [mm x3, deg x3] (BASE, ZYZ)
    joint: List[float] = field(default_factory=list)    # entry_pose [deg x6]
    result: Optional[itf.PointResult] = None            # DB 에 저장된 가장 최근 검사 결과

    def flag(self) -> Tuple[str, str]:
        """눈에 띄게 표시할 것: (행 색 부류 'INCOMPLETE'/'', 설명)."""
        if not self.in_recipe:
            return 'INCOMPLETE', '레시피에 없는 Point (결과만 남아 있음)'
        if not self.enabled:
            return 'INCOMPLETE', '검사 제외 (enabled=false)'
        return '', ''

    @property
    def badge(self) -> Tuple[str, str]:
        """상세 팝업의 배지: (문구, 색 부류)."""
        if not self.in_recipe:
            return '레시피 없음', 'INCOMPLETE'
        if not self.enabled:
            return '검사 제외', 'INCOMPLETE'
        if self.result is None:
            return '검사 전', ''
        category = itf.ResultCode.category(self.result.result)
        return self.result.result, category

    def matches(self, recipe_id: str, text: str) -> bool:
        """Recipe 필터와 검색어(대소문자 무시, 부분 일치)에 맞는가."""
        if recipe_id != ALL_RECIPES and self.recipe_id != recipe_id:
            return False
        words = text.lower().split()
        haystack = ' '.join((self.recipe_id, self.point_id, self.point_name, self.cable_type,
                             self.result.result if self.result else '')).lower()
        return all(word in haystack for word in words)


def _recipe_rows(info: inspection_recipe.RecipeFile) -> List[LookupRow]:
    """레시피 파일 1개의 Point 들 (실행 순서대로)."""
    data = info.data
    rows = []
    for point_id in data['execution_order']:
        p = data['points'][point_id]
        pull, grip, entry = p['pull_setting'], p['grip_setting'], p['entry_pose']
        rows.append(LookupRow(
            info.recipe_id, point_id, info.recipe_version, p.get('point_name', ''),
            data['connector_type'], p['enabled'],
            max_displacement_mm=pull['normal_displacement_limit_mm'],
            # Main 과 같은 뜻: force_limit_n 에 도달하면 멈추고 그 힘이 합격 기준이다.
            required_pull_force_n=pull['force_limit_n'],
            pull_max_distance_mm=pull['max_distance_mm'],
            grip_width_mm=grip['hard_width_mm'],
            task=list(entry['task']), joint=list(entry['joint'])))
    return rows


def _orphan_row(result: itf.PointResult) -> LookupRow:
    """레시피에 없는 결과 1건. 조건과 위치는 결과에 실려 온 값을 쓴다."""
    return LookupRow(
        result.recipe_id, result.point_id, result.recipe_version, result.point_name,
        result.cable_type, max_displacement_mm=result.displacement_limit_mm,
        required_pull_force_n=result.required_pull_force_n,
        pull_max_distance_mm=result.pull_max_distance_mm, grip_width_mm=result.grip_width_mm,
        in_recipe=False, task=list(result.task), joint=list(result.joint), result=result)


def load_rows(db_path: str, recipe_dir: str) -> Tuple[List[LookupRow], List[str]]:
    """
    레시피 폴더와 결과 DB 를 읽어 (행 목록, 알림 목록) 을 돌려준다.

    Qt 와 무관한 순수 함수다(백그라운드 스레드에서 부른다). 한쪽을 못 읽어도 다른 쪽은 보여 준다.
    """
    notes: List[str] = []
    rows: List[LookupRow] = []

    if recipe_dir:
        recipes, problems = inspection_recipe.scan(recipe_dir)
        notes += [f'레시피 파일: {p}' for p in problems]
        for info in recipes.values():
            rows += _recipe_rows(info)
    else:
        notes.append('레시피 폴더가 지정되지 않음')

    if not db_path:
        notes.append('DB 경로가 지정되지 않음 (launch 인자 recipe_db)')
        return rows, notes
    try:
        latest = result_db.ResultDb(db_path).latest_by_point()
    except result_db.ResultDbError as e:
        notes.append(f'검사 결과: {e}')
        return rows, notes
    for row in rows:
        row.result = latest.pop((row.recipe_id, row.point_id), None)
    rows += [_orphan_row(result) for result in latest.values()]
    return rows, notes


class _LoadSignals(QObject):
    done = pyqtSignal(object, object)       # rows, notes


class _LoadTask(QRunnable):
    """load_rows 를 스레드 풀에서 돌린다."""

    def __init__(self, db_path, recipe_dir):
        super().__init__()
        self.signals = _LoadSignals()
        self._args = (db_path, recipe_dir)

    def run(self):
        try:
            rows, notes = load_rows(*self._args)
        except Exception as e:  # noqa: BLE001 - 조회 실패가 HMI 를 죽이면 안 된다
            rows, notes = [], [f'조회 실패: {e!r}']
        self.signals.done.emit(rows, notes)


class _ExportSignals(QObject):
    done = pyqtSignal(object, object)       # (db 경로, csv 경로, 건수) 또는 None, 오류 메시지


class _ExportTask(QRunnable):
    """export_all 을 스레드 풀에서 돌린다. DB 가 크면 시간이 걸릴 수 있다."""

    def __init__(self, directory, db_path):
        super().__init__()
        self.signals = _ExportSignals()
        self._args = (directory, db_path)

    def run(self):
        try:
            self.signals.done.emit(result_db.export_all(*self._args), '')
        except result_db.ResultDbError as e:
            self.signals.done.emit(None, str(e))
        except Exception as e:  # noqa: BLE001 - 저장 실패가 HMI 를 죽이면 안 된다
            self.signals.done.emit(None, repr(e))


class LookupTab(QWidget):
    """통합 조회 탭."""

    def __init__(self, db_path: str = '', recipe_dir: str = '', parent=None):
        super().__init__(parent)
        self._db_path = db_path
        self._recipe_dir = recipe_dir
        self._rows: List[LookupRow] = []
        self._task = None
        self._export_task = None
        self._export_popup = None           # 떠 있는 '결과 파일 저장 완료' 알림
        self._loaded_once = False
        self._detail = None                 # 처음 행을 누를 때 만든다

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 6)
        layout.setSpacing(6)

        bar = QHBoxLayout()
        bar.addWidget(self._role(QLabel('Recipe'), 'key'))
        self.recipe_filter = QComboBox()
        self.recipe_filter.addItem(ALL_RECIPES)
        bar.addWidget(self.recipe_filter)
        self.search = QLineEdit(
            placeholderText='검색: Point · 이름 · 종류 · 결과 (띄어 쓰면 모두 포함)')
        self.search.setClearButtonEnabled(True)
        bar.addWidget(self.search, 1)
        self.reload_btn = QPushButton('조회', objectName='lookupReloadBtn')
        self.reload_btn.setStyleSheet(
            'QPushButton { background: #379DD3; font-size: 13px; padding: 4px 16px; }'
            'QPushButton:disabled { background: #D5DBE3; }')
        bar.addWidget(self.reload_btn)
        # '검사' 탭의 결과 파일 저장과 같은 모양이되, 이쪽은 DB 전체를 담는다.
        self.export_btn = QPushButton('결과 파일 저장', objectName='lookupExportBtn')
        self.export_btn.setStyleSheet(
            'QPushButton { background: #FFFFFF; color: #2B3440; border: 1px solid #9AA5B1;'
            ' font-size: 13px; padding: 4px 12px; border-radius: 6px; }'
            'QPushButton:hover { background: #EEF2F6; }'
            'QPushButton:disabled { background: #F2F4F7; color: #B5BDC7;'
            ' border: 1px solid #D9E0E7; }')
        self.export_btn.setToolTip(
            'DB 에 쌓인 검사 결과 전체를 새 파일 둘(.db + .csv)로 저장합니다.\n'
            '화면 필터와 무관하며 공용 DB 는 바뀌지 않습니다.')
        bar.addWidget(self.export_btn)
        layout.addLayout(bar)

        self.table = QTableWidget(0, len(COLUMNS))
        self.table.setHorizontalHeaderLabels(COLUMNS)
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(30)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)      # 읽기 전용
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setFocusPolicy(Qt.NoFocus)
        self.table.setSortingEnabled(True)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.Stretch)        # '현재 검사 결과' 표와 같은 정책
        for column, name in enumerate(COLUMNS):
            if name in FIXED_WIDTHS:
                header.setSectionResizeMode(
                    column, QHeaderView.Interactive if name == 'Recipe' else QHeaderView.Fixed)
                self.table.setColumnWidth(column, FIXED_WIDTHS[name])
        for column, name in enumerate(COLUMNS):
            if name in COLUMN_TIPS:
                self.table.horizontalHeaderItem(column).setToolTip(COLUMN_TIPS[name])
        layout.addWidget(self.table, 1)

        self.summary = self._role(QLabel('—', wordWrap=True), 'key')
        layout.addWidget(self.summary)

        self.reload_btn.clicked.connect(self.reload)
        self.export_btn.clicked.connect(self._on_export)
        self.table.cellClicked.connect(self._open_detail)
        self.search.textChanged.connect(self._apply_filter)
        self.recipe_filter.currentTextChanged.connect(self._apply_filter)

    @staticmethod
    def _role(widget, role):
        widget.setProperty('role', role)
        return widget

    def showEvent(self, event):
        """탭을 처음 열 때 한 번 자동으로 조회한다."""
        super().showEvent(event)
        if not self._loaded_once:
            self._loaded_once = True
            self.reload()

    def reload(self):
        """DB 와 레시피 폴더를 다시 읽는다 (백그라운드)."""
        if self._task is not None:
            return                          # 이미 조회 중
        self.reload_btn.setEnabled(False)
        self.summary.setText('조회 중…')
        self._task = _LoadTask(self._db_path, self._recipe_dir)
        self._task.signals.done.connect(self._on_loaded)
        QThreadPool.globalInstance().start(self._task)

    def _on_loaded(self, rows, notes):
        self._task = None
        self.reload_btn.setEnabled(True)
        self._rows = rows
        self._notes = notes
        self._loaded_at = datetime.now().strftime('%H:%M:%S')

        keep = self.recipe_filter.currentText()
        self.recipe_filter.blockSignals(True)
        self.recipe_filter.clear()
        self.recipe_filter.addItem(ALL_RECIPES)
        self.recipe_filter.addItems(sorted({row.recipe_id for row in rows}))
        index = self.recipe_filter.findText(keep)
        self.recipe_filter.setCurrentIndex(index if index >= 0 else 0)
        self.recipe_filter.blockSignals(False)
        self._apply_filter()

    # ------------------------------------------------------- 결과 파일 저장 (DB 전체)
    def _export_dir(self) -> Path:
        """결과 파일을 둘 곳: 레시피 DB 옆의 runs 폴더. '검사' 탭과 같은 위치다."""
        if self._db_path:
            return Path(self._db_path).expanduser().parent / 'runs'
        return Path('~/ros_ws/results/runs').expanduser()

    def _on_export(self):
        """DB 에 쌓인 검사 결과 전체를 새 파일 둘(.db + .csv)로 내보낸다. 먼저 확인 창이 뜬다."""
        if self._export_task is not None:
            return                          # 이미 저장 중
        if not self._db_path:
            self._popup(QMessageBox.Warning, '결과 파일 저장',
                        'DB 경로가 설정되지 않아 저장할 수 없습니다.')
            return
        box = QMessageBox(
            QMessageBox.Question, '결과 파일 저장',
            'DB 에 저장된 검사 결과를 전부 파일로 내보냅니다.\n\n'
            f'읽을 DB: {self._db_path}\n'
            f'저장 위치: {self._export_dir()}\n'
            '파일 이름: all_<날짜_시각>.db / .csv\n\n'
            '화면의 Recipe 필터와 검색어는 적용되지 않습니다.\n'
            '공용 DB 는 바뀌지 않습니다.',
            QMessageBox.Ok | QMessageBox.Cancel, self)
        box.button(QMessageBox.Ok).setText('저장')
        box.button(QMessageBox.Cancel).setText('취소')
        box.setDefaultButton(QMessageBox.Cancel)
        if box.exec_() != QMessageBox.Ok:
            return
        self.export_btn.setEnabled(False)
        self.export_btn.setText('저장 중…')
        self._export_task = _ExportTask(self._export_dir(), self._db_path)
        self._export_task.signals.done.connect(self._on_exported)
        QThreadPool.globalInstance().start(self._export_task)

    def _on_exported(self, paths, error):
        self._export_task = None
        self.export_btn.setEnabled(True)
        self.export_btn.setText('결과 파일 저장')
        if paths is None:
            self._popup(QMessageBox.Critical, '결과 파일 저장 실패', str(error))
            return
        db_path, csv_path, count = paths
        self.export_btn.setToolTip(f'마지막 저장: {db_path}')
        self._popup(QMessageBox.Information, '결과 파일 저장 완료',
                    f'결과 {count}건을 저장했습니다.\n\n{db_path}\n{csv_path}')

    def _popup(self, icon, title, text):
        """비모달 알림. 창이 떠 있어도 '검사' 탭의 STOP 을 누를 수 있어야 한다."""
        box = QMessageBox(icon, title, text, QMessageBox.Ok, self)
        box.button(QMessageBox.Ok).setText('확인')
        box.setModal(False)
        box.show()
        self._export_popup = box        # 참조를 남겨 둬야 창이 바로 닫히지 않는다

    def _apply_filter(self, *_args):
        shown = [row for row in self._rows
                 if row.matches(self.recipe_filter.currentText(), self.search.text())]
        self.table.setSortingEnabled(False)         # 채우는 동안 정렬이 행을 옮기지 않게
        self.table.setRowCount(len(shown))
        for index, row in enumerate(shown):
            self._fill_row(index, row)
        self.table.setSortingEnabled(True)
        # Recipe 를 하나 골랐으면 모든 행이 같은 값이므로 그 열은 숨겨 폭을 아낀다.
        self.table.setColumnHidden(0, self.recipe_filter.currentText() != ALL_RECIPES)
        self._update_summary(shown)

    def _fill_row(self, index: int, row: LookupRow):
        category, note = row.flag()
        background = RESULT_COLORS[category][2] if category else '#FFFFFF'
        dash = '—'
        result = row.result
        cells = (row.recipe_id,
                 result.stamp[5:16].replace('T', ' ') if result else dash,
                 row.point_id,
                 row.cable_type or dash,
                 result.result if result else dash,
                 '›')
        tip = ' · '.join(t for t in (f'{row.recipe_id} / {row.point_id} {row.point_name}'.strip(),
                                     f'버전 {row.recipe_version}' if row.recipe_version else '',
                                     note) if t)
        for col, value in enumerate(cells):
            item = QTableWidgetItem()
            item.setData(Qt.DisplayRole, value)
            item.setTextAlignment(Qt.AlignCenter)
            item.setBackground(QBrush(QColor(background)))
            item.setToolTip(tip)
            if col == 0:
                item.setData(Qt.UserRole, row)      # 정렬로 행이 옮겨져도 따라다닌다
            if col == COL_RESULT and result:
                item.setForeground(QBrush(QColor(
                    RESULT_COLORS[itf.ResultCode.category(result.result)][0])))
                font = item.font()
                font.setBold(True)
                item.setFont(font)
                item.setToolTip(result.reason or tip)
            self.table.setItem(index, col, item)

    def _open_detail(self, table_row: int, _col: int = 0):
        """누른 행의 상세 팝업을 띄운다. 비모달이라 STOP 을 막지 않는다."""
        item = self.table.item(table_row, 0)
        row = item.data(Qt.UserRole) if item else None
        if row is None:
            return
        if self._detail is None:
            self._detail = LookupDetailDialog(self)
        self._detail.show_row(row)
        self._detail.show()
        self._detail.raise_()

    def _update_summary(self, shown):
        orphan = sum(1 for row in shown if not row.in_recipe)
        disabled = sum(1 for row in shown if row.in_recipe and not row.enabled)
        parts = [f'표시 {len(shown)}건 / 전체 {len(self._rows)}건']
        inspected = sum(1 for row in shown if row.result)
        if inspected:
            parts.append(f'검사 결과 있음 {inspected}건')
        if disabled:
            parts.append(f'검사 제외 {disabled}건')
        if orphan:
            parts.append(f'레시피에 없는 결과 {orphan}건')
        parts.append(f'조회 {self._loaded_at}')
        parts += self._notes
        self.summary.setText('  ·  '.join(parts))
