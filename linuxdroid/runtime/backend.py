"""Contrato dos adaptadores de runtime.

Regras desta camada:

* um adaptador recebe todas as dependências externas por injeção;
* um adaptador nunca importa PySide6 e nunca chama ``sudo``;
* um adaptador devolve modelos puros ou levanta ``RuntimeFailureError``;
* operações futuras ficam explícitas e **falham honestamente** até serem
  implementadas — não existem métodos que finjam sucesso.
"""
from __future__ import annotations

import threading
import time
from abc import ABC, abstractmethod
from typing import Any, Optional

from .errors import RuntimeFailureError, make_failure
from .models import (
    OperationResult,
    RuntimeAvailability,
    RuntimeCapabilities,
    RuntimeErrorCode,
    RuntimeFeature,
    RuntimeOperation,
    RuntimeSnapshot,
    RuntimeState,
)

__all__ = [
    "OperationContext",
    "RuntimeBackend",
    "FutureRuntimeOperations",
]


class OperationContext:
    """Contexto cooperativo passado pelo manager a cada chamada.

    Cancelamento é cooperativo: o adaptador pode checar ``cancelled`` e
    interromper uma espera. O manager também cancela o ``Future`` quando
    possível. Isso evita ``kill()`` de processos e mantém o contrato portátil.
    """

    def __init__(
        self,
        operation: RuntimeOperation,
        timeout: float,
        cancel_event: Optional[threading.Event] = None,
        *,
        clock: Any = time.monotonic,
        manager: Any = None,
    ):
        self.operation = operation
        self.timeout = float(timeout)
        self.cancel_event = cancel_event or threading.Event()
        self._clock = clock
        self.started_at = float(clock())
        self.manager = manager

    @property
    def cancelled(self) -> bool:
        return self.cancel_event.is_set()

    def remaining(self) -> float:
        return max(0.0, self.timeout - (float(self._clock()) - self.started_at))

    def raise_if_cancelled(self) -> None:
        if self.cancelled:
            raise RuntimeFailureError(
                make_failure(
                    RuntimeErrorCode.CANCELED,
                    f"Operação {self.operation.value} cancelada.",
                    operation=self.operation,
                )
            )


class FutureRuntimeOperations(ABC):
    """Extensões previstas na arquitetura, ainda não implementadas.

    A existência dos métodos define o ponto de extensão para futuros
    adaptadores. A implementação padrão **recusa** a chamada com
    ``NOT_IMPLEMENTED``; portanto nenhum adaptador atual afirma fazer algo
    que não faz.
    """

    def _not_implemented(self, feature: RuntimeFeature) -> None:
        raise RuntimeFailureError(
            make_failure(
                RuntimeErrorCode.NOT_IMPLEMENTED,
                f"{feature.value}: operação prevista, ainda não implementada.",
                detail="Extensão reservada para uma próxima versão do Runtime Manager.",
            )
        )

    def install_app(self, package_path: str, *, context: Optional[OperationContext] = None) -> OperationResult:
        self._not_implemented(RuntimeFeature.INSTALL_APP)

    def launch_app(self, package_id: str, *, context: Optional[OperationContext] = None) -> OperationResult:
        self._not_implemented(RuntimeFeature.LAUNCH_APP)

    def list_apps(self, *, context: Optional[OperationContext] = None) -> OperationResult:
        self._not_implemented(RuntimeFeature.LIST_APPS)

    def remove_app(self, package_id: str, *, context: Optional[OperationContext] = None) -> OperationResult:
        self._not_implemented(RuntimeFeature.REMOVE_APP)

    def get_property(self, key: str, *, context: Optional[OperationContext] = None) -> OperationResult:
        self._not_implemented(RuntimeFeature.GET_PROPERTY)

    def set_property(self, key: str, value: str, *, context: Optional[OperationContext] = None) -> OperationResult:
        self._not_implemented(RuntimeFeature.SET_PROPERTY)

    def adb_connect(self, *, context: Optional[OperationContext] = None) -> OperationResult:
        self._not_implemented(RuntimeFeature.ADB_CONNECT)

    def show_full_ui(self, *, context: Optional[OperationContext] = None) -> OperationResult:
        self._not_implemented(RuntimeFeature.SHOW_FULL_UI)

    def create_instance(self, name: str, *, context: Optional[OperationContext] = None) -> OperationResult:
        self._not_implemented(RuntimeFeature.CREATE_INSTANCE)

    def clone_instance(self, source: str, *, context: Optional[OperationContext] = None) -> OperationResult:
        self._not_implemented(RuntimeFeature.CLONE_INSTANCE)

    def backup(self, destination: str, *, context: Optional[OperationContext] = None) -> OperationResult:
        self._not_implemented(RuntimeFeature.BACKUP)

    def restore(self, source: str, *, context: Optional[OperationContext] = None) -> OperationResult:
        self._not_implemented(RuntimeFeature.RESTORE)

    def diagnostics(self, *, context: Optional[OperationContext] = None) -> OperationResult:
        self._not_implemented(RuntimeFeature.DIAGNOSTICS)


class RuntimeBackend(FutureRuntimeOperations, ABC):
    """Interface mínima que todo adaptador precisa implementar."""

    name: str = "base"

    @abstractmethod
    def status(self, *, context: Optional[OperationContext] = None) -> RuntimeSnapshot:
        """Consulta sessão e container **separadamente**."""

    @abstractmethod
    def start(self, *, context: Optional[OperationContext] = None) -> OperationResult:
        """Inicia a sessão do runtime."""

    @abstractmethod
    def stop(self, *, context: Optional[OperationContext] = None) -> OperationResult:
        """Encerra a sessão do runtime."""

    @abstractmethod
    def restart(self, *, context: Optional[OperationContext] = None) -> OperationResult:
        """Reinicia a sessão do runtime."""

    @abstractmethod
    def freeze(self, *, context: Optional[OperationContext] = None) -> OperationResult:
        """Congela o container sem encerrar a sessão."""

    @abstractmethod
    def unfreeze(self, *, context: Optional[OperationContext] = None) -> OperationResult:
        """Reativa um container congelado."""

    @abstractmethod
    def capabilities(self) -> RuntimeCapabilities:
        """Declara somente as operações realmente disponíveis."""


def unavailable_snapshot(
    availability: RuntimeAvailability,
    message: str,
    capabilities: RuntimeCapabilities,
) -> RuntimeSnapshot:
    """Helper para adaptadores que não conseguem nem consultar o runtime."""
    return RuntimeSnapshot(
        session_state=RuntimeState.UNKNOWN,
        container_state=RuntimeState.UNKNOWN,
        runtime_availability=availability,
        capabilities=capabilities,
        details={"reason": message},
    )
