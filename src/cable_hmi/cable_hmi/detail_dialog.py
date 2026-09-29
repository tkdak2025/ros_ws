"""
상세 팝업 두 가지. 선택한 행에 따라 내용이 바뀐다.

  ResultDetailDialog   '현재 검사 결과' 표의 결과 1건       배치: result_detail_dialog.ui
  LookupDetailDialog   '통합 조회' 표의 레시피 포인트 1개   배치: lookup_detail_dialog.ui

두 창은 같은 구성이다. 작업자가 위에서부터 '무엇 → 왜 → 근거' 순서로 읽게 했다.

  머리      Point · 이름 / 레시피 · 종류 · 검사 시간 / 결과 배지
  한 줄 이유 whyLabel - 판정을 한 문장으로 (예: '11.1 N 으로 15 N 에 못 미친 채 25 mm 까지 당겨짐')
  판정 근거  힘 / 변위 / Pull 최소 폭 3줄: 측정 · 기준 · 결과 + 기준선 게이지
  세부 정보  코드 원문, 좌표 등. 접혀 있고 '세부 정보 ▸' 를 누르면 펼친다. 값이 없는 줄은 숨긴다.
  아래 줄    DB 저장 여부 / 자료 출처

배치·글자·색은 .ui 에 있다 (Qt Designer 로 편집). 이 파일이 의존하는 것은 objectName 뿐이다.
Designer 에서 지우거나 이름을 바꾸면 그 항목만 창에서 빠지고 창은 그대로 뜨며, 빠진 이름은
터미널에 경고로 나온다. 게이지 자리의 QProgressBar 는 실행할 때 LimitGauge 로 바꿔 끼운다.
"""

from pathlib import Path
import sys
from typing import Optional, Tuple

from PyQt5 import uic
from PyQt5.QtWidgets import QDialog, QLabel, QProgressBar, QPushButton, QSizePolicy, QWidget

from . import interface as itf
from .limit_gauge import LimitGauge
from .style import BAD_COLOR, chip_style, MUTED_COLOR, OK_COLOR, RESULT_COLORS

UI_DIR = Path(__file__).parent

GRIP_GAUGE_SCALE_MM = 30.0      # main_window 의 그리퍼 폭 게이지와 같은 눈금
NEUTRAL_COLORS = ('#2B3440', '#EEF1F5')     # 한 줄 이유 칸: 결과가 없을 때 (글자, 바탕)

# 세부 정보 줄 (objectName 앞부분). 값이 비면 줄째로 숨긴다.
DETAIL_KEYS = ('resultCode', 'reasonCode', 'judgmentStatus', 'termination', 'reason',
               'softWidth', 'widthDelta', 'gripWidth', 'maxDistance', 'task', 'joint',
               'product', 'forceId')


# ---------------------------------------------------------------------------------------------
# 글자 만들기 (Qt 없이 시험할 수 있게 함수로 둔다)
# ---------------------------------------------------------------------------------------------

def _measured(result: Optional[itf.PointResult]) -> bool:
    """측정값이 있는 결과인가. 동작 오류 등으로 힘·변위가 모두 0 이면 측정 못 한 것이다."""
    return result is not None and not (result.max_force_n == 0.0 and result.displacement_mm == 0.0)


