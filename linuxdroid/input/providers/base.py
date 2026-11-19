"""Contrato de provider, reaproveitando a interface existente de capacidades."""
from __future__ import annotations

from abc import ABC

from ...services.capabilities import InputCaptureBackend


class InputProvider(InputCaptureBackend, ABC):
    """Fonte de eventos normalizados.

    `InputCaptureBackend` ja define start/stop/read_events/describe em
    `services/capabilities.py`; este contrato apenas docmenta que a fonte
    entrega `InputEvent`, sem criar uma interface concorrente.
    """


class ProviderError(RuntimeError):
    """Fila de eventos cheia ou operacao de provider invalida."""


__all__ = ["InputProvider", "ProviderError"]
