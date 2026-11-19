"""Pecas de interface reutilizaveis."""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QVBoxLayout, QWidget


def label(text: str, name: str = "") -> QLabel:
    lb = QLabel(text)
    if name:
        lb.setObjectName(name)
    lb.setWordWrap(True)
    return lb


def demo_badge(text: str = "Demo") -> QLabel:
    lb = QLabel(text)
    lb.setObjectName("demoBadge")
    lb.setAlignment(Qt.AlignCenter)
    lb.setFixedHeight(20)
    return lb


def title_row(title: str, subtitle: str = "", demo: bool = False) -> QWidget:
    box = QWidget()
    lay = QVBoxLayout(box)
    lay.setContentsMargins(0, 0, 0, 0)
    row = QHBoxLayout()
    row.addWidget(label(title, "h1"))
    if demo:
        row.addWidget(demo_badge())
    row.addStretch()
    lay.addLayout(row)
    if subtitle:
        lay.addWidget(label(subtitle, "muted"))
    return box


def panel(name: str = "panel") -> QFrame:
    f = QFrame()
    f.setObjectName(name)
    return f
