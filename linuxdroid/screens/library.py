"""Tela 3: Biblioteca (grid + busca)."""
from PySide6.QtCore import Signal
from PySide6.QtWidgets import QGridLayout, QLineEdit, QScrollArea, QVBoxLayout, QWidget

from ..models import GameEntry
from ..widgets.common import label, title_row
from ..widgets.game_card import GameCard


class LibraryScreen(QWidget):
    play_requested = Signal(object)

    def __init__(self, games: list[GameEntry]):
        super().__init__()
        self.games = games
        outer = QVBoxLayout(self)
        outer.setContentsMargins(28, 24, 28, 16)
        outer.setSpacing(14)
        outer.addWidget(title_row("Biblioteca", "Registro local dos seus jogos."))

        self.search = QLineEdit()
        self.search.setPlaceholderText("Buscar jogo por nome...")
        self.search.textChanged.connect(self.refresh)
        outer.addWidget(self.search)

        self.empty = label("Nenhum jogo encontrado.", "muted")
        outer.addWidget(self.empty)
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        outer.addWidget(self.scroll, 1)
        self.refresh()

    def refresh(self):
        term = self.search.text().strip().lower()
        shown = [g for g in self.games if term in g.name.lower()]
        self.empty.setVisible(not shown)
        holder = QWidget()
        grid = QGridLayout(holder)
        grid.setSpacing(12)
        cols = 4
        for i, g in enumerate(shown):
            card = GameCard(g, show_package=True)
            card.play_clicked.connect(self.play_requested)
            grid.addWidget(card, i // cols, i % cols)
        grid.setRowStretch(len(shown) // cols + 1, 1)
        grid.setColumnStretch(cols, 1)
        self.scroll.setWidget(holder)