def why_text(result: Optional[itf.PointResult]) -> str:
    """판정을 작업자 말로 한 문장. result 가 None 이면 검사 이력이 없는 것이다."""
    if result is None:
        return '아직 저장된 검사 결과가 없습니다.'
    code = result.reason_code
    force, disp = result.max_force_n, result.displacement_mm
    required, limit = result.required_pull_force_n, result.displacement_limit_mm
    if code == itf.ReasonCode.PASS_FORCE_DISPLACEMENT_OK:
        return (f'{disp:.1f} mm 안에서 {force:.1f} N 도달 — '
                f'기준 {required:g} N · 허용 {limit:g} mm 모두 만족, 체결 정상')
    if code == itf.ReasonCode.FAIL_MAX_DISTANCE:
        return (f'{force:.1f} N으로 기준 {required:g} N에 못 미친 채 '
                f'최대 거리 {disp:.0f} mm까지 당겨짐 — 체결 불량 의심')
    if code == itf.ReasonCode.FAIL_DISPLACEMENT_LIMIT:
        return (f'변위 {disp:.1f} mm로 허용 {limit:g} mm를 넘음 '
                f'(최대 힘 {force:.1f} N) — 커넥터 밀림 의심')
    if code in (itf.ReasonCode.FAIL_GRIP_WIDTH, itf.ReasonCode.FAIL_GRIP_SLIP):
        failure = result.grip_failure_width_mm or itf.GRIP_FAILURE_WIDTH_MM
        return (f'당기는 중 그리퍼 폭이 {result.pull_width_mm:.1f} mm로 기준 {failure:g} mm 미만 — '
                '파지 폭 기준 미달로 FAIL')
    # SYSTEM_ERROR 와 옛 코드: 판정 노드가 적은 문장이 가장 정확하다.
    label = itf.ReasonCode.LABELS.get(code, '')
    detail = result.reason or label or itf.TerminationReason.label(result.termination_reason)
    return f'판정을 만들지 못함 — {detail}' if detail else '판정을 만들지 못함'


def _pose_text(values, names, units) -> str:
    """좌표 6개를 'X 1.0  Y 2.0 ...' 로. units = (앞 3개 단위, 뒤 3개 단위). 없으면 ''."""
    if len(values) != 6:
        return ''
    parts = [f'{name} {value:.2f}' for name, value in zip(names, values)]
    if units[0] == units[1]:
        return f'{"   ".join(parts)}  {units[0]}'
    return f'{"   ".join(parts[:3])}  {units[0]}\n{"   ".join(parts[3:])}  {units[1]}'


def _coded(code: str, label: str) -> str:
    return f'{label} ({code})' if label and code else code or ''


# ---------------------------------------------------------------------------------------------
# 대화상자
# ---------------------------------------------------------------------------------------------

