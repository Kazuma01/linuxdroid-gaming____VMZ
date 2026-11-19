"""Nucleo de input normalizado do LinuxDroid Gaming (Fase V3).

Este pacote nao depende de PySide6, Waydroid, Phantom, evdev ou dispositivos
reais. Todos os testes usam `SimulatedInputProvider` e `RecordingTouchBackend`.

Fluxo::

    provider -> normalizer -> MappingEngine -> ContactManager -> TouchInjectBackend
                                  |
                          CursorVirtual / RuntimeStateMachine

Nada aqui injeta eventos Android. O backend padrao de testes apenas grava
comandos em memoria e informa isso explicitamente no diagnostico.
"""
from __future__ import annotations

from .events import (
    EVENT_TYPES,
    InputEvent,
    identity_for_event,
    is_button_event,
    is_key_event,
    is_motion_event,
    is_wheel_event,
)
from .normalizer import NormalizationError, Normalizer
from .providers import EventScript, SimulatedInputProvider
from .backends import RecordingTouchBackend, TouchCommand
from .contacts import (
    Contact,
    ContactManager,
    ContactManagerError,
    InvalidContact,
    SlotExhausted,
)
from .state import CaptureStateMachine, InvalidTransition, RuntimeState, SafeReleaseReport
from .engine import MappingEngine, ProfileRejected
from .runtime import InputRuntime
from .editor_model import BindingEditor
from .diagnostics import Diagnostics

__all__ = [
    "EVENT_TYPES",
    "InputEvent",
    "identity_for_event",
    "is_button_event",
    "is_key_event",
    "is_motion_event",
    "is_wheel_event",
    "NormalizationError",
    "Normalizer",
    "EventScript",
    "SimulatedInputProvider",
    "RecordingTouchBackend",
    "TouchCommand",
    "Contact",
    "ContactManager",
    "ContactManagerError",
    "InvalidContact",
    "SlotExhausted",
    "CaptureStateMachine",
    "InvalidTransition",
    "RuntimeState",
    "SafeReleaseReport",
    "MappingEngine",
    "ProfileRejected",
    "InputRuntime",
    "BindingEditor",
    "Diagnostics",
]
