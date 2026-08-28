from __future__ import annotations

import ctypes
import sys
from ctypes import wintypes

from PySide6.QtCore import QEvent, QObject, Qt, QTimer
from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication, QDialog, QWidget

_TITLE_BAR_FILTER: QObject | None = None


APP_STYLE = r"""
* {
    color: #F3F4F6;
    font-family: "Segoe UI Variable", "Segoe UI";
    font-size: 13px;
}
QMainWindow, QDialog, QWidget { background-color: #0D0F12; }
QLabel { background: transparent; }
QFrame#header { background: #12151A; border-bottom: 1px solid #2A303A; }
QFrame#sidebar { background: #12151A; border-right: 1px solid #2A303A; }
QFrame#card { background: #171A20; border: 1px solid #2A303A; border-radius: 12px; }
QFrame#sidebarSection { background: transparent; border: none; }
QFrame#processesPanel { background: transparent; border-top: 1px solid #2A303A; }
QFrame#sidebarRow {
    background: transparent; border: 1px solid transparent; border-radius: 8px;
}
QFrame#sidebarRow:hover { background: #1C2027; border-color: #2A303A; }
QFrame#sidebarRow[selected="true"] { background: #1B2B42; border-color: #31547E; }
QFrame#keywordsPanel, QFrame#costCard {
    background: #12151A; border: 1px solid #2A303A; border-radius: 9px;
}
QFrame#toggleRow {
    background: #171A20; border: 1px solid #2A303A; border-radius: 8px;
}
QFrame#divider { background: #2A303A; border: none; min-height: 1px; max-height: 1px; }
QLabel#brand { font-size: 20px; font-weight: 700; color: #F9FAFB; }
QLabel#eyebrow { font-size: 11px; font-weight: 700; color: #9CA3AF; letter-spacing: 1px; }
QLabel#cardHeading { font-size: 15px; font-weight: 700; color: #F9FAFB; letter-spacing: 0.5px; }
QLabel#microLabel { font-size: 10px; font-weight: 700; color: #7B8494; letter-spacing: 0.5px; }
QLabel#title { font-size: 25px; font-weight: 700; color: #F9FAFB; }
QLabel#cardTitle { font-size: 17px; font-weight: 700; color: #F9FAFB; }
QLabel#researchLink { font-size: 17px; font-weight: 700; color: #F3F4F6; }
QLabel#researchLink:hover { color: #FFFFFF; }
QLabel#exportCardTitle { font-size: 20px; font-weight: 700; color: #F9FAFB; }
QLabel#cardMeta, QLabel#exportMeta { color: #8B94A3; font-size: 11px; }
QLabel#rowTitle { font-weight: 600; color: #F3F4F6; }
QLabel#bodyText { color: #D8DCE3; line-height: 1.35; }
QLabel#costValue { font-weight: 700; color: #F9FAFB; }
QLabel#validationError { color: #EF4444; font-size: 12px; }
QLabel#infoBox {
    background: #172236; color: #B8C9E5; border: 1px solid #29466D;
    border-radius: 7px; padding: 9px;
}
QLabel#subtitle, QLabel#muted { color: #9CA3AF; }
QLabel#connected { color: #22C55E; font-weight: 600; }
QLabel#warning { color: #F59E0B; font-weight: 600; }
QLabel#error { color: #EF4444; font-weight: 600; }

QPushButton, QToolButton {
    background: #1C2027; color: #F3F4F6; border: 1px solid #2A303A;
    border-radius: 7px; padding: 7px 12px; font-weight: 600;
}
QPushButton:hover, QToolButton:hover { background: #232832; border-color: #3B4655; }
QPushButton:pressed, QToolButton:pressed { background: #2A303A; }
QPushButton:focus, QToolButton:focus { border-color: #3B82F6; }
QPushButton#primary { background: #3B82F6; color: #FFFFFF; border-color: #3B82F6; }
QPushButton#primary:hover { background: #4B8CF7; border-color: #60A5FA; }
QPushButton#primary:pressed { background: #2563EB; }
QPushButton#toolbarAction {
    padding: 4px 8px; border-radius: 6px; font-size: 11px; background: #1C2027;
}
QPushButton#linkButton {
    background: transparent; border: none; color: #60A5FA; padding: 4px; text-align: left;
}
QPushButton#linkButton:hover { color: #93C5FD; text-decoration: underline; }
QPushButton#danger { color: #F87171; border-color: #7F3036; }
QPushButton#danger:hover { background: #351B20; border-color: #EF4444; }
QPushButton:disabled, QToolButton:disabled {
    color: #626A76; background: #15181D; border-color: #232832;
}

QLineEdit, QTextEdit, QPlainTextEdit, QComboBox, QSpinBox, QDoubleSpinBox,
QDateEdit, QDateTimeEdit, QTimeEdit {
    background: #1C2027; color: #F3F4F6; border: 1px solid #2A303A;
    border-radius: 7px; padding: 7px;
    selection-background-color: #3B82F6; selection-color: #FFFFFF;
}
QLineEdit:hover, QTextEdit:hover, QPlainTextEdit:hover, QComboBox:hover,
QSpinBox:hover, QDoubleSpinBox:hover { border-color: #3B4655; }
QLineEdit:focus, QTextEdit:focus, QPlainTextEdit:focus, QComboBox:focus,
QSpinBox:focus, QDoubleSpinBox:focus { border-color: #3B82F6; }
QLineEdit:disabled, QTextEdit:disabled, QPlainTextEdit:disabled, QComboBox:disabled,
QSpinBox:disabled { background: #15181D; color: #626A76; border-color: #232832; }
QComboBox::drop-down { border: none; width: 24px; background: transparent; }
QComboBox QAbstractItemView { background: #1C2027; border: 1px solid #2A303A; }

QListWidget, QTreeWidget, QTableWidget, QTableView, QTreeView, QListView,
QAbstractItemView {
    background: #171A20; alternate-background-color: #15181D; color: #F3F4F6;
    border: 1px solid #2A303A; border-radius: 7px; outline: none;
    selection-background-color: #244F89; selection-color: #FFFFFF;
}
QFrame#sidebar QListWidget { background: transparent; border: none; }
QFrame#sidebar QListWidget::item:selected { background: #1B2B42; }
QListWidget#keywordDetailList { background: #0F1216; border-color: #232832; }
QListWidget#keywordDetailList::item { padding: 5px 7px; margin: 0; }
QListWidget::item, QTreeView::item { padding: 9px; border-radius: 7px; margin: 1px 2px; }
QListWidget::item:hover, QTreeView::item:hover { background: #232832; }
QListWidget::item:selected, QTreeView::item:selected { background: #244F89; color: #FFFFFF; }
QHeaderView::section {
    background: #1C2027; color: #9CA3AF; border: none;
    border-right: 1px solid #2A303A; border-bottom: 1px solid #2A303A; padding: 7px;
}
QTableCornerButton::section { background: #1C2027; border: 1px solid #2A303A; }

QScrollArea { border: none; background: #0D0F12; }
QScrollArea > QWidget > QWidget, QAbstractScrollArea::viewport { background: transparent; }
QWidget#flowHost, QWidget#configurationMain { background: transparent; }
QSplitter#configurationSplitter { background: transparent; }
QScrollBar:vertical { background: #12151A; width: 11px; margin: 0; border: none; }
QScrollBar::handle:vertical {
    background: #3B4655; min-height: 30px; border-radius: 5px; margin: 2px;
}
QScrollBar::handle:vertical:hover { background: #566274; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical,
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background: none; height: 0; }
QScrollBar:horizontal { background: #12151A; height: 11px; margin: 0; border: none; }
QScrollBar::handle:horizontal {
    background: #3B4655; min-width: 30px; border-radius: 5px; margin: 2px;
}
QScrollBar::handle:horizontal:hover { background: #566274; }
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal,
QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal { background: none; width: 0; }

QMenu, QMenuBar { background: #171A20; color: #F3F4F6; border: 1px solid #2A303A; }
QMenu::item { padding: 7px 28px 7px 12px; }
QMenu::item:selected, QMenuBar::item:selected { background: #232832; color: #FFFFFF; }
QMenu::item:disabled { color: #626A76; }
QMenu::separator { height: 1px; background: #2A303A; margin: 5px 8px; }

QTabWidget::pane { background: #171A20; border: 1px solid #2A303A; border-radius: 7px; }
QTabBar::tab { background: #12151A; color: #9CA3AF; padding: 8px 14px; border: 1px solid #2A303A; }
QTabBar::tab:hover { background: #232832; }
QTabBar::tab:selected { background: #171A20; color: #F3F4F6; border-bottom-color: #3B82F6; }

QProgressBar {
    border: none; background: #232832; color: #F3F4F6;
    border-radius: 4px; min-height: 8px; text-align: center;
}
QProgressBar::chunk { background: #3B82F6; border-radius: 4px; }
QCheckBox, QRadioButton { spacing: 7px; background: transparent; }
QCheckBox::indicator, QRadioButton::indicator {
    width: 17px; height: 17px; border: 1px solid #596579; background: #171A20;
}
QCheckBox::indicator { border-radius: 4px; }
QRadioButton::indicator { border-radius: 9px; }
QCheckBox::indicator:hover, QRadioButton::indicator:hover { border-color: #60A5FA; }
QCheckBox::indicator:checked, QRadioButton::indicator:checked {
    background: #3B82F6; border: 4px solid #A8CAFF;
}
QCheckBox:hover, QRadioButton:hover { color: #FFFFFF; }
QCheckBox:disabled, QRadioButton:disabled { color: #626A76; }
QGroupBox { border: 1px solid #2A303A; border-radius: 8px; margin-top: 10px; padding-top: 8px; }
QGroupBox::title { color: #9CA3AF; subcontrol-origin: margin; left: 10px; padding: 0 4px; }

QStatusBar { background: #12151A; color: #9CA3AF; border-top: 1px solid #2A303A; }
QStatusBar::item { border: none; }
QToolBar, QDockWidget { background: #12151A; border: 1px solid #2A303A; }
QSplitter::handle { background: #2A303A; }
QSplitter::handle:hover { background: #3B82F6; }
QSplitter#configurationSplitter::handle {
    background: transparent; border-right: 1px solid #2A303A;
}
QSplitter#configurationSplitter::handle:hover { border-right: 1px solid #3B82F6; }
QSplitter#mainSplitter::handle { background: #252B34; }
QSplitter#mainSplitter::handle:hover { background: #3B82F6; }

QFrame#sidebarSectionHeader { background: transparent; border-radius: 6px; }
QFrame#sidebarSectionHeader:hover { background: #171A20; }
QLabel#sectionHeading {
    font-size: 13px; font-weight: 700; letter-spacing: 0.5px; color: #E5E7EB;
}
QToolButton#modalCloseButton {
    background: transparent; border: none; color: #9CA3AF; font-size: 20px;
    min-width: 28px; max-width: 28px; padding: 0px;
}
QToolButton#modalCloseButton:hover { color: #F3F4F6; background: #232832; border-radius: 6px; }
QWidget#completionBackdrop { background: rgba(6, 8, 11, 0.72); }
QFrame#completionCard {
    background: #14171D; border: 1px solid #2A303A; border-radius: 14px;
}
QLabel#completionTitle { font-size: 20px; font-weight: 700; color: #F3F4F6; }
QLabel#completionDuration { font-size: 15px; color: #9CA3AF; }
QToolButton#gearButton, QToolButton#pencilButton, QToolButton#iconAction {
    background: transparent; border: none; color: #788291; font-size: 15px;
    min-width: 26px; max-width: 26px; min-height: 26px; max-height: 26px; padding: 4px;
}
QToolButton#gearButton:hover, QToolButton#pencilButton:hover, QToolButton#iconAction:hover {
    color: #DCE9FF; background: #29364A; border-radius: 6px;
}
QToolButton#gearButton:disabled, QToolButton#pencilButton:disabled,
QToolButton#iconAction:disabled, QToolButton#gearButton:disabled:hover,
QToolButton#pencilButton:disabled:hover, QToolButton#iconAction:disabled:hover {
    background: transparent; border: none; color: #4A515C;
}
QToolButton#overflowButton {
    background: transparent; border: none; color: #8E98A7; font-size: 18px;
    font-weight: 700; min-width: 28px; max-width: 28px;
    min-height: 28px; max-height: 28px; padding: 0px;
}
QToolButton#overflowButton:hover {
    color: #F3F4F6; background: #29364A; border-radius: 6px;
}
QToolButton#overflowButton::menu-indicator { image: none; width: 0px; }
QToolButton#platformPill {
    background: #171A20; color: #B7BEC9; border: 1px solid #465163;
    border-radius: 15px; padding: 7px 14px;
}
QToolButton#platformPill:hover { background: #202630; border-color: #64748B; }
QToolButton#platformPill:checked {
    background: #1D3C66; color: #E5F0FF; border-color: #4E8AD4;
}
QToolButton#switch {
    min-width: 48px; max-width: 48px; border-radius: 14px; padding: 5px 8px;
    background: #242A33; color: #98A1AE; border: 1px solid #4A5566;
}
QToolButton#switch:checked {
    background: #1F6B4B; color: #D9FBE9; border-color: #34A36F;
}
QToolButton#keywordChip {
    background: #202A38; color: #D8E7FA; border: 1px solid #37506F;
    border-radius: 13px; padding: 5px 9px;
}
QToolButton#keywordChip:hover { background: #293B52; border-color: #5685BE; }

QLabel#platformBadge {
    background: #171A20; color: #B7BEC9; border: 1px solid #465163;
    border-radius: 12px; padding: 5px 12px; font-weight: 600; font-size: 12px;
}
QFrame#miniCard, QFrame#metricCard, QFrame#exportMetricCard {
    background: #12151A; border: 1px solid #2A303A; border-radius: 9px;
}
QFrame#intentBox { background: transparent; border: 1px solid #2A303A; border-radius: 8px; }
QLabel#miniCardValue { font-size: 14px; font-weight: 700; color: #F3F4F6; }
QLabel#miniCardValue[state="on"] { color: #22C55E; }
QLabel#miniCardValue[state="off"] { color: #9CA3AF; }
QLabel#miniCardValue[state="neutral"] { color: #D8DCE3; }
QLabel#miniCardValue[state="error"] { color: #EF4444; }
QLabel#metricValue { font-size: 19px; font-weight: 700; color: #F9FAFB; }
QLabel#exportMetricValue { font-size: 16px; font-weight: 700; color: #E9EDF3; }
QLabel#statusBadge {
    border-radius: 11px; padding: 3px 11px; font-size: 11px; font-weight: 700; letter-spacing: 0.5px;
}
QLabel#statusBadge[state="completed"] { background: #123524; color: #34D399; }
QLabel#statusBadge[state="running"] { background: #1C2C42; color: #60A5FA; }
QLabel#statusBadge[state="warning"] { background: #2E2411; color: #F2B84B; }
QLabel#statusBadge[state="failed"] { background: #331416; color: #F87171; }
QLabel#statusBadge[state="neutral"] { background: #1C2027; color: #9CA3AF; }
QLabel#statusBadge[state="cancelled"] { background: #2E2A11; color: #E5D64B; }
QLabel#stageBlockTitle { font-size: 11px; font-weight: 700; letter-spacing: 0.5px; color: #D8DCE3; }
QLabel#stageBlockRange { font-size: 10px; color: #6B7280; }
QLabel#stageBlockDetail { font-size: 11px; color: #9CA3AF; }
QLabel#stageStatusBox {
    border-radius: 6px; font-size: 11px; font-weight: 700;
    background: #1C2027; color: #D8DCE3; border: 1px solid #2A303A;
}
QLabel#stageStatusBox[state="running"] { color: #34D399; border-color: #2FA66C; }
QLabel#stageStatusBox[state="complete"] { background: #123524; color: #34D399; border-color: #2FA66C; }
QLabel#stageStatusBox[state="warning"] { background: #2E2411; color: #F2B84B; border-color: #D69632; }
QLabel#stageStatusBox[state="failed"] { background: #331416; color: #F87171; border-color: #EF4444; }
QLabel#stageStatusBox[state="cancelled"] { background: #2E2A11; color: #E5D64B; border-color: #D6C632; }
QLabel#stageStatusBox[state="neutral"] { background: #1C2027; color: #9CA3AF; border-color: #2A303A; }
QFrame#intentField, QFrame#keywordEditor {
    background: #1C2027; border: 1px solid #2A303A; border-radius: 8px;
}
QFrame#intentField QTextEdit, QFrame#keywordEditor QLineEdit {
    border: none; background: transparent;
}
QFrame#intentField[limitState="near"], QFrame#keywordEditor[limitState="near"] {
    border-color: #D69632;
}
QFrame#intentField[limitState="exact"], QFrame#keywordEditor[limitState="exact"] {
    border-color: #2FA66C;
}
QFrame#intentField[limitState="error"] { border-color: #EF4444; }
QLabel#limitCounter { color: #8B95A5; font-size: 12px; }
QLabel#limitCounter[limitState="near"] { color: #F2B84B; }
QLabel#limitCounter[limitState="exact"] { color: #42C985; }
QMessageBox { background: #171A20; }
QMessageBox QLabel { color: #F3F4F6; background: transparent; }
QDialogButtonBox { background: transparent; }
QToolTip { background: #232832; color: #F3F4F6; border: 1px solid #3B4655; padding: 6px; }
QFrame#sidebar QListWidget::item:selected { background: #1B2B42; }
QListWidget#agentSidebarList::item:selected,
QListWidget#researchSidebarList::item:selected,
QListWidget#processSidebarList::item:selected { background: transparent; }
"""


