"""Tela 3: Biblioteca (grid + busca + filtros)."""
from PySide6.QtCore import QTimer, Signal
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QGridLayout, QHBoxLayout, QLineEdit,
    QScrollArea, QVBoxLayout, QWidget,
)

from .. import storage
from ..models import GameEntry
from ..services.library_metadata import (
    ORDERS, STATES, STATE_ALL, STATE_INSTALLED, STATE_LAUNCHED,
    STATE_UNCONFIRMED, categories, filtered_games, sorted_games,
)
from ..widgets.common import label, title_row
from ..widgets.game_card import GameCard


class LibraryScreen(QWidget):
    play_requested = Signal(object)
    remove_requested = Signal(object)

    def __init__(self, games: list[GameEntry]):
        super().__init__()
        self.games = games
        self.columns = self._columns_for_width(self.width())
        self._refresh_pending = False
        outer = QVBoxLayout(self)
        outer.setContentsMargins(28, 24, 28, 16)
        outer.setSpacing(14)
        outer.addWidget(title_row("Biblioteca", "Registro local dos seus jogos."))

        filters = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText("Buscar jogo por nome ou package ID...")
        self.search.textChanged.connect(self.refresh)
        filters.addWidget(self.search, 1)
        self.favorites_only = QCheckBox("Só favoritos")
        self.favorites_only.toggled.connect(self.refresh)
        filters.addWidget(self.favorites_only)
        self.category_combo = QComboBox()
        self.category_combo.addItem("Todas as categorias", "")
        self.category_combo.currentIndexChanged.connect(self.refresh)
        filters.addWidget(self.category_combo)
        self.state_combo = QComboBox()
        for value, text in (
            (STATE_ALL, "Estado: todos"),
            (STATE_INSTALLED, "Estado: instalados"),
            (STATE_UNCONFIRMED, "Estado: instalação não confirmada"),
            (STATE_LAUNCHED, "Estado: comando de lançamento aceito"),
        ):
            self.state_combo.addItem(text, value)
        self.state_combo.setToolTip(
            "Instalados vêm de 'waydroid app list'. "
            "'Comando de lançamento aceito' não prova que o jogo abriu ou está em execução."
        )
        self.state_combo.currentIndexChanged.connect(self.refresh)
        filters.addWidget(self.state_combo)
        self.order_combo = QComboBox()
        for value, text in (
            ("name", "Ordenar: nome"),
            ("recent", "Ordenar: último lançamento"),
            ("favorites", "Ordenar: favoritos"),
        ):
            self.order_combo.addItem(text, value)
        self.order_combo.currentIndexChanged.connect(self.refresh)
        filters.addWidget(self.order_combo)
        outer.addLayout(filters)

        hint = label(
            "Estado: 'instalados' usa a lista do Android; 'comando de lançamento aceito' "
            "não indica jogo em execução.",
            "muted",
        )
        hint.setWordWrap(True)
        outer.addWidget(hint)

        self.empty = label("Nenhum jogo encontrado.", "muted")
        outer.addWidget(self.empty)
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        outer.addWidget(self.scroll, 1)
        self.refresh()

    @staticmethod
    def _columns_for_width(width: int) -> int:
        """Grade responsiva: 2 colunas em telas estreitas, 4 em largas."""
        if width < 560:
            return 2
        if width < 860:
            return 3
        return 4

    def resizeEvent(self, event):
        super().resizeEvent(event)
        columns = self._columns_for_width(self.width())
        if columns != self.columns:
            self.columns = columns
            if not self._refresh_pending:
                self._refresh_pending = True
                QTimer.singleShot(0, self._deferred_refresh)

    def _deferred_refresh(self):
        self._refresh_pending = False
        if hasattr(self, "scroll"):
            self.refresh()

    def refresh_categories(self):
        current = self.category_combo.currentData() or ""
        self.category_combo.blockSignals(True)
        self.category_combo.clear()
        self.category_combo.addItem("Todas as categorias", "")
        for name in categories(self.games):
            self.category_combo.addItem(name, name)
        index = self.category_combo.findData(current)
        self.category_combo.setCurrentIndex(index if index >= 0 else 0)
        self.category_combo.blockSignals(False)

    def refresh(self):
        self.refresh_categories()
        state = self.state_combo.currentData()
        shown = filtered_games(
            self.games,
            term=self.search.text(),
            favorites_only=self.favorites_only.isChecked(),
            category=self.category_combo.currentData() or "",
            state=state if state in STATES else STATE_ALL,
        )
        order = self.order_combo.currentData()
        shown = sorted_games(shown, order=order if order in ORDERS else "name")
        self.empty.setVisible(not shown)
        holder = QWidget()
        grid = QGridLayout(holder)
        grid.setSpacing(12)
        cols = self.columns
        for i, game in enumerate(shown):
            card = GameCard(game, show_package=True)
            card.play_clicked.connect(self.play_requested)
            card.remove_clicked.connect(self.remove_requested)
            card.favorite_toggled.connect(self._favorite_toggled)
            grid.addWidget(card, i // cols, i % cols)
        grid.setRowStretch(len(shown) // cols + 1, 1)
        grid.setColumnStretch(cols, 1)
        self.scroll.setWidget(holder)

    def _favorite_toggled(self, game, checked):
        game.favorite = bool(checked)
        storage.save_library(self.games)
        # Recriar os cards durante a emissão do sinal destruiria o emissor;
        # agenda a atualização para o próximo ciclo do event loop.
        QTimer.singleShot(0, self.refresh)
