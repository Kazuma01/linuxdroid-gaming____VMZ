"""Backend de testes: grava comandos touch em memoria, sem injetar nada.

O nome, o `mode` e o `describe()` deixam explicito que nenhum evento Android
foi enviado. Nao ha socket, ADB, uinput, uinput, Phantom ou dispositivo real.
"""
from __future__ import annotations

import time
from dataclasses import dataclass

from ...services.capabilities import Capability, Support, TouchInjectBackend

ACTIONS = frozenset({"down", "move", "up", "cancel"})


class RecordingBackendError(RuntimeError):
    """Falha simulada do backend de gravacao."""


class BackendDisconnected(RecordingBackendError):
    """Backend desconectado; nenhum comando pode ser entregue."""


@dataclass(frozen=True)
class TouchCommand:
    """Comando abstrato registrado pelo backend de gravacao."""

    sequence: int
    action: str
    slot: int
    x: float
    y: float
    timestamp: float
    profile_name: str = ""
    contact_id: int | None = None
    source_event_id: int | None = None

    def to_dict(self) -> dict:
        return {
            "sequence": self.sequence,
            "action": self.action,
            "slot": self.slot,
            "x": self.x,
            "y": self.y,
            "timestamp": self.timestamp,
            "profile_name": self.profile_name,
            "contact_id": self.contact_id,
            "source_event_id": self.source_event_id,
        }


class RecordingTouchBackend(TouchInjectBackend):
    """Implementacao padrao dos testes, explicitamente nao-real."""

    mode = "recording_only_no_injection"
    is_real = False

    def __init__(
        self,
        *,
        clock=None,
        max_touches: int = 10,
        fail_on: frozenset[str] = frozenset(),
    ) -> None:
        self.clock = clock or time.monotonic
        self.max_touches = max(1, int(max_touches))
        self.fail_on = frozenset(fail_on)
        self._commands: list[TouchCommand] = []
        self._active: dict[int, tuple[float, float]] = {}
        self._sequence = 0
        self._connected = True

    # -- metadados -----------------------------------------------------------

    @property
    def is_connected(self) -> bool:
        return self._connected

    @property
    def commands(self) -> tuple[TouchCommand, ...]:
        return tuple(self._commands)

    @property
    def active_slots(self) -> tuple[int, ...]:
        return tuple(sorted(self._active))

    def describe(self) -> Capability:
        return Capability(
            "Backend de gravacao",
            Support.SUPPORTED,
            f"Grava {len(self._commands)} comando(s) em memoria; NENHUMA injecao Android realizada.",
            "Somente testes e simulacao.",
        )

    def max_concurrent_touches(self) -> int:
        return self.max_touches

    # -- controle de teste ---------------------------------------------------

    def disconnect(self) -> None:
        self._connected = False

    def reconnect(self) -> None:
        self._connected = True

    def set_failure(self, action: str | None) -> None:
        self.fail_on = frozenset() if action is None else frozenset({action})

    def clear(self) -> None:
        self._commands.clear()
        self._active.clear()

    def actions(self) -> tuple[str, ...]:
        return tuple(command.action for command in self._commands)

    # -- TouchInjectBackend --------------------------------------------------

    def down(
        self,
        x: float,
        y: float,
        slot: int = 0,
        *,
        timestamp: float | None = None,
        profile_name: str = "",
        contact_id: int | None = None,
        event_id: int | None = None,
    ) -> TouchCommand:
        self._check("down", slot, require_active=False)
        if len(self._active) >= self.max_touches:
            raise RecordingBackendError("Limite de contatos simultaneos do backend atingido.")
        command = self._record("down", slot, x, y, timestamp, profile_name, contact_id, event_id)
        self._active[slot] = (float(x), float(y))
        return command

    def move(
        self,
        x: float,
        y: float,
        slot: int = 0,
        *,
        timestamp: float | None = None,
        profile_name: str = "",
        contact_id: int | None = None,
        event_id: int | None = None,
    ) -> TouchCommand:
        self._check("move", slot, require_active=True)
        x, y = float(x), float(y)
        self._active[slot] = (x, y)
        return self._record("move", slot, x, y, timestamp, profile_name, contact_id, event_id)

    def up(
        self,
        slot: int = 0,
        *,
        timestamp: float | None = None,
        profile_name: str = "",
        contact_id: int | None = None,
        event_id: int | None = None,
    ) -> TouchCommand:
        self._check("up", slot, require_active=True)
        x, y = self._active.pop(slot)
        return self._record("up", slot, x, y, timestamp, profile_name, contact_id, event_id)

    def cancel(
        self,
        slot: int = 0,
        *,
        timestamp: float | None = None,
        profile_name: str = "",
        contact_id: int | None = None,
        reason: str = "safe_release",
    ) -> TouchCommand | None:
        if slot not in self._active:
            return None
        self._check("cancel", slot, require_active=True)
        x, y = self._active.pop(slot)
        command = self._record("cancel", slot, x, y, timestamp, profile_name, contact_id, None)
        return command

    def release_all(self, *, timestamp: float | None = None, profile_name: str = "") -> tuple[TouchCommand, ...]:
        released: list[TouchCommand] = []
        for slot in tuple(sorted(self._active)):
            command = self.cancel(slot, timestamp=timestamp, profile_name=profile_name)
            if command is not None:
                released.append(command)
        return tuple(released)

    def _check(self, action: str, slot: int, *, require_active: bool) -> None:
        if action not in ACTIONS:
            raise RecordingBackendError(f"Acao desconhecida: {action!r}")
        if not self._connected:
            raise BackendDisconnected("Backend de gravacao desconectado.")
        if not 0 <= slot <= 254:
            raise RecordingBackendError(f"Slot invalido: {slot}; 255 e reservado.")
        if require_active and slot not in self._active:
            raise RecordingBackendError(f"Slot {slot} nao esta ativo; MOVE/UP sem DOWN.")
        if action in self.fail_on:
            raise RecordingBackendError(f"Falha simulada do backend em {action.upper()}.")

    def _record(
        self,
        action: str,
        slot: int,
        x: float,
        y: float,
        timestamp: float | None,
        profile_name: str,
        contact_id: int | None,
        event_id: int | None,
    ) -> TouchCommand:
        self._sequence += 1
        command = TouchCommand(
            sequence=self._sequence,
            action=action,
            slot=slot,
            x=float(x),
            y=float(y),
            timestamp=self.clock() if timestamp is None else float(timestamp),
            profile_name=profile_name,
            contact_id=contact_id,
            source_event_id=event_id,
        )
        self._commands.append(command)
        return command


__all__ = [
    "ACTIONS",
    "TouchCommand",
    "RecordingTouchBackend",
    "RecordingBackendError",
    "BackendDisconnected",
]
