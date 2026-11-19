"""Evento de entrada normalizado e imutavel.

Um `InputEvent` NAO e um evento Qt, evdev ou Android: e a representacao interna
comum produzida pelo normalizador. A origem (`source`) e o espaco do codigo
(`code_space`) sao sempre preservados para impedir conversoes inventadas.

Timestamps usam uma referencia monotônica fornecida pelo provider. Nenhuma
hora civil e usada para medir intervalos.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Mapping

from ..controls.keys import (
    PROVENANCE_STATES,
    InputBinding,
    kind_for_canonical,
    namespace_for_canonical,
    normalize_phantom_name,
)

EVENT_TYPES = frozenset({
    "key_down", "key_up", "key_repeat",
    "mouse_down", "mouse_up", "mouse_motion", "relative_motion",
    "wheel_up", "wheel_down",
    "focus_gained", "focus_lost",
    "device_connected", "device_disconnected",
})

_PRESS_TYPES = frozenset({"key_down", "mouse_down"})
_RELEASE_TYPES = frozenset({"key_up", "mouse_up"})
_REPEAT_TYPES = frozenset({"key_repeat"})
_WHEEL_TYPES = frozenset({"wheel_up", "wheel_down"})
_MOTION_TYPES = frozenset({"mouse_motion", "relative_motion", "wheel_up", "wheel_down"})


class EventError(ValueError):
    """Evento normalizado invalido."""


@dataclass(frozen=True)
class InputEvent:
    """Representacao normalizada de uma entrada humana ou de estado de dispositivo."""

    event_id: int
    timestamp: float
    event_type: str
    device_id: str = "unknown"
    namespace: str = "other"
    code: int | None = None
    code_space: str = "unknown"
    canonical_name: str = ""
    value: float = 0.0
    modifiers: tuple[str, ...] = ()
    source: str = "unknown"
    pressed: bool = False
    released: bool = False
    repeated: bool = False
    relative_x: float = 0.0
    relative_y: float = 0.0
    relative_unit: str = "normalized"
    wheel_direction: int = 0
    focus: bool | None = None
    provenance: str = "unverified"
    raw: Mapping[str, object] | None = None
    notes: str = ""

    def __post_init__(self) -> None:
        if not isinstance(self.event_id, int) or isinstance(self.event_id, bool) or self.event_id < 1:
            raise EventError("event_id precisa ser inteiro positivo.")
        if not isinstance(self.timestamp, (int, float)) or not math.isfinite(float(self.timestamp)):
            raise EventError("timestamp monotônico precisa ser finito.")
        if self.event_type not in EVENT_TYPES:
            raise EventError(f"tipo de evento desconhecido: {self.event_type!r}")
        if self.code_space not in ("evdev", "qt_native_scan_code", "qt_virtual_key", "phantom_name", "unknown"):
            raise EventError(f"espaco de codigo desconhecido: {self.code_space!r}")
        if self.provenance not in PROVENANCE_STATES:
            raise EventError(f"proveniencia desconhecida: {self.provenance!r}")
        if self.relative_unit not in ("normalized", "pixels"):
            raise EventError(f"unidade relativa desconhecida: {self.relative_unit!r}")
        if not isinstance(self.modifiers, tuple):
            object.__setattr__(self, "modifiers", tuple(self.modifiers))
        if self.raw is not None:
            object.__setattr__(self, "raw", MappingProxyType(dict(self.raw)))

        # Flags derivadas do tipo: um evento nunca pode dizer que e DOWN e UP.
        object.__setattr__(self, "pressed", self.event_type in _PRESS_TYPES)
        object.__setattr__(self, "released", self.event_type in _RELEASE_TYPES)
        object.__setattr__(self, "repeated", self.event_type in _REPEAT_TYPES)
        if self.wheel_direction == 0 and self.event_type in _WHEEL_TYPES:
            object.__setattr__(
                self, "wheel_direction", 1 if self.event_type == "wheel_up" else -1
            )
        if self.focus is None and self.event_type in ("focus_gained", "focus_lost"):
            object.__setattr__(self, "focus", self.event_type == "focus_gained")

    @property
    def is_wheel(self) -> bool:
        return self.event_type in _WHEEL_TYPES

    @property
    def is_motion(self) -> bool:
        return self.event_type in _MOTION_TYPES

    @property
    def lifetime(self) -> str:
        if self.pressed:
            return "down"
        if self.released:
            return "up"
        if self.repeated:
            return "repeat"
        return "state"

    def to_dict(self) -> dict:
        return {
            "event_id": self.event_id,
            "timestamp": self.timestamp,
            "event_type": self.event_type,
            "device_id": self.device_id,
            "namespace": self.namespace,
            "code": self.code,
            "code_space": self.code_space,
            "canonical_name": self.canonical_name,
            "value": self.value,
            "modifiers": list(self.modifiers),
            "source": self.source,
            "pressed": self.pressed,
            "released": self.released,
            "repeated": self.repeated,
            "relative_x": self.relative_x,
            "relative_y": self.relative_y,
            "relative_unit": self.relative_unit,
            "wheel_direction": self.wheel_direction,
            "focus": self.focus,
            "provenance": self.provenance,
            "notes": self.notes,
        }


def is_key_event(event: InputEvent) -> bool:
    return event.event_type in ("key_down", "key_up", "key_repeat")


def is_button_event(event: InputEvent) -> bool:
    return event.event_type in ("mouse_down", "mouse_up")


def is_wheel_event(event: InputEvent) -> bool:
    return event.is_wheel


def is_motion_event(event: InputEvent) -> bool:
    return event.event_type in ("mouse_motion", "relative_motion")


def identity_for_event(event: InputEvent) -> str:
    """Chave de conflito usada pelo motor, sem promover proveniencia."""
    canonical = normalize_phantom_name(event.canonical_name) or ""
    if not canonical and event.code_space == "evdev":
        from ..controls.keys import canonical_for_code

        canonical = canonical_for_code(event.code, "evdev") or ""
    binding = InputBinding(
        namespace=namespace_for_canonical(canonical),
        event_type=kind_for_canonical(canonical),
        canonical_name=canonical,
        modifiers=event.modifiers,
        label=canonical,
        provenance=event.provenance,
    )
    return binding.identity()


__all__ = [
    "EVENT_TYPES",
    "EventError",
    "InputEvent",
    "identity_for_event",
    "is_button_event",
    "is_key_event",
    "is_motion_event",
    "is_wheel_event",
]
