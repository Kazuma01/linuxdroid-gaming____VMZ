"""Painel Waydroid: sessão, modo janela única, instalação e dispositivos."""
import tempfile
from pathlib import Path

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QComboBox, QFileDialog, QHBoxLayout, QMessageBox, QPlainTextEdit,
    QPushButton, QVBoxLayout, QWidget,
)

from ..models import WaydroidState
from ..services.adb_service import AdbService
from ..services.installer import plan_apk_installation, plan_xapk_installation
from ..services.waydroid_service import WaydroidService
from ..widgets.common import label, panel, title_row

COLORS = {
    WaydroidState.RUNNING: "#22c55e",
    WaydroidState.FROZEN: "#f59e0b",
    WaydroidState.STARTING: "#f59e0b",
    WaydroidState.ERROR: "#ef4444",
    WaydroidState.NOT_INSTALLED: "#ef4444",
}


class WaydroidScreen(QWidget):
    state_changed = Signal(object)
    apps_loaded = Signal(object)

    def __init__(self):
        super().__init__()
        self.service = WaydroidService(self)
        self.adb = AdbService(self)
        self.status = None
        self.state = WaydroidState.UNKNOWN
        self._multi_windows = None
        self._xapk_tempdir = None

        outer = QVBoxLayout(self)
        outer.setContentsMargins(28, 22, 28, 18)
        outer.setSpacing(11)
        outer.addWidget(title_row("Central Android", "Gerencie os jogos e a experiência Waydroid em um só lugar."))

        status_box = panel()
        status_layout = QVBoxLayout(status_box)
        status_layout.setContentsMargins(18, 14, 18, 14)
        self.state_label = label("Estado: verificando…", "h2")
        self.hint = label("Consultando Waydroid instalado no sistema.", "muted")
        status_layout.addWidget(self.state_label)
        status_layout.addWidget(self.hint)
        buttons = QHBoxLayout()
        self.btn_refresh = QPushButton("Atualizar")
        self.btn_start = QPushButton("Iniciar sessão")
        self.btn_start.setObjectName("primary")
        self.btn_stop = QPushButton("Parar")
        self.btn_restart = QPushButton("Reiniciar")
        for button in (self.btn_refresh, self.btn_start, self.btn_stop, self.btn_restart):
            buttons.addWidget(button)
        buttons.addStretch()
        status_layout.addLayout(buttons)
        outer.addWidget(status_box)

        mode_box = panel()
        mode_layout = QVBoxLayout(mode_box)
        mode_layout.setContentsMargins(18, 12, 18, 12)
        mode_layout.addWidget(label("EXPERIÊNCIA DE EMULADOR", "h2"))
        mode_row = QHBoxLayout()
        self.mode_combo = QComboBox()
        self.mode_combo.addItem("Janela única — apps dentro da superfície Android", False)
        self.mode_combo.addItem("Janelas separadas — apps integrados ao desktop", True)
        self.btn_apply_mode = QPushButton("Aplicar modo")
        self.btn_apply_mode.setObjectName("primary")
        mode_row.addWidget(self.mode_combo, 1)
        mode_row.addWidget(self.btn_apply_mode)
        mode_layout.addLayout(mode_row)
        self.mode_hint = label(
            "Janela única é a opção mais próxima de um emulador tradicional. "
            "O Waydroid reinicia a sessão para aplicar a alteração.", "muted"
        )
        mode_layout.addWidget(self.mode_hint)
        outer.addWidget(mode_box)

        tools_box = panel()
        tools_layout = QVBoxLayout(tools_box)
        tools_layout.setContentsMargins(18, 12, 18, 12)
        tools_layout.addWidget(label("APLICATIVOS E DISPOSITIVOS", "h2"))
        app_row = QHBoxLayout()
        self.btn_apps = QPushButton("Atualizar biblioteca Android")
        self.btn_apps.setObjectName("primary")
        self.btn_install = QPushButton("Instalar APK / XAPK")
        self.btn_install.setObjectName("primary")
        self.btn_full_ui = QPushButton("Abrir tela Android")
        app_row.addWidget(self.btn_apps, 1)
        app_row.addWidget(self.btn_install)
        app_row.addWidget(self.btn_full_ui)
        tools_layout.addLayout(app_row)
        device_row = QHBoxLayout()
        self.btn_connect_adb = QPushButton("Conectar ADB Waydroid")
        self.btn_detect_adb = QPushButton("Detectar dispositivos")
        self.btn_gamepad = QPushButton("Ativar repasse de controle USB")
        device_row.addWidget(self.btn_connect_adb)
        device_row.addWidget(self.btn_detect_adb)
        device_row.addWidget(self.btn_gamepad)
        tools_layout.addLayout(device_row)
        self.adb_status = label("ADB: não conectado / não verificado.", "muted")
        tools_layout.addWidget(self.adb_status)
        outer.addWidget(tools_box)

        nav_box = panel()
        nav_layout = QVBoxLayout(nav_box)
        nav_layout.setContentsMargins(18, 12, 18, 12)
        nav_layout.addWidget(label("ATALHOS ANDROID", "h2"))
        nav_row = QHBoxLayout()
        self.btn_back = QPushButton("← Voltar")
        self.btn_home = QPushButton("⌂ Início")
        self.btn_recent = QPushButton("▣ Recentes")
        self.btn_volume_down = QPushButton("Volume −")
        self.btn_volume_up = QPushButton("Volume +")
        for button in (self.btn_back, self.btn_home, self.btn_recent, self.btn_volume_down, self.btn_volume_up):
            nav_row.addWidget(button)
        nav_layout.addLayout(nav_row)
        outer.addWidget(nav_box)

        outer.addWidget(label("Log técnico", "h2"))
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumBlockCount(500)
        outer.addWidget(self.log, 1)

        self.btn_refresh.clicked.connect(self.refresh_with_mode)
        self.btn_start.clicked.connect(self.start)
        self.btn_stop.clicked.connect(self.stop)
        self.btn_restart.clicked.connect(self.restart)
        self.btn_apps.clicked.connect(self.list_apps)
        self.btn_install.clicked.connect(self.install_package)
        self.btn_full_ui.clicked.connect(self.open_full_ui)
        self.btn_connect_adb.clicked.connect(self.connect_adb)
        self.btn_detect_adb.clicked.connect(self.detect_devices)
        self.btn_gamepad.clicked.connect(self.enable_gamepad)
        self.btn_apply_mode.clicked.connect(self.apply_display_mode)
        self.btn_back.clicked.connect(lambda: self._send_android_key(4))
        self.btn_home.clicked.connect(lambda: self._send_android_key(3))
        self.btn_recent.clicked.connect(lambda: self._send_android_key(187))
        self.btn_volume_down.clicked.connect(lambda: self._send_android_key(25))
        self.btn_volume_up.clicked.connect(lambda: self._send_android_key(24))
        self.service.status_changed.connect(self._status)
        self.service.log_line.connect(self._append)
        self.service.apps_loaded.connect(self.apps_loaded)
        self.adb.log_line.connect(self._append)
        self.adb.devices_loaded.connect(self._devices_loaded)

        self.refresh()
        # Nao consultar propriedades automaticamente: em Waydroid 1.6.x isso
        # pode perturbar um container FROZEN. O modo so e lido sob demanda.
        self.detect_devices()

    @property
    def single_window_mode(self) -> bool:
        return self._multi_windows is False

    def _append(self, message):
        self.log.appendPlainText(message)

    def refresh(self):
        """Atualiza apenas o estado observável; nao executa `waydroid prop get`."""
        self.service.refresh()

    def refresh_with_mode(self):
        """Acao explicita do usuario: atualiza estado e consulta o modo de janela."""
        self.refresh()
        self.service.get_multi_windows(self._mode_received)

    def _status(self, status):
        self.status = status
        self.state = status.state
        color = COLORS.get(status.state, "#a5a5b5")
        self.state_label.setText(f"Estado: <span style='color:{color}'>{status.state.value}</span>")
        self.hint.setText(status.message or f"Sessão: {status.session or '—'} | Container: {status.container or '—'} | IP: {status.ip or '—'}")
        session_active = status.state in (WaydroidState.RUNNING, WaydroidState.FROZEN)
        self.btn_start.setEnabled(not session_active and status.state is not WaydroidState.STARTING)
        self.btn_stop.setEnabled(session_active)
        self.btn_restart.setEnabled(session_active)
        self.state_changed.emit(status.state)

    def _mode_received(self, result):
        if not result.ok:
            self.mode_hint.setText("Não foi possível consultar o modo atual. Escolha uma opção e aplique manualmente.")
            return
        value = (result.stdout + result.stderr).strip().lower().split("=")[-1].strip()
        if value in ("true", "1"):
            self._multi_windows = True
        elif value in ("false", "0", ""):
            self._multi_windows = False
        else:
            self.mode_hint.setText("Não foi possível interpretar o modo atual. Você ainda pode aplicar uma opção abaixo.")
            return
        self.mode_combo.blockSignals(True)
        index = self.mode_combo.findData(self._multi_windows)
        if index >= 0:
            self.mode_combo.setCurrentIndex(index)
        self.mode_combo.blockSignals(False)
        self.mode_hint.setText(
            "Modo atual: janelas separadas." if self._multi_windows else
            "Modo atual: janela única — experiência de emulador."
        )

    def apply_display_mode(self):
        multi_windows = bool(self.mode_combo.currentData())
        question = QMessageBox.question(
            self, "Aplicar modo de exibição",
            "O Waydroid precisa reiniciar a sessão para aplicar esse modo. Deseja continuar?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if question != QMessageBox.StandardButton.Yes:
            return

        def property_done(result):
            if not result.ok:
                QMessageBox.warning(self, "Waydroid", "Não foi possível alterar a propriedade. Confira o log técnico.")
                return
            self.mode_hint.setText("Propriedade atualizada. Reiniciando a sessão Android…")
            self.service.restart(lambda restart_result: self._mode_restart_done(restart_result, multi_windows))

        self.service.set_multi_windows(multi_windows, property_done)

    def _mode_restart_done(self, result, multi_windows):
        if result.ok:
            self._multi_windows = multi_windows
            self.mode_hint.setText("Modo de janela única aplicado." if not multi_windows else "Modo de janelas separadas aplicado.")
        else:
            self.mode_hint.setText("A propriedade foi salva, mas a sessão não reiniciou corretamente. Veja o log técnico.")
        self.refresh()

    def switch_to_emulator_mode(self, callback=None):
        """Ativa janela única para manter os apps dentro da superfície Android."""
        if self._multi_windows is False:
            if callback:
                callback(True)
            return

        def property_done(result):
            if not result.ok:
                self.mode_hint.setText("Não foi possível ativar a janela única. Confira o log técnico.")
                if callback:
                    callback(False)
                return

            self.mode_hint.setText("Janela única configurada. Reiniciando a sessão Android…")

            def restarted(restart_result):
                if restart_result.ok:
                    self._multi_windows = False
                    self.mode_combo.setCurrentIndex(self.mode_combo.findData(False))
                    self.mode_hint.setText("Modo de janela única aplicado — experiência de emulador ativa.")
                else:
                    self.mode_hint.setText("A janela única foi configurada, mas o Waydroid não reiniciou corretamente.")
                self.refresh()
                if callback:
                    callback(bool(restart_result.ok))

            self.service.restart(restarted)

        self.service.set_multi_windows(False, property_done)

    def start(self):
        self._append("Solicitando início da sessão Waydroid…")
        self.service.start()

    def stop(self):
        if QMessageBox.question(self, "Parar Waydroid", "Deseja parar a sessão Android?") == QMessageBox.StandardButton.Yes:
            self.service.stop()

    def restart(self):
        if QMessageBox.question(self, "Reiniciar Waydroid", "Deseja reiniciar a sessão Android?") == QMessageBox.StandardButton.Yes:
            self.service.restart()

    def list_apps(self):
        self._append("Buscando aplicativos com o gerenciador nativo do Waydroid…")
        self.service.list_apps()

    def open_full_ui(self):
        self.service.show_full_ui()

    def _send_android_key(self, keycode):
        if self.state != WaydroidState.RUNNING:
            self._append("Inicie a sessão Waydroid para enviar comandos ao Android.")
            return
        if not self.adb.serial:
            QMessageBox.information(self, "Conecte o ADB", "Clique em ‘Conectar ADB Waydroid’ e aceite a autorização no Android para usar os atalhos.")
            return
        self.adb.send_keyevent(keycode)

    def connect_adb(self):
        self.adb_status.setText("ADB: solicitando conexão pelo Waydroid…")
        self.service.adb_connect(lambda _result: self.detect_devices())

    def detect_devices(self):
        self.adb.devices()

    def _devices_loaded(self, devices):
        ready = [device for device in devices if device.state == "device"]
        self.adb.serial = ready[0].serial if ready else None
        if ready:
            self.adb_status.setText(f"ADB: conectado ({ready[0].serial}).")
        else:
            self.adb_status.setText("ADB: nenhum dispositivo autorizado. Conecte e aceite a autorização na tela Android.")

    def install_package(self):
        path, _ = QFileDialog.getOpenFileName(self, "Instalar aplicativo Android", str(Path.home() / "Downloads"),
                                              "Pacotes Android (*.apk *.xapk)")
        if not path:
            return
        suffix = Path(path).suffix.lower()
        if suffix == ".apk":
            plan = plan_apk_installation(path)
            if not plan.ok:
                self._append(f"APK recusado: {plan.message}")
                QMessageBox.warning(self, "APK recusado", plan.message)
                return
            self._append(f"Instalando APK — {plan.message}")
            self.service.install_app(path, self._single_install_done)
            return
        if suffix != ".xapk":
            return
        if not self.adb.serial:
            QMessageBox.information(
                self, "Conecte o ADB primeiro",
                "Este XAPK contém vários APKs (base + splits). Clique em ‘Conectar ADB Waydroid’, "
                "aceite a autorização no Android e tente novamente.",
            )
            return
        self._install_xapk(path)

    def _single_install_done(self, result):
        if result.ok:
            QMessageBox.information(self, "Instalação", "APK instalado com sucesso.")
            self.list_apps()
        else:
            QMessageBox.warning(self, "Instalação", "A instalação falhou. Confira o log técnico; o APK pode ser incompatível com a arquitetura do Waydroid.")

    def _install_xapk(self, path):
        tempdir = tempfile.TemporaryDirectory(prefix="linuxdroid-xapk-")
        plan = plan_xapk_installation(path, Path(tempdir.name))
        if not plan.ok:
            tempdir.cleanup()
            self._append(f"XAPK recusado: {plan.message}")
            QMessageBox.warning(self, "XAPK recusado", plan.message)
            return
        self._xapk_tempdir = tempdir
        extracted = list(plan.apks)

        self._append(f"Instalando XAPK com {len(extracted)} split(s) — {plan.message}")
        self.adb.install_multiple(extracted, self._xapk_install_done)

    def _xapk_install_done(self, ok):
        if self._xapk_tempdir:
            self._xapk_tempdir.cleanup()
            self._xapk_tempdir = None
        if ok:
            QMessageBox.information(self, "Instalação", "XAPK instalado com sucesso.")
            self.list_apps()
        else:
            QMessageBox.warning(self, "Instalação", "Falha ao instalar o XAPK. Veja o log; pode haver incompatibilidade de arquitetura ou splits ausentes.")

    def enable_gamepad(self):
        answer = QMessageBox.question(
            self, "Ativar controle USB",
            "O Waydroid tentará ativar o repasse de eventos de controle USB. A sessão será reiniciada. "
            "O reconhecimento ainda depende do controle e do jogo. Continuar?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return

        def props_done(result):
            if not result.ok:
                QMessageBox.warning(self, "Gamepad", "Não foi possível aplicar as propriedades. Veja o log técnico.")
                return
            self.service.restart(lambda restarted: QMessageBox.information(
                self, "Gamepad", "Propriedades aplicadas." if restarted.ok else "Propriedades alteradas, mas a sessão não reiniciou corretamente."
            ))

        self.service.enable_gamepad_passthrough(props_done)

    def shutdown(self):
        if self._xapk_tempdir:
            self._xapk_tempdir.cleanup()
            self._xapk_tempdir = None
        self.service.shutdown()
        self.adb.shutdown()

    def closeEvent(self, event):
        self.shutdown()
        super().closeEvent(event)
