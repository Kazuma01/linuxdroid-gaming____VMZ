"""RuntimeManager: orquestração, máquina de estados e histórico.

A interface gráfica deve usar **somente** esta classe. Ela concentra:

* validação de transições (incluindo sessão RUNNING + container FROZEN);
* concorrência (uma operação mutante por vez);
* timeout e cancelamento cooperativo;
* erros estruturados, eventos e histórico;
* recuperação explícita após falha.

Nenhuma chamada de shell, D-Bus ou Qt acontece aqui: tudo passa pelo
``RuntimeBackend`` injetado.
"""
from __future__ import annotations

import threading
import time
from pathlib import Path
from concurrent.futures import Future, ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeoutError
from dataclasses import replace
from typing import Any, Callable, Optional

from ..services.parsing import (
    is_valid_package,
    is_valid_property_key,
    is_valid_property_value,
)
from .backend import OperationContext, RuntimeBackend
from .errors import RuntimeFailureError, make_failure, map_exception
from .models import (
    Listener,
    OperationRecord,
    OperationResult,
    OperationStatus,
    RuntimeAvailability,
    RuntimeCapabilities,
    RuntimeErrorCode,
    RuntimeEvent,
    RuntimeEventType,
    RuntimeFailure,
    RuntimeFeature,
    RuntimeOperation,
    RuntimeSnapshot,
    RuntimeState,
)

__all__ = ["RuntimeManager"]

MUTATING_OPERATIONS = frozenset(
    {
        RuntimeOperation.START,
        RuntimeOperation.STOP,
        RuntimeOperation.RESTART,
        RuntimeOperation.FREEZE,
        RuntimeOperation.UNFREEZE,
    }
)

# Operações auxiliares não alteram o estado da sessão/container, mas também
# precisam de serialização: duas instalações simultâneas ou uma instalação
# durante o launch produziriam resultados ambíguos.
AUXILIARY_OPERATIONS = frozenset(
    {
        RuntimeOperation.LIST_APPS,
        RuntimeOperation.LAUNCH_APP,
        RuntimeOperation.INSTALL_APP,
        RuntimeOperation.REMOVE_APP,
        RuntimeOperation.GET_PROPERTY,
        RuntimeOperation.SET_PROPERTY,
        RuntimeOperation.ADB_CONNECT,
        RuntimeOperation.SHOW_FULL_UI,
        RuntimeOperation.DIAGNOSTICS,
    }
)

SERIALIZED_OPERATIONS = MUTATING_OPERATIONS | AUXILIARY_OPERATIONS

# Operações que precisam consultar o estado real antes de validar. Apps e
# propriedades dependem de um Android ativo; `prop get` é recusado quando o
# container está congelado, conforme regra explícita do projeto.
STATE_VALIDATED_OPERATIONS = MUTATING_OPERATIONS | frozenset(
    {
        RuntimeOperation.LAUNCH_APP,
        RuntimeOperation.INSTALL_APP,
        RuntimeOperation.REMOVE_APP,
        RuntimeOperation.GET_PROPERTY,
        RuntimeOperation.SET_PROPERTY,
        RuntimeOperation.ADB_CONNECT,
        RuntimeOperation.SHOW_FULL_UI,
    }
)

FEATURE_FOR_OPERATION = {
    RuntimeOperation.STATUS: RuntimeFeature.STATUS,
    RuntimeOperation.START: RuntimeFeature.START,
    RuntimeOperation.STOP: RuntimeFeature.STOP,
    RuntimeOperation.RESTART: RuntimeFeature.RESTART,
    RuntimeOperation.FREEZE: RuntimeFeature.FREEZE,
    RuntimeOperation.UNFREEZE: RuntimeFeature.UNFREEZE,
    RuntimeOperation.RECOVER: RuntimeFeature.RECOVER,
    RuntimeOperation.LIST_APPS: RuntimeFeature.LIST_APPS,
    RuntimeOperation.LAUNCH_APP: RuntimeFeature.LAUNCH_APP,
    RuntimeOperation.INSTALL_APP: RuntimeFeature.INSTALL_APP,
    RuntimeOperation.REMOVE_APP: RuntimeFeature.REMOVE_APP,
    RuntimeOperation.GET_PROPERTY: RuntimeFeature.GET_PROPERTY,
    RuntimeOperation.SET_PROPERTY: RuntimeFeature.SET_PROPERTY,
    RuntimeOperation.ADB_CONNECT: RuntimeFeature.ADB_CONNECT,
    RuntimeOperation.SHOW_FULL_UI: RuntimeFeature.SHOW_FULL_UI,
    RuntimeOperation.DIAGNOSTICS: RuntimeFeature.DIAGNOSTICS,
}

