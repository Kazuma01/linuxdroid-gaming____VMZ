"""Janela principal: sidebar + telas + barra de estado."""
from PySide6.QtGui import QPixmap
from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (QButtonGroup, QFrame, QHBoxLayout, QLabel, QMainWindow, QMessageBox,
                               QPushButton, QStackedWidget, QVBoxLayout, QWidget)

from . import storage
from .models import GameEntry, WaydroidState
from .screens.about import AboutScreen
from .screens.controls import ControlsScreen
from .screens.home import HomeScreen
from .screens.library import LibraryScreen
from .screens.settings import SettingsScreen
from .screens.waydroid import WaydroidScreen
from .widgets.common import demo_badge, label


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("LinuxDroid Gaming")
        self.resize(1280, 720)
        self.setMinimumSize(1000, 600)
        self.games = storage.load_library()

        root = QWidget()
        root.setObjectName("root")
        self.setCentralWidget(root)
        outer = QVBoxLayout(root)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        body = QHBoxLayout()
        body.setSpacing(0)
        outer.addLayout(body, 1)

        # ---- telas ----
        self.home = HomeScreen(self.games)
        self.library = LibraryScreen(self.games)
        self.controls = ControlsScreen(self.games)
        self.waydroid = WaydroidScreen()
        self.settings = SettingsScreen()
        self.about = AboutScreen()
        screens = [("Início", self.home), ("Biblioteca", self.library), ("Controles", self.controls),
                   ("Waydroid", self.waydroid), ("Configurações", self.settings), ("Sobre", self.about)]

        # ---- sidebar ----
        side = QFrame()
        side.setObjectName("sidebar")
        side.setFixedWidth(220)
        sl = QVBoxLayout(side)
        sl.setContentsMargins(14, 18, 14, 14)
        sl.setSpacing(6)
        brand_mark = QLabel()
        brand_mark.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        mark_path = str(__import__("pathlib").Path(__file__).resolve().parent / "assets" / "linuxdroid_eva_mark.png")
        mark_pixmap = QPixmap(mark_path)
        if not mark_pixmap.isNull():
            brand_mark.setPixmap(mark_pixmap.scaled(58, 58, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        sl.addWidget(brand_mark)
        sl.addWidget(label("LinuxDroid Gaming", "appTitle"))
        sl.addWidget(label("EVANGELION PROJECT • v0.3.1", "appVersion"))
        sl.addSpacing(14)
        self.stack = QStackedWidget()
        group = QButtonGroup(self)
        group.setExclusive(True)
        for i, (name, widget) in enumerate(screens):
            btn = QPushButton(name)
            btn.setObjectName("navButton")
            btn.setCheckable(True)
            btn.setChecked(i == 0)
            btn.clicked.connect(lambda _=False, idx=i: self.stack.setCurrentIndex(idx))
            group.addButton(btn)
            sl.addWidget(btn)
            self.stack.addWidget(widget)
        sl.addStretch()
        body.addWidget(side)
        body.addWidget(self.stack, 1)

        # ---- barra de estado ----
        bar = QFrame()
        bar.setObjectName("statusBar")
        bl = QHBoxLayout(bar)
        bl.setContentsMargins(16, 6, 16, 6)
        self.status_label = label("")
        bl.addWidget(self.status_label)
        bl.addStretch()
        bl.addWidget(label("Waydroid • controles Phantom opcionais", "muted"))
        bl.addWidget(demo_badge("v0.3.1"))
        outer.addWidget(bar)

        # ---- ligacoes ----
        self.waydroid.state_changed.connect(self.update_status)
        self.waydroid.apps_loaded.connect(self.on_android_apps_loaded)
        self.home.play_requested.connect(self.play)
        self.library.play_requested.connect(self.play)
        self.home.games_changed.connect(self.on_games_changed)
        self.update_status(self.waydroid.state)

    def update_status(self, state: WaydroidState):
        self.status_label.setText(f"Waydroid: {state.value}")

    def on_games_changed(self):
        storage.save_library(self.games)
        self.library.refresh()
        self.controls.set_games(self.games)

    def on_android_apps_loaded(self, apps):
        # Waydroid retorna pares (nome, package ID); a biblioteca mantém os dados locais existentes.
        by_package = {g.package_id: g for g in self.games if g.package_id}
        added = 0
        for name, package_id in apps:
            if package_id not in by_package:
                self.games.append(GameEntry(name or package_id.rsplit(".", 1)[-1].title(), package_id,
                                            installed_status="installed"))
                added += 1
            else:
                by_package[package_id].installed_status = "installed"
        storage.save_library(self.games)
        self.home.refresh()
        self.library.refresh()
        self.controls.set_games(self.games)
        QMessageBox.information(self, "Biblioteca Android", f"{len(apps)} aplicativo(s) encontrados; {added} novo(s) adicionado(s).")

    def play(self, game: GameEntry):
        if not game.package_id:
            QMessageBox.warning(self, "Package ID ausente", f"{game.name} não tem package ID. Atualize a biblioteca Android para importar o identificador.")
            return
        if self.waydroid.state != WaydroidState.RUNNING:
            answer = QMessageBox.question(
                self, "Iniciar ambiente Android",
                "O Waydroid está parado. Deseja iniciar a sessão Android e abrir o jogo automaticamente?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            if answer != QMessageBox.StandardButton.Yes:
                return
            self.status_label.setText("Waydroid: iniciando ambiente Android…")

            def started(result):
                if not result.ok:
                    QMessageBox.warning(self, "Iniciar Waydroid", f"Não foi possível iniciar o Android.\n\n{result.text or result.error}")
                    return
                self._launch_game(game)

            self.waydroid.service.start(started)
            return

        self._launch_game(game)

    def _launch_game(self, game: GameEntry):
        # Em modo multi-janela, oferece migrar para a experiência de emulador.
        if self.waydroid._multi_windows is True:
            answer = QMessageBox.question(
                self,
                "Ativar experiência de emulador",
                "O Waydroid está configurado para abrir cada aplicativo em uma janela separada. "
                "Para manter o jogo dentro de uma única tela Android, como em um emulador, "
                "o LinuxDroid precisa mudar para janela única e reiniciar a sessão.\n\n"
                "Deseja ativar esse modo agora?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            if answer == QMessageBox.StandardButton.Yes:
                self.status_label.setText("Waydroid: ativando janela única…")

                def mode_ready(ok):
                    if not ok:
                        QMessageBox.warning(
                            self, "Modo de emulador",
                            "Não foi possível ativar a janela única. Você ainda pode usar o modo de janelas separadas pela Central Android.",
                        )
                        return
                    self._launch_game_in_current_mode(game)

                self.waydroid.switch_to_emulator_mode(mode_ready)
                return

        self._launch_game_in_current_mode(game)

    def _launch_game_in_current_mode(self, game: GameEntry):
        def start_app(mapping_loaded=False):
            def launch_app():
                self.waydroid.service.launch_app(
                    game.package_id,
                    lambda result: self._app_launch_done(game, result, mapping_loaded),
                )

            # Na janela única, abre primeiro a superfície Android e depois o jogo.
            if self.waydroid.single_window_mode:
                def surface_ready(result):
                    delay = 1000 if result.ok else 250
                    QTimer.singleShot(delay, launch_app)
                self.waydroid.service.show_full_ui(surface_ready)
            else:
                launch_app()

        # Quando existir um perfil Phantom salvo, ele é validado e carregado automaticamente.
        attempted = self.controls.activate_profile_for_game(game.package_id, start_app)
        if not attempted:
            start_app(False)

    def _app_launch_done(self, game, result, mapping_loaded=False):
        self._launch_feedback(game, result.ok, result.text)
        if result.ok and mapping_loaded:
            # F8 no Phantom continua disponível para alternar captura; aqui iniciamos automaticamente.
            QTimer.singleShot(1600, self.controls.phantom.enter_capture)

    def closeEvent(self, event):
        self.controls.shutdown()
        self.waydroid.shutdown()
        super().closeEvent(event)

    def _launch_feedback(self, game, ok, details=""):
        if ok:
            self.status_label.setText(f"Waydroid: executando {game.name}")
            return
        QMessageBox.warning(self, "Abrir aplicativo", f"Não foi possível abrir {game.name}.\n\n{details or 'Confira o log da tela Waydroid.'}")
