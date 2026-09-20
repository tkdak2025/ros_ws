"""
케이블 체결 검사 HMI 메인 화면.

화면 배치와 스타일은 main_window.ui (Qt Designer) 에 있고, 이 파일은 동작만 담당한다.
원칙: HMI 는 검사 노드 상태의 '렌더러'다. 버튼을 눌러도 화면 상태를 스스로
바꾸지 않고 명령만 보낸 뒤, 돌아오는 status 로만 화면과 버튼 활성화를 갱신한다.
"""

from datetime import datetime
import html
import os
import sys
import time

from PyQt5 import uic
from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtGui import QBrush, QColor
from PyQt5.QtWidgets import (
    QComboBox, QHeaderView, QLabel, QMainWindow, QMessageBox, QPlainTextEdit, QProgressBar,
    QPushButton, QSlider, QTableWidget, QTableWidgetItem, QTabWidget, QWidget,
)

from . import interface as itf
from .detail_dialog import ResultDetailDialog
from .lookup_tab import LookupTab
from .style import (
    BAD_COLOR, chip_style, DIALOG_QSS, LOG_COLORS, MUTED_COLOR, OK_COLOR, RESULT_COLORS,
    WARN_COLOR,
)

# 없으면 실행을 거부하는 위젯. 나머지는 Designer 에서 지워도 HMI 가 뜬다.
REQUIRED_WIDGETS = ('estopBtn',)
UI_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'main_window.ui')

Cmd = itf.CommandName
State = itf.State

MONITOR_STATES = (State.MONITOR, State.MONITOR_MOVING)
RESULT_CODES = (itf.ResultCode.PASS, itf.ResultCode.MISSING, *itf.ResultCode.FAIL_CODES)
# '현재 검사 결과' 표의 열. 이름과 순서는 통합 조회 탭(lookup_tab.COLUMNS)의 용어에 맞춘다.
RESULT_HEADERS = ('검사 시간', 'Point', '케이블', '종류', '결과', '상세')
COL_TIME, COL_POINT, COL_CABLE, COL_TYPE, COL_RESULT, COL_DETAIL = range(len(RESULT_HEADERS))
SPEED_HOLD_SEC = 1.0      # 슬라이더 조작 후 이 시간 동안은 status 값으로 덮어쓰지 않는다
SPEED_DEBOUNCE_MS = 300

STATE_BADGE_COLORS = {
    State.RUNNING: '#1E8E5A', State.MOVING: '#1E8E5A', State.PAUSED: '#B7791F',
    State.MONITOR_MOVING: '#1E8E5A',
    State.ESTOP: '#D12F3A', State.ERROR: '#D12F3A',
}


def _set(label: QLabel, text: str, color: str = ''):
    label.setText(text)
    label.setStyleSheet(f'color: {color};' if color else '')


