"""Adaptador falso para testes do Runtime Manager.

Não executa nada: apenas registra chamadas e aplica transições em memória.
Pode simular delays cooperativos, falhas, respostas inválidas e mudanças de
disponibilidade para exercitar timeout, cancelamento e recuperação.
"""
from __future__ import annotations

import threading
import time
from typing import Any, Callable, Optional

from ..services.parsing import (
    is_valid_package,
    is_valid_property_key,
    is_valid_property_value,
)
from .backend import OperationContext, RuntimeBackend
from .errors import RuntimeFailureError, make_failure
from .models import (
    AUXILIARY_FEATURES,
    CORE_FEATURES,
    OperationResult,
    RuntimeAvailability,
    RuntimeCapabilities,
    RuntimeErrorCode,
    RuntimeOperation,
    RuntimeSnapshot,
    RuntimeState,
)

__all__ = ["FakeRuntimeBackend"]

Effect = Callable[[OperationContext], None]


class FakeRuntimeBackend(RuntimeBackend):
    """Backend determinístico, sem subprocess e sem D-Bus."""

    def __init__(
        self,
        *,
        name: str = "fake",
        session: RuntimeState = RuntimeState.STOPPED,
        container: RuntimeState = RuntimeState.STOPPED,
        availability: RuntimeAvailability = RuntimeAvailability.AVAILABLE,
        capabilities: Optional[RuntimeCapabilities] = None,
        clock: Callable[[], float] = time.monotonic,
    ):
        self.name = name
        self.session_state = session
        self.container_state = container
        self.runtime_availability = availability
        self._capabilities = capabilities or RuntimeCapabilities(
            backend=name, supported=CORE_FEATURES | AUXILIARY_FEATURES
        )
        self._clock = clock
        self._lock = threading.Lock()
        self.calls: list[RuntimeOperation] = []
        self.contexts: list[OperationContext] = []
        self._effects: dict[RuntimeOperation, list[Effect]] = {}
        self._failures: dict[RuntimeOperation, list[RuntimeFailureError]] = {}
        self._responses: dict[RuntimeOperation, list[Any]] = {}
        self.delay = 0.0
        self.status_raises_for_unavailable = True
        self.details: dict[str, Any] = {}
        self.apps: list[tuple[str, str]] = []
        self.launched: list[str] = []
        self.installed: list[str] = []
        self.removed: list[str] = []
        self.properties: dict[str, str] = {}
        self.adb_connects: int = 0
        self.full_ui_shown: int = 0

    # ------------------------------------------------------------------
    # Configuração dos testes
    # ------------------------------------------------------------------
    def set_states(
        self,
        session: RuntimeState,
        container: RuntimeState,
        availability: Optional[RuntimeAvailability] = None,
    ) -> None:
        with self._lock:
            self.session_state = session
            self.container_state = container
            if availability is not None:
                self.runtime_availability = availability

    def set_delay(self, seconds: float) -> None:
        self.delay = max(0.0, float(seconds))

    def queue_effect(self, operation: RuntimeOperation, effect: Effect) -> None:
        with self._lock:
            self._effects.setdefault(operation, []).append(effect)

    def queue_failure(
        self,
        operation: RuntimeOperation,
        code: RuntimeErrorCode,
        message: str,
        *,
        retryable: bool = False,
    ) -> None:
        failure = make_failure(code, message, operation=operation, retryable=retryable)
        with self._lock:
            self._failures.setdefault(operation, []).append(RuntimeFailureError(failure))

    def queue_exception(self, operation: RuntimeOperation, exception: BaseException) -> None:
        with self._lock:
            self._failures.setdefault(operation, []).append(exception)

    def queue_response(self, operation: RuntimeOperation, response: Any) -> None:
        with self._lock:
            self._responses.setdefault(operation, []).append(response)

    def clear_scripting(self) -> None:
        with self._lock:
            self._effects.clear()
            self._failures.clear()
            self._responses.clear()

    def reset_calls(self) -> None:
        with self._lock:
            self.calls.clear()
            self.contexts.clear()

    def capabilities(self) -> RuntimeCapabilities:
        return self._capabilities

    # ------------------------------------------------------------------
    # Contrato do backend
    # ------------------------------------------------------------------
    def status(self, *, context: Optional[OperationContext] = None) -> RuntimeSnapshot:
        self._record(RuntimeOperation.STATUS, context)
        forced_response = self._consume_script(RuntimeOperation.STATUS, context)
        if forced_response is not None:
            return forced_response
        if self.runtime_availability in (
            RuntimeAvailability.NOT_FOUND,
            RuntimeAvailability.PERMISSION_DENIED,
            RuntimeAvailability.SERVICE_UNAVAILABLE,
        ) and self.status_raises_for_unavailable:
            code = {
                RuntimeAvailability.NOT_FOUND: RuntimeErrorCode.NOT_FOUND,
                RuntimeAvailability.PERMISSION_DENIED: RuntimeErrorCode.PERMISSION_DENIED,
                RuntimeAvailability.SERVICE_UNAVAILABLE: RuntimeErrorCode.SERVICE_UNAVAILABLE,
            }[self.runtime_availability]
            raise RuntimeFailureError(
                make_failure(code, f"Runtime {self.runtime_availability.value}.", retryable=True)
            )
        with self._lock:
            return RuntimeSnapshot(
                session_state=self.session_state,
                container_state=self.container_state,
                runtime_availability=self.runtime_availability,
                capabilities=self._capabilities,
                details=dict(self.details),
            )

    def start(self, *, context: Optional[OperationContext] = None) -> OperationResult:
        return self._mutate(RuntimeOperation.START, context)

    def stop(self, *, context: Optional[OperationContext] = None) -> OperationResult:
        return self._mutate(RuntimeOperation.STOP, context)

    def restart(self, *, context: Optional[OperationContext] = None) -> OperationResult:
        return self._mutate(RuntimeOperation.RESTART, context)

    def freeze(self, *, context: Optional[OperationContext] = None) -> OperationResult:
        return self._mutate(RuntimeOperation.FREEZE, context)

    def unfreeze(self, *, context: Optional[OperationContext] = None) -> OperationResult:
        return self._mutate(RuntimeOperation.UNFREEZE, context)

    # ------------------------------------------------------------------
    # Operações auxiliares: apenas registros em memória, sem subprocess.
    # ------------------------------------------------------------------
    def list_apps(self, *, context: Optional[OperationContext] = None) -> OperationResult:
        self._record(RuntimeOperation.LIST_APPS, context)
        response = self._consume_script(RuntimeOperation.LIST_APPS, context)
        if response is not None:
            return response
        return OperationResult(
            RuntimeOperation.LIST_APPS,
            True,
            f"{len(self.apps)} aplicativo(s) no backend falso.",
            data={
                "apps": [
                    {"name": name, "package_id": package_id}
                    for name, package_id in self.apps
                ]
            },
        )

    def launch_app(
        self, package_id: str, *, context: Optional[OperationContext] = None
    ) -> OperationResult:
        self._record(RuntimeOperation.LAUNCH_APP, context)
        response = self._consume_script(RuntimeOperation.LAUNCH_APP, context)
        if response is not None:
            return response
        if not is_valid_package(package_id):
            raise RuntimeFailureError(
                make_failure(
                    RuntimeErrorCode.INVALID_ARGUMENT,
                    "Package ID inválido.",
                    operation=RuntimeOperation.LAUNCH_APP,
                )
            )
        with self._lock:
            self.launched.append(package_id)
        return OperationResult(
            RuntimeOperation.LAUNCH_APP,
            True,
            f"Launch registrado no backend falso: {package_id}.",
            data={"package_id": package_id},
        )

    def install_app(
        self, package_path: str, *, context: Optional[OperationContext] = None
    ) -> OperationResult:
        self._record(RuntimeOperation.INSTALL_APP, context)
        response = self._consume_script(RuntimeOperation.INSTALL_APP, context)
        if response is not None:
            return response
        with self._lock:
            self.installed.append(str(package_path))
        return OperationResult(
            RuntimeOperation.INSTALL_APP,
            True,
            "Instalação registrada no backend falso.",
            data={"path": str(package_path)},
        )

    def remove_app(
        self, package_id: str, *, context: Optional[OperationContext] = None
    ) -> OperationResult:
        self._record(RuntimeOperation.REMOVE_APP, context)
        response = self._consume_script(RuntimeOperation.REMOVE_APP, context)
        if response is not None:
            return response
        if not is_valid_package(package_id):
            raise RuntimeFailureError(
                make_failure(
                    RuntimeErrorCode.INVALID_ARGUMENT,
                    "Package ID inválido.",
                    operation=RuntimeOperation.REMOVE_APP,
                )
            )
        with self._lock:
            self.removed.append(package_id)
            self.apps = [(n, p) for n, p in self.apps if p != package_id]
        return OperationResult(
            RuntimeOperation.REMOVE_APP,
            True,
            f"Remoção registrada no backend falso: {package_id}.",
            data={"package_id": package_id},
        )

    def get_property(
        self, key: str, *, context: Optional[OperationContext] = None
    ) -> OperationResult:
        self._record(RuntimeOperation.GET_PROPERTY, context)
        response = self._consume_script(RuntimeOperation.GET_PROPERTY, context)
        if response is not None:
            return response
        if not is_valid_property_key(key):
            raise RuntimeFailureError(
                make_failure(
                    RuntimeErrorCode.INVALID_ARGUMENT,
                    "Chave de propriedade inválida.",
                    operation=RuntimeOperation.GET_PROPERTY,
                )
            )
        with self._lock:
            value = self.properties.get(key, "")
        return OperationResult(
            RuntimeOperation.GET_PROPERTY,
            True,
            f"Propriedade {key} consultada no backend falso.",
            data={"key": key, "value": value},
        )

    def set_property(
        self, key: str, value: str, *, context: Optional[OperationContext] = None
    ) -> OperationResult:
        self._record(RuntimeOperation.SET_PROPERTY, context)
        response = self._consume_script(RuntimeOperation.SET_PROPERTY, context)
        if response is not None:
            return response
        if not is_valid_property_key(key) or not is_valid_property_value(value):
            raise RuntimeFailureError(
                make_failure(
                    RuntimeErrorCode.INVALID_ARGUMENT,
                    "Chave ou valor de propriedade inválido.",
                    operation=RuntimeOperation.SET_PROPERTY,
                )
            )
        with self._lock:
            self.properties[key] = value
        return OperationResult(
            RuntimeOperation.SET_PROPERTY,
            True,
            f"Propriedade {key} registrada no backend falso.",
            data={"key": key, "value": value},
        )

    def adb_connect(self, *, context: Optional[OperationContext] = None) -> OperationResult:
        self._record(RuntimeOperation.ADB_CONNECT, context)
        response = self._consume_script(RuntimeOperation.ADB_CONNECT, context)
        if response is not None:
            return response
        with self._lock:
            self.adb_connects += 1
        return OperationResult(
            RuntimeOperation.ADB_CONNECT,
            True,
            "Conexão ADB registrada no backend falso.",
        )

    def show_full_ui(self, *, context: Optional[OperationContext] = None) -> OperationResult:
        self._record(RuntimeOperation.SHOW_FULL_UI, context)
        response = self._consume_script(RuntimeOperation.SHOW_FULL_UI, context)
        if response is not None:
            return response
        with self._lock:
            self.full_ui_shown += 1
        return OperationResult(
            RuntimeOperation.SHOW_FULL_UI,
            True,
            "Superfície Android registrada no backend falso.",
        )

    def diagnostics(self, *, context: Optional[OperationContext] = None) -> OperationResult:
        self._record(RuntimeOperation.DIAGNOSTICS, context)
        response = self._consume_script(RuntimeOperation.DIAGNOSTICS, context)
        if response is not None:
            return response
        with self._lock:
            return OperationResult(
                RuntimeOperation.DIAGNOSTICS,
                True,
                "Diagnóstico somente leitura no backend falso.",
                data={
                    "session": self.session_state.value,
                    "container": self.container_state.value,
                    "availability": self.runtime_availability.value,
                    "details": dict(self.details),
                },
            )

    # ------------------------------------------------------------------
    # Interno
    # ------------------------------------------------------------------
    def _record(self, operation: RuntimeOperation, context: Optional[OperationContext]) -> None:
        with self._lock:
            self.calls.append(operation)
            if context is not None:
                self.contexts.append(context)

    def _wait(self, context: Optional[OperationContext]) -> None:
        if self.delay <= 0:
            return
        if context is None:
            time.sleep(self.delay)
            return
        context.cancel_event.wait(self.delay)
        context.raise_if_cancelled()

    def _pop(self, container: dict, operation: RuntimeOperation) -> Optional[Any]:
        with self._lock:
            items = container.get(operation) or []
            return items.pop(0) if items else None

    def _consume_script(self, operation: RuntimeOperation, context: Optional[OperationContext]) -> Any:
        effect = self._pop(self._effects, operation)
        if effect is not None:
            effect(context)
        self._wait(context)
        exception = self._pop(self._failures, operation)
        if exception is not None:
            raise exception
        response = self._pop(self._responses, operation)
        return response

    def _mutate(
        self, operation: RuntimeOperation, context: Optional[OperationContext]
    ) -> OperationResult:
        self._record(operation, context)
        response = self._consume_script(operation, context)
        if response is not None:
            return response

        with self._lock:
            if operation in (RuntimeOperation.START, RuntimeOperation.RESTART):
                self.session_state = RuntimeState.RUNNING
                self.container_state = RuntimeState.RUNNING
            elif operation is RuntimeOperation.STOP:
                self.session_state = RuntimeState.STOPPED
                self.container_state = RuntimeState.STOPPED
            elif operation is RuntimeOperation.FREEZE:
                self.container_state = RuntimeState.FROZEN
            elif operation is RuntimeOperation.UNFREEZE:
                self.container_state = RuntimeState.RUNNING
        return OperationResult(
            operation=operation,
            ok=True,
            message=f"{operation.value} concluído no backend falso.",
        )