def apply_dark_palette(app: QApplication) -> None:
    global _TITLE_BAR_FILTER
    palette = QPalette()
    palette.setColor(QPalette.ColorRole.Window, QColor("#0D0F12"))
    palette.setColor(QPalette.ColorRole.WindowText, QColor("#F3F4F6"))
    palette.setColor(QPalette.ColorRole.Base, QColor("#1C2027"))
    palette.setColor(QPalette.ColorRole.AlternateBase, QColor("#171A20"))
    palette.setColor(QPalette.ColorRole.ToolTipBase, QColor("#232832"))
    palette.setColor(QPalette.ColorRole.ToolTipText, QColor("#F3F4F6"))
    palette.setColor(QPalette.ColorRole.Text, QColor("#F3F4F6"))
    palette.setColor(QPalette.ColorRole.Button, QColor("#1C2027"))
    palette.setColor(QPalette.ColorRole.ButtonText, QColor("#F3F4F6"))
    palette.setColor(QPalette.ColorRole.BrightText, QColor("#EF4444"))
    palette.setColor(QPalette.ColorRole.Highlight, QColor("#3B82F6"))
    palette.setColor(QPalette.ColorRole.HighlightedText, QColor("#FFFFFF"))
    palette.setColor(QPalette.ColorRole.PlaceholderText, QColor("#737B88"))
    palette.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.Text, QColor("#626A76"))
    palette.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.ButtonText, QColor("#626A76"))
    app.setPalette(palette)
    app.setStyleSheet(APP_STYLE)
    if _TITLE_BAR_FILTER is None:
        _TITLE_BAR_FILTER = _DarkTitleBarFilter(app)
        app.installEventFilter(_TITLE_BAR_FILTER)


def apply_dark_title_bar(widget: QWidget) -> None:
    """Best-effort dark DWM title bar; safely does nothing off Windows/older DWM."""
    if sys.platform != "win32":
        return
    try:
        hwnd = wintypes.HWND(int(widget.winId()))
        enabled = ctypes.c_int(1)
        dwmapi = ctypes.WinDLL("dwmapi")
        for attribute in (20, 19):
            result = dwmapi.DwmSetWindowAttribute(
                hwnd, attribute, ctypes.byref(enabled), ctypes.sizeof(enabled)
            )
            if result == 0:
                break
    except (AttributeError, OSError, TypeError, ValueError):
        return


def install_dark_title_bar(widget: QWidget) -> None:
    widget.setAttribute(Qt.WidgetAttribute.WA_NativeWindow, True)
    QTimer.singleShot(0, lambda: apply_dark_title_bar(widget))


class _DarkTitleBarFilter(QObject):
    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if (
            isinstance(watched, QDialog)
            and event.type() == QEvent.Type.Show
            and not watched.property("virloDarkTitleBarApplied")
        ):
            watched.setProperty("virloDarkTitleBarApplied", True)
            install_dark_title_bar(watched)
        return super().eventFilter(watched, event)
