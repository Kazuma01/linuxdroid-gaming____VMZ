"""Execução assíncrona de comandos sem shell e sem elevação automática."""
import shutil, time
from PySide6.QtCore import QObject, QProcess, QTimer, QProcessEnvironment
from ..models import CommandResult

FORBIDDEN = {"sudo", "su", "pkexec", "doas", "run0", "gksu", "gksudo", "kdesu"}

class ProcessRunner(QObject):
    def __init__(self, parent=None):
        super().__init__(parent); self.active=set()
    def run(self, program, args=(), callback=None, timeout_ms=20000):
        args=[str(x) for x in args]
        if program.rsplit("/",1)[-1] in FORBIDDEN:
            raise PermissionError("O launcher não executa comandos privilegiados.")
        # Waydroid precisa ser executado com o Python do sistema. Quando o
        # launcher está dentro de .venv, o shebang via /usr/bin/env python
        # pode escolher o Python virtual, que não contém o módulo dbus do Arch.
        if program == "waydroid":
            exe = "/usr/bin/python"
            args = ["/usr/bin/waydroid", *args]
        else:
            exe=program if program.startswith("/") else shutil.which(program)
        if not exe:
            QTimer.singleShot(0, lambda: callback and callback(CommandResult(program,args,error="not_found",stderr=f"{program} não encontrado no PATH")))
            return
        proc=QProcess(self); self.active.add(proc); env=QProcessEnvironment.systemEnvironment(); env.insert("LC_MESSAGES","C"); proc.setProcessEnvironment(env); proc.setStandardInputFile(QProcess.nullDevice())
        timer=QTimer(self); timer.setSingleShot(True); started=time.monotonic(); done={"v":False,"timeout":False}
        def finish(code=-1,error=""):
            if done["v"]: return
            done["v"]=True; timer.stop()
            out=bytes(proc.readAllStandardOutput()).decode("utf-8","replace"); err=bytes(proc.readAllStandardError()).decode("utf-8","replace")
            if done["timeout"]: error="timeout"; code=-1
            result=CommandResult(program,args,code,out,err,error,int((time.monotonic()-started)*1000))
            self.active.discard(proc); proc.deleteLater(); timer.deleteLater()
            if callback: callback(result)
        proc.finished.connect(lambda code,status: finish(code,""))
        proc.errorOccurred.connect(lambda err: finish(-1,"failed_to_start") if err==QProcess.ProcessError.FailedToStart else None)
        timer.timeout.connect(lambda: (done.update(timeout=True),proc.kill()))
        timer.start(timeout_ms); proc.start(exe,args)
    def shutdown(self):
        for proc in tuple(self.active): proc.kill()
