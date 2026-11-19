"""Serviço Waydroid usado pela interface.

Todos os comandos `waydroid` usados pela interface passam pelo
``RuntimeManager`` via ponte Qt: ciclo de vida, apps, propriedades, ADB e
superfície. Não há mais subprocesso Waydroid direto neste serviço.
"""
from PySide6.QtCore import QObject, Signal

from ..models import WaydroidState, WaydroidStatus
from ..runtime.presentation import (
    operation_to_command_result,
    snapshot_to_waydroid_status,
)
from ..runtime.qt_bridge import RuntimeManagerBridge
from ..runtime.models import RuntimeOperation


class WaydroidService(QObject):
    status_changed = Signal(object)
    log_line = Signal(str)
    apps_loaded = Signal(object)

    def __init__(self, parent=None, *, backend=None):
        super().__init__(parent)
        self.status = WaydroidState.UNKNOWN
        self.bridge = RuntimeManagerBridge(backend=backend, parent=self)
        self.bridge.snapshot_changed.connect(self._on_snapshot)
        self.bridge.log_line.connect(lambda text: self.log_line.emit(text))
        self.bridge.operation_done.connect(self._on_operation_done)

    # ------------------------------------------------------------------
    # Integração com o RuntimeManager
    # ------------------------------------------------------------------
    def _on_snapshot(self, snapshot):
        status = snapshot_to_waydroid_status(snapshot)
        self.status = status.state
        self.status_changed.emit(status)

    def _on_operation_done(self, _token, result):
        if result.operation is RuntimeOperation.STATUS and not result.ok:
            if result.snapshot is not None:
                self._on_snapshot(result.snapshot)
        if not result.ok:
            self.log_line.emit(f"Falha: {result.message}")
        elif not result.skipped:
            self.log_line.emit(result.message or "Concluído.")

    def _runtime(self, operation, callback=None, timeout=None, **kwargs):
        def done(result):
            command = operation_to_command_result(result)
            if callback:
                callback(command)

        return self.bridge.request(operation, done, timeout, **kwargs)

    def refresh(self):
        """Atualiza sessão/container sem consultar propriedades Android."""
        self._runtime(RuntimeOperation.STATUS, timeout=12)

    def start(self, callback=None):
        self._runtime(RuntimeOperation.START, callback, 45)

    def stop(self, callback=None):
        self._runtime(RuntimeOperation.STOP, callback, 30)

    def restart(self, callback=None):
        self._runtime(RuntimeOperation.RESTART, callback, 75)

    def freeze(self, callback=None):
        """Congela o container pelo método oficial; exige cliente D-Bus."""
        self._runtime(RuntimeOperation.FREEZE, callback, 30)

    def unfreeze(self, callback=None):
        """Reativa um container congelado sem reiniciar a sessão."""
        self._runtime(RuntimeOperation.UNFREEZE, callback, 30)

    # ------------------------------------------------------------------
    # Operações auxiliares já migradas para o manager
    # ------------------------------------------------------------------
    def list_apps(self):
        def done(result):
            apps = []
            if result.ok:
                for item in result.data.get("apps", []):
                    name, package_id = item.get("name", ""), item.get("package_id", "")
                    if name and package_id:
                        apps.append((name, package_id))
            self.apps_loaded.emit(apps)

        self.bridge.request(RuntimeOperation.LIST_APPS, done, 30)

    def launch_app(self, package_id, callback=None):
        self._runtime(RuntimeOperation.LAUNCH_APP, callback, 45, package_id=package_id)

    def install_app(self, apk_path, callback=None):
        self._runtime(RuntimeOperation.INSTALL_APP, callback, 120, package_path=str(apk_path))

    def remove_app(self, package_id, callback=None):
        self._runtime(RuntimeOperation.REMOVE_APP, callback, 45, package_id=package_id)

    def adb_connect(self, callback=None):
        # Waydroid 1.6+ controla a conexão ADB de forma própria; não depende de IP manual.
        self._runtime(RuntimeOperation.ADB_CONNECT, callback, 30)

    def get_property(self, key, callback=None):
        self._runtime(RuntimeOperation.GET_PROPERTY, callback, 12, key=str(key))

    def set_property(self, key, value, callback=None):
        self._runtime(
            RuntimeOperation.SET_PROPERTY, callback, 15,
            key=str(key), value=str(value),
        )

    def enable_gamepad_passthrough(self, callback=None):
        def first_done(first_result):
            if not first_result.ok:
                if callback:
                    callback(first_result)
                return
            self.set_property("persist.waydroid.uevent", "true", callback)
        self.set_property("persist.waydroid.udev", "true", first_done)

    def show_full_ui(self, callback=None):
        self._runtime(RuntimeOperation.SHOW_FULL_UI, callback, 30)

    def get_multi_windows(self, callback):
        self.get_property("persist.waydroid.multi_windows", callback)

    def set_multi_windows(self, enabled, callback=None):
        value = "true" if enabled else "false"
        self.set_property("persist.waydroid.multi_windows", value, callback)

    def shutdown(self):
        self.bridge.shutdown()
