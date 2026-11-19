"""Normalizacao independente da origem do evento.

Aceita dicionarios de providers futuros (Qt, evdev, simulacao) e produz
`InputEvent`. Conversoes explicitas:

  * nome canonico -> namespace/tipo via tabela Phantom;
  * codigo evdev -> nome canonico via tabela auditada;
  * codigo Qt -> permanece em `qt_*`, sem conversao para evdev;
  * proveniencia informada pelo backend e preservada; caso contrario, um nome
    reconhecido recebe apenas `validated_by_vocabulary`.
"""
from __future__ import annotations

from typing import Any, Mapping

from ..controls.keys import (
    PROVENANCE_STATES,
    canonical_for_code,
    kind_for_canonical,
    namespace_for_canonical,
    normalize_phantom_name,
)
from .events import EVENT_TYPES, EventError, InputEvent

_TYPE_ALIASES = {
    "press": "key_down",
    "keydown": "key_down",
    "key_down": "key_down",
    "key_down_repeat": "key_repeat",
    "repeat": "key_repeat",
    "keyrepeat": "key_repeat",
    "release": "key_up",
    "keyup": "key_up",
    "key_up": "key_up",
    "mouse_press": "mouse_down",
    "mousedown": "mouse_down",
    "mouse_down": "mouse_down",
    "mouse_release": "mouse_up",
    "mouseup": "mouse_up",
    "mouse_up": "mouse_up",
    "motion": "mouse_motion",
    "mouse_motion": "mouse_motion",
    "absolute_motion": "mouse_motion",
    "relative": "relative_motion",
    "relative_motion": "relative_motion",
    "scroll_up": "wheel_up",
    "wheel_up": "wheel_up",
    "scroll_down": "wheel_down",
    "wheel_down": "wheel_down",
    "focus": "focus_gained",
    "focus_in": "focus_gained",
    "focus_gained": "focus_gained",
    "focus_out": "focus_lost",
    "focus_lost": "focus_lost",
    "connect": "device_connected",
    "device_connected": "device_connected",
    "disconnect": "device_disconnected",
    "device_disconnected": "device_disconnected",
}

class NormalizationError(ValueError):
    """Evento de origem nao pode ser convertido com seguranca."""


class Normalizer:
    """Converte eventos brutos em `InputEvent` sem inventar identidade fisica."""

    def normalize(self, raw: InputEvent | Mapping[str, Any]) -> InputEvent:
        if isinstance(raw, InputEvent):
            return raw
        if not isinstance(raw, Mapping):
            raise NormalizationError("Evento bruto precisa ser um objeto mapeador.")

        data = dict(raw)
        event_type = self._event_type(data)
        name = normalize_phantom_name(data.get("canonical_name") or data.get("canonical") or data.get("name"))
        code = self._code(data.get("code"))
        code_space = str(data.get("code_space", "unknown") or "unknown")

        if name is None and code_space == "evdev" and code is not None:
            name = canonical_for_code(code, "evdev")
        if name is None:
            name = ""

        provenance = str(data.get("provenance", "unverified") or "unverified")
        if provenance not in PROVENANCE_STATES:
            raise NormalizationError(f"Proveniencia desconhecida: {provenance!r}")
        if provenance in ("unverified", "validated_by_vocabulary") and name:
            provenance = "validated_by_vocabulary"

        namespace = str(data.get("namespace") or namespace_for_canonical(name))
        kind = str(data.get("event_kind") or kind_for_canonical(name))
        if "modifiers" in data:
            modifiers = data.get("modifiers") or ()
            if isinstance(modifiers, str):
                modifiers = (modifiers,)
            modifiers = tuple(str(modifier) for modifier in modifiers)
        else:
            modifiers = ()

        relative_unit = str(data.get("relative_unit", "normalized") or "normalized")
        if relative_unit not in ("normalized", "pixels"):
            relative_unit = "normalized"

        wheel_direction = self._wheel_direction(data, event_type)
        focus = data.get("focus")
        if focus is not None:
            focus = bool(focus)

        try:
            return InputEvent(
                event_id=int(data["event_id"]),
                timestamp=float(data["timestamp"]),
                event_type=event_type,
                device_id=str(data.get("device_id", "unknown") or "unknown"),
                namespace=namespace,
                code=code,
                code_space=code_space,
                canonical_name=name,
                value=float(data.get("value", 0.0) or 0.0),
                modifiers=modifiers,
                source=str(data.get("source", "unknown") or "unknown"),
                relative_x=float(data.get("relative_x", data.get("dx", 0.0)) or 0.0),
                relative_y=float(data.get("relative_y", data.get("dy", 0.0)) or 0.0),
                relative_unit=relative_unit,
                wheel_direction=wheel_direction,
                focus=focus,
                provenance=provenance,
                raw=data,
                notes=str(data.get("notes", "") or ""),
            )
        except (EventError, KeyError, TypeError, ValueError) as error:
            raise NormalizationError(str(error)) from error

    def normalize_many(self, events) -> list[InputEvent]:
        return [self.normalize(event) for event in events]

    @staticmethod
    def _event_type(data: Mapping[str, Any]) -> str:
        raw = str(data.get("event_type", data.get("type", "")) or "").strip().lower()
        resolved = _TYPE_ALIASES.get(raw, raw)
        if resolved not in EVENT_TYPES:
            raise NormalizationError(f"Tipo de evento nao suportado: {data.get('event_type', data.get('type'))!r}")
        return resolved

    @staticmethod
    def _code(value: Any) -> int | None:
        if value is None or value == "":
            return None
        try:
            code = int(value)
        except (TypeError, ValueError) as error:
            raise NormalizationError(f"Codigo numerico invalido: {value!r}") from error
        return code

    @staticmethod
    def _wheel_direction(data: Mapping[str, Any], event_type: str) -> int:
        if event_type == "wheel_up":
            return 1
        if event_type == "wheel_down":
            return -1
        value = data.get("wheel_direction", 0)
        if isinstance(value, str):
            lowered = value.strip().lower()
            if lowered in ("up", "1"):
                return 1
            if lowered in ("down", "-1"):
                return -1
            return 0
        try:
            return int(value or 0)
        except (TypeError, ValueError):
            return 0


__all__ = ["NormalizationError", "Normalizer"]
