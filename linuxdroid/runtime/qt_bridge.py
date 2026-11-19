"""Ponte Qt entre a interface e o RuntimeManager.

A interface usa apenas esta ponte: nenhuma tela executa `waydroid`, `adb` ou
`busctl`. As chamadas do manager rodam em uma QThread para não travar a UI,
e os eventos voltam para a thread da interface por sinais do Qt.

O núcleo (`manager.py`, `backend.py`, modelos) continua sem PySide6; este é o
único módulo do pacote que importa Qt.
"""
from __future__ import annotations

import threading
from typing import Any, Callable, Optional

from PySide6.QtCore import QObject, QThread, Signal, Slot

from .manager import RuntimeManager
from .models import OperationResult, RuntimeEvent, RuntimeEventType, RuntimeOperation
from .waydroid_backend import WaydroidRuntimeBackend

__all__ = ["RuntimeManagerBridge"]


class _RuntimeWorker(QObject):
    """Executa operações do manager fora da thread da interface."""

    operation_finished = Signal(object, object)  # token, OperationResult

    def __init__(self, manager: RuntimeManager):
        super().__init__()
        self._manager = manager

    @Slot(object, object)
    def execute(self, token: int, request: tuple) -> None:
        # Formato antigo: (operation, timeout). Formato estendido aceita
        # argumentos nomeados para operações como launch_app(package_id=...).
        if len(request) == 3:
            operation, timeout, kwargs = request
        else:
            operation, timeout = request
            kwargs = {}
        method = getattr(self._manager, operation.value, None)
        if method is None:
            result = OperationResult(
                operation=operation,
                ok=False,
                message=f"Operação {operation.value} indisponível no RuntimeManager.",
            )
        else:
            result = method(timeout=timeout, **kwargs)
        self.operation_finished.emit(token, result)

    @Slot(object)
    def cancel(self, operation: RuntimeOperation) -> None:
        self._manager.cancel(operation)


class RuntimeManagerBridge(QObject):
    """Fachada Qt com sinais e callbacks para as telas."""

    operation_done = Signal(object, object)  # token, OperationResult
    snapshot_changed = Signal(object)       # RuntimeSnapshot
    event_occurred = Signal(object)         # RuntimeEvent
    log_line = Signal(str)

    execute_request = Signal(object, object)
    cancel_request = Signal(object)

    def __init__(
        self,
        backend: Optional[Any] = None,
        *,
        manager: Optional[RuntimeManager] = None,
        parent: Optional[QObject] = None,
    ):
        super().__init__(parent)
        self.manager = manager or RuntimeManager(backend or WaydroidRuntimeBackend())
        self._lock = threading.Lock()
        self._callbacks: dict[int, Callable[[OperationResult], None]] = {}
        self._next_token = 0
        self._closed = False

        self._thread = QThread(self)
        self._worker = _RuntimeWorker(self.manager)
        self._worker.moveToThread(self._thread)
        self.execute_request.connect(self._worker.execute)
        self.cancel_request.connect(self._worker.cancel)
        self._worker.operation_finished.connect(self._on_operation_finished)
        self._thread.start()
        self._unsubscribe = self.manager.subscribe(self._on_runtime_event)

    def request(
        self,
        operation: RuntimeOperation,
        callback: Optional[Callable[[OperationResult], None]] = None,
        timeout: Optional[float] = None,
        **kwargs: Any,
    ) -> int:
        """Envia uma intenção ao manager; ``callback`` roda na thread da UI.

        ``kwargs`` são repassados ao método correspondente do manager e
        existem para operações com parâmetros (por exemplo, ``package_id``).
        """
        if isinstance(operation, str):
            operation = RuntimeOperation(operation)
        with self._lock:
            if self._closed:
                raise RuntimeError("RuntimeManagerBridge foi encerrado.")
            self._next_token += 1
            token = self._next_token
            self._callbacks[token] = callback
        detail = " ".join(str(value) for value in kwargs.values())
        self.log_line.emit(f"$ runtime {operation.value}" + (f" {detail}" if detail else ""))
        self.execute_request.emit(token, (operation, timeout, kwargs))
        return token

    def cancel(self, operation: RuntimeOperation) -> None:
        self.cancel_request.emit(operation)

    def _on_operation_finished(self, token: int, result: OperationResult) -> None:
        with self._lock:
            callback = self._callbacks.pop(token, None)
        self.log_line.emit(result.message or f"Operação {result.operation.value} concluída.")
        self.operation_done.emit(token, result)
        if callback is not None:
            callback(result)

    def _on_runtime_event(self, event: RuntimeEvent) -> None:
        self.event_occurred.emit(event)
        if event.kind in (RuntimeEventType.SNAPSHOT_UPDATED, RuntimeEventType.OPERATION_SUCCEEDED):
            if event.snapshot is not None:
                self.snapshot_changed.emit(event.snapshot)
        if event.failure is not None:
            self.log_line.emit(f"{event.kind.value}: {event.failure.message}")

    def shutdown(self, *, wait: bool = True) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
            self._callbacks.clear()
        self._unsubscribe()
        self._thread.quit()
        if wait:
            self._thread.wait(3000)
        self.manager.shutdown(wait=wait)
