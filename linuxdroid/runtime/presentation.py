"""Conversões puras entre modelos do runtime e modelos antigos da UI.

Este módulo não importa Qt. Ele permite que a interface continue usando
``WaydroidStatus``/``CommandResult`` enquanto a fonte da verdade é o
``RuntimeManager``.
"""
from __future__ import annotations

from ..models import CommandResult, WaydroidState, WaydroidStatus
from .models import (
    OperationResult,
    RuntimeAvailability,
    RuntimeOperation,
    RuntimeSnapshot,
    RuntimeState,
)

__all__ = ["snapshot_to_waydroid_status", "operation_to_command_result"]

_STATE_MAP = {
    RuntimeState.NOT_INSTALLED: WaydroidState.NOT_INSTALLED,
    RuntimeState.NOT_INITIALIZED: WaydroidState.NOT_INITIALIZED,
    RuntimeState.STOPPED: WaydroidState.STOPPED,
    RuntimeState.STARTING: WaydroidState.STARTING,
    RuntimeState.RUNNING: WaydroidState.RUNNING,
    RuntimeState.FREEZING: WaydroidState.FROZEN,
    RuntimeState.FROZEN: WaydroidState.FROZEN,
    RuntimeState.ERROR: WaydroidState.ERROR,
    RuntimeState.UNKNOWN: WaydroidState.UNKNOWN,
}


def snapshot_to_waydroid_status(snapshot: RuntimeSnapshot) -> WaydroidStatus:
    """Traduz o snapshot sem achatar sessão e container em um estado só."""
    availability = snapshot.runtime_availability
    if availability is RuntimeAvailability.NOT_FOUND:
        state = WaydroidState.NOT_INSTALLED
        message = "Runtime não encontrado no PATH."
    elif availability is RuntimeAvailability.NOT_INITIALIZED:
        state = WaydroidState.NOT_INITIALIZED
        message = "Runtime ainda não foi inicializado."
    elif availability is RuntimeAvailability.PERMISSION_DENIED:
        state = WaydroidState.ERROR
        message = "Permissão negada ao consultar o runtime."
    else:
        if snapshot.is_frozen:
            state = WaydroidState.FROZEN
            message = "Container congelado: a sessão existe, mas o Android não está ativo."
        elif snapshot.session_state is RuntimeState.STOPPING:
            state = WaydroidState.STOPPED
            message = "Sessão parando; aguarde antes de iniciar novamente."
        elif snapshot.session_state is RuntimeState.STARTING:
            state = WaydroidState.STARTING
            message = "Sessão em inicialização."
        else:
            state = _STATE_MAP.get(snapshot.container_state, WaydroidState.UNKNOWN)
            if state is WaydroidState.STOPPED and snapshot.session_state is RuntimeState.RUNNING:
                # Sessão ativa sem container: não é "Parado" comum.
                state = WaydroidState.ERROR
                message = "Sessão ativa, mas o container não está ativo."
            else:
                message = ""
    if snapshot.last_error:
        suffix = snapshot.last_error.message
        message = f"{message} {suffix}".strip() if message else suffix
    return WaydroidStatus(
        state=state,
        session=snapshot.session_state.value,
        container=snapshot.container_state.value,
        ip=str(snapshot.details.get("ip_address", "")),
        message=message,
    )


def operation_to_command_result(result: OperationResult) -> CommandResult:
    """Mantém o contrato antigo (``ok``/``text``/``error``) sem executar nada."""
    operation = result.operation if isinstance(result.operation, RuntimeOperation) else None
    name = operation.value if operation is not None else "operation"
    # Para `prop get`, o chamador antigo espera o valor em stdout, não o texto
    # descritivo da operação. Preserva o contrato da tela sem executar nada.
    stdout = result.message
    if operation is RuntimeOperation.GET_PROPERTY and isinstance(result.data, dict):
        stdout = str(result.data.get("value", ""))
    return CommandResult(
        program="waydroid",
        args=[name],
        exit_code=0 if result.ok else 1,
        stdout=stdout,
        stderr=result.failure.detail if result.failure else "",
        error="" if result.ok else (result.failure.code.value if result.failure else "failed"),
    )
