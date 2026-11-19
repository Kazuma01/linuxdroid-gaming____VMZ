"""Tela inicial do launcher."""
from pathlib import Path
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QHBoxLayout, QInputDialog, QLabel, QPushButton, QScrollArea, QVBoxLayout, QWidget
from .. import storage
from ..models import GameEntry
from ..services.library_metadata import recent_games
from ..widgets.common import label, panel, title_row
from ..widgets.game_card import GameCard

class HomeScreen(QWidget):
    play_requested = Signal(object)
    games_changed = Signal()
    def __init__(self, games: list[GameEntry]):
        super().__init__()
        self.games = games
        outer = QVBoxLayout(self)
        outer.setContentsMargins(30, 25, 30, 20)
        outer.setSpacing(18)
        outer.addWidget(title_row("Seu espaço de jogos", "Uma central para seus jogos Android no Linux."))
        banner = panel("banner")
        bl = QHBoxLayout(banner)
        bl.setContentsMargins(20, 15, 20, 15)
        bl.setSpacing(18)
        copy = QVBoxLayout()
        eyebrow = label("LINUXDROID GAMING  /  EVANGELION PROJECT", "muted")
        headline = label("PLAY YOUR WAY.", "h1")
        headline.setStyleSheet("font-size: 30px; color: #d7c4ff;")
        description = label("Organize sua biblioteca e execute seus jogos pelo Waydroid.", "muted")
        copy.addWidget(eyebrow)
        copy.addSpacing(4)
        copy.addWidget(headline)
        copy.addWidget(description)
        copy.addStretch()
        bl.addLayout(copy, 1)
        artwork = QLabel()
        artwork.setAlignment(Qt.AlignCenter)
        artwork.setMinimumWidth(260)
        artwork.setMaximumWidth(390)
        artwork.setMinimumHeight(145)
        image_path = Path(__file__).resolve().parents[1] / "assets" / "eva_hero_banner.jpg"
        pixmap = QPixmap(str(image_path))
        if not pixmap.isNull():
            artwork.setPixmap(pixmap.scaled(390, 160, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        else:
            artwork.setText("EVA // 01")
        bl.addWidget(artwork)
        outer.addWidget(banner)
        head = QHBoxLayout()
        head.addWidget(label("Continue jogando", "h2"))
        head.addStretch()
        add = QPushButton("+ Adicionar jogo")
        add.setObjectName("primary")
        add.clicked.connect(self.add_game)
        head.addWidget(add)
        outer.addLayout(head)
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        outer.addWidget(self.scroll, 1)
        self.refresh()
    def refresh(self):
        holder = QWidget()
        lay = QHBoxLayout(holder)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(14)
        for game in recent_games(self.games, 8):
            card = GameCard(game)
            card.play_clicked.connect(self.play_requested)
            card.favorite_toggled.connect(self._favorite_toggled)
            lay.addWidget(card)
        if not self.games:
            lay.addWidget(label("Sua biblioteca está vazia. Adicione um jogo para começar.", "muted"))
        lay.addStretch()
        self.scroll.setWidget(holder)
    def add_game(self):
        name, ok = QInputDialog.getText(self, "Adicionar jogo", "Nome do jogo:")
        if not ok or not name.strip():
            return
        pkg, ok = QInputDialog.getText(self, "Adicionar jogo", "Package ID (opcional, ex.: com.empresa.jogo):")
        if not ok:
            pkg = ""
        self.games.append(GameEntry(name.strip(), pkg.strip()))
        self.games_changed.emit()
        self.refresh()

    def _favorite_toggled(self, game, checked):
        game.favorite = bool(checked)
        # O card já atualizou a estrela; salvar e notificar sem recriar o
        # widget durante a emissão do sinal evita destruir o emissor.
        self.games_changed.emit()
