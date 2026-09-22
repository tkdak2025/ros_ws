"""
'통합 조회' 탭: 레시피 DB 와 레시피 JSON 의 내용을 한 표에서 검색한다.

이 탭은 검사 결과가 아니라 '지금 DB·파일에 들어 있는 내용' 을 보여 준다. 그래서 HMI 의
다른 부분과 달리 DB 를 직접 읽는다. 대신 다음을 지킨다.
  - 읽기 전용이다. 값을 고치는 기능은 없다.
  - 조회는 별도 스레드에서 한다. DB 가 잠겨 있어도 화면과 STOP 버튼이 멈추지 않는다.
  - 검사에 쓰는 기준은 여전히 노드가 보낸 값(status / result)이다. 이 탭의 값은 검사에
    아무 영향을 주지 않는다.

포인트 1개가 1행이다. DB(케이블·판정 기준)와 JSON(위치)을 recipe_id + point_id 로 맞춰
한쪽에만 있는 포인트와 티칭 안 된 포인트를 색으로 표시한다. 같은 DB 에 저장된 검사 결과
(result_db.py, result_recorder_node 가 씀)에서 포인트별 가장 최근 결과와 검사 시간도 함께 보여 준다.
표에는 '현재 검사 결과' 표와 같은 열만 둔다(검사 시간 / Point / 케이블 / 종류 / 결과 / 상세).
판정 기준, 좌표 같은 나머지는 행을 누르면 뜨는 상세 팝업에 있다.
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Optional, Tuple

from PyQt5.QtCore import pyqtSignal, QObject, QRunnable, Qt, QThreadPool
from PyQt5.QtGui import QBrush, QColor
from PyQt5.QtWidgets import (
    QAbstractItemView, QComboBox, QHBoxLayout, QHeaderView, QLabel, QLineEdit, QPushButton,
    QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from . import interface as itf
from . import recipe_catalog
from . import recipe_db
from . import result_db
from .detail_dialog import LookupDetailDialog
from .style import RESULT_COLORS

ALL_RECIPES = '전체'

POSITION_TAUGHT = '티칭됨'
POSITION_UNTAUGHT = '미티칭'          # JSON 좌표가 전부 0 (자리표시자)
POSITION_NONE = '위치 없음'           # 레시피 JSON 에 이 포인트가 없음
POSITION_UNKNOWN = '—'                # 레시피 폴더를 읽지 못함

# '현재 검사 결과' 표(main_window.RESULT_HEADERS)와 같은 열 + 맨 앞의 Recipe.
# 나머지 정보(판정 기준, 좌표, 위치 상태 ...)는 상세 팝업에 있다.
COLUMNS = ('Recipe', '검사 시간', 'Point', '케이블', '종류', '결과', '상세')
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
    product_id: str = ''
    point_name: str = ''
    cable_id: str = ''
    cable_type: str = ''
    max_displacement_mm: float = 0.0
    pull_force_limit_n: float = 0.0
    repeat_count: int = 0
    required_pull_force_n: float = 0.0
    grip_width_mm: float = 0.0
    in_db: bool = True
    position: str = POSITION_UNKNOWN
    in_json: bool = False
    task: List[float] = field(default_factory=list)     # [mm x3, deg x3] (BASE, ZYZ)
    joint: List[float] = field(default_factory=list)    # [deg x6]
    result: Optional[itf.PointResult] = None            # DB 에 저장된 가장 최근 검사 결과

    @property
    def taught(self) -> bool:
        """레시피 JSON 에 실제로 티칭된 좌표가 있는가."""
        return self.position == POSITION_TAUGHT

    def flag(self) -> Tuple[str, str]:
        """눈에 띄게 표시할 문제: (색 부류 'FAIL'/'MISSING'/'', 설명)."""
        if not self.in_db:
            return 'FAIL', 'DB 에 없는 포인트 (레시피 JSON 에만 있음)'
        if self.position in (POSITION_UNTAUGHT, POSITION_NONE):
            return 'MISSING', f'위치: {self.position}'
        return '', ''

    @property
    def badge(self) -> Tuple[str, str]:
        """상세 팝업의 배지: (문구, 색 부류)."""
        category, _note = self.flag()
        if not self.in_db:
            return 'DB 없음', category
        return self.position, category or ('PASS' if self.taught else '')

    def matches(self, recipe_id: str, text: str) -> bool:
        """Recipe 필터와 검색어(대소문자 무시, 부분 일치)에 맞는가."""
        if recipe_id != ALL_RECIPES and self.recipe_id != recipe_id:
            return False
        words = text.lower().split()
        haystack = ' '.join((self.recipe_id, self.point_id, self.point_name, self.cable_id,
                             self.cable_type, self.product_id, self.position,
                             self.result.result if self.result else '')).lower()
        return all(word in haystack for word in words)


def load_rows(db_path: str, recipe_dir: str) -> Tuple[List[LookupRow], List[str]]:
    """
    DB(레시피 + 검사 결과)와 레시피 폴더를 읽어 (행 목록, 알림 목록) 을 돌려준다.

    Qt 와 무관한 순수 함수다(백그라운드 스레드에서 부른다). 한쪽을 못 읽어도 다른 쪽은 보여 준다.
    """
    notes: List[str] = []
    rows: List[LookupRow] = []

    json_recipes = {}
    if recipe_dir:
        json_recipes, problems = recipe_catalog.scan(recipe_dir)
        notes += [f'레시피 파일: {p}' for p in problems]
    else:
        notes.append('레시피 폴더가 지정되지 않음 - 위치 대조 생략')

    def json_point(recipe_id, point_id):
        info = json_recipes.get(recipe_id)
        return next((p for p in info.points if p.point_id == point_id), None) if info else None

    def position_of(recipe_id, point_id):
        if not recipe_dir:
            return POSITION_UNKNOWN
        point = json_point(recipe_id, point_id)
        if point is None:
            return POSITION_NONE
        return POSITION_TAUGHT if point.taught else POSITION_UNTAUGHT

    def name_of(recipe_id, point_id, db_name):
        # 포인트 이름은 DB 와 JSON 어느 쪽에 있어도 된다. DB 에 없으면 JSON 의 이름을 쓴다.
        point = json_point(recipe_id, point_id)
        return db_name or (point.point_name if point else '')

    db_points = set()
    if db_path:
        try:
            db = recipe_db.RecipeDb(db_path)
            for recipe_id in db.list_recipes():
                info = db.load_recipe(recipe_id)
                for p in info.points.values():
                    db_points.add((recipe_id, p.point_id))
                    point = json_point(recipe_id, p.point_id)
                    rows.append(LookupRow(
                        recipe_id, p.point_id, info.recipe_version, info.product_id,
                        name_of(recipe_id, p.point_id, p.point_name),
                        p.cable_id, p.cable_type, p.max_displacement_mm,
                        p.pull_force_limit_n, p.repeat_count, p.grip_width_mm,
                        required_pull_force_n=p.required_pull_force_n,
                        in_db=True, position=position_of(recipe_id, p.point_id),
                        in_json=point is not None,
                        task=list(point.task) if point else [],
                        joint=list(point.joint) if point else []))
        except recipe_db.RecipeDbError as e:
            notes.append(f'DB: {e}')
    else:
        notes.append('DB 경로가 지정되지 않음 (launch 인자 recipe_db)')

    # 레시피 JSON 에는 있는데 DB 에 없는 포인트도 보여 준다.
    for recipe_id, info in json_recipes.items():
        for point in info.points:
            if (recipe_id, point.point_id) not in db_points:
                rows.append(LookupRow(
                    recipe_id, point.point_id, info.recipe_version, point_name=point.point_name,
                    in_db=False,
                    position=POSITION_TAUGHT if point.taught else POSITION_UNTAUGHT,
                    in_json=True, task=list(point.task), joint=list(point.joint)))

    if db_path:                 # 검사 결과는 같은 DB 파일의 다른 테이블에 있다
        try:
            latest = result_db.ResultDb(db_path).latest_by_point()
            for row in rows:
                row.result = latest.get((row.recipe_id, row.point_id))
        except result_db.ResultDbError as e:
            notes.append(f'검사 결과: {e}')
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


class LookupTab(QWidget):
    """통합 조회 탭."""

    def __init__(self, db_path: str = '', recipe_dir: str = '', parent=None):
        super().__init__(parent)
        self._db_path = db_path
        self._recipe_dir = recipe_dir
        self._rows: List[LookupRow] = []
        self._task = None
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
            placeholderText='검색: Point · 이름 · 케이블 · 종류 · 결과 (띄어 쓰면 모두 포함)')
        self.search.setClearButtonEnabled(True)
        bar.addWidget(self.search, 1)
        self.reload_btn = QPushButton('조회', objectName='lookupReloadBtn')
        self.reload_btn.setStyleSheet(
            'QPushButton { background: #379DD3; font-size: 13px; padding: 4px 16px; }'
            'QPushButton:disabled { background: #D5DBE3; }')
        bar.addWidget(self.reload_btn)
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
                 (row.cable_id or dash) if row.in_db else 'DB 없음',
                 row.cable_type or dash,
                 result.result if result else dash,
                 '›')
        tip = ' · '.join(t for t in (f'{row.recipe_id} / {row.point_id} {row.point_name}'.strip(),
                                     f'버전 {row.recipe_version}' if row.recipe_version else '',
                                     f'제품 {row.product_id}' if row.product_id else '',
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
        missing = sum(1 for row in shown if not row.in_db)
        untaught = sum(1 for row in shown if row.position in (POSITION_UNTAUGHT, POSITION_NONE))
        parts = [f'현재 DB 내용 {len(shown)}건 / 전체 {len(self._rows)}건']
        inspected = sum(1 for row in shown if row.result)
        if inspected:
            parts.append(f'검사 결과 있음 {inspected}건')
        if missing:
            parts.append(f'DB 에 없는 포인트 {missing}건')
        if untaught:
            parts.append(f'위치 미티칭·없음 {untaught}건')
        parts.append(f'조회 {self._loaded_at}')
        parts += self._notes
        self.summary.setText('  ·  '.join(parts))
