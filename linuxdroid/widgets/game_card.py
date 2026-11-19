"""Card reutilizável para jogos da biblioteca."""
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QVBoxLayout
from ..models import GameEntry
from .common import label

class GameCard(QFrame):
    play_clicked = Signal(object)
    favorite_toggled = Signal(object, bool)
    remove_clicked = Signal(object)

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
        install_text = {
            "installed": "INSTALADO",
            "missing": "NÃO ENCONTRADO",
        }.get(game.installed_status, "INSTALAÇÃO NÃO CONFIRMADA")
        status = label("ANDROID • " + install_text, "muted")
        status.setAlignment(Qt.AlignCenter)
        lay.addWidget(status)
        if game.last_launched_at:
            played = label(
                "Último comando aceito: " + game.last_launched_at[:16].replace("T", " "),
                "muted",
            )
            played.setAlignment(Qt.AlignCenter)
            lay.addWidget(played)
        actions = QHBoxLayout()
        self.favorite_btn = QPushButton("★" if game.favorite else "☆")
        self.favorite_btn.setObjectName("favorite")
        self.favorite_btn.setToolTip("Favorito")
        self.favorite_btn.setCheckable(True)
        self.favorite_btn.setChecked(bool(game.favorite))
        self.favorite_btn.toggled.connect(self._on_favorite)
        actions.addWidget(self.favorite_btn)
        self.remove_btn = QPushButton("Remover")
        self.remove_btn.setObjectName("danger")
        self.remove_btn.setToolTip(
            "Remove o pacote Android e seus dados. Exige confirmação; não é reversível."
        )
        # Só oferece remoção quando o Android confirmou a instalação e há
        # package ID válido — nunca por heurística ou nome de arquivo.
        self.remove_btn.setEnabled(
            game.installed_status == "installed" and bool(game.package_id)
        )
        self.remove_btn.clicked.connect(lambda: self.remove_clicked.emit(self.game))
        actions.addWidget(self.remove_btn)
        btn = QPushButton("▶  Jogar")
        btn.setObjectName("primary")
        btn.clicked.connect(lambda: self.play_clicked.emit(self.game))
        actions.addWidget(btn, 1)
        lay.addLayout(actions)

    def _on_favorite(self, checked: bool) -> None:
        self.favorite_btn.setText("★" if checked else "☆")
        self.favorite_toggled.emit(self.game, checked)
