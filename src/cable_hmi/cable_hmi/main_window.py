"""
케이블 체결 검사 HMI 메인 화면.

화면 배치와 스타일은 main_window.ui (Qt Designer) 에 있고, 이 파일은 동작만 담당한다.
원칙: HMI 는 검사 노드 상태의 '렌더러'다. 버튼을 눌러도 화면 상태를 스스로
바꾸지 않고 명령만 보낸 뒤, 돌아오는 status 로만 화면과 버튼 활성화를 갱신한다.
"""

from datetime import datetime
import html
import os
from pathlib import Path
import sys
import time
import uuid

from PyQt5 import uic
from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtGui import QBrush, QColor
from PyQt5.QtWidgets import (
    QComboBox, QHeaderView, QLabel, QMainWindow, QMessageBox, QPlainTextEdit, QProgressBar,
    QPushButton, QSlider, QTableWidget, QTableWidgetItem, QTabWidget, QWidget,
)

from . import inspection_recipe
from . import interface as itf
from . import result_db
from .detail_dialog import ResultDetailDialog
from .limit_gauge import LimitGauge
from .lookup_tab import LookupTab
from .style import (
    BAD_COLOR, chip_style, DIALOG_QSS, LOG_COLORS, MUTED_COLOR, OK_COLOR, RESULT_COLORS,
    WARN_COLOR,
)

# 그리퍼 폭 게이지의 눈금 끝(mm). 검사 폭(16~27 mm)이 잘 보이게 잡았다. 더 열리면 꽉 찬다.
GRIP_GAUGE_SCALE_MM = 30.0
DEFAULT_FORCE_SCALE_N = 20.0    # 힘 게이지 눈금 끝 - 검사 조건이 아직 없을 때(Point 사이)

# 없으면 실행을 거부하는 위젯. 나머지는 Designer 에서 지워도 HMI 가 뜬다.
REQUIRED_WIDGETS = ('estopBtn',)
UI_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'main_window.ui')

Cmd = itf.CommandName
State = itf.State

MONITOR_STATES = (State.MONITOR, State.MONITOR_MOVING)
RESULT_CODES = (itf.ResultCode.PASS, *itf.ResultCode.FAIL_CODES)
# '현재 검사 결과' 표의 열. 이름과 순서는 통합 조회 탭(lookup_tab.COLUMNS)의 용어에 맞춘다.
# 다만 '케이블' 열은 없다 - 판정 노드가 보내는 메시지(cable_interfaces/msg/InspectionResult)에
# cable_id 가 없기 때문이다. 통합 조회 탭은 레시피 DB 에서 읽으므로 그 열을 그대로 쓴다.
RESULT_HEADERS = ('검사 시간', 'Point', '종류', '결과', '상세')
COL_TIME, COL_POINT, COL_TYPE, COL_RESULT, COL_DETAIL = range(len(RESULT_HEADERS))
SPEED_HOLD_SEC = 1.0      # 슬라이더 조작 후 이 시간 동안은 status 값으로 덮어쓰지 않는다
SPEED_DEBOUNCE_MS = 300
PULL_HOLD_SEC = 3.0       # Pull 이 끝난 뒤 마지막 힘·변위를 보여 주는 시간. 그 뒤 실시간으로
DEFAULT_TOOL_WEIGHT_KG = 1.47   # TP 에 등록한 Tool 무게 (tool_weight_kg 파라미터가 없을 때)
RECIPE_SCAN_MS = 2000    # 레시피 폴더가 바뀌었는지 이 간격으로 본다(파일을 고치면 목록에 반영)

