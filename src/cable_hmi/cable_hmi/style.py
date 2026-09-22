"""
코드에서 동적으로 입히는 색.

정적인 스타일시트(QSS)는 main_window.ui 의 MainWindow.styleSheet 에 있다.
"""

# 결과 부류(PASS/FAIL/MISSING)별 색: (글자, 칩 배경, 테이블 행 배경)
RESULT_COLORS = {
    'PASS': ('#1E8E5A', '#E6F7EE', '#F1FBF6'),
    'FAIL': ('#D12F3A', '#FFE8EA', '#FFF4F4'),
    'MISSING': ('#B7791F', '#FFF0D8', '#FFF8E8'),
}

OK_COLOR = '#1E8E5A'
BAD_COLOR = '#D12F3A'
WARN_COLOR = '#B7791F'
MUTED_COLOR = '#8A94A3'

LOG_COLORS = {'INFO': '#2B3440', 'WARN': WARN_COLOR, 'ERROR': BAD_COLOR}

# 대화상자(QMessageBox) 버튼. 메인 화면의 QPushButton 규칙은 글자만 흰색으로 만들고 배경이
# 없어서, 따로 지정하지 않으면 대화상자 버튼이 거의 보이지 않는다.
DIALOG_QSS = """
QMessageBox QPushButton { background: #379DD3; color: #FFFFFF; border-radius: 6px;
                          padding: 6px 18px; min-width: 64px; font-size: 13px; }
QMessageBox QPushButton:hover { background: #2C8BC0; }
QMessageBox QPushButton:default { border: 2px solid #1F6E99; }
"""


def chip_style(category: str) -> str:
    """PASS/FAIL/MISSING 칩(둥근 배지)용 스타일."""
    fg, bg, _row = RESULT_COLORS.get(category, (MUTED_COLOR, '#EEF1F5', '#FFFFFF'))
    return (f'background: {bg}; color: {fg}; font-weight: bold; '
            f'border-radius: 10px; padding: 3px 12px;')