class _DetailDialog(QDialog):
    """.ui 를 읽어 만드는 비모달 상세 창. 두 창이 같이 쓰는 머리 · 근거 · 세부 정보 채우기."""

    UI_FILE = ''

    def __init__(self, parent=None):
        super().__init__(parent)
        uic.loadUi(str(UI_DIR / self.UI_FILE), self)
        # 모달이면 떠 있는 동안 STOP 을 누를 수 없다. Designer 에서 modal 을 켜도 여기서 끈다.
        self.setModal(False)
        self._attic = QWidget(self)
        self._attic.hide()
        self.missing_widgets = []

        w = self._label
        self._head_title, self._head_sub, self._badge = w('headTitle'), w('headSub'), w('badge')
        self._why = w('whyLabel')
        # 창이 필요보다 클 때 남는 높이가 제목 띠로 가지 않게 제목은 높이를 고정한다.
        title = w('titleLabel')
        title.setSizePolicy(title.sizePolicy().horizontalPolicy(), QSizePolicy.Fixed)
        # 배지는 머리 두 줄 높이로 늘어나지 않고 가운데에 칩 크기로 선다.
        self._badge.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        self._basis = {key: {part: w(f'{key}{part}') for part in ('Value', 'Limit', 'Verdict')}
                       for key in ('force', 'disp', 'width')}
        self._gauges = {key: self._gauge(f'{key}Gauge') for key in ('force', 'disp', 'width')}
        self._details = {key: (w(f'{key}Key'), w(f'{key}Value')) for key in DETAIL_KEYS}
        self._details_panel = self.findChild(QWidget, 'detailsPanel') or QWidget(self._attic)
        self._details_btn = self.findChild(QPushButton, 'detailsBtn')
        if self._details_btn is None:
            self.missing_widgets.append('detailsBtn')
            self._details_btn = QPushButton(self._attic)
            self._details_btn.setCheckable(True)
        self._details_btn.toggled.connect(self._toggle_details)
        self._toggle_details(self._details_btn.isChecked())
        self._load()

        if self.missing_widgets:
            print(f'[cable_hmi] {self.UI_FILE} 에 없는 위젯: {", ".join(self.missing_widgets)}',
                  file=sys.stderr)

    def _load(self):
        """창마다 더 찾을 위젯."""

    def _label(self, name: str) -> QLabel:
        """라벨을 objectName 으로 찾는다. Designer 에서 지워졌으면 숨겨진 대역을 돌려준다."""
        found = self.findChild(QLabel, name)
        if found is not None:
            return found
        self.missing_widgets.append(name)
        return QLabel(self._attic)

    def _gauge(self, name: str) -> LimitGauge:
        """.ui 의 게이지 자리(QProgressBar)를 LimitGauge 로 바꿔 끼운다. 자리가 없으면 숨긴다."""
        placeholder = self.findChild(QProgressBar, name)
        gauge = LimitGauge()
        gauge.setObjectName(name)
        layout = placeholder.parentWidget().layout() if placeholder is not None else None
        if layout is None:
            self.missing_widgets.append(name)
            gauge.setParent(self._attic)
            return gauge
        gauge.setToolTip(placeholder.toolTip())
        layout.replaceWidget(placeholder, gauge)
        placeholder.hide()
        placeholder.deleteLater()
        return gauge

    def _toggle_details(self, shown: bool):
        self._details_panel.setVisible(shown)
        self._details_btn.setText('세부 정보 ▾' if shown else '세부 정보 ▸')
        self._fit_height()

    def _fit_height(self):
        """내용에 맞게 높이를 줄이거나 늘린다(너비는 사용자가 늘린 대로 둔다)."""
        layout = self.layout()
        if layout is None:
            return
        layout.activate()
        # 줄바꿈 라벨이 있어 높이는 '지금 너비에서' 필요한 만큼으로 잰다. sizeHint 로 재면
        # 더 좁은 너비 기준이라 남는 높이가 제목 띠로 몰린다.
        height = (layout.totalHeightForWidth(self.width()) if layout.hasHeightForWidth()
                  else self.sizeHint().height())
        self.resize(self.width(), max(height, layout.totalMinimumSize().height()))

    # --- 채우기 -------------------------------------------------------------------------------

    def _fill_head(self, title: str, sub: str, badge: Tuple[str, str], why: str):
        self._head_title.setText(title)
        self._head_sub.setText(sub)
        text, category = badge
        self._badge.setText(text or '—')
        # SYSTEM_ERROR 처럼 긴 코드는 글자를 줄여 머리 두 줄을 밀어내지 않게 한다.
        size = 18 if len(text or '') <= 6 else 13
        self._badge.setStyleSheet(chip_style(category) + f'font-size: {size}px;')
        fg, bg = (RESULT_COLORS[category][:2] if category in RESULT_COLORS else NEUTRAL_COLORS)
        self._why.setText(why)
        self._why.setStyleSheet(f'background: {bg}; color: {fg};')

    def _fill_basis(self, result: Optional[itf.PointResult], required: float, limit: float,
                    reach: float, failure_width: float, soft_width: float = 0.0):
        """
        판정 근거 3줄. 기준은 호출하는 쪽이 준다(결과 창 = 검사 당시 값, 조회 창 = 레시피).

        result 가 없거나 측정하지 못한 결과면 측정 · 결과 칸은 '—', 게이지는 기준선만 남는다.
        """
        measured = _measured(result)

        # 힘: 기준에 '도달해야' 좋다. 눈금은 기준의 4/3 이상, 측정값이 더 크면 그만큼 늘린다.
        force = result.max_force_n if measured else None
        ok = force is not None and required > 0 and force >= required
        scale = max(required * 4 / 3, (force or 0.0) * 1.05) or 20.0
        self._set_row('force', force, 'N', f'≥ {required:g} N' if required > 0 else '—',
                      ('도달', OK_COLOR) if ok else ('미도달', BAD_COLOR))
        self._gauges['force'].set_state(force, scale, OK_COLOR if ok else BAD_COLOR,
                                        [(required, f'기준 {required:g}')], f'{scale:.0f} N')

        # 변위: 허용 변위를 '넘지 않아야' 좋다. 눈금 끝은 최대 거리(없으면 측정값까지).
        disp = result.displacement_mm if measured else None
        over = disp is not None and limit > 0 and disp > limit
        scale = reach if reach > limit else max(limit * 2, (disp or 0.0) * 1.05)
        self._set_row('disp', disp, 'mm', f'≤ {limit:g} mm' if limit > 0 else '—',
                      ('초과', BAD_COLOR) if over else ('이내', OK_COLOR))
        self._gauges['disp'].set_state(
            disp, scale, BAD_COLOR if over else OK_COLOR, [(limit, f'허용 {limit:g}')],
            f'최대 {reach:g} mm' if reach > limit else f'{scale:.0f} mm')

        # Pull 최소 폭: 파지 실패 기준보다 좁으면 파지 실패. 폭을 싣지 않은 옛 결과는 '—'.
        width = result.pull_width_mm if measured and result.pull_width_mm > 0 else None
        failed = width is not None and width < failure_width
        self._set_row('width', width, 'mm', f'≥ {failure_width:g} mm',
                      ('파지 실패', BAD_COLOR) if failed else ('정상 파지', OK_COLOR))
        marks = [(failure_width, f'실패 {failure_width:g}')]
        if soft_width > 0:
            marks.append((soft_width, f'Soft {soft_width:.1f}'))
        self._gauges['width'].set_state(width, GRIP_GAUGE_SCALE_MM,
                                        BAD_COLOR if failed else OK_COLOR, marks,
                                        f'{GRIP_GAUGE_SCALE_MM:g} mm')

    def _set_row(self, key, value, unit, limit_text, verdict):
        labels = self._basis[key]
        labels['Value'].setText('—' if value is None else f'{value:.1f} {unit}')
        labels['Limit'].setText(limit_text)
        text, color = verdict if value is not None else ('—', MUTED_COLOR)
        labels['Verdict'].setText(text)
        labels['Verdict'].setStyleSheet(f'color: {color};')

    def _fill_details(self, result: Optional[itf.PointResult], grip_width: float,
                      max_distance: float, task, joint):
        """세부 정보. 값이 빈 줄은 숨긴다."""
        values = dict.fromkeys(DETAIL_KEYS, '')
        values['gripWidth'] = f'{grip_width:g} mm (지시)' if grip_width > 0 else ''
        values['maxDistance'] = f'{max_distance:g} mm' if max_distance > 0 else ''
        values['task'] = _pose_text(task, ('X', 'Y', 'Z', 'A', 'B', 'C'), ('mm', 'deg'))
        values['joint'] = _pose_text(joint, ('J1', 'J2', 'J3', 'J4', 'J5', 'J6'), ('deg', 'deg'))
        if values['task'] and not any(task):
            values['task'] += '\n(미티칭 - 좌표가 전부 0)'
        if result is not None:
            values['resultCode'] = result.result
            values['reasonCode'] = _coded(result.reason_code,
                                          itf.ReasonCode.LABELS.get(result.reason_code, ''))
            values['judgmentStatus'] = _coded(
                result.judgment_status, itf.JudgmentStatus.LABELS.get(result.judgment_status, ''))
            values['termination'] = _coded(
                result.termination_reason,
                itf.TerminationReason.label(result.termination_reason))
            values['reason'] = result.reason
            if result.soft_width_mm > 0:
                values['softWidth'] = f'{result.soft_width_mm:.2f} mm'
            if result.soft_width_mm > 0 and result.pull_width_mm > 0:
                values['widthDelta'] = f'{result.width_delta_mm:+.2f} mm'
            values['product'] = result.product_id
            values['forceId'] = result.force_data_id
        for key, (key_label, value_label) in self._details.items():
            value_label.setText(values[key])
            key_label.setVisible(bool(values[key]))
            value_label.setVisible(bool(values[key]))

    def _show_filled(self):
        self._fit_height()


