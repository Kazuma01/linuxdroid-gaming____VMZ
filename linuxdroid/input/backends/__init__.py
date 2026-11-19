"""Backends de toque. Apenas gravacao em memoria e adaptador Phantom."""
from .recording import (
    ACTIONS,
    BackendDisconnected,
    RecordingBackendError,
    RecordingTouchBackend,
    TouchCommand,
)
from .phantom_adapter import (
    PhantomAdapter,
    PhantomCommandError,
    PhantomUnavailable,
    PhantomValidation,
)

__all__ = [
    "ACTIONS",
    "TouchCommand",
    "RecordingTouchBackend",
    "RecordingBackendError",
    "BackendDisconnected",
    "PhantomAdapter",
    "PhantomValidation",
    "PhantomUnavailable",
    "PhantomCommandError",
]