STATE_BADGE_COLORS = {
    State.RUNNING: '#1E8E5A', State.MOVING: '#1E8E5A', State.PAUSED: '#B7791F',
    State.PAUSE_REQUEST: '#B7791F',
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
        self._move_cycle = {'FAIL': 0}
        self._speed_hold_until = 0.0
        self._detail = ResultDetailDialog(self)
        self._popup = None            # 떠 있는 에러 팝업 (없으면 None)
        self._export_popup = None     # 떠 있는 '결과 파일 저장 완료' 알림
        # 검사 시퀀스(Main, hmi 모드)에 보낼 레시피. HMI 가 원본을 들고 있다(PR #9).
        self._local_recipes = {}      # recipe_id -> inspection_recipe.RecipeFile
        self._recipe_signature = None
        self._start_pending = None    # 응답을 기다리는 검사 시작 요청의 request_id
        self._pull_held = None        # 마지막 Pull 값 (_hold_pull)
        self._pull_live = False       # 지금 Pull 실시간 값이 들어오는 중인가
        self._pull_end_time = 0.0     # 마지막 Pull 이 끝난 시각 (monotonic)
        read = getattr(bridge, 'parameter', lambda _name: '')
        try:
            self._tool_weight_kg = float(read('tool_weight_kg') or DEFAULT_TOOL_WEIGHT_KG)
        except ValueError:
            self._tool_weight_kg = DEFAULT_TOOL_WEIGHT_KG

        self._missing_widgets = []
        self._load_ui()

        bridge.status_received.connect(self.on_status)
        bridge.result_received.connect(self.on_result)
        bridge.log_received.connect(self.on_log)
        if hasattr(bridge, 'start_answered'):       # 테스트용 대역 bridge 에는 없을 수 있다
            bridge.start_answered.connect(self.on_start_answer)

        self._watchdog = QTimer(self, interval=300)
        self._watchdog.timeout.connect(self._check_link)
        self._watchdog.start()

        self._speed_timer = QTimer(self, interval=SPEED_DEBOUNCE_MS, singleShot=True)
        self._speed_timer.timeout.connect(self._send_speed)

        self._recipe_timer = QTimer(self, interval=RECIPE_SCAN_MS)
        self._recipe_timer.timeout.connect(self._scan_recipes)
        self._recipe_timer.start()
        self._scan_recipes()

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

    def _gauge(self, name: str) -> LimitGauge:
        """
        .ui 의 게이지 자리(QProgressBar)를 기준선이 있는 게이지로 바꿔 끼운다.

        자리가 없으면(Designer 에서 지움) 숨겨진 게이지를 돌려준다 - 숫자만 보인다.
        """
        placeholder = self.findChild(QProgressBar, name)
        gauge = LimitGauge()
        gauge.setObjectName(name)
        layout = placeholder.parentWidget().layout() if placeholder is not None else None
        if layout is None:
            self._missing_widgets.append(name)
            gauge.setParent(self._attic)
            return gauge
        gauge.setToolTip(placeholder.toolTip())
        layout.replaceWidget(placeholder, gauge)
        placeholder.hide()              # 지워지기 전까지 제자리(왼쪽 위)에 그려지지 않게
        placeholder.deleteLater()
        return gauge

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
            'Tool': w('toolName'), 'Tool Weight': w('toolWeight'), 'TCP': w('toolTcp')}
        self.conn_rows = {
            'Robot 연결': w('connRobot'), 'ROS2 통신': w('connRos'),
            'RG2 연결': w('connGripper')}
        # '검사 정보' 칸: 제목에 Point · 현재 단계, 그 아래 합격 규칙 한 줄. 검사 조건은 따로 칸을
        # 두지 않고 게이지의 기준선으로 보여 준다(값과 기준을 한 막대에서 비교하게).
        self.point_title = w('pointPanelTitle')
        self.point_rule = w('pointRule')
        self.point_rows = {
            '속도 설정': w('pointSpeed'), '그리퍼 폭': w('pointGripper'),
            '현재 힘 값': w('pointForce'), '현재 변위': w('pointDisplacement'),
            '현재 판정': w('pointJudgement')}
        self.grip_gauge = self._gauge('gripGauge')
        self.force_gauge = self._gauge('forceGauge')
        self.disp_gauge = self._gauge('dispGauge')
        # '로봇 상태' 박스 (main_window.ui 의 extraPanel)
        self.extra_rows = {
            'Task좌표': w('extraRow1'), 'Joint 좌표': w('extraRow2'),
            '로봇 동작': w('extraRow3'), '서보 상태': w('extraRow5'),
            '현재 알람': w('extraRow4')}
        self.chips = {'전체': w('chipTotal'), 'PASS': w('chipPass'),
                      'FAIL': w('chipFail')}
        w('chipMissing').hide()
        self.state_badge = w('stateBadge')
        self.start_btn, self.pause_btn, self.resume_btn = (
            w('startBtn', QPushButton), w('pauseBtn', QPushButton), w('resumeBtn', QPushButton))
        self.estop_btn, self.estop_state, self.estop_reset_btn = (
            w('estopBtn', QPushButton), w('estopState'), w('estopResetBtn', QPushButton))
        self.home_btn, self.fail_btn, self.missing_btn = (
            w('homeBtn', QPushButton), w('failBtn', QPushButton), w('missingBtn', QPushButton))
        self.missing_btn.hide()
        self.move_hint = w('moveHint')
        self.recipe_combo = w('recipeCombo', QComboBox)
        # 콤보는 비어 있을 때 잡은 폭을 계속 쓴다. 목록이 채워지면 내용에 맞춰 다시 잡게 한다.
        self.recipe_combo.setSizeAdjustPolicy(QComboBox.AdjustToContents)
        self.product_id, self.product_result = w('productId'), w('productResult')
        self.table, self.log_view = w('resultTable', QTableWidget), w('logView', QPlainTextEdit)
        self.export_btn = w('exportBtn', QPushButton)
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
        # 검사 시퀀스(Main)는 STOP 만 받는다. ESTOP 을 보내면 '지원하지 않는 명령' 으로 버려져
        # 로봇이 멈추지 않는다 (2026-09-23 확인).
        self.estop_btn.clicked.connect(lambda: self._send(Cmd.STOP))
        self.estop_reset_btn.clicked.connect(self._on_estop_reset)
        self.home_btn.clicked.connect(self._on_home)
        self.fail_btn.clicked.connect(lambda: self._on_move_to('FAIL'))
        self.export_btn.clicked.connect(self._on_export)
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
        # 레시피는 검사 시작에 쓰는 것과 같은 폴더에서 읽는다.
        self.lookup_tab = LookupTab(read('recipe_db'), self._inspection_recipe_dir(), self)
        tabs.addTab(self.lookup_tab, '통합 조회')

    # ------------------------------------------------------- ROS -> 화면
    def on_status(self, status: itf.SystemStatus):
        """검사 노드 status 수신. 화면 갱신의 유일한 출발점."""
        # 상태 분리 계약에서는 로봇상태만 와도 이 함수가 불린다. 그것만으로는 Main 이 살아 있다고
        # 보지 않는다(문서 1장) - 작업상태가 최근에 왔을 때만 연결 시각을 갱신한다.
        if status.work_fresh:
            self._last_status_time = time.monotonic()
        self._status = status
        if not self._linked and status.work_fresh:
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

    # ------------------------------------------------------- 결과 파일 저장
    def _export_dir(self) -> Path:
        """결과 파일을 둘 곳: 레시피 DB 옆의 runs 폴더. 경로 인자가 없으면 ~/ros_ws/results/runs."""
        read = getattr(self._bridge, 'parameter', lambda _name: '')
        configured = str(read('recipe_db') or '')
        if configured:
            return Path(configured).expanduser().parent / 'runs'
        return Path('~/ros_ws/results/runs').expanduser()

    def _on_export(self):
        """
        지금 표에 있는 검사 결과만 새 파일 둘(.db + .csv)로 내보낸다. 누르면 먼저 확인 창이 뜬다.

        공용 DB 는 건드리지 않는다 - 늘 새 파일을 만들므로 저장 노드와 부딪히지 않고,
        자동 저장(result_recorder_node)은 그대로 돌아간다.
        """
        if not self._results:
            self._append_log('WARN', '[HMI] 저장할 검사 결과가 없습니다.')
            return
        count = len(self._results)
        run_id = self._status.run_id or self._results[0].run_id
        if not self._confirm_ok_cancel(
                '결과 파일 저장',
                f'이번 검사 결과 {count}건을 파일로 저장합니다.\n\n'
                f'저장 위치: {self._export_dir()}\n'
                f'파일 이름: run_{run_id}_<날짜_시각>.db / .csv\n\n'
                '공용 DB 는 바뀌지 않습니다.'):
            self._append_log('INFO', '[HMI] 결과 파일 저장 취소')
            return
        try:
            db_path, csv_path = result_db.export_run(
                self._export_dir(), self._results, self._status)
        except result_db.ResultDbError as e:
            self._append_log('ERROR', f'[HMI] 결과 파일 저장 실패 - {e}')
            self._show_popup('ERROR', f'결과 파일 저장 실패\n{e}')
            return
        self._append_log('INFO', f'[HMI] 결과 {count}건 저장: {db_path}')
        self._append_log('INFO', f'[HMI] 결과 {count}건 저장: {csv_path}')
        self.export_btn.setToolTip(f'마지막 저장: {db_path}')
        # 저장을 마쳤다는 알림은 비모달이다 - 창이 떠 있어도 STOP 을 누를 수 있다.
        box = self._message_box(
            QMessageBox.Information, '결과 파일 저장 완료',
            f'결과 {count}건을 저장했습니다.\n\n{db_path}\n{csv_path}', QMessageBox.Ok)
        box.button(QMessageBox.Ok).setText('확인')
        box.setModal(False)
        box.show()
        self._export_popup = box        # 참조를 남겨 둬야 창이 바로 닫히지 않는다

    def _hold_pull(self, s: itf.SystemStatus):
        """
        마지막 Pull 값을 붙잡아 둔다: {'point', 'force'(최대), 'disp'(마지막), 'criteria'} 또는 None.

        실시간 값이 들어오는 동안(Pull 중) 갱신하고, 값이 끊긴 뒤 PULL_HOLD_SEC 동안은 그대로
        돌려준다. 그 뒤에는 None (화면은 다시 실시간 값). 다음 Pull 이 오면 새로 시작한다.
        """
        live = s.force_n is not None or s.displacement_mm is not None
        if not live:
            if self._pull_live:              # 방금 Pull 이 끝났다 - 이때부터 PULL_HOLD_SEC 동안 보여 준다
                self._pull_live = False
                self._pull_end_time = time.monotonic()
                QTimer.singleShot(int(PULL_HOLD_SEC * 1000) + 50, self._render)
            if time.monotonic() - self._pull_end_time >= PULL_HOLD_SEC:
                return None                  # 보여 줄 시간이 지났다 - 다시 실시간 표시
            return self._pull_held
        hold = self._pull_held
        if not self._pull_live or hold is None or hold['point'] != s.current_point:
            hold = {'point': s.current_point, 'force': None, 'disp': None}
        self._pull_live = True
        if s.force_n is not None:
            hold['force'] = s.force_n if hold['force'] is None else max(hold['force'], s.force_n)
        if s.displacement_mm is not None:
            hold['disp'] = s.displacement_mm
        hold['criteria'] = s.criteria        # Pull 이 끝나면 Main 이 기준도 비울 수 있다
        self._pull_held = hold
        return hold

    def _ensure_run(self, run_id: int):
        """새 검사(run)가 시작되면 이전 결과를 비운다."""
        if run_id == self._run_id:
            return
        self._run_id = run_id
        self._pull_held, self._pull_live = None, False
        self._results.clear()
        self.table.setRowCount(0)
        self._move_cycle = {'FAIL': 0}
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
            # 상태 분리 계약의 로봇·RG2 값은 Main 과 따로 온다(끊기면 이미 False 로 만료돼 있다).
            if not linked and not s.split_contract:
                _set(label, '—', MUTED_COLOR)
            else:
                _set(label, '정상' if ok else '끊김', OK_COLOR if ok else BAD_COLOR)

        conn(self.conn_rows['Robot 연결'], s.robot_connected)
        conn(self.conn_rows['RG2 연결'], s.gripper_connected)
        _set(self.conn_rows['ROS2 통신'], '정상' if linked else '끊김',
             OK_COLOR if linked else BAD_COLOR)

        if linked:
            label = State.LABELS.get(s.state, s.state)
            if (s.state in (State.PAUSE_REQUEST, State.PAUSED)
                    and s.pause_reason == itf.PauseReason.COMM_LOST):
                label += ' · 통신 단절'        # 통신이 돌아와도 이어하기를 눌러야 재개된다
            color = STATE_BADGE_COLORS.get(s.state, '')
        else:
            label, color = '통신 끊김', BAD_COLOR
        self.state_badge.setText(f'●  {label}')
        self.state_badge.setStyleSheet(f'background: {color};' if color else '')

        tool = s.tool
        _set(self.tool_state, '완료' if tool.configured else '미완료',
             OK_COLOR if tool.configured else WARN_COLOR)
        _set(self.tool_rows['Tool'], tool.name or '—')
        # 검사 PC 는 무게를 보내지 않는다(상태 분리 계약). 보내 오면 그 값, 아니면 HMI 설정값
        # (tool_weight_kg - TP 에 등록한 Tool 무게, 표시용).
        weight = tool.weight_kg if tool.weight_kg > 0 else self._tool_weight_kg
        _set(self.tool_rows['Tool Weight'], f'{weight:.2f} kg' if weight > 0 else '—')
        _set(self.tool_rows['TCP'], tool.tcp or '—')

        c = s.criteria
        # 제목 = 어느 Point 의 무슨 단계인가. 검사 PC 가 보낸 단계 코드는 한글로 보인다(원래 코드는 툴팁).
        title = ' · '.join(t for t in (s.current_point, itf.Step.label(s.current_step)) if t)
        self.point_title.setText(title or '검사 진행')
        self.point_title.setToolTip(s.current_step)
        speed_known = s.speed_percent > 0      # 0 = 노드가 아직 속도를 모름
        _set(self.point_rows['속도 설정'], f'{s.speed_percent} %' if speed_known else '—')
        # None = 보내는 쪽이 모르는 값(조회 실패·만료·Pull 밖). 0.0 으로 그리지 않고 '—' 로 둔다.
        width = s.gripper_width_mm
        _set(self.point_rows['그리퍼 폭'], '—' if width is None else f'{width:.1f} mm')
        force, disp = s.force_n, s.displacement_mm
        # Pull 은 기준 힘에 닿으면 멈춰서 1초 남짓이면 끝난다. 끝나면 Main 이 값을 비우므로,
        # 마지막 Pull 값을 PULL_HOLD_SEC 동안 붙잡아 보여 준다(_hold_pull).
        held = self._hold_pull(s)
        tag, lim = '', c
        if held is not None and force is None and disp is None:
            force, disp, lim = held['force'], held['disp'], held['criteria']
            tag = ' (종료)'
        tip = (f"{held['point']} Pull 종료 값 - 최대 힘 / 마지막 변위.\n"
               f'{PULL_HOLD_SEC:g}초 뒤 실시간 값으로 돌아갑니다.' if tag else '')
        self.point_rows['현재 힘 값'].setToolTip(tip)
        self.point_rows['현재 변위'].setToolTip(tip)
        if force is not None:
            # Pull 을 멈출지 비교하는 힘. 합격 기준 힘(#06)이 실려 오면 '현재 / 기준' 으로.
            _set(self.point_rows['현재 힘 값'],
                 (f'{force:.1f} / {lim.required_pull_force_n:.1f} N'
                  if lim.required_pull_force_n > 0 else f'{force:.1f} N') + tag)
        elif s.raw_force_n is not None:
            # Pull 밖: 센서 원시 힘만 있다. 기준 힘과 비교할 값이 아니므로 기준을 붙이지 않는다.
            _set(self.point_rows['현재 힘 값'], f'{s.raw_force_n:.1f} N (센서)', MUTED_COLOR)
        else:
            _set(self.point_rows['현재 힘 값'], '—')
        over = disp is not None and lim.max_displacement_mm > 0 and disp > lim.max_displacement_mm
        if disp is None:
            _set(self.point_rows['현재 변위'], '—')
        else:
            _set(self.point_rows['현재 변위'],
                 (f'{disp:.1f} / {lim.max_displacement_mm:.1f} mm' if lim.max_displacement_mm > 0
                  else f'{disp:.1f} mm') + tag,
                 BAD_COLOR if over else '')
        self._render_limits(lim, force, disp, over, width, s.raw_force_n)
        judge_color = ''
        if s.judgement in RESULT_CODES:
            judge_color = RESULT_COLORS[itf.ResultCode.category(s.judgement)][0]
        _set(self.point_rows['현재 판정'], s.judgement or '—', judge_color)

        # 현재 TCP 좌표와 로봇 동작 상태. 보내는 쪽이 채우지 않으면 '—' 로 남는다.
        task, joint = s.task or [], s.joint or []
        # 칸이 좁아 X·Y·Z 를 한 줄에 넣으려고 mm 단위 정수로 줄였다. 소수점과 자세(A·B·C)는
        # 마우스를 올리면 툴팁으로 보인다.
        if len(task) >= 3:
            _set(self.extra_rows['Task좌표'],
                 f'X {task[0]:.0f}  Y {task[1]:.0f}  Z {task[2]:.0f}')
            tip = f'X {task[0]:.1f}   Y {task[1]:.1f}   Z {task[2]:.1f}  [mm]'
            if len(task) >= 6:
                tip += f'\nA {task[3]:.1f}   B {task[4]:.1f}   C {task[5]:.1f}  [deg]'
        else:
            _set(self.extra_rows['Task좌표'], '—')
            tip = ''
        self.extra_rows['Task좌표'].setToolTip(tip)
        if len(joint) >= 6:
            pairs = [f'J{i + 1} {joint[i]:.1f}' for i in range(6)]
            joint_text = '\n'.join('   '.join(pairs[i:i + 2]) for i in (0, 2, 4))
        else:
            joint_text = '—'
        _set(self.extra_rows['Joint 좌표'], joint_text)
        motion = s.robot_motion
        if motion == itf.RobotMotion.MOVING:
            motion_color = OK_COLOR
        elif motion in ('', itf.RobotMotion.STANDBY):
            motion_color = ''
        else:
            motion_color = WARN_COLOR       # 서보 OFF, 보호정지, 비상정지 ...
        _set(self.extra_rows['로봇 동작'],
             itf.RobotMotion.label(motion) or motion or '—', motion_color)
        # 서보는 조회 서비스가 없어 제어기 상태에서 끌어낸 값이다 (interface.Servo 참고).
        servo = s.servo
        _set(self.extra_rows['서보 상태'], itf.Servo.LABELS.get(servo, '—'),
             OK_COLOR if servo == itf.Servo.ON else (BAD_COLOR if servo == itf.Servo.OFF else ''))
        _set(self.extra_rows['현재 알람'], s.alarm or '없음', BAD_COLOR if s.alarm else '')
        # 알람 문구는 길 수 있다. 칸에서 잘려도 마우스를 올리면 전체를 볼 수 있게 한다.
        self.extra_rows['현재 알람'].setToolTip(s.alarm)

        stopped = s.estop or s.state == State.STOPPED
        _set(self.estop_state, '정지됨' if stopped else '정상',
             BAD_COLOR if stopped else OK_COLOR)

        self._render_recipe()
        self._render_counts()

        self.progress_bar.setValue(max(0, min(100, s.progress_percent)))
        # 진행률 옆에는 '어디를 검사 중인가'(현재 단계)를 쓴다. current_point 는 모니터 노드에서는
        # TCP 좌표라서 여기에 맞지 않는다. 검사 중이 아닐 때는 상태만 쓴다.
        busy = s.state in (State.RUNNING, State.PAUSE_REQUEST, State.PAUSED, State.MOVING)
        where = f'{itf.Step.label(s.current_step)} · ' if busy and s.current_step else ''
        # 판정은 로봇 이동과 비동기다(#06). 남은 판정이 있으면 Job 이 아직 끝나지 않은 이유가 된다.
        pending = f'   판정 대기 {s.pending_judgments}건' if s.pending_judgments else ''
        self.progress_text.setText(
            f'{s.progress_percent}%   {where}{State.LABELS.get(s.state, s.state)}{pending}')

        if time.monotonic() >= self._speed_hold_until and not self.speed_slider.isSliderDown():
            if speed_known:
                self.speed_slider.blockSignals(True)
                self.speed_slider.setValue(s.speed_percent)
                self.speed_slider.blockSignals(False)
            self.speed_label.setText(f'{s.speed_percent}%' if speed_known else '—')

        self._refresh_controls()

    def _start_by_service(self) -> bool:
        """검사 PC 가 hmi 모드 Main 인가. 그렇다면 레시피는 HMI 가 고르고 검사 시작 서비스로 보낸다."""
        return self._status.control_mode == itf.ControlMode.HMI

    def _render_recipe(self):
        s = self._status
        # hmi 모드 Main 은 레시피 목록을 보내지 않는다(빈 목록). HMI 가 읽은 목록을 쓴다.
        names = list(self._local_recipes if self._start_by_service() else s.available_recipes)
        items = [self.recipe_combo.itemText(i) for i in range(self.recipe_combo.count())]
        if items != names:
            keep = self.recipe_combo.currentText()
            self.recipe_combo.blockSignals(True)
            self.recipe_combo.clear()
            self.recipe_combo.addItems(names)
            if keep in names:
                self.recipe_combo.setCurrentText(keep)
            self.recipe_combo.blockSignals(False)
        # 이름이 길면 칸에서 잘린다. 전체 이름은 마우스를 올리면 보인다.
        self.recipe_combo.setToolTip(self.recipe_combo.currentText())
        # 검사 중에는 실제로 돌고 있는 Recipe 를 보여 준다.
        if s.state in MONITOR_STATES:
            # 모니터 모드: 콤보는 노드가 알려 준 선택을 그대로 따른다(아직 안 골랐으면 빈 칸).
            index = self.recipe_combo.findText(s.recipe_id) if s.recipe_id else -1
            self.recipe_combo.setCurrentIndex(index)
        elif s.state not in (State.IDLE, State.DONE) and s.recipe_id in names:
            self.recipe_combo.setCurrentText(s.recipe_id)
        self.product_id.setText(s.product_id or '—')

        text, category = {
            itf.ProductResult.PASS: ('제품 판정  PASS', 'PASS'),
            itf.ProductResult.FAIL: ('제품 판정  FAIL', 'FAIL'),
            itf.ProductResult.INCOMPLETE: ('제품 판정  미검사 Point 있음', 'INCOMPLETE'),
        }.get(s.product_result, ('', ''))
        if s.end_reason == itf.EndReason.NOT_COMPLETE:
            # #07 Work Finish 가 Job 종료를 승인하지 않았다. 검사 결과와는 다른 이야기다.
            text, category = '작업 종료 보류', 'INCOMPLETE'
        self.product_result.setText(text)
        self.product_result.setStyleSheet(chip_style(category) if text else '')

    def _render_limits(self, c: itf.Criteria, force, disp, over: bool, width, raw_force):
        """
        합격 규칙 한 줄과 세 게이지(그리퍼 폭 / 힘 / 변위)를 그린다. 기준은 게이지 위 세로선이다.

        기준 0 = 실려 오지 않음(Point 사이, 대기 중). 그때는 선을 긋지 않는다. 값이 None 이어도
        기준선은 그려 두어, 당기기 전에도 목표가 어디인지 보이게 한다.
        force 가 None(Pull 밖)이면 힘 게이지는 센서 원시 힘(raw_force)을 회색으로 실시간 보여 준다.
        """
        required, limit, reach = (c.required_pull_force_n, c.max_displacement_mm,
                                  c.pull_max_distance_mm)
        if required > 0 and limit > 0:
            self.point_rule.setText(f'PASS = {limit:g} mm 안에서 {required:g} N 도달')
        else:
            self.point_rule.setText('검사 조건 —')
        self.point_rule.setToolTip(
            '기준 힘에 닿으면 당기기를 멈춘다. 그때까지 변위가 허용 변위 이하면 PASS.\n'
            f'최대 거리({reach:g} mm)까지 당겨도 기준 힘에 못 닿으면 FAIL. '
            f'당기는 중 그리퍼 폭이 {itf.GRIP_FAILURE_WIDTH_MM:g} mm 미만이면 파지 실패(FAIL).')

        # 힘: 기준에 '도달해야' 좋다. 눈금은 기준의 4/3 (15 N 이면 20 N) - 넘어선 만큼도 보이게.
        # 기준이 아직 없으면(Point 사이) 센서 힘을 볼 수 있게 20 N 눈금을 쓴다.
        scale = required * 4 / 3 if required > 0 else DEFAULT_FORCE_SCALE_N
        if force is not None:           # Pull 중(또는 끝난 뒤 유지): 기준과 비교하는 힘
            value, color = force, OK_COLOR if force >= required else BAD_COLOR
        else:                           # Pull 밖: 센서 원시 힘. 기준과 비교할 값이 아니라 회색
            value, color = raw_force, MUTED_COLOR
        self.force_gauge.set_state(value, scale, color, [(required, f'목표 {required:g}')],
                                   f'{scale:g} N')
        # 변위: 허용 변위를 '넘지 않아야' 좋다. 눈금 끝은 최대 거리 - 최대 거리 FAIL 도 보인다.
        scale = reach if reach > limit else limit * 2
        self.disp_gauge.set_state(
            disp, scale, BAD_COLOR if over else OK_COLOR,
            [(limit, f'허용 {limit:g}')], f'최대 {scale:g} mm' if scale > 0 else '')
        # 그리퍼 폭: 파지 실패 기준(16 mm)보다 좁으면 빨강, 아니면 초록. 판정은 당기는 중에만
        # 적용되지만, 작업자가 늘 기준과 비교해 볼 수 있게 색은 항상 칠한다.
        failed = width is not None and width < itf.GRIP_FAILURE_WIDTH_MM
        color = BAD_COLOR if failed else OK_COLOR
        marks = [(itf.GRIP_FAILURE_WIDTH_MM, f'실패 {itf.GRIP_FAILURE_WIDTH_MM:g}')]
        if c.grip_width_mm > 0:
            marks.append((c.grip_width_mm, f'지시 {c.grip_width_mm:g}'))
        self.grip_gauge.set_state(width, GRIP_GAUGE_SCALE_MM, color, marks,
                                  f'{GRIP_GAUGE_SCALE_MM:g} mm')

    def _render_counts(self):
        # INCOMPLETE(판정 미완)는 제품 결과가 아니므로 칩에 세지 않는다. 전체 수에는 들어간다.
        counts = {'PASS': 0, 'FAIL': 0, 'INCOMPLETE': 0}
        for r in self._results:
            counts[itf.ResultCode.category(r.result)] += 1
        incomplete = counts.pop('INCOMPLETE')
        total = self._status.total_points or len(self._results)
        self.chips['전체'].setText(
            f'전체 {total} · 판정 미완 {incomplete}' if incomplete else f'전체 {total}')
        for category, n in counts.items():
            self.chips[category].setText(f'{category} {n}건')
        self.fail_btn.setText(f"FAIL 포인트 이동 ({counts['FAIL']})")

    def _refresh_controls(self):
        s = self._status
        state = s.state if self._linked else None
        # 문서의 SYSTEM_READY = IDLE / DONE 이다. STOPPED 와 ERROR 는 START 를 받지 못하고
        # Home 이동으로만 복구된다 (STOP/ERROR 뒤 자동 Home Return 없음).
        # 검사 시퀀스(Main)가 status 를 보내면 Main 이 받는 명령만 누를 수 있게 한다.
        # terminal 모드의 Main 은 HMI 명령을 전부 버리므로 조작 버튼을 모두 막는다.
        main_seq = itf.ControlMode.is_main(s.control_mode)
        terminal = s.control_mode == itf.ControlMode.TERMINAL
        ready = state in (State.IDLE, State.DONE) and not s.estop and not terminal
        recoverable = (state in (State.STOPPED, State.ERROR, State.MONITOR)
                       and not s.estop and not terminal)
        categories = [itf.ResultCode.category(r.result) for r in self._results]

        # 시작 요청의 응답을 기다리는 동안은 다시 누를 수 없다(같은 검사를 두 번 보내지 않게).
        self.start_btn.setEnabled(ready and bool(self.recipe_combo.currentText())
                                  and self._start_pending is None)
        self.pause_btn.setEnabled(state in (State.RUNNING, State.MOVING) and not terminal)
        self.resume_btn.setEnabled(state == State.PAUSED and not terminal)
        # 모니터 노드는 검사는 못 하지만 Home 이동은 받는다(로봇이 멈춰 있을 때만).
        # 오류(ERROR) 뒤에는 자동 Home Return 이 없으므로 사용자가 Home 이동으로 복구한다.
        self.home_btn.setEnabled(ready or recoverable)
        # 결과 파일 저장은 상태와 무관하다: 검사 중에도, 중단된 뒤에도 표에 있는 것을 저장할 수 있다.
        self.export_btn.setEnabled(bool(self._results))
        self.fail_btn.setEnabled(ready and 'FAIL' in categories and not main_seq)  # MOVE_TO_POINT
        # 모니터 모드에서는 검사는 못 하지만 Recipe 내용을 보려고 고를 수는 있다(로봇이 멈춰 있을 때).
        self.recipe_combo.setEnabled(ready or (state == State.MONITOR and not s.estop))
        self.speed_slider.setEnabled(self._linked and not main_seq)               # SET_SPEED
        self.estop_reset_btn.setVisible(self._linked and s.estop and not main_seq)  # ESTOP_RESET
        # 비상정지 버튼은 어떤 상태에서도 비활성화하지 않는다.

        if not self._linked:
            hint = '검사 노드와 통신이 끊겨 이동 명령을 보낼 수 없습니다.'
        elif terminal:
            hint = '검사 PC 가 터미널 모드 - HMI 명령을 받지 않습니다.'
        elif main_seq and state in (State.IDLE, State.DONE):
            hint = '검사 시퀀스는 Home 이동만 지원합니다.'
        elif s.estop:
            hint = '비상정지 작동 중 - 해제 후 이동할 수 있습니다.'
        elif state in (State.MONITOR, State.MONITOR_MOVING):
            hint = '모니터 모드 - 로봇 값 표시, Home 이동, 속도 설정, STOP 만 동작합니다.'
        elif state in (State.STOPPED, State.ERROR):
            label = State.LABELS.get(state, state)
            hint = f'{label} · Home 이동 후 다시 시작하세요.'
        elif not ready:
            hint = '대기 · 검사 완료 상태에서만 이동합니다.'
        else:
            hint = '결과 행을 고르면 그 Point 로 이동합니다.'
        # 좁은 사이드바에서 두 줄을 넘지 않게 줄인 문구다. 자세한 설명은 마우스를 올리면 나온다.
        self.move_hint.setText(hint)
        self.move_hint.setToolTip(
            '결과 행을 선택하면 그 Point 로, 선택하지 않으면 해당 결과의 Point 를 '
            '차례로 이동합니다. 대기 또는 검사 완료 상태에서만 가능합니다.')

    def _fill_row(self, row: int, r: itf.PointResult):
        category = itf.ResultCode.category(r.result)
        fg, _chip, row_bg = RESULT_COLORS[category]
        cells = [r.stamp[11:19] if len(r.stamp) >= 19 else r.stamp,
                 r.point_id, r.cable_type or '—', r.result, '›']
        for col, text in enumerate(cells):
            item = QTableWidgetItem(text)
            item.setTextAlignment(Qt.AlignCenter)
            item.setBackground(QBrush(QColor(row_bg)))
            if col == COL_RESULT:
                item.setForeground(QBrush(QColor(fg)))
                font = item.font()
                font.setBold(True)
                item.setFont(font)
                # 결과 칸은 PASS / FAIL 만. 상세 원인(#06 reason_code)은 툴팁과 상세 팝업에
                status = itf.JudgmentStatus.LABELS.get(r.judgment_status, '')
                term = itf.TerminationReason.label(r.termination_reason)
                item.setToolTip('\n'.join(t for t in (r.reason_code, status, term, r.reason) if t))
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
        if not self._start_by_service():
            self._send(Cmd.START, recipe_id=self.recipe_combo.currentText())   # mock·모니터 노드
            return
        # hmi 모드 Main: 고른 레시피 전체를 검사 시작 서비스로 보낸다. 누를 때 파일을 다시 읽어
        # 지금 파일 내용이 그대로 가게 한다.
        recipe_id = self.recipe_combo.currentText()
        info = self._local_recipes.get(recipe_id)
        try:
            if info is None:
                raise ValueError('목록에 없는 레시피입니다')
            info = inspection_recipe.load(info.path)
            if info.recipe_id != recipe_id:
                raise ValueError(f'파일의 recipe_id 가 {info.recipe_id} 로 바뀌었습니다')
            if not info.enabled_count:
                raise ValueError('활성(enabled) 검사포인트가 없습니다')
            recipe = inspection_recipe.to_message(info.data)
        except ValueError as e:
            text = f'[HMI] 레시피 {recipe_id} 를 보낼 수 없습니다: {e}'
            self._append_log('ERROR', text)
            self._show_popup('ERROR', text)
            return
        request_id = uuid.uuid4().hex
        if not self._bridge.request_start(request_id, recipe):
            text = f'[HMI] 검사 시작 서비스(/{itf.SERVICE_START})가 보이지 않습니다. 검사 PC 를 확인하세요.'
            self._append_log('WARN', text)
            self._show_popup('WARN', text)
            return
        self._start_pending = request_id
        self._append_log('INFO', f'[HMI] 검사 시작 요청: {info.recipe_id} v{info.recipe_version} '
                                 f'(Point {info.enabled_count}/{info.point_count}개)')
        QTimer.singleShot(int(itf.START_TIMEOUT_SEC * 1000),
                          lambda: self._on_start_timeout(request_id))
        self._refresh_controls()

    def _on_start_timeout(self, request_id: str):
        """응답이 늦으면 경고만 한다. 다시 보내지 않는다 - 이미 접수됐을 수 있기 때문이다."""
        if self._start_pending != request_id:
            return
        self._start_pending = None
        text = (f'[HMI] 검사 시작 응답이 {itf.START_TIMEOUT_SEC:g}초 동안 없습니다. 자동으로 다시 '
                '보내지 않습니다. 작업 상태를 확인한 뒤 필요하면 다시 누르세요.')
        self._append_log('WARN', text)
        self._show_popup('WARN', text)
        self._refresh_controls()

    def on_start_answer(self, answer: itf.StartAnswer):
        """검사 시작 서비스 응답. 접수는 시작일 뿐 - 진행과 결과는 work_status 로 본다."""
        late = self._start_pending != answer.request_id
        if not late:
            self._start_pending = None
        suffix = ' (늦게 도착한 응답)' if late else ''
        if answer.error:
            text = f'[HMI] 검사 시작 요청 실패{suffix}: {answer.error}'
            self._append_log('ERROR', text)
            self._show_popup('ERROR', text)
        elif answer.accepted:
            self._append_log('INFO', f'[HMI] 검사 시작 {itf.StartCode.label(answer.code)}{suffix} '
                                     f'- run {answer.run_id}')
        else:
            text = (f'[HMI] 검사 시작 거절{suffix}: {itf.StartCode.label(answer.code)} '
                    f'({answer.code})\n{answer.message}')
            self._append_log('WARN', text.replace('\n', ' - '))
            self._show_popup('WARN', text)
        self._refresh_controls()

    def _inspection_recipe_dir(self) -> str:
        read = getattr(self._bridge, 'parameter', lambda _name: '')
        return str(read('inspection_recipe_dir') or itf.DEFAULT_INSPECTION_RECIPE_DIR)

    def _scan_recipes(self):
        """레시피 폴더가 바뀌었으면 다시 읽는다. 읽지 못한 파일은 이유를 로그에 남긴다."""
        folder = self._inspection_recipe_dir()
        signature = inspection_recipe.signature(folder)
        if signature == self._recipe_signature:
            return
        self._recipe_signature = signature
        self._local_recipes, problems = inspection_recipe.scan(folder)
        names = ', '.join(self._local_recipes) or '없음'
        self._append_log('INFO', f'[HMI] 검사 레시피 {len(self._local_recipes)}개: {names}')
        for problem in problems:
            self._append_log('WARN', f'[HMI] 검사 레시피 건너뜀 - {problem}')
        self._render_recipe()
        self._refresh_controls()

    def _message_box(self, icon, title: str, text: str, buttons) -> QMessageBox:
        """
        이 화면의 모든 대화상자는 여기서 만든다.

        부모를 이 창으로 두어야 _load_ui 에서 덧붙인 대화상자 버튼 스타일(DIALOG_QSS)을 물려받는다.
        """
        return QMessageBox(icon, title, text, buttons, self)

    def _confirm_ok_cancel(self, title: str, text: str) -> bool:
        """
        확인/취소 창. 기본 선택은 '확인'.

        로봇을 움직이지 않는 동작(파일 저장 등)에 쓴다. 로봇이 움직이는 동작은 _confirm 을 쓴다
        (기본 선택이 '아니오' 라서 엔터를 잘못 눌러도 움직이지 않는다).
        """
        box = self._message_box(QMessageBox.Question, title, text,
                                QMessageBox.Ok | QMessageBox.Cancel)
        box.button(QMessageBox.Ok).setText('확인')
        box.button(QMessageBox.Cancel).setText('취소')
        box.setDefaultButton(QMessageBox.Ok)
        return box.exec_() == QMessageBox.Ok

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
