"""Card reutilizável para jogos da biblioteca."""
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QFrame, QLabel, QPushButton, QVBoxLayout
from ..models import GameEntry
from .common import label

class GameCard(QFrame):
    play_clicked = Signal(object)
    def __init__(self, game: GameEntry, show_package: bool = False):
        super().__init__()
        self.game = game
        self.setObjectName("card")
        self.setMinimumWidth(170)
        self.setMaximumWidth(220)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(13, 13, 13, 13)
        lay.setSpacing(9)
        thumb = QFrame()
        thumb.setObjectName("thumb")
        thumb.setMinimumHeight(105)
        tl = QVBoxLayout(thumb)
        mark = QLabel(game.name[:1].upper() or "G")
        mark.setAlignment(Qt.AlignCenter)
        mark.setStyleSheet("font-size: 38px; font-weight: 800; color: #b69aff;")
        tl.addWidget(mark)
        lay.addWidget(thumb)
        name = label(game.name, "h2")
        name.setAlignment(Qt.AlignCenter)
        name.setMaximumHeight(42)
        lay.addWidget(name)
        if show_package:
            pkg = label(game.package_id or "Package ID não definido", "muted")
            pkg.setAlignment(Qt.AlignCenter)
            pkg.setWordWrap(True)
            lay.addWidget(pkg)
        status = label("ANDROID • " + (game.installed_status or "unknown").upper(), "muted")
        status.setAlignment(Qt.AlignCenter)
        lay.addWidget(status)
        btn = QPushButton("▶  Jogar")
        btn.setObjectName("primary")
        btn.clicked.connect(lambda: self.play_clicked.emit(self.game))
        lay.addWidget(btn)