class MainWindow(QMainWindow):
    """bridge 는 status/result/log signal 과 send_command() 만 있으면 된다."""

    def __init__(self, bridge):
        super().__init__()
        self._bridge = bridge
        self._status = itf.SystemStatus()
        self._linked = False
        self._last_status_time = 0.0
        self._results = []            # 테이블 행과 같은 순서의 itf.PointResult
        self._run_id = None
        self._move_cycle = {'FAIL': 0, 'MISSING': 0}
        self._speed_hold_until = 0.0
        self._detail = ResultDetailDialog(self)
        self._popup = None            # 떠 있는 에러 팝업 (없으면 None)

        self._missing_widgets = []
        self._load_ui()

        bridge.status_received.connect(self.on_status)
        bridge.result_received.connect(self.on_result)
        bridge.log_received.connect(self.on_log)

        self._watchdog = QTimer(self, interval=300)
        self._watchdog.timeout.connect(self._check_link)
        self._watchdog.start()

        self._speed_timer = QTimer(self, interval=SPEED_DEBOUNCE_MS, singleShot=True)
        self._speed_timer.timeout.connect(self._send_speed)

        self._render()
        self._append_log('INFO', '[HMI] 시작 - 검사 노드의 status 를 기다리는 중')
        if self._missing_widgets:
            text = '[HMI] main_window.ui 에 없는 위젯(표시 생략): ' + ', '.join(self._missing_widgets)
            self._append_log('WARN', text)
            print(text, file=sys.stderr)

    # ------------------------------------------------------------------ UI
    def _widget(self, name: str, cls=QLabel):
        """
        .ui 에서 objectName 으로 위젯을 찾는다.

        Designer 에서 지워져 없으면 숨겨진 대역 위젯을 돌려주어 나머지 코드가 그대로
        돌게 하고, 빠진 이름은 시작 시 시스템 로그에 경고로 남긴다.
        """
        found = self.findChild(cls, name)
        if found is not None:
            return found
        if name in REQUIRED_WIDGETS:
            raise RuntimeError(
                f"main_window.ui 에 필수 위젯 '{name}' ({cls.__name__}) 이 없습니다. "
                'Qt Designer 에서 objectName 을 확인하세요.')
        self._missing_widgets.append(name)
        # 숨긴 부모 밑에 두어, 코드가 setVisible(True) 를 불러도 화면에 나타나지 않게 한다.
        return cls(self._attic)

    def _load_ui(self):
        """
        화면 배치·스타일은 main_window.ui 에 있다 (Qt Designer 로 편집).

        이 파일이 의존하는 것은 아래에서 참조하는 objectName 뿐이다. Designer 에서
        위젯을 지우거나 이름을 바꾸면 그 항목만 화면에서 빠지고 HMI 는 계속 뜬다
        (_widget 참고). 비상정지 버튼만은 없으면 실행을 거부한다.
        """
        uic.loadUi(UI_FILE, self)
        # .ui 의 QPushButton 규칙은 글자만 흰색으로 만들어 대화상자 버튼이 안 보인다. 대화상자에
        # 직접 스타일을 걸면 창을 띄울 때 반영되지 않아서, 이 창의 스타일 뒤에 덧붙인다.
        self.setStyleSheet(self.styleSheet() + DIALOG_QSS)
        self._attic = QWidget(self)
        self._attic.hide()
        w = self._widget

        self.tool_state = w('toolState')
        self.tool_rows = {
            'Tool': w('toolName'), 'Tool Weight': w('toolWeight'), 'TCP': w('toolTcp'),
            'Force Zero': w('toolForceZero'), '현재 알람': w('toolAlarm')}
        self.conn_rows = {
            'Robot 연결': w('connRobot'), 'ROS2 통신': w('connRos'),
            'RG2 연결': w('connGripper')}
        self.point_rows = {
            '현재 위치': w('pointPosition'), '현재 단계': w('pointStep'),
            '속도 설정': w('pointSpeed'), '그리퍼 폭': w('pointGripper'),
            '현재 힘 값': w('pointForce'), '현재 변위': w('pointDisplacement'),
            '현재 판정': w('pointJudgement')}
        self.criteria_rows = {
            '허용 변위': w('critDisplacement'), 'Pull Force': w('critForce'),
            'Push / Pull 반복': w('critRepeat'), 'Grip 폭': w('critGrip')}
        self.chips = {'전체': w('chipTotal'), 'PASS': w('chipPass'),
                      'MISSING': w('chipMissing'), 'FAIL': w('chipFail')}
        self.state_badge = w('stateBadge')
        self.start_btn, self.pause_btn, self.resume_btn = (
            w('startBtn', QPushButton), w('pauseBtn', QPushButton), w('resumeBtn', QPushButton))
        self.estop_btn, self.estop_state, self.estop_reset_btn = (
            w('estopBtn', QPushButton), w('estopState'), w('estopResetBtn', QPushButton))
        self.home_btn, self.fail_btn, self.missing_btn = (
            w('homeBtn', QPushButton), w('failBtn', QPushButton), w('missingBtn', QPushButton))
        self.move_hint = w('moveHint')
        self.recipe_combo, self.recipe_version = w('recipeCombo', QComboBox), w('recipeVersion')
        self.product_id, self.product_result = w('productId'), w('productResult')
        self.table, self.log_view = w('resultTable', QTableWidget), w('logView', QPlainTextEdit)
        self.speed_slider, self.speed_label = w('speedSlider', QSlider), w('speedLabel')
        self.progress_bar, self.progress_text = w('progressBar', QProgressBar), w('progressText')

        self._add_lookup_tab()

        # 헤더 열 너비 정책은 .ui 로 표현할 수 없어 코드에 둔다. 열 제목도 여기서 정한다: 열의 수와
        # 뜻이 아래 _fill_row 와 짝을 이루고, 통합 조회 탭과 같은 용어를 써야 하기 때문이다
        # (.ui 에 적힌 열 제목보다 이쪽이 우선한다).
        self.table.setColumnCount(len(RESULT_HEADERS))
        self.table.setHorizontalHeaderLabels(RESULT_HEADERS)
        hdr = self.table.horizontalHeader()
        hdr.setSectionResizeMode(QHeaderView.Stretch)
        for col, width in ((COL_TIME, 90), (COL_TYPE, 80), (COL_RESULT, 180), (COL_DETAIL, 50)):
            hdr.setSectionResizeMode(col, QHeaderView.Fixed)
            self.table.setColumnWidth(col, width)

        self.start_btn.clicked.connect(self._on_start)
        self.pause_btn.clicked.connect(lambda: self._send(Cmd.PAUSE))
        self.resume_btn.clicked.connect(lambda: self._send(Cmd.RESUME))
        self.estop_btn.clicked.connect(lambda: self._send(Cmd.ESTOP))
        self.estop_reset_btn.clicked.connect(self._on_estop_reset)
        self.home_btn.clicked.connect(self._on_home)
        self.fail_btn.clicked.connect(lambda: self._on_move_to('FAIL'))
        self.missing_btn.clicked.connect(lambda: self._on_move_to('MISSING'))
        self.speed_slider.valueChanged.connect(self._on_speed_changed)
        self.recipe_combo.activated.connect(self._on_recipe_chosen)   # 사용자가 고를 때만 발생
        self.table.cellClicked.connect(self._on_cell_clicked)
        self.table.cellDoubleClicked.connect(lambda row, _col: self._open_detail(row))
        self.table.itemSelectionChanged.connect(self._on_selection_changed)

    def _add_lookup_tab(self):
        """'시스템 로그' 옆에 '통합 조회' 탭을 붙인다. .ui 는 건드리지 않고 코드에서 추가한다."""
        tabs = self.findChild(QTabWidget, 'tabs')
        if tabs is None:
            self._missing_widgets.append('tabs')
            return
        # bridge 에 parameter() 가 없으면(테스트용 대역 등) 경로 없이 띄운다.
        read = getattr(self._bridge, 'parameter', lambda _name: '')
        self.lookup_tab = LookupTab(read('recipe_db'), read('recipe_dir'), self)
        tabs.addTab(self.lookup_tab, '통합 조회')

    # ------------------------------------------------------- ROS -> 화면
    def on_status(self, status: itf.SystemStatus):
        """검사 노드 status 수신. 화면 갱신의 유일한 출발점."""
        self._last_status_time = time.monotonic()
        self._status = status
        if not self._linked:
            self._linked = True
            self._append_log('INFO', '[HMI] 검사 노드 연결됨')
            self._bridge.send_command(Cmd.SYNC)
        self._ensure_run(status.run_id)
        self._render()

    def on_result(self, result: itf.PointResult):
        """Point 결과 수신. 같은 run 의 같은 Point 는 덮어쓴다(재검사·SYNC 대응)."""
        self._ensure_run(result.run_id)
        for row, old in enumerate(self._results):
            if old.point_id == result.point_id:
                self._results[row] = result
                break
        else:
            row = len(self._results)
            self._results.append(result)
            self.table.insertRow(row)
        self._fill_row(row, result)
        if self._detail.isVisible() and self.table.currentRow() == row:
            self._detail.show_result(result)
        self._render_counts()
        self._refresh_controls()

    def on_log(self, entry: itf.LogEntry):
        """검사 노드의 시스템 로그 수신. popup 표시가 있으면 팝업으로도 띄운다."""
        self._append_log(entry.level, entry.text, entry.stamp)
        if entry.popup:
            self._show_popup(entry.level, entry.text)

    def _show_popup(self, level: str, text: str):
        """
        에러 팝업을 띄운다.

        비모달이다 - 팝업이 떠 있어도 STOP 을 비롯한 화면 조작을 막지 않는다.
        이미 떠 있으면 새 창을 또 띄우지 않고 같은 창에 줄을 추가한다(Tool 과 TCP 가 함께 실패하는 경우).
        """
        if self._popup is not None and self._popup.isVisible():
            lines = self._popup.text().split('\n')
            if text not in lines:
                self._popup.setText('\n'.join(lines + [text]))
            if level == 'ERROR':
                self._popup.setIcon(QMessageBox.Critical)
            self._popup.raise_()
            return
        box = self._message_box(
            QMessageBox.Critical if level == 'ERROR' else QMessageBox.Warning,
            '오류' if level == 'ERROR' else '경고', text, QMessageBox.Ok)
        box.setModal(False)
        box.show()
        self._popup = box

    def _ensure_run(self, run_id: int):
        """새 검사(run)가 시작되면 이전 결과를 비운다."""
        if run_id == self._run_id:
            return
        self._run_id = run_id
        self._results.clear()
        self.table.setRowCount(0)
        self._move_cycle = {'FAIL': 0, 'MISSING': 0}
        self._render_counts()

    def _check_link(self):
        alive = (time.monotonic() - self._last_status_time) < itf.STATUS_TIMEOUT_SEC
        if self._linked and not alive:
            self._linked = False
            self._append_log('ERROR', '[HMI] 검사 노드 status 수신 끊김')
            self._render()

    # ------------------------------------------------------------- 렌더링
    def _render(self):
        s, linked = self._status, self._linked

        def conn(label, ok):
            if not linked:
                _set(label, '—', MUTED_COLOR)
            else:
                _set(label, '정상' if ok else '끊김', OK_COLOR if ok else BAD_COLOR)

        conn(self.conn_rows['Robot 연결'], s.robot_connected)
        conn(self.conn_rows['RG2 연결'], s.gripper_connected)
        _set(self.conn_rows['ROS2 통신'], '정상' if linked else '끊김',
             OK_COLOR if linked else BAD_COLOR)

        if linked:
            label = State.LABELS.get(s.state, s.state)
            color = STATE_BADGE_COLORS.get(s.state, '')
        else:
            label, color = '통신 끊김', BAD_COLOR
        self.state_badge.setText(f'●  {label}')
        self.state_badge.setStyleSheet(f'background: {color};' if color else '')

        tool = s.tool
        _set(self.tool_state, '완료' if tool.configured else '미완료',
             OK_COLOR if tool.configured else WARN_COLOR)
        _set(self.tool_rows['Tool'], tool.name or '—')
        _set(self.tool_rows['Tool Weight'],
             f'{tool.weight_kg:.2f} kg' if tool.weight_kg > 0 else '—')
        _set(self.tool_rows['TCP'], tool.tcp or '—')
        _set(self.tool_rows['Force Zero'], '완료' if tool.force_zero_done else '미완료',
             OK_COLOR if tool.force_zero_done else WARN_COLOR)
        _set(self.tool_rows['현재 알람'], s.alarm or '없음', BAD_COLOR if s.alarm else '')

        c = s.criteria
        _set(self.point_rows['현재 위치'], s.current_point or '—')
        _set(self.point_rows['현재 단계'], s.current_step or '—')
        speed_known = s.speed_percent > 0      # 0 = 노드가 아직 속도를 모름
        _set(self.point_rows['속도 설정'], f'{s.speed_percent} %' if speed_known else '—')
        _set(self.point_rows['그리퍼 폭'], f'{s.gripper_width_mm:.1f} mm')
        _set(self.point_rows['현재 힘 값'], f'{s.force_n:.1f} N')
        over = c.max_displacement_mm > 0 and s.displacement_mm > c.max_displacement_mm
        _set(self.point_rows['현재 변위'],
             f'{s.displacement_mm:.1f} / {c.max_displacement_mm:.1f} mm',
             BAD_COLOR if over else '')
        judge_color = ''
        if s.judgement in RESULT_CODES:
            judge_color = RESULT_COLORS[itf.ResultCode.category(s.judgement)][0]
        _set(self.point_rows['현재 판정'], s.judgement or '—', judge_color)

        _set(self.criteria_rows['허용 변위'], f'≤ {c.max_displacement_mm:.1f} mm')
        _set(self.criteria_rows['Pull Force'], f'≥ {c.pull_force_n:.1f} N')
        _set(self.criteria_rows['Push / Pull 반복'], f'{c.repeat_count}회')
        _set(self.criteria_rows['Grip 폭'], f'{c.grip_width_mm:.1f} mm')

        _set(self.estop_state, '작동 중' if s.estop else '현재 해제',
             BAD_COLOR if s.estop else OK_COLOR)

        self._render_recipe()
        self._render_counts()

        self.progress_bar.setValue(max(0, min(100, s.progress_percent)))
        # 진행률 옆에는 '어디를 검사 중인가'(현재 단계)를 쓴다. current_point 는 모니터 노드에서는
        # TCP 좌표라서 여기에 맞지 않는다. 검사 중이 아닐 때는 상태만 쓴다.
        busy = s.state in (State.RUNNING, State.PAUSED, State.MOVING)
        where = f'{s.current_step} · ' if busy and s.current_step else ''
        self.progress_text.setText(
            f'{s.progress_percent}%   {where}{State.LABELS.get(s.state, s.state)}')

        if time.monotonic() >= self._speed_hold_until and not self.speed_slider.isSliderDown():
            if speed_known:
                self.speed_slider.blockSignals(True)
                self.speed_slider.setValue(s.speed_percent)
                self.speed_slider.blockSignals(False)
            self.speed_label.setText(f'{s.speed_percent}%' if speed_known else '—')

        self._refresh_controls()

    def _render_recipe(self):
        s = self._status
        items = [self.recipe_combo.itemText(i) for i in range(self.recipe_combo.count())]
        if items != list(s.available_recipes):
            keep = self.recipe_combo.currentText()
            self.recipe_combo.blockSignals(True)
            self.recipe_combo.clear()
            self.recipe_combo.addItems(s.available_recipes)
            if keep in s.available_recipes:
                self.recipe_combo.setCurrentText(keep)
            self.recipe_combo.blockSignals(False)
        # 검사 중에는 실제로 돌고 있는 Recipe 를 보여 준다.
        if s.state in MONITOR_STATES:
            # 모니터 모드: 콤보는 노드가 알려 준 선택을 그대로 따른다(아직 안 골랐으면 빈 칸).
            index = self.recipe_combo.findText(s.recipe_id) if s.recipe_id else -1
            self.recipe_combo.setCurrentIndex(index)
        elif s.state not in (State.IDLE, State.DONE) and s.recipe_id in s.available_recipes:
            self.recipe_combo.setCurrentText(s.recipe_id)
        self.recipe_version.setText(s.recipe_version)
        self.product_id.setText(s.product_id or '—')

        text, category = {
            itf.ProductResult.PASS: ('제품 판정  PASS', 'PASS'),
            itf.ProductResult.FAIL: ('제품 판정  FAIL', 'FAIL'),
            itf.ProductResult.INCOMPLETE: ('제품 판정  미검사 Point 있음', 'MISSING'),
        }.get(s.product_result, ('', ''))
        self.product_result.setText(text)
        self.product_result.setStyleSheet(chip_style(category) if text else '')

    def _render_counts(self):
        counts = {'PASS': 0, 'MISSING': 0, 'FAIL': 0}
        for r in self._results:
            counts[itf.ResultCode.category(r.result)] += 1
        total = self._status.total_points or len(self._results)
        self.chips['전체'].setText(f'전체 {total}')
        for category, n in counts.items():
            self.chips[category].setText(f'{category} {n}건')
        self.fail_btn.setText(f"FAIL 포인트 이동 ({counts['FAIL']})")
        self.missing_btn.setText(f"MISSING 포인트 이동 ({counts['MISSING']})")

    def _refresh_controls(self):
        s = self._status
        state = s.state if self._linked else None
        ready = state in (State.IDLE, State.DONE) and not s.estop
        categories = [itf.ResultCode.category(r.result) for r in self._results]

        self.start_btn.setEnabled(ready and bool(self.recipe_combo.currentText()))
        self.pause_btn.setEnabled(state in (State.RUNNING, State.MOVING))
        self.resume_btn.setEnabled(state == State.PAUSED)
        # 모니터 노드는 검사는 못 하지만 Home 이동은 받는다(로봇이 멈춰 있을 때만).
        self.home_btn.setEnabled(ready or (state == State.MONITOR and not s.estop))
        self.fail_btn.setEnabled(ready and 'FAIL' in categories)
        self.missing_btn.setEnabled(ready and 'MISSING' in categories)
        # 모니터 모드에서는 검사는 못 하지만 Recipe 내용을 보려고 고를 수는 있다(로봇이 멈춰 있을 때).
        self.recipe_combo.setEnabled(ready or (state == State.MONITOR and not s.estop))
        self.speed_slider.setEnabled(self._linked)
        self.estop_reset_btn.setVisible(self._linked and s.estop)
        # 비상정지 버튼은 어떤 상태에서도 비활성화하지 않는다.

        if not self._linked:
            hint = '검사 노드와 통신이 끊겨 이동 명령을 보낼 수 없습니다.'
        elif s.estop:
            hint = '비상정지 작동 중 - 해제 후 이동할 수 있습니다.'
        elif state in (State.MONITOR, State.MONITOR_MOVING):
            hint = '모니터 모드 - 로봇 값 표시, Home 이동, 속도 설정, STOP 만 동작합니다.'
        elif not ready:
            hint = '이동 명령은 대기 또는 검사 완료 상태에서만 가능합니다.'
        else:
            hint = '결과 행을 선택하면 그 Point 로, 아니면 해당 결과의 Point 를 차례로 이동합니다.'
        self.move_hint.setText(hint)

    def _fill_row(self, row: int, r: itf.PointResult):
        category = itf.ResultCode.category(r.result)
        fg, _chip, row_bg = RESULT_COLORS[category]
        cells = [r.stamp[11:19] if len(r.stamp) >= 19 else r.stamp,
                 r.point_id, r.cable_id or '—', r.cable_type or '—', r.result, '›']
        for col, text in enumerate(cells):
            item = QTableWidgetItem(text)
            item.setTextAlignment(Qt.AlignCenter)
            item.setBackground(QBrush(QColor(row_bg)))
            if col == COL_RESULT:
                item.setForeground(QBrush(QColor(fg)))
                font = item.font()
                font.setBold(True)
                item.setFont(font)
                item.setToolTip(r.reason)
            self.table.setItem(row, col, item)

    def _append_log(self, level: str, text: str, stamp: str = ''):
        clock = stamp[11:19] if len(stamp) >= 19 else datetime.now().strftime('%H:%M:%S')
        color = LOG_COLORS.get(level, LOG_COLORS['INFO'])
        self.log_view.appendHtml(
            f'<span style="color:{MUTED_COLOR}">{clock}</span> '
            f'<span style="color:{color}">[{html.escape(level)}] {html.escape(text)}</span>')

    # ------------------------------------------------------- 화면 -> ROS
    def _send(self, name: str, **args):
        self._bridge.send_command(name, **args)
        detail = f' {args}' if args else ''
        self._append_log('INFO', f'[HMI] 명령 전송: {name}{detail}')

    def _on_start(self):
        self._send(Cmd.START, recipe_id=self.recipe_combo.currentText())

    def _message_box(self, icon, title: str, text: str, buttons) -> QMessageBox:
        """
        이 화면의 모든 대화상자는 여기서 만든다.

        부모를 이 창으로 두어야 _load_ui 에서 덧붙인 대화상자 버튼 스타일(DIALOG_QSS)을 물려받는다.
        """
        return QMessageBox(icon, title, text, buttons, self)

    def _confirm(self, title: str, text: str) -> bool:
        """예/아니오 확인 창. 기본 선택은 '아니오'."""
        box = self._message_box(QMessageBox.Question, title, text,
                                QMessageBox.Yes | QMessageBox.No)
        box.setDefaultButton(QMessageBox.No)
        return box.exec_() == QMessageBox.Yes

    def _on_recipe_chosen(self, index: int):
        """모니터 모드에서 Recipe 를 고르면 노드에 알린다. 표시는 돌아온 status 로 바뀐다."""
        if self._status.state in MONITOR_STATES and index >= 0:
            self._send(Cmd.SELECT_RECIPE, recipe_id=self.recipe_combo.itemText(index))

    def _on_home(self):
        if self._confirm('Home 이동',
                         '로봇이 Home 위치로 이동합니다.\n이동 경로에 사람이나 장애물이 없습니까?'):
            self._send(Cmd.MOVE_HOME)

    def _on_estop_reset(self):
        if self._confirm('비상정지 해제',
                         '로봇 주변이 안전한지 확인했습니까?\n비상정지를 해제합니다.'):
            self._send(Cmd.ESTOP_RESET)

    def _on_move_to(self, category: str):
        """선택된 행이 해당 부류면 그 Point 로, 아니면 해당 Point 들을 차례로 돈다."""
        candidates = [r for r in self._results
                      if itf.ResultCode.category(r.result) == category]
        if not candidates:
            return
        row = self.table.currentRow()
        selected = self._results[row] if 0 <= row < len(self._results) else None
        if selected in candidates:
            target = selected
        else:
            target = candidates[self._move_cycle[category] % len(candidates)]
            self._move_cycle[category] += 1
        self._send(Cmd.MOVE_TO_POINT, point_id=target.point_id, reason=category)

    def _on_speed_changed(self, value: int):
        self._speed_hold_until = time.monotonic() + SPEED_HOLD_SEC
        self.speed_label.setText(f'{value}%')
        self._speed_timer.start()

    def _send_speed(self):
        self._speed_hold_until = time.monotonic() + SPEED_HOLD_SEC
        self._send(Cmd.SET_SPEED, percent=self.speed_slider.value())

    # ------------------------------------------------------------ 상세 팝업
    def _on_cell_clicked(self, row: int, col: int):
        if col == COL_DETAIL:
            self._open_detail(row)

    def _on_selection_changed(self):
        row = self.table.currentRow()
        if self._detail.isVisible() and 0 <= row < len(self._results):
            self._detail.show_result(self._results[row])

    def _open_detail(self, row: int):
        if 0 <= row < len(self._results):
            self._detail.show_result(self._results[row])
            self._detail.show()
            self._detail.raise_()
