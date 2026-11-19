"""Tema visual grafite, violeta e ciano do LinuxDroid Gaming."""
BG = "#0d0f16"
PANEL = "#151824"
PANEL_ALT = "#1b1f2d"
BORDER = "#292e40"
TEXT = "#eef0fa"
MUTED = "#9299b0"
PURPLE = "#8b5cf6"
BLUE = "#58a6ff"
GREEN = "#35d07f"
AMBER = "#f4b942"
RED = "#ff647c"

STYLESHEET = f"""
* {{ font-family: "Inter", "Noto Sans", sans-serif; font-size: 13px; color: {TEXT}; }}
QMainWindow, QWidget#root, QStackedWidget, QScrollArea, QScrollArea > QWidget > QWidget {{ background: {BG}; }}
QScrollArea {{ border: none; }}
#sidebar {{ background: {PANEL}; border-right: 1px solid {BORDER}; }}
#appTitle {{ font-size: 20px; font-weight: 800; letter-spacing: 0.3px; }}
#appVersion {{ color: {MUTED}; font-size: 10px; letter-spacing: 1px; }}
QPushButton#navButton {{ text-align: left; padding: 11px 13px; border-radius: 9px; background: transparent; border: 1px solid transparent; color: {MUTED}; font-weight: 600; }}
QPushButton#navButton:hover {{ background: {PANEL_ALT}; color: {TEXT}; }}
QPushButton#navButton:checked {{ background: #292044; border: 1px solid #59418c; color: #d8c7ff; }}
QLabel#h1 {{ font-size: 25px; font-weight: 800; }}
QLabel#h2 {{ font-size: 17px; font-weight: 700; }}
QLabel#muted {{ color: {MUTED}; }}
QFrame#card, QFrame#panel {{ background: {PANEL}; border: 1px solid {BORDER}; border-radius: 14px; }}
QFrame#card:hover {{ border: 1px solid {PURPLE}; background: #191b29; }}
QFrame#banner {{ background: #15182a; border: 1px solid #39315c; border-radius: 16px; }}
QFrame#thumb {{ background: #22243a; border-radius: 11px; border: 1px solid #35314f; }}
QPushButton {{ background: {PANEL_ALT}; border: 1px solid {BORDER}; border-radius: 9px; padding: 9px 14px; font-weight: 600; }}
QPushButton:hover {{ border: 1px solid {PURPLE}; background: #242035; }}
QPushButton:focus {{ border: 1px solid {BLUE}; }}
QPushButton:disabled {{ color: #5a5e70; background: #171923; border: 1px solid #22252f; }}
QPushButton#primary {{ background: {PURPLE}; border: 1px solid {PURPLE}; font-weight: 700; color: white; }}
QPushButton#primary:hover {{ background: #9d77f8; }}
QPushButton#primary:disabled {{ background: #3a3260; color: #8b86a8; }}
QLineEdit, QComboBox, QSpinBox {{ background: {PANEL}; border: 1px solid {BORDER}; border-radius: 9px; padding: 8px 10px; }}
QLineEdit:focus, QComboBox:focus, QSpinBox:focus {{ border: 1px solid {BLUE}; }}
QGroupBox {{ border: 1px solid {BORDER}; border-radius: 10px; margin-top: 10px; padding: 12px 8px 8px 8px; font-weight: 700; color: #d8c7ff; }}
QGroupBox::title {{ subcontrol-origin: margin; left: 12px; padding: 0 5px; }}
QSplitter::handle {{ background: {BORDER}; width: 2px; }}
QScrollBar:vertical {{ background: {BG}; width: 10px; margin: 0; }}
QScrollBar::handle:vertical {{ background: #35344a; border-radius: 5px; min-height: 24px; }}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
QComboBox QAbstractItemView {{ background: {PANEL}; selection-background-color: #2a2250; }}
QListWidget {{ background: {PANEL}; border: 1px solid {BORDER}; border-radius: 10px; padding: 5px; }}
QListWidget::item {{ padding: 10px; border-radius: 7px; }}
QListWidget::item:selected {{ background: #2a2250; }}
QPlainTextEdit {{ background: #090b10; border: 1px solid {BORDER}; border-radius: 10px; font-family: "JetBrains Mono", monospace; font-size: 12px; }}
QCheckBox {{ spacing: 9px; }}
QCheckBox::indicator {{ width: 18px; height: 18px; border-radius: 5px; border: 1px solid {BORDER}; background: {PANEL}; }}
QCheckBox::indicator:checked {{ background: {PURPLE}; border: 1px solid {PURPLE}; }}
QLabel#demoBadge {{ background: #35280c; color: {AMBER}; border: 1px solid #70541a; border-radius: 6px; padding: 3px 7px; font-size: 10px; font-weight: 800; }}
QFrame#statusBar {{ background: {PANEL}; border-top: 1px solid {BORDER}; }}
"""
