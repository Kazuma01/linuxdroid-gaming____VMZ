"""Ponto de entrada: python -m linuxdroid"""
import sys

from PySide6.QtWidgets import QApplication

from .main_window import MainWindow
from .theme import STYLESHEET


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("LinuxDroid Gaming")
    app.setApplicationVersion("0.3.1")
    app.setStyleSheet(STYLESHEET)
    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
