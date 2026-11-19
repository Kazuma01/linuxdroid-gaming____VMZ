"""Integração opcional com Phantom (mapeador de teclado/mouse para Waydroid)."""
import shutil
from PySide6.QtCore import QObject, Signal
from .process_runner import ProcessRunner


class PhantomService(QObject):
    log_line = Signal(str)
    status_ready = Signal(str, bool)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.runner = ProcessRunner(self)

    @staticmethod
    def available() -> bool:
        return bool(shutil.which("phantom"))

    @staticmethod
    def gui_available() -> bool:
        return bool(shutil.which("phantom-gui"))

    def _run(self, args, callback=None, timeout=15000):
        self.log_line.emit("$ phantom " + " ".join(map(str, args)))

        def done(result):
            output = (result.stdout + result.stderr).strip()
            if output:
                self.log_line.emit(output)
            elif not result.ok:
                self.log_line.emit(f"Falha ao executar Phantom: {result.error or result.exit_code}")
            if callback:
                callback(result)

        self.runner.run("phantom", args, done, timeout)

    def status(self, callback=None):
        if not self.available():
            self.status_ready.emit("Phantom não encontrado. Instale o mapeador opcional para ativar teclado/mouse no Waydroid.", False)
            if callback:
                callback(False)
            return

        def done(result):
            text = (result.stdout + result.stderr).strip() or ("Phantom respondeu." if result.ok else "Daemon Phantom indisponível.")
            self.status_ready.emit(text, result.ok)
            if callback:
                callback(bool(result.ok))

        self._run(["status"], done)

    def audit_profile(self, path, callback=None):
        self._run(["audit", str(path)], callback, 30000)

    def load_profile(self, path, callback=None):
        self._run(["load", str(path)], callback, 30000)

    def enter_capture(self, callback=None):
        self._run(["enter-capture"], callback)

    def exit_capture(self, callback=None):
        self._run(["exit-capture"], callback)

    def toggle_mouse(self, callback=None):
        """Alterna entre toque de menu e mira do mouse (atalho F1 do Phantom)."""
        self._run(["toggle-mouse"], callback)

    def open_gui(self):
        if not self.gui_available():
            self.log_line.emit("phantom-gui não encontrado. Instale o pacote completo do Phantom.")
            return
        self.runner.run("phantom-gui", [], lambda result: self.log_line.emit(result.text or "Editor Phantom encerrado."), 21600000)

    def shutdown(self):
        self.runner.shutdown()
