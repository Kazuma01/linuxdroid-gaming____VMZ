"""Modelos puros do Runtime Manager.

Nenhum modelo aqui importa Qt, subprocess, D-Bus ou qualquer serviço externo.
Eles são a linguagem comum entre a interface, o RuntimeManager e os
adaptadores de runtime.

A separação mais importante deste módulo é explícita: ``session_state`` e
``container_state`` são campos independentes. ``Session: RUNNING`` com
``Container: FROZEN`` é um estado válido e deve ser representado como tal,
nunca reduzido a um único ``RuntimeState``.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Optional


class RuntimeState(str, Enum):
    """Estado de um dos dois planos observáveis: sessão ou container."""

    NOT_INSTALLED = "NOT_INSTALLED"
    NOT_INITIALIZED = "NOT_INITIALIZED"
    STOPPED = "STOPPED"
    STARTING = "STARTING"
    RUNNING = "RUNNING"
    FREEZING = "FREEZING"
    FROZEN = "FROZEN"
    STOPPING = "STOPPING"
    ERROR = "ERROR"
    UNKNOWN = "UNKNOWN"


class RuntimeAvailability(str, Enum):
    """Disponibilidade do runtime no host, independente do seu estado."""

    AVAILABLE = "AVAILABLE"
    NOT_FOUND = "NOT_FOUND"
    PERMISSION_DENIED = "PERMISSION_DENIED"
    SERVICE_UNAVAILABLE = "SERVICE_UNAVAILABLE"
    NOT_INITIALIZED = "NOT_INITIALIZED"
    UNKNOWN = "UNKNOWN"


class RuntimeOperation(str, Enum):
    """Operações implementadas nesta versão do Runtime Manager."""

    STATUS = "status"
    START = "start"
    STOP = "stop"
    RESTART = "restart"
    FREEZE = "freeze"
    UNFREEZE = "unfreeze"
    RECOVER = "recover"
    LIST_APPS = "list_apps"
    LAUNCH_APP = "launch_app"
    INSTALL_APP = "install_app"
    REMOVE_APP = "remove_app"
    GET_PROPERTY = "get_property"
    SET_PROPERTY = "set_property"
    ADB_CONNECT = "adb_connect"
    SHOW_FULL_UI = "show_full_ui"
    DIAGNOSTICS = "diagnostics"


class RuntimeFeature(str, Enum):
    """ Capacidades anunciadas por um adaptador.

    Os valores além de STATUS/START/STOP/RESTART/FREEZE/UNFREEZE/RECOVER são
    extensões previstas. Um adaptador só deve anunciá-las quando a operação
    correspondente existir de fato — nunca para fingir funcionalidade.
    """

    STATUS = "status"
    START = "start"
    STOP = "stop"
    RESTART = "restart"
    FREEZE = "freeze"
    UNFREEZE = "unfreeze"
    RECOVER = "recover"
    INSTALL_APP = "install_app"
    LAUNCH_APP = "launch_app"
    LIST_APPS = "list_apps"
    REMOVE_APP = "remove_app"
    GET_PROPERTY = "get_property"
    SET_PROPERTY = "set_property"
    ADB_CONNECT = "adb_connect"
    SHOW_FULL_UI = "show_full_ui"
    CREATE_INSTANCE = "create_instance"
    CLONE_INSTANCE = "clone_instance"
    BACKUP = "backup"
    RESTORE = "restore"
    DIAGNOSTICS = "diagnostics"


class OperationStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    TIMED_OUT = "timed_out"
    CANCELED = "canceled"
    SKIPPED = "skipped"


class RuntimeEventType(str, Enum):
    SNAPSHOT_UPDATED = "snapshot_updated"
    OPERATION_STARTED = "operation_started"
    OPERATION_SUCCEEDED = "operation_succeeded"
    OPERATION_FAILED = "operation_failed"
    OPERATION_CANCELED = "operation_canceled"
    OPERATION_TIMED_OUT = "operation_timed_out"
    OPERATION_SKIPPED = "operation_skipped"
    ERROR_CLEARED = "error_cleared"
    RECOVERED = "recovered"


class RuntimeErrorCode(str, Enum):
    """Códigos estáveis para erros estruturados, traduzíveis pela UI."""

    NOT_FOUND = "not_found"
    PERMISSION_DENIED = "permission_denied"
    SERVICE_UNAVAILABLE = "service_unavailable"
    NOT_INITIALIZED = "not_initialized"
    TIMEOUT = "timeout"
    INVALID_RESPONSE = "invalid_response"
    UNSUPPORTED_OPERATION = "unsupported_operation"
    INVALID_TRANSITION = "invalid_transition"
    DUPLICATE_OPERATION = "duplicate_operation"
    INVALID_ARGUMENT = "invalid_argument"
    CANCELED = "canceled"
    NOT_IMPLEMENTED = "not_implemented"
    BACKEND_ERROR = "backend_error"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class RuntimeFailure:
    """Erro estruturado, sem texto de terminal cru exposto à interface."""

    code: RuntimeErrorCode
    message: str
    operation: Optional[RuntimeOperation] = None
    detail: str = ""
    retryable: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code.value,
            "message": self.message,
            "operation": self.operation.value if self.operation else None,
            "detail": self.detail,
            "retryable": self.retryable,
        }


@dataclass(frozen=True)
class RuntimeCapabilities:
    """O que o adaptador afirma suportar — nunca o que se deseja suportar."""

    backend: str = "unknown"
    supported: frozenset[RuntimeFeature] = field(default_factory=frozenset)
    experimental: frozenset[RuntimeFeature] = field(default_factory=frozenset)
    notes: str = ""

    def supports(self, feature: RuntimeFeature) -> bool:
        return feature in self.supported

    def to_dict(self) -> dict[str, Any]:
        return {
            "backend": self.backend,
            "supported": sorted(item.value for item in self.supported),
            "experimental": sorted(item.value for item in self.experimental),
            "notes": self.notes,
        }


CORE_FEATURES = frozenset(
    {
        RuntimeFeature.STATUS,
        RuntimeFeature.START,
        RuntimeFeature.STOP,
        RuntimeFeature.RESTART,
        RuntimeFeature.FREEZE,
        RuntimeFeature.UNFREEZE,
        RuntimeFeature.RECOVER,
    }
)

# Extensões implementadas nesta versão. Um adaptador só as anuncia quando o
# comando correspondente existe de fato; as demais extensões do contrato
# (instâncias, backup/restore) permanecem recusadas com NOT_IMPLEMENTED.
AUXILIARY_FEATURES = frozenset(
    {
        RuntimeFeature.LIST_APPS,
        RuntimeFeature.LAUNCH_APP,
        RuntimeFeature.INSTALL_APP,
        RuntimeFeature.REMOVE_APP,
        RuntimeFeature.GET_PROPERTY,
        RuntimeFeature.SET_PROPERTY,
        RuntimeFeature.ADB_CONNECT,
        RuntimeFeature.SHOW_FULL_UI,
        RuntimeFeature.DIAGNOSTICS,
    }
)


@dataclass(frozen=True)
class RuntimeSnapshot:
    """Foto do runtime. Sessão e container são lidos separadamente."""

    session_state: RuntimeState = RuntimeState.UNKNOWN
    container_state: RuntimeState = RuntimeState.UNKNOWN
    runtime_availability: RuntimeAvailability = RuntimeAvailability.UNKNOWN
    active_operation: Optional[RuntimeOperation] = None
    last_error: Optional[RuntimeFailure] = None
    capabilities: RuntimeCapabilities = field(
        default_factory=lambda: RuntimeCapabilities(backend="unknown")
    )
    taken_at: float = field(default_factory=time.time)
    details: dict[str, Any] = field(default_factory=dict)

    @property
    def is_frozen(self) -> bool:
        return self.container_state in (RuntimeState.FROZEN, RuntimeState.FREEZING)

    @property
    def is_running(self) -> bool:
        return (
            self.session_state is RuntimeState.RUNNING
            and self.container_state is RuntimeState.RUNNING
        )

    @property
    def is_stopped(self) -> bool:
        return self.container_state in (
            RuntimeState.STOPPED,
            RuntimeState.NOT_INITIALIZED,
            RuntimeState.NOT_INSTALLED,
        )

    @property
    def effective_state(self) -> RuntimeState:
        """Estado resumido para exibição, sem apagar a distinção dos campos.

        O resumo existe apenas para a UI; decisões de transição devem usar
        ``session_state`` e ``container_state`` diretamente.
        """

        if self.runtime_availability is RuntimeAvailability.NOT_FOUND:
            return RuntimeState.NOT_INSTALLED
        if self.session_state is RuntimeState.NOT_INITIALIZED:
            return RuntimeState.NOT_INITIALIZED
        if self.is_frozen:
            return self.container_state
        if self.session_state in (RuntimeState.STARTING, RuntimeState.STOPPING):
            return self.session_state
        if self.is_stopped:
            return RuntimeState.STOPPED
        if self.container_state is RuntimeState.RUNNING:
            return RuntimeState.RUNNING
        if self.session_state is RuntimeState.ERROR or self.container_state is RuntimeState.ERROR:
            return RuntimeState.ERROR
        return RuntimeState.UNKNOWN

    def with_error(self, error: Optional[RuntimeFailure]) -> "RuntimeSnapshot":
        return RuntimeSnapshot(
            session_state=self.session_state,
            container_state=self.container_state,
            runtime_availability=self.runtime_availability,
            active_operation=self.active_operation,
            last_error=error,
            capabilities=self.capabilities,
            taken_at=self.taken_at,
            details=dict(self.details),
        )

    def with_operation(self, operation: Optional[RuntimeOperation]) -> "RuntimeSnapshot":
        return RuntimeSnapshot(
            session_state=self.session_state,
            container_state=self.container_state,
            runtime_availability=self.runtime_availability,
            active_operation=operation,
            last_error=self.last_error,
            capabilities=self.capabilities,
            taken_at=self.taken_at,
            details=dict(self.details),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "session_state": self.session_state.value,
            "container_state": self.container_state.value,
            "runtime_availability": self.runtime_availability.value,
            "active_operation": self.active_operation.value if self.active_operation else None,
            "last_error": self.last_error.to_dict() if self.last_error else None,
            "capabilities": self.capabilities.to_dict(),
            "effective_state": self.effective_state.value,
            "taken_at": self.taken_at,
        }


@dataclass(frozen=True)
class OperationResult:
    """Resultado padronizado de qualquer operação do RuntimeManager."""

    operation: RuntimeOperation
    ok: bool
    message: str = ""
    failure: Optional[RuntimeFailure] = None
    snapshot: Optional[RuntimeSnapshot] = None
    data: dict[str, Any] = field(default_factory=dict)
    started_at: float = 0.0
    duration_ms: int = 0
    skipped: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "operation": self.operation.value,
            "ok": self.ok,
            "message": self.message,
            "failure": self.failure.to_dict() if self.failure else None,
            "snapshot": self.snapshot.to_dict() if self.snapshot else None,
            "skipped": self.skipped,
            "duration_ms": self.duration_ms,
        }


@dataclass(frozen=True)
class RuntimeEvent:
    """Evento observável para a interface (substitui sinais espalhados)."""

    kind: RuntimeEventType
    timestamp: float
    operation: Optional[RuntimeOperation] = None
    message: str = ""
    failure: Optional[RuntimeFailure] = None
    snapshot: Optional[RuntimeSnapshot] = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind.value,
            "timestamp": self.timestamp,
            "operation": self.operation.value if self.operation else None,
            "message": self.message,
            "failure": self.failure.to_dict() if self.failure else None,
        }


@dataclass(frozen=True)
class OperationRecord:
    """Entrada do histórico — operações concluídas ou recusadas."""

    operation: RuntimeOperation
    status: OperationStatus
    started_at: float
    finished_at: Optional[float] = None
    message: str = ""
    failure: Optional[RuntimeFailure] = None
    duration_ms: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "operation": self.operation.value,
            "status": self.status.value,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "message": self.message,
            "failure": self.failure.to_dict() if self.failure else None,
            "duration_ms": self.duration_ms,
        }


Listener = Callable[[RuntimeEvent], None]
