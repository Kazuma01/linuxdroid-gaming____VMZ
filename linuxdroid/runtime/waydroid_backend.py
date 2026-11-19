"""Adaptador Waydroid: único lugar que conhece CLI e D-Bus do Waydroid.

Todas as dependências externas são injetadas:

* ``command_runner`` — executa `waydroid ...` sem shell e sem sudo;
* ``dbus`` — chama `Freeze`/`Unfreeze` em `id.waydro.Container`.

Os testes usam implementações falsas; nenhum comando real é executado neles.
"""
from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any, Optional, Protocol, Sequence

from ..models import CommandResult
from ..services.command_paths import resolve_command
from ..services.parsing import (
    is_valid_package,
    is_valid_property_key,
    is_valid_property_value,
    parse_waydroid_apps,
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
    RuntimeFeature,
    RuntimeOperation,
    RuntimeSnapshot,
    RuntimeState,
)

__all__ = [
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

DBUS_SERVICE = "id.waydro.Container"
DBUS_PATH = "/ContainerManager"
DBUS_INTERFACE = "id.waydro.ContainerManager"

FORBIDDEN = {"sudo", "su", "pkexec", "doas", "run0", "gksu", "gksudo", "kdesu"}


class CommandRunner(Protocol):
    """Contrato mínimo para execução injetada de comandos."""

    def run(
        self, program: str, args: Sequence[str], *, timeout: Optional[float] = None
    ) -> CommandResult: ...


class DBusClient(Protocol):
    """Contrato mínimo para comunicação D-Bus injetada."""

    def call(
        self,
        *,
        bus: str,
        service: str,
        path: str,
        interface: str,
        method: str,
        args: Sequence[Any],
        timeout: Optional[float] = None,
    ) -> Any: ...


class SubprocessCommandRunner:
    """Implementação padrão, sem shell e sem elevação de privilégio."""

    def run(
        self, program: str, args: Sequence[str], *, timeout: Optional[float] = None
    ) -> CommandResult:
        args = [str(arg) for arg in args]
        if program.rsplit("/", 1)[-1] in FORBIDDEN:
            raise PermissionError("O Runtime Manager não executa comandos privilegiados.")
        executable, final_args = resolve_command(program, args)
        if not executable:
            return CommandResult(
                program, final_args, error="not_found", stderr=f"{program} não encontrado no PATH"
            )
        command = [executable, *final_args]
        try:
            completed = subprocess.run(
                command,
                capture_output=True,
                text=True,
                timeout=timeout,
                check=False,
                shell=False,
            )
            return CommandResult(
                program,
                final_args,
                exit_code=completed.returncode,
                stdout=completed.stdout,
                stderr=completed.stderr,
            )
        except subprocess.TimeoutExpired as exc:
            return CommandResult(
                program,
                final_args,
                error="timeout",
                stdout=exc.stdout or "",
                stderr=str(exc),
            )
        except FileNotFoundError as exc:
            return CommandResult(program, final_args, error="not_found", stderr=str(exc))
        except PermissionError as exc:
            return CommandResult(program, final_args, error="permission_denied", stderr=str(exc))


class SystemBusDBusClient:
    """Adaptador fino sobre um barramento injetado (por exemplo, pydbus)."""

    def __init__(self, bus: Any):
        self._bus = bus

    def call(
        self,
        *,
        bus: str,
        service: str,
        path: str,
        interface: str,
        method: str,
        args: Sequence[Any],
        timeout: Optional[float] = None,
    ) -> Any:
        if bus != "system":
            raise ValueError("Somente o barramento do sistema é suportado pelo Waydroid.")
        proxy = self._bus.get(service, path)
        target = getattr(proxy, method, None)
        if target is None:
            raise AttributeError(f"Método D-Bus {method} não existe em {service}{path}.")
        return target(*args)


_STATE_MAP = {
    "RUNNING": RuntimeState.RUNNING,
    "FROZEN": RuntimeState.FROZEN,
    "STOPPED": RuntimeState.STOPPED,
    "STARTING": RuntimeState.STARTING,
    "STOPPING": RuntimeState.STOPPING,
    "FREEZING": RuntimeState.FREEZING,
    "NOT_INITIALIZED": RuntimeState.NOT_INITIALIZED,
    "ERROR": RuntimeState.ERROR,
}


def _map_state(value: str) -> RuntimeState:
    token = value.strip().upper().replace(" ", "_").replace("-", "_")
    return _STATE_MAP.get(token, RuntimeState.UNKNOWN)


def parse_status_output(
    stdout: str,
    stderr: str = "",
    exit_code: int = 0,
    error: str = "",
) -> tuple[RuntimeState, RuntimeState, RuntimeAvailability, dict[str, Any]]:
    """Converte a saída de `waydroid status` em campos independentes."""
    text = f"{stdout}\n{stderr}".lower()
    details: dict[str, Any] = {}

    if error == "not_found" or "não encontrado" in text:
        return (
            RuntimeState.UNKNOWN,
            RuntimeState.UNKNOWN,
            RuntimeAvailability.NOT_FOUND,
            {"reason": "waydroid não encontrado no PATH"},
        )
    if error == "permission_denied" or "permission denied" in text or "permissão negada" in text:
        return (
            RuntimeState.UNKNOWN,
            RuntimeState.UNKNOWN,
            RuntimeAvailability.PERMISSION_DENIED,
            {"reason": "acesso ao runtime negado"},
        )
    if "not initialized" in text or "não inicializado" in text:
        return (
            RuntimeState.NOT_INITIALIZED,
            RuntimeState.NOT_INITIALIZED,
            RuntimeAvailability.NOT_INITIALIZED,
            {"reason": "runtime não inicializado"},
        )

    values: dict[str, str] = {}
    for line in (stdout or "").splitlines():
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        values[key.strip().lower()] = value.strip()

    session = _map_state(values.get("session", ""))
    container = _map_state(values.get("container", ""))
    details["vendor_type"] = values.get("vendor type", "")
    details["ip_address"] = values.get("ip address", "")
    details["raw_exit_code"] = int(exit_code)
    if session is RuntimeState.UNKNOWN and container is RuntimeState.UNKNOWN:
        details["reason"] = "saída sem Session/Container reconhecíveis"
    return session, container, RuntimeAvailability.AVAILABLE, details


class WaydroidRuntimeBackend(RuntimeBackend):
    """Adaptador concreto. Não é usado pelos testes unitários do manager."""

    def __init__(
        self,
        *,
        command_runner: Optional[CommandRunner] = None,
        dbus: Optional[DBusClient] = None,
        freeze_enabled: bool = True,
    ):
        self.name = "waydroid"
        self.command_runner: CommandRunner = command_runner or SubprocessCommandRunner()
        self.dbus = dbus
        self.freeze_enabled = freeze_enabled

    def capabilities(self) -> RuntimeCapabilities:
        supported = set(CORE_FEATURES) | set(AUXILIARY_FEATURES)
        if self.dbus is None or not self.freeze_enabled:
            supported.discard(RuntimeFeature.FREEZE)
            supported.discard(RuntimeFeature.UNFREEZE)
        return RuntimeCapabilities(
            backend=self.name,
            supported=frozenset(supported),
            notes=(
                "Sessão/container via CLI waydroid status; "
                "Freeze/Unfreeze via D-Bus id.waydro.Container (sem sudo); "
                "apps, propriedades, ADB, superfície e diagnóstico via CLI waydroid, todos sem sudo."
            ),
        )

    def status(self, *, context: Optional[OperationContext] = None) -> RuntimeSnapshot:
        result = self._run(["status"], context, label=RuntimeOperation.STATUS)
        session, container, availability, details = parse_status_output(
            result.stdout, result.stderr, result.exit_code, result.error
        )
        return RuntimeSnapshot(
            session_state=session,
            container_state=container,
            runtime_availability=availability,
            capabilities=self.capabilities(),
            details=details,
        )

    def start(self, *, context: Optional[OperationContext] = None) -> OperationResult:
        self._run(["session", "start"], context, label=RuntimeOperation.START)
        return OperationResult(RuntimeOperation.START, True, "Sessão Waydroid iniciada.")

    def stop(self, *, context: Optional[OperationContext] = None) -> OperationResult:
        self._run(["session", "stop"], context, label=RuntimeOperation.STOP)
        return OperationResult(RuntimeOperation.STOP, True, "Sessão Waydroid encerrada.")

    def restart(self, *, context: Optional[OperationContext] = None) -> OperationResult:
        self._run(["session", "stop"], context, label=RuntimeOperation.RESTART)
        if context is not None:
            context.raise_if_cancelled()
        self._run(["session", "start"], context, label=RuntimeOperation.RESTART)
        return OperationResult(RuntimeOperation.RESTART, True, "Sessão Waydroid reiniciada.")

    def freeze(self, *, context: Optional[OperationContext] = None) -> OperationResult:
        self._check_freeze_support()
        self._dbus_call("Freeze", context)
        return OperationResult(
            RuntimeOperation.FREEZE, True, "Container Waydroid congelado via D-Bus."
        )

    def unfreeze(self, *, context: Optional[OperationContext] = None) -> OperationResult:
        self._check_freeze_support()
        self._dbus_call("Unfreeze", context)
        return OperationResult(
            RuntimeOperation.UNFREEZE, True, "Container Waydroid reativado via D-Bus."
        )

    # ------------------------------------------------------------------
    # Operações auxiliares — mesmos comandos já usados pelo serviço Qt,
    # agora com validação, timeout, eventos e histórico do manager.
    # ------------------------------------------------------------------
    def list_apps(self, *, context: Optional[OperationContext] = None) -> OperationResult:
        result = self._run(["app", "list"], context, label=RuntimeOperation.LIST_APPS)
        apps = parse_waydroid_apps(result.stdout)
        return OperationResult(
            RuntimeOperation.LIST_APPS,
            True,
            f"{len(apps)} aplicativo(s) encontrado(s).",
            data={
                "apps": [
                    {"name": name, "package_id": package_id} for name, package_id in apps
                ]
            },
        )

    def launch_app(
        self, package_id: str, *, context: Optional[OperationContext] = None
    ) -> OperationResult:
        if not is_valid_package(package_id):
            raise RuntimeFailureError(
                make_failure(
                    RuntimeErrorCode.INVALID_ARGUMENT,
                    "Package ID inválido.",
                    operation=RuntimeOperation.LAUNCH_APP,
                )
            )
        self._run(["app", "launch", package_id], context, label=RuntimeOperation.LAUNCH_APP)
        return OperationResult(
            RuntimeOperation.LAUNCH_APP,
            True,
            f"Comando de abertura aceito para {package_id}.",
            data={"package_id": package_id},
        )

    def install_app(
        self, package_path: str, *, context: Optional[OperationContext] = None
    ) -> OperationResult:
        path = Path(package_path)
        if path.suffix.lower() != ".apk":
            raise RuntimeFailureError(
                make_failure(
                    RuntimeErrorCode.INVALID_ARGUMENT,
                    "Somente um arquivo .apk é aceito por esta operação.",
                    operation=RuntimeOperation.INSTALL_APP,
                    detail="XAPK é tratado pelo planejador de splits, não por esta operação.",
                )
            )
        if not path.is_file():
            raise RuntimeFailureError(
                make_failure(
                    RuntimeErrorCode.NOT_FOUND,
                    "Arquivo APK não encontrado.",
                    operation=RuntimeOperation.INSTALL_APP,
                )
            )
        self._run(["app", "install", str(path)], context, label=RuntimeOperation.INSTALL_APP)
        return OperationResult(
            RuntimeOperation.INSTALL_APP,
            True,
            "Comando de instalação aceito; o Android ainda valida o pacote.",
            data={"path": str(path)},
        )

    def remove_app(
        self, package_id: str, *, context: Optional[OperationContext] = None
    ) -> OperationResult:
        if not is_valid_package(package_id):
            raise RuntimeFailureError(
                make_failure(
                    RuntimeErrorCode.INVALID_ARGUMENT,
                    "Package ID inválido.",
                    operation=RuntimeOperation.REMOVE_APP,
                )
            )
        self._run(["app", "remove", package_id], context, label=RuntimeOperation.REMOVE_APP)
        return OperationResult(
            RuntimeOperation.REMOVE_APP,
            True,
            f"Comando de remoção aceito para {package_id}; o Android confirma a exclusão.",
            data={"package_id": package_id},
        )

    def get_property(
        self, key: str, *, context: Optional[OperationContext] = None
    ) -> OperationResult:
        if not is_valid_property_key(key):
            raise RuntimeFailureError(
                make_failure(
                    RuntimeErrorCode.INVALID_ARGUMENT,
                    "Chave de propriedade inválida.",
                    operation=RuntimeOperation.GET_PROPERTY,
                )
            )
        result = self._run(["prop", "get", key], context, label=RuntimeOperation.GET_PROPERTY)
        return OperationResult(
            RuntimeOperation.GET_PROPERTY,
            True,
            f"Propriedade {key} consultada.",
            data={"key": key, "value": result.stdout.strip()},
        )

    def set_property(
        self, key: str, value: str, *, context: Optional[OperationContext] = None
    ) -> OperationResult:
        if not is_valid_property_key(key) or not is_valid_property_value(value):
            raise RuntimeFailureError(
                make_failure(
                    RuntimeErrorCode.INVALID_ARGUMENT,
                    "Chave ou valor de propriedade inválido.",
                    operation=RuntimeOperation.SET_PROPERTY,
                )
            )
        self._run(
            ["prop", "set", key, value], context, label=RuntimeOperation.SET_PROPERTY
        )
        return OperationResult(
            RuntimeOperation.SET_PROPERTY,
            True,
            f"Propriedade {key} enviada ao Waydroid.",
            data={"key": key, "value": value},
        )

    def adb_connect(self, *, context: Optional[OperationContext] = None) -> OperationResult:
        self._run(["adb", "connect"], context, label=RuntimeOperation.ADB_CONNECT)
        return OperationResult(
            RuntimeOperation.ADB_CONNECT,
            True,
            "Conexão ADB solicitada ao Waydroid; a autorização no Android ainda é necessária.",
        )

    def show_full_ui(self, *, context: Optional[OperationContext] = None) -> OperationResult:
        self._run(["show-full-ui"], context, label=RuntimeOperation.SHOW_FULL_UI)
        return OperationResult(
            RuntimeOperation.SHOW_FULL_UI,
            True,
            "Superfície Android trazida para a frente; resolução não foi alterada.",
        )

    def diagnostics(self, *, context: Optional[OperationContext] = None) -> OperationResult:
        result = self._run(["status"], context, label=RuntimeOperation.DIAGNOSTICS)
        session, container, availability, details = parse_status_output(
            result.stdout, result.stderr, result.exit_code, result.error
        )
        return OperationResult(
            RuntimeOperation.DIAGNOSTICS,
            True,
            "Diagnóstico somente leitura concluído.",
            data={
                "session": session.value,
                "container": container.value,
                "availability": availability.value,
                "details": details,
            },
        )

    # ------------------------------------------------------------------
    # Interno
    # ------------------------------------------------------------------
    def _run(
        self,
        args: Sequence[str],
        context: Optional[OperationContext],
        *,
        label: Optional[RuntimeOperation] = None,
    ) -> CommandResult:
        if context is not None:
            context.raise_if_cancelled()
            timeout = context.remaining() or None
        else:
            timeout = None
        result = self.command_runner.run("waydroid", args, timeout=timeout)
        if result.error in ("not_found", "permission_denied"):
            code = (
                RuntimeErrorCode.NOT_FOUND
                if result.error == "not_found"
                else RuntimeErrorCode.PERMISSION_DENIED
            )
            raise RuntimeFailureError(
                make_failure(code, result.stderr or "Falha ao executar waydroid.", operation=label)
            )
        if result.error == "timeout":
            raise RuntimeFailureError(
                make_failure(
                    RuntimeErrorCode.TIMEOUT,
                    "Comando waydroid excedeu o tempo limite.",
                    operation=label,
                    retryable=True,
                )
            )
        if not result.ok:
            raise RuntimeFailureError(
                make_failure(
                    RuntimeErrorCode.BACKEND_ERROR,
                    "Comando waydroid terminou com erro.",
                    operation=label,
                    detail=result.text,
                )
            )
        return result

    def _check_freeze_support(self) -> None:
        if self.dbus is None or not self.freeze_enabled:
            raise RuntimeFailureError(
                make_failure(
                    RuntimeErrorCode.UNSUPPORTED_OPERATION,
                    "Controle de freeze não está disponível neste adaptador.",
                    detail="É necessário injetar um cliente D-Bus do sistema.",
                )
            )

    def _dbus_call(
        self, method: str, context: Optional[OperationContext]
    ) -> Any:
        if context is not None:
            context.raise_if_cancelled()
        timeout = context.remaining() if context is not None else None
        try:
            return self.dbus.call(
                bus="system",
                service=DBUS_SERVICE,
                path=DBUS_PATH,
                interface=DBUS_INTERFACE,
                method=method,
                args=(),
                timeout=timeout or None,
            )
        except RuntimeFailureError:
            raise
        except PermissionError as exc:
            raise RuntimeFailureError(
                make_failure(
                    RuntimeErrorCode.PERMISSION_DENIED,
                    "Permissão negada para controlar o container via D-Bus.",
                    detail=str(exc),
                )
            ) from exc
        except Exception as exc:
            low = str(exc).lower()
            if "unknownmethod" in low or "does not exist" in low:
                code = RuntimeErrorCode.NOT_IMPLEMENTED
            elif "serviceunknown" in low or "not known" in low:
                code = RuntimeErrorCode.SERVICE_UNAVAILABLE
            else:
                code = RuntimeErrorCode.BACKEND_ERROR
            raise RuntimeFailureError(
                make_failure(code, f"Chamada D-Bus {method} falhou.", detail=str(exc))  # noqa: B904
            ) from exc