class ResultDetailDialog(_DetailDialog):
    """
    결과 1건의 상세 정보. 모달이 아니므로 떠 있어도 비상정지를 누를 수 있다.

    판정 기준은 DB 의 현재 값이 아니라 결과에 실려 온 '검사 당시' 값이다.
    """

    UI_FILE = 'result_detail_dialog.ui'

    def _load(self):
        self._db = self._label('dbSaved')

    def show_result(self, result: itf.PointResult):
        """팝업 내용을 주어진 결과로 채운다."""
        category = itf.ResultCode.category(result.result)
        self._fill_head(*_head_texts(result.point_id, result.point_name, result.recipe_id,
                                     result.recipe_version, result.cable_type, result.stamp),
                        (result.result, category), why_text(result))
        self._fill_basis(result, result.required_pull_force_n, result.displacement_limit_mm,
                         result.pull_max_distance_mm,
                         result.grip_failure_width_mm or itf.GRIP_FAILURE_WIDTH_MM,
                         result.soft_width_mm)
        self._fill_details(result, result.grip_width_mm, result.pull_max_distance_mm,
                           result.task, result.joint)
        if result.db_saved:
            self._db.setText('● DB 저장 완료')
            self._db.setStyleSheet(f'color: {OK_COLOR};')
        else:
            self._db.setText('○ DB 저장 안 됨')
            self._db.setStyleSheet(f'color: {MUTED_COLOR};')
        self._show_filled()


