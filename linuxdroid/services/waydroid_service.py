"""Operações Waydroid via CLI do usuário; não chama sudo."""
from PySide6.QtCore import QObject, Signal

from ..models import WaydroidState, WaydroidStatus
from .process_runner import ProcessRunner
from .parsing import waydroid_status, parse_waydroid_apps


class WaydroidService(QObject):
    status_changed = Signal(object)
    log_line = Signal(str)
    apps_loaded = Signal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.runner = ProcessRunner(self)
        self.status = WaydroidState.UNKNOWN

    def _run(self, args, cb=None, timeout=25000):
        self.log_line.emit("$ waydroid " + " ".join(map(str, args)))

        def done(result):
            output = (result.stdout + result.stderr).strip()
            self.log_line.emit(output or ("Concluído." if result.ok else f"Falha: {result.error or result.exit_code}"))
            if cb:
                cb(result)

        self.runner.run("waydroid", args, done, timeout)

    def refresh(self):
        def done(result):
            if result.error == "not_found":
                status = WaydroidStatus(
                    WaydroidState.NOT_INSTALLED,
                    message="Waydroid não foi encontrado no PATH. Instale/configure-o no sistema antes de usar o launcher.",
                )
            else:
                status = waydroid_status(result.stdout, result.stderr, result.exit_code)
            self.status = status.state
            self.status_changed.emit(status)

        self._run(["status"], done, 12000)

    def start(self, callback=None):
        def done(result):
            self.refresh()
            if callback:
                callback(result)
        self._run(["session", "start"], done, 45000)

    def stop(self, callback=None):
        def done(result):
            self.refresh()
            if callback:
                callback(result)
        self._run(["session", "stop"], done, 30000)

    def restart(self, callback=None):
        def after_stop(_result):
            self._run(["session", "start"], lambda result: (self.refresh(), callback(result) if callback else None), 45000)
        self._run(["session", "stop"], after_stop, 30000)

    def list_apps(self):
        self._run(
            ["app", "list"],
            lambda result: self.apps_loaded.emit(parse_waydroid_apps(result.stdout)) if result.ok else self.apps_loaded.emit([]),
            30000,
        )

    def launch_app(self, package_id, callback=None):
        self._run(["app", "launch", package_id], callback, 30000)

    def install_app(self, apk_path, callback=None):
        self._run(["app", "install", str(apk_path)], callback, 120000)

    def remove_app(self, package_id, callback=None):
        self._run(["app", "remove", package_id], callback, 45000)

    def adb_connect(self, callback=None):
        # Waydroid 1.6+ controla a conexão ADB de forma própria; não depende de IP manual.
        self._run(["adb", "connect"], callback, 30000)

    def set_property(self, key, value, callback=None):
        self._run(["prop", "set", str(key), str(value)], callback, 15000)

    def enable_gamepad_passthrough(self, callback=None):
        def first_done(first_result):
            if not first_result.ok:
                if callback:
                    callback(first_result)
                return
            self.set_property("persist.waydroid.uevent", "true", callback)
        self.set_property("persist.waydroid.udev", "true", first_done)

    def show_full_ui(self, callback=None):
        self._run(["show-full-ui"], callback, 30000)

    def get_multi_windows(self, callback):
        self._run(["prop", "get", "persist.waydroid.multi_windows"], callback, 12000)

    def set_multi_windows(self, enabled, callback=None):
        value = "true" if enabled else "false"
        self._run(["prop", "set", "persist.waydroid.multi_windows", value], callback, 15000)

    def shutdown(self):
        self.runner.shutdown()
