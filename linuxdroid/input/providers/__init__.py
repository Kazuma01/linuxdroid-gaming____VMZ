"""Providers de entrada. Apenas simulacao nesta fase."""
from .base import InputProvider, ProviderError
from .simulated import EventScript, SimulatedInputProvider

__all__ = ["InputProvider", "ProviderError", "EventScript", "SimulatedInputProvider"]
