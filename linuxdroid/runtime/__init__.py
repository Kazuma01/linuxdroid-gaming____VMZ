"""Runtime Manager independente da interface gráfica.

Camadas:

    UI → RuntimeManager → RuntimeBackend → Android Runtime

Este pacote não importa PySide6 e não executa comandos por conta própria:
subprocessos e D-Bus são injetados no `WaydroidRuntimeBackend`.
"""
from .models import (
    RuntimeState,
    RuntimeAvailability,
    RuntimeOperation,
    RuntimeFeature,
    OperationStatus,
    RuntimeEventType,
    CORE_FEATURES,
    AUXILIARY_FEATURES,
    RuntimeCapabilities,
    RuntimeSnapshot,
    OperationResult,
    RuntimeEvent,
    OperationRecord,
)
from .errors import RuntimeErrorCode, RuntimeFailure, RuntimeFailureError, make_failure, map_exception
from .backend import RuntimeBackend, FutureRuntimeOperations, OperationContext
from .manager import RuntimeManager
from .fake_backend import FakeRuntimeBackend
from .waydroid_backend import (
    DBUS_SERVICE,
    DBUS_PATH,
    DBUS_INTERFACE,
    CommandRunner,
    DBusClient,
    SubprocessCommandRunner,
    SystemBusDBusClient,
    WaydroidRuntimeBackend,
    parse_status_output,
)

__all__ = [
    "RuntimeState",
    "RuntimeAvailability",
    "RuntimeOperation",
    "RuntimeFeature",
    "OperationStatus",
    "RuntimeEventType",
    "CORE_FEATURES",
    "AUXILIARY_FEATURES",
    "RuntimeCapabilities",
    "RuntimeSnapshot",
    "OperationResult",
    "RuntimeEvent",
    "OperationRecord",
    "RuntimeErrorCode",
    "RuntimeFailure",
    "RuntimeFailureError",
    "make_failure",
    "map_exception",
    "RuntimeBackend",
    "FutureRuntimeOperations",
    "OperationContext",
    "RuntimeManager",
    "FakeRuntimeBackend",
    "DBUS_SERVICE",
    "DBUS_PATH",
    "DBUS_INTERFACE",
    "CommandRunner",
    "DBusClient",
    "SubprocessCommandRunner",
    "SystemBusDBusClient",
    "WaydroidRuntimeBackend",
    "parse_status_output",
]
