"""ADB auxiliar para dispositivos e instalação de pacotes APK divididos."""
from PySide6.QtCore import QObject, Signal
from ..models import GameEntry
from .process_runner import ProcessRunner
from .parsing import parse_devices,parse_packages,is_valid_package
class AdbService(QObject):
    log_line=Signal(str); apps_loaded=Signal(object); devices_loaded=Signal(object)
    def __init__(self,parent=None): super().__init__(parent); self.runner=ProcessRunner(self); self.serial=None
    def _run(self,args,cb=None,timeout=20000):
        self.log_line.emit("$ adb "+" ".join(args))
        def done(r):
            self.log_line.emit((r.stdout+r.stderr).strip() or ("Concluído." if r.ok else f"Falha: {r.error or r.exit_code}"))
            if cb: cb(r)
        self.runner.run("adb",args,done,timeout)
    def devices(self):
        self._run(["devices","-l"],lambda r:self.devices_loaded.emit(parse_devices(r.stdout)) if r.ok else self.devices_loaded.emit([]))
    def connect(self, host, callback=None):
        if not host:
            self.log_line.emit("Waydroid não informou IP; não foi possível conectar ADB."); callback and callback(False); return
        target=host if ":" in host else host+":5555"
        self._run(["connect",target],lambda r:(callback(bool(r.ok and "connected to" in r.stdout.lower())) if callback else None),15000)
    def list_apps(self):
        args=[]
        if self.serial: args.extend(["-s",self.serial])
        args.extend(["shell","pm","list","packages"])
        self._run(args,lambda r:self.apps_loaded.emit([GameEntry(pkg.rsplit(".",1)[-1].replace("_"," ").title(),pkg,installed_status="installed") for pkg in parse_packages(r.stdout)]) if r.ok else self.apps_loaded.emit([]),30000)
    def install_multiple(self, apk_paths, callback=None):
        paths = [str(path) for path in apk_paths if str(path).lower().endswith(".apk")]
        if not paths:
            self.log_line.emit("Nenhum APK válido foi encontrado no pacote.")
            callback and callback(False)
            return
        args = []
        if self.serial:
            args.extend(["-s", self.serial])
        args.extend(["install-multiple", "-r", *paths])
        self._run(args, lambda result: callback(bool(result.ok and "Success" in result.stdout)) if callback else None, 120000)

    def send_keyevent(self, keycode, callback=None):
        if not self.serial:
            self.log_line.emit("ADB sem dispositivo autorizado; conecte o Waydroid antes de enviar teclas.")
            callback and callback(False)
            return
        self._run(["-s", self.serial, "shell", "input", "keyevent", str(int(keycode))],
                  lambda result: callback(bool(result.ok)) if callback else None, 12000)

    def launch(self,package_id,callback=None):
        if not is_valid_package(package_id):
            self.log_line.emit("Package ID inválido."); callback and callback(False); return
        args=[]
        if self.serial: args.extend(["-s",self.serial])
        args.extend(["shell","monkey","-p",package_id,"-c","android.intent.category.LAUNCHER","1"])
        self._run(args,lambda r:(callback(bool(r.ok and "Events injected: 1" in r.stdout)) if callback else None),25000)
    def shutdown(self): self.runner.shutdown()