class LookupDetailDialog(_DetailDialog):
    """
    통합 조회 표에서 고른 레시피 포인트 1개의 상세 정보.

    '지금 레시피 파일 · DB 에 들어 있는 내용' 이다: 기준은 레시피(레시피에 없는 Point 는 결과에
    실려 온 값), 측정은 DB 의 가장 최근 결과.
    모달이 아니므로 떠 있어도 비상정지를 누를 수 있다.
    """

    UI_FILE = 'lookup_detail_dialog.ui'

    def _load(self):
        self._source = self._label('source')

    def show_row(self, row):
        """팝업 내용을 주어진 lookup_tab.LookupRow 로 채운다."""
        result = row.result
        why = why_text(result)
        _category, note = row.flag()
        if note:
            why = f'{note}\n{why}'
        self._fill_head(*_head_texts(row.point_id, row.point_name, row.recipe_id,
                                     row.recipe_version, row.cable_type,
                                     result.stamp if result else ''),
                        row.badge, why)
        self._fill_basis(result, row.required_pull_force_n, row.max_displacement_mm,
                         row.pull_max_distance_mm,
                         (result.grip_failure_width_mm if result else 0.0)
                         or itf.GRIP_FAILURE_WIDTH_MM,
                         result.soft_width_mm if result else 0.0)
        # 레시피의 위치는 Entry 자세(검사 위치)다.
        self._fill_details(result, row.grip_width_mm, row.pull_max_distance_mm,
                           row.task, row.joint)
        marks = [('레시피', row.in_recipe), ('검사 결과', result is not None)]
        self._source.setText('   '.join(f'{"●" if on else "○"} {name}' for name, on in marks))
        self._source.setStyleSheet(
            f'color: {OK_COLOR if row.in_recipe and result else MUTED_COLOR};')
        self._show_filled()


def _head_texts(point_id, point_name, recipe_id, version, cable_type, stamp) -> Tuple[str, str]:
    """머리 두 줄: ('HARNESS_03 · 하네스 03', 'rcp_BMW_LWR_01 v0.1 · HARNESS · 09-23 21:18:12')."""
    title = ' · '.join(x for x in (point_id, point_name) if x) or '—'
    recipe = f'{recipe_id} {version}'.strip()
    when = stamp.replace('T', ' ')[:19]
    sub = ' · '.join(x for x in (recipe, cable_type, when) if x) or '—'
    return title, sub