AVAILABILITY_FOR_CODE = {
    RuntimeErrorCode.NOT_FOUND: RuntimeAvailability.NOT_FOUND,
    RuntimeErrorCode.PERMISSION_DENIED: RuntimeAvailability.PERMISSION_DENIED,
    RuntimeErrorCode.SERVICE_UNAVAILABLE: RuntimeAvailability.SERVICE_UNAVAILABLE,
    RuntimeErrorCode.NOT_INITIALIZED: RuntimeAvailability.NOT_INITIALIZED,
}


class RuntimeManager:
    """Fachada única entre a interface e o runtime Android."""

    def __init__(
        self,
        backend: RuntimeBackend,
        *,
        executor: Optional[ThreadPoolExecutor] = None,
        default_timeout: float = 30.0,
        clock: Callable[[], float] = time.monotonic,
        history_limit: int = 100,
        event_limit: int = 200,
    ):
        if not isinstance(backend, RuntimeBackend):
            raise TypeError("backend deve implementar RuntimeBackend")
        self._backend = backend
        self._owns_executor = executor is None
        self._executor = executor or ThreadPoolExecutor(
            max_workers=2, thread_name_prefix="linuxdroid-runtime"
        )
        self._clock = clock
        self._default_timeout = float(default_timeout)
        self._history_limit = max(1, int(history_limit))
        self._event_limit = max(1, int(event_limit))

        self._lock = threading.RLock()
        self._listeners: list[Listener] = []
        self._events: list[RuntimeEvent] = []
        self._history: list[OperationRecord] = []
        self._active: Optional[RuntimeOperation] = None
        self._context: Optional[OperationContext] = None
        self._future: Optional[Future] = None
        self._snapshot = RuntimeSnapshot(capabilities=self._backend.capabilities())
        self._last_error: Optional[RuntimeFailure] = None
        self._closed = False

    # ------------------------------------------------------------------
    # Leitura de estado
    # ------------------------------------------------------------------
    @property
    def backend(self) -> RuntimeBackend:
        return self._backend

    @property
    def snapshot(self) -> RuntimeSnapshot:
        """Última foto conhecida; não faz E/S."""
        with self._lock:
            return self._snapshot

    @property
    def last_error(self) -> Optional[RuntimeFailure]:
        with self._lock:
            return self._last_error

    @property
    def is_busy(self) -> bool:
        with self._lock:
            return self._active is not None

    def capabilities(self) -> RuntimeCapabilities:
        return self._backend.capabilities()

    def events(self, since: float = 0.0) -> tuple[RuntimeEvent, ...]:
        with self._lock:
            return tuple(event for event in self._events if event.timestamp >= since)

    def history(self, limit: Optional[int] = None) -> tuple[OperationRecord, ...]:
        with self._lock:
            records = tuple(self._history)
        if limit is None:
            return records
        return records[-max(0, int(limit)) :]

    def subscribe(self, listener: Listener) -> Callable[[], None]:
        """Registra observador de eventos; devolve função de remoção."""
        if not callable(listener):
            raise TypeError("listener deve ser chamável")
        with self._lock:
            self._listeners.append(listener)

        def unsubscribe() -> None:
            with self._lock:
                if listener in self._listeners:
                    self._listeners.remove(listener)

        return unsubscribe

    # ------------------------------------------------------------------
    # Operações públicas
    # ------------------------------------------------------------------
    def status(self, *, timeout: Optional[float] = None) -> OperationResult:
        """Consulta sessão e container de forma independente."""
        return self._execute(
            RuntimeOperation.STATUS,
            lambda context: self._backend.status(context=context),
            timeout=timeout,
        )

    def refresh(self, *, timeout: Optional[float] = None) -> OperationResult:
        return self.status(timeout=timeout)

    def start(self, *, timeout: Optional[float] = None) -> OperationResult:
        return self._execute(
            RuntimeOperation.START,
            lambda context: self._backend.start(context=context),
            timeout=timeout,
        )

    def stop(self, *, timeout: Optional[float] = None) -> OperationResult:
        return self._execute(
            RuntimeOperation.STOP,
            lambda context: self._backend.stop(context=context),
            timeout=timeout,
        )

    def restart(self, *, timeout: Optional[float] = None) -> OperationResult:
        return self._execute(
            RuntimeOperation.RESTART,
            lambda context: self._backend.restart(context=context),
            timeout=timeout,
        )

    def freeze(self, *, timeout: Optional[float] = None) -> OperationResult:
        return self._execute(
            RuntimeOperation.FREEZE,
            lambda context: self._backend.freeze(context=context),
            timeout=timeout,
        )

    def unfreeze(self, *, timeout: Optional[float] = None) -> OperationResult:
        return self._execute(
            RuntimeOperation.UNFREEZE,
            lambda context: self._backend.unfreeze(context=context),
            timeout=timeout,
        )

    # ------------------------------------------------------------------
    # Operações auxiliares (contrato estendido, com capacidade explícita)
    # ------------------------------------------------------------------
    def list_apps(self, *, timeout: Optional[float] = None) -> OperationResult:
        """Lista pacotes Android; não altera o estado do runtime."""
        return self._execute(
            RuntimeOperation.LIST_APPS,
            lambda context: self._backend.list_apps(context=context),
            timeout=timeout,
        )

    def launch_app(self, package_id: str, *, timeout: Optional[float] = None) -> OperationResult:
        """Envia o comando de abertura; não afirma que o jogo chegou ao lobby."""
        started = self._clock()
        if not is_valid_package(package_id):
            return self._refuse(
                RuntimeOperation.LAUNCH_APP,
                make_failure(
                    RuntimeErrorCode.INVALID_ARGUMENT,
                    "Package ID inválido.",
                    operation=RuntimeOperation.LAUNCH_APP,
                ),
                started,
            )
        return self._execute(
            RuntimeOperation.LAUNCH_APP,
            lambda context: self._backend.launch_app(package_id, context=context),
            timeout=timeout,
        )

    def install_app(self, package_path, *, timeout: Optional[float] = None) -> OperationResult:
        """Instala um APK único; o chamador deve ter validado os splits antes."""
        started = self._clock()
        path = Path(package_path) if isinstance(package_path, (str, Path)) else None
        if path is None or path.suffix.lower() != ".apk":
            return self._refuse(
                RuntimeOperation.INSTALL_APP,
                make_failure(
                    RuntimeErrorCode.INVALID_ARGUMENT,
                    "Informe um arquivo .apk válido.",
                    operation=RuntimeOperation.INSTALL_APP,
                ),
                started,
            )
        return self._execute(
            RuntimeOperation.INSTALL_APP,
            lambda context: self._backend.install_app(str(path), context=context),
            timeout=timeout,
        )

    def remove_app(self, package_id: str, *, timeout: Optional[float] = None) -> OperationResult:
        """Remove um pacote; operação destrutiva, exige android ativo e confirmação na UI."""
        started = self._clock()
        if not is_valid_package(package_id):
            return self._refuse(
                RuntimeOperation.REMOVE_APP,
                make_failure(
                    RuntimeErrorCode.INVALID_ARGUMENT,
                    "Package ID inválido.",
                    operation=RuntimeOperation.REMOVE_APP,
                ),
                started,
            )
        return self._execute(
            RuntimeOperation.REMOVE_APP,
            lambda context: self._backend.remove_app(package_id, context=context),
            timeout=timeout,
        )

    def get_property(self, key: str, *, timeout: Optional[float] = None) -> OperationResult:
        """Lê uma propriedade Waydroid; recusada se o container estiver congelado."""
        started = self._clock()
        if not is_valid_property_key(key):
            return self._refuse(
                RuntimeOperation.GET_PROPERTY,
                make_failure(
                    RuntimeErrorCode.INVALID_ARGUMENT,
                    "Chave de propriedade inválida.",
                    operation=RuntimeOperation.GET_PROPERTY,
                ),
                started,
            )
        return self._execute(
            RuntimeOperation.GET_PROPERTY,
            lambda context: self._backend.get_property(key, context=context),
            timeout=timeout,
        )

    def set_property(self, key: str, value: str, *, timeout: Optional[float] = None) -> OperationResult:
        """Altera uma propriedade Waydroid; nunca toca em arquivos do Android."""
        started = self._clock()
        if not is_valid_property_key(key) or not is_valid_property_value(value):
            return self._refuse(
                RuntimeOperation.SET_PROPERTY,
                make_failure(
                    RuntimeErrorCode.INVALID_ARGUMENT,
                    "Chave ou valor de propriedade inválido.",
                    operation=RuntimeOperation.SET_PROPERTY,
                ),
                started,
            )
        return self._execute(
            RuntimeOperation.SET_PROPERTY,
            lambda context: self._backend.set_property(key, value, context=context),
            timeout=timeout,
        )

    def adb_connect(self, *, timeout: Optional[float] = None) -> OperationResult:
        """Solicita a conexão ADB gerenciada pelo próprio Waydroid."""
        return self._execute(
            RuntimeOperation.ADB_CONNECT,
            lambda context: self._backend.adb_connect(context=context),
            timeout=timeout,
        )

    def show_full_ui(self, *, timeout: Optional[float] = None) -> OperationResult:
        """Traz a superfície Android para a frente; não altera resolução."""
        return self._execute(
            RuntimeOperation.SHOW_FULL_UI,
            lambda context: self._backend.show_full_ui(context=context),
            timeout=timeout,
        )

    def diagnostics(self, *, timeout: Optional[float] = None) -> OperationResult:
        """Coleta dados somente leitura; nunca altera propriedades do Android."""
        return self._execute(
            RuntimeOperation.DIAGNOSTICS,
            lambda context: self._backend.diagnostics(context=context),
            timeout=timeout,
        )

    def cancel(self, operation: Optional[RuntimeOperation] = None) -> bool:
        """Cancela a operação em andamento, se houver e corresponder."""
        with self._lock:
            if self._active is None:
                return False
            if operation is not None and operation is not self._active:
                return False
            context, future = self._context, self._future
        if context is None:
            return False
        context.cancel_event.set()
        if future is not None:
            future.cancel()
        return True

    def clear_error(self) -> None:
        with self._lock:
            self._last_error = None
            self._snapshot = self._snapshot.with_error(None)
        self._emit(
            RuntimeEvent(
                kind=RuntimeEventType.ERROR_CLEARED,
                timestamp=self._clock(),
                message="Erro removido do estado do runtime.",
            )
        )

    def recover(self, *, timeout: Optional[float] = None) -> OperationResult:
        """Limpa o erro e volta a consultar o runtime.

        A recuperação não esconde falha persistente: se o adaptador continuar
        indisponível, o resultado é a própria falha da consulta.
        """
        self.clear_error()
        result = self.status(timeout=timeout)
        recovered = replace(result, operation=RuntimeOperation.RECOVER)
        if result.ok:
            self._emit(
                RuntimeEvent(
                    kind=RuntimeEventType.RECOVERED,
                    timestamp=self._clock(),
                    operation=RuntimeOperation.RECOVER,
                    message="Runtime respondeu novamente após a falha.",
                )
            )
        return recovered

    def shutdown(self, *, wait: bool = False) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
        if self._owns_executor:
            self._executor.shutdown(wait=wait)

    # ------------------------------------------------------------------
    # Núcleo
    # ------------------------------------------------------------------
    def _emit(self, event: RuntimeEvent) -> None:
        with self._lock:
            self._events.append(event)
            if len(self._events) > self._event_limit:
                del self._events[: len(self._events) - self._event_limit]
            listeners = tuple(self._listeners)
        for listener in listeners:
            # Um observador com bug não pode derrubar o runtime.
            try:
                listener(event)
            except Exception:
                continue

    def _validate(
        self, operation: RuntimeOperation, snapshot: RuntimeSnapshot
    ) -> Optional[tuple[Optional[RuntimeFailure], Optional[str]]]:
        """Devolve ``(falha, mensagem_de_skip)`` ou ``None`` quando válido."""
        availability = snapshot.runtime_availability
        if operation not in (RuntimeOperation.STATUS, RuntimeOperation.RECOVER):
            if availability is RuntimeAvailability.NOT_FOUND:
                return (
                    make_failure(
                        RuntimeErrorCode.NOT_FOUND,
                        "Runtime não encontrado neste host.",
                        operation=operation,
                    ),
                    None,
                )
            if availability is RuntimeAvailability.PERMISSION_DENIED:
                return (
                    make_failure(
                        RuntimeErrorCode.PERMISSION_DENIED,
                        "Permissão negada para controlar o runtime.",
                        operation=operation,
                    ),
                    None,
                )
            if availability is RuntimeAvailability.SERVICE_UNAVAILABLE:
                return (
                    make_failure(
                        RuntimeErrorCode.SERVICE_UNAVAILABLE,
                        "Serviço do runtime não está disponível.",
                        operation=operation,
                        retryable=True,
                    ),
                    None,
                )

        feature = FEATURE_FOR_OPERATION[operation]
        if not snapshot.capabilities.supports(feature):
            return (
                make_failure(
                    RuntimeErrorCode.UNSUPPORTED_OPERATION,
                    f"O adaptador {snapshot.capabilities.backend} não suporta {feature.value}.",
                    operation=operation,
                ),
                None,
            )

        session, container = snapshot.session_state, snapshot.container_state

        if operation in AUXILIARY_OPERATIONS:
            if availability is RuntimeAvailability.NOT_INITIALIZED:
                return (
                    make_failure(
                        RuntimeErrorCode.NOT_INITIALIZED,
                        "O runtime precisa ser inicializado antes desta operação.",
                        operation=operation,
                    ),
                    None,
                )
            if operation in (
                RuntimeOperation.LAUNCH_APP,
                RuntimeOperation.INSTALL_APP,
                RuntimeOperation.REMOVE_APP,
                RuntimeOperation.ADB_CONNECT,
                RuntimeOperation.SHOW_FULL_UI,
            ):
                if session is not RuntimeState.RUNNING or container is not RuntimeState.RUNNING:
                    return (
                        make_failure(
                            RuntimeErrorCode.INVALID_TRANSITION,
                            "Android não está ativo. Inicie ou reative a sessão antes de alterar apps.",
                            operation=operation,
                        ),
                        None,
                    )
            if operation in (RuntimeOperation.GET_PROPERTY, RuntimeOperation.SET_PROPERTY):
                if container in (RuntimeState.FROZEN, RuntimeState.FREEZING):
                    return (
                        make_failure(
                            RuntimeErrorCode.INVALID_TRANSITION,
                            "Container congelado: `prop get/set` não é executado neste estado. Reative antes de consultar propriedades.",
                            operation=operation,
                            retryable=True,
                        ),
                        None,
                    )
                if session is not RuntimeState.RUNNING:
                    return (
                        make_failure(
                            RuntimeErrorCode.INVALID_TRANSITION,
                            "Sessão Android inativa: propriedades só são consultadas com a sessão ativa.",
                            operation=operation,
                            retryable=True,
                        ),
                        None,
                    )

        if operation is RuntimeOperation.FREEZE:
            if container in (RuntimeState.FROZEN, RuntimeState.FREEZING):
                return (None, "Container já congelado; nada a fazer.")
            if container not in (RuntimeState.RUNNING, RuntimeState.UNKNOWN):
                return (
                    make_failure(
                        RuntimeErrorCode.INVALID_TRANSITION,
                        "Só é possível congelar um container em execução.",
                        operation=operation,
                    ),
                    None,
                )

        if operation is RuntimeOperation.UNFREEZE:
            if container in (RuntimeState.RUNNING, RuntimeState.STARTING):
                return (None, "Container já ativo; nada a fazer.")
            if container is not RuntimeState.FROZEN:
                return (
                    make_failure(
                        RuntimeErrorCode.INVALID_TRANSITION,
                        "Não há container congelado para reativar.",
                        operation=operation,
                    ),
                    None,
                )

        if operation is RuntimeOperation.START:
            if session in (RuntimeState.STARTING, RuntimeState.STOPPING):
                return (
                    make_failure(
                        RuntimeErrorCode.INVALID_TRANSITION,
                        "O runtime já está iniciando ou parando.",
                        operation=operation,
                    ),
                    None,
                )
            if session is RuntimeState.RUNNING:
                detail = (
                    "Use 'reativar' para um container congelado."
                    if snapshot.is_frozen
                    else "O runtime já está ativo."
                )
                return (
                    make_failure(
                        RuntimeErrorCode.INVALID_TRANSITION,
                        "Não é possível iniciar novamente.",
                        operation=operation,
                        detail=detail,
                    ),
                    None,
                )
            if availability is RuntimeAvailability.NOT_INITIALIZED:
                return (
                    make_failure(
                        RuntimeErrorCode.NOT_INITIALIZED,
                        "O runtime precisa ser inicializado antes de iniciar a sessão.",
                        operation=operation,
                    ),
                    None,
                )

        if operation is RuntimeOperation.STOP:
            if session in (
                RuntimeState.STOPPED,
                RuntimeState.STOPPING,
                RuntimeState.NOT_INITIALIZED,
                RuntimeState.NOT_INSTALLED,
            ):
                return (
                    make_failure(
                        RuntimeErrorCode.INVALID_TRANSITION,
                        "O runtime já está parado.",
                        operation=operation,
                    ),
                    None,
                )

        if operation is RuntimeOperation.RESTART:
            if session in (RuntimeState.STARTING, RuntimeState.STOPPING):
                return (
                    make_failure(
                        RuntimeErrorCode.INVALID_TRANSITION,
                        "Aguarde a operação atual terminar antes de reiniciar.",
                        operation=operation,
                    ),
                    None,
                )
            if availability is RuntimeAvailability.NOT_INITIALIZED:
                return (
                    make_failure(
                        RuntimeErrorCode.NOT_INITIALIZED,
                        "O runtime precisa ser inicializado antes de reiniciar.",
                        operation=operation,
                    ),
                    None,
                )

        return None

    def _execute(
        self,
        operation: RuntimeOperation,
        call: Callable[[OperationContext], Any],
        *,
        timeout: Optional[float],
    ) -> OperationResult:
        started = self._clock()
        effective_timeout = self._default_timeout if timeout is None else max(0.001, float(timeout))

        with self._lock:
            if self._closed:
                failure = make_failure(
                    RuntimeErrorCode.SERVICE_UNAVAILABLE,
                    "RuntimeManager foi encerrado.",
                    operation=operation,
                )
                return self._refuse(operation, failure, started)
            duplicate = self._active is not None and operation in SERIALIZED_OPERATIONS
            snapshot = self._snapshot

        if duplicate:
            failure = make_failure(
                RuntimeErrorCode.DUPLICATE_OPERATION,
                f"Já existe uma operação em andamento: {self._active.value}.",
                operation=operation,
            )
            return self._refuse(operation, failure, started)

        context = OperationContext(
            operation,
            effective_timeout,
            threading.Event(),
            clock=self._clock,
            manager=self,
        )

        # Toda operação mutante é validada contra o estado **observado agora**,
        # não contra uma foto antiga: o container pode ter sido reativado fora
        # do launcher desde a última consulta.
        if operation in STATE_VALIDATED_OPERATIONS:
            try:
                observed = self._backend.status(context=context)
                if not isinstance(observed, RuntimeSnapshot):
                    raise RuntimeFailureError(
                        make_failure(
                            RuntimeErrorCode.INVALID_RESPONSE,
                            "Consulta prévia devolveu resposta inválida.",
                            operation=operation,
                            retryable=True,
                        )
                    )
                snapshot = observed
                with self._lock:
                    self._snapshot = observed
            except Exception as exc:
                return self._refuse(operation, map_exception(exc, operation=operation), started)

        validation = self._validate(operation, snapshot)
        if validation is not None:
            failure, skipped = validation
            if skipped is not None:
                return self._skip(operation, skipped, started, snapshot)
            return self._refuse(operation, failure, started)

        record = OperationRecord(operation, OperationStatus.RUNNING, started)
        with self._lock:
            self._active = operation
            self._context = context
            self._history.append(record)
            record_index = len(self._history) - 1
            self._last_error = None
            self._snapshot = snapshot.with_operation(operation).with_error(None)
            active_snapshot = self._snapshot

        self._emit(
            RuntimeEvent(
                kind=RuntimeEventType.OPERATION_STARTED,
                timestamp=self._clock(),
                operation=operation,
                message=f"Operação {operation.value} iniciada.",
                snapshot=active_snapshot,
            )
        )

        future: Optional[Future] = None
        try:
            future = self._executor.submit(call, context)
            with self._lock:
                self._future = future
            raw = future.result(timeout=effective_timeout)
            context.raise_if_cancelled()
            self._check_response(operation, raw)

            if operation is RuntimeOperation.STATUS:
                return self._complete_status(operation, raw, started, record_index)
            return self._complete_mutation(
                operation,
                raw,
                started,
                record_index,
                context,
                # Launch/install não alteram o estado da sessão; uma consulta
                # posterior só adicionaria ruído e custo.
                refresh=operation not in AUXILIARY_OPERATIONS,
            )

        except FutureTimeoutError:
            # Timeout também sinaliza cancelamento cooperativo para que o
            # adaptador interrompa esperas em vez de continuar em segundo plano.
            context.cancel_event.set()
            if future is not None:
                future.cancel()
            failure = make_failure(
                RuntimeErrorCode.TIMEOUT,
                f"Tempo limite de {effective_timeout:g}s excedido em {operation.value}.",
                operation=operation,
                retryable=True,
            )
            return self._fail(operation, failure, started, record_index, RuntimeEventType.OPERATION_TIMED_OUT)
        except RuntimeFailureError as exc:
            failure = map_exception(exc, operation=operation)
            return self._fail(operation, failure, started, record_index)
        except Exception as exc:  # converte qualquer falha de adaptador
            failure = map_exception(exc, operation=operation)
            return self._fail(operation, failure, started, record_index)
        finally:
            with self._lock:
                self._active = None
                self._context = None
                self._future = None
                self._snapshot = self._snapshot.with_operation(None)
                if record_index < len(self._history):
                    record = self._history[record_index]
                    if record.status is OperationStatus.RUNNING:
                        self._history[record_index] = replace(
                            record,
                            status=OperationStatus.FAILED,
                            finished_at=self._clock(),
                            message="Operação encerrada sem resultado.",
                            duration_ms=self._duration(started),
                        )
                        self._last_error = make_failure(
                            RuntimeErrorCode.BACKEND_ERROR,
                            "Operação encerrada sem resultado.",
                            operation=operation,
                        )

    # ------------------------------------------------------------------
    # Conclusão de resultados
    # ------------------------------------------------------------------
    def _duration(self, started: float) -> int:
        return max(0, int((self._clock() - started) * 1000))

    def _check_response(self, operation: RuntimeOperation, raw: Any) -> None:
        expected = RuntimeSnapshot if operation is RuntimeOperation.STATUS else OperationResult
        if not isinstance(raw, expected):
            raise RuntimeFailureError(
                make_failure(
                    RuntimeErrorCode.INVALID_RESPONSE,
                    f"O adaptador devolveu {type(raw).__name__} para {operation.value}; esperado {expected.__name__}.",
                    operation=operation,
                    retryable=True,
                )
            )
        if isinstance(raw, OperationResult):
            if not isinstance(raw.operation, RuntimeOperation) or raw.operation is not operation:
                raise RuntimeFailureError(
                    make_failure(
                        RuntimeErrorCode.INVALID_RESPONSE,
                        "Resultado da operação com identificador ausente ou divergente.",
                        operation=operation,
                        retryable=True,
                    )
                )

    def _complete_status(
        self,
        operation: RuntimeOperation,
        raw: RuntimeSnapshot,
        started: float,
        record_index: int,
    ) -> OperationResult:
        duration = self._duration(started)
        with self._lock:
            self._snapshot = raw
            self._last_error = raw.last_error
            record = self._history[record_index]
            self._history[record_index] = replace(
                record,
                status=OperationStatus.SUCCEEDED,
                finished_at=self._clock(),
                message="Estado do runtime consultado.",
                duration_ms=duration,
            )
            snapshot = self._snapshot
        self._emit(
            RuntimeEvent(
                kind=RuntimeEventType.SNAPSHOT_UPDATED,
                timestamp=self._clock(),
                operation=operation,
                message="Estado do runtime consultado.",
                snapshot=snapshot,
            )
        )
        self._emit(
            RuntimeEvent(
                kind=RuntimeEventType.OPERATION_SUCCEEDED,
                timestamp=self._clock(),
                operation=operation,
                message="Consulta de estado concluída.",
                snapshot=snapshot,
            )
        )
        return OperationResult(
            operation=operation,
            ok=True,
            message="Estado do runtime consultado.",
            snapshot=snapshot,
            started_at=started,
            duration_ms=duration,
        )

    def _complete_mutation(
        self,
        operation: RuntimeOperation,
        raw: OperationResult,
        started: float,
        record_index: int,
        context: OperationContext,
        *,
        refresh: bool = True,
    ) -> OperationResult:
        duration = self._duration(started)
        refresh_failure: Optional[RuntimeFailure] = None
        refreshed: Optional[RuntimeSnapshot] = None
        if raw.ok and refresh:
            try:
                candidate = self._backend.status(context=context)
                if not isinstance(candidate, RuntimeSnapshot):
                    raise RuntimeFailureError(
                        make_failure(
                            RuntimeErrorCode.INVALID_RESPONSE,
                            "Consulta posterior à operação devolveu resposta inválida.",
                            operation=operation,
                        )
                    )
                refreshed = candidate
            except Exception as exc:
                refresh_failure = map_exception(exc, operation=RuntimeOperation.STATUS)

        with self._lock:
            if refreshed is not None:
                self._snapshot = refreshed
                self._last_error = refreshed.last_error
            snapshot = self._snapshot
            record = self._history[record_index]
            self._history[record_index] = replace(
                record,
                status=OperationStatus.SUCCEEDED if raw.ok else OperationStatus.FAILED,
                finished_at=self._clock(),
                message=raw.message or f"Operação {operation.value} concluída.",
                failure=raw.failure,
                duration_ms=duration,
            )
            if not raw.ok:
                self._last_error = raw.failure

        if not raw.ok:
            self._emit(
                RuntimeEvent(
                    kind=RuntimeEventType.OPERATION_FAILED,
                    timestamp=self._clock(),
                    operation=operation,
                    message=raw.message,
                    failure=raw.failure,
                    snapshot=snapshot,
                )
            )
        else:
            if refreshed is not None:
                self._emit(
                    RuntimeEvent(
                        kind=RuntimeEventType.SNAPSHOT_UPDATED,
                        timestamp=self._clock(),
                        operation=operation,
                        message="Estado do runtime atualizado após a operação.",
                        snapshot=snapshot,
                    )
                )
            self._emit(
                RuntimeEvent(
                    kind=RuntimeEventType.OPERATION_SUCCEEDED,
                    timestamp=self._clock(),
                    operation=operation,
                    message=raw.message or f"Operação {operation.value} concluída.",
                    snapshot=snapshot,
                )
            )
            if refresh_failure is not None:
                self._emit(
                    RuntimeEvent(
                        kind=RuntimeEventType.SNAPSHOT_UPDATED,
                        timestamp=self._clock(),
                        operation=operation,
                        message="Operação concluída, mas o estado não pôde ser atualizado.",
                        failure=refresh_failure,
                    )
                )

        data = dict(raw.data)
        if refresh_failure is not None:
            data["refresh_failure"] = refresh_failure.to_dict()
        return OperationResult(
            operation=operation,
            ok=raw.ok,
            message=raw.message or f"Operação {operation.value} concluída.",
            failure=raw.failure,
            snapshot=snapshot,
            data=data,
            started_at=started,
            duration_ms=duration,
        )

    def _fail(
        self,
        operation: RuntimeOperation,
        failure: RuntimeFailure,
        started: float,
        record_index: Optional[int],
        event_kind: RuntimeEventType = RuntimeEventType.OPERATION_FAILED,
    ) -> OperationResult:
        duration = self._duration(started)
        if event_kind is RuntimeEventType.OPERATION_FAILED:
            if failure.code is RuntimeErrorCode.CANCELED:
                event_kind = RuntimeEventType.OPERATION_CANCELED
            elif failure.code is RuntimeErrorCode.TIMEOUT:
                event_kind = RuntimeEventType.OPERATION_TIMED_OUT
        with self._lock:
            availability = AVAILABILITY_FOR_CODE.get(failure.code)
            capabilities = self._snapshot.capabilities
            self._last_error = failure
            if availability is not None:
                self._snapshot = RuntimeSnapshot(
                    session_state=self._snapshot.session_state,
                    container_state=self._snapshot.container_state,
                    runtime_availability=availability,
                    active_operation=None,
                    last_error=failure,
                    capabilities=capabilities,
                    taken_at=self._snapshot.taken_at,
                    details=dict(self._snapshot.details),
                )
            else:
                self._snapshot = self._snapshot.with_error(failure)
            snapshot = self._snapshot
            if record_index is not None and record_index < len(self._history):
                record = self._history[record_index]
                status = {
                    RuntimeEventType.OPERATION_TIMED_OUT: OperationStatus.TIMED_OUT,
                    RuntimeEventType.OPERATION_CANCELED: OperationStatus.CANCELED,
                }.get(event_kind, OperationStatus.FAILED)
                self._history[record_index] = replace(
                    record,
                    status=status,
                    finished_at=self._clock(),
                    message=failure.message,
                    failure=failure,
                    duration_ms=duration,
                )
        self._emit(
            RuntimeEvent(
                kind=event_kind,
                timestamp=self._clock(),
                operation=operation,
                message=failure.message,
                failure=failure,
                snapshot=snapshot,
            )
        )
        return OperationResult(
            operation=operation,
            ok=False,
            message=failure.message,
            failure=failure,
            snapshot=snapshot,
            started_at=started,
            duration_ms=duration,
        )

    def _refuse(
        self, operation: RuntimeOperation, failure: RuntimeFailure, started: float
    ) -> OperationResult:
        duration = self._duration(started)
        with self._lock:
            availability = AVAILABILITY_FOR_CODE.get(failure.code)
            self._last_error = failure
            if availability is not None:
                self._snapshot = RuntimeSnapshot(
                    session_state=self._snapshot.session_state,
                    container_state=self._snapshot.container_state,
                    runtime_availability=availability,
                    active_operation=None,
                    last_error=failure,
                    capabilities=self._snapshot.capabilities,
                    taken_at=self._snapshot.taken_at,
                    details=dict(self._snapshot.details),
                )
            else:
                self._snapshot = self._snapshot.with_error(failure)
            self._history.append(
                OperationRecord(
                    operation=operation,
                    status=OperationStatus.FAILED,
                    started_at=started,
                    finished_at=self._clock(),
                    message=failure.message,
                    failure=failure,
                    duration_ms=duration,
                )
            )
            self._trim_history()
            snapshot = self._snapshot
        self._emit(
            RuntimeEvent(
                kind=RuntimeEventType.OPERATION_FAILED,
                timestamp=self._clock(),
                operation=operation,
                message=failure.message,
                failure=failure,
                snapshot=snapshot,
            )
        )
        return OperationResult(
            operation=operation,
            ok=False,
            message=failure.message,
            failure=failure,
            snapshot=snapshot,
            started_at=started,
            duration_ms=duration,
        )

    def _skip(
        self,
        operation: RuntimeOperation,
        message: str,
        started: float,
        snapshot: RuntimeSnapshot,
    ) -> OperationResult:
        duration = self._duration(started)
        with self._lock:
            self._last_error = None
            self._snapshot = self._snapshot.with_error(None)
            self._history.append(
                OperationRecord(
                    operation=operation,
                    status=OperationStatus.SKIPPED,
                    started_at=started,
                    finished_at=self._clock(),
                    message=message,
                    duration_ms=duration,
                )
            )
            self._trim_history()
            current = self._snapshot
        self._emit(
            RuntimeEvent(
                kind=RuntimeEventType.OPERATION_SKIPPED,
                timestamp=self._clock(),
                operation=operation,
                message=message,
                snapshot=current,
            )
        )
        return OperationResult(
            operation=operation,
            ok=True,
            message=message,
            snapshot=current,
            started_at=started,
            duration_ms=duration,
            skipped=True,
        )

    def _trim_history(self) -> None:
        if len(self._history) > self._history_limit:
            del self._history[: len(self._history) - self._history_limit]
