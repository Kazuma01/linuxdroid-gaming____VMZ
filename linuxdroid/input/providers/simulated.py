"""Provider determinístico usado por todos os testes do motor.

Nao abre dispositivos, nao usa timers reais e nunca le input fisico. O teste
pode controlar cada timestamp; quando NAO informado, usa-se apenas o relogio
monotonico injetado (`time.monotonic` por padrao).
"""
from __future__ import annotations

import time
from collections import deque
from typing import Callable, Iterable, Mapping

from ...services.capabilities import Capability, Support
from ..events import InputEvent
from ..normalizer import Normalizer
from .base import InputProvider, ProviderError

Clock = Callable[[], float]


class EventScript:
    """Sequencia reutilizavel de especificacoes de evento."""

    def __init__(self, name: str = "script") -> None:
        self.name = name
        self.steps: list[dict] = []

    def add(self, event_type: str, **fields) -> "EventScript":
        step = {"event_type": event_type}
        step.update(fields)
        self.steps.append(step)
        return self

    def key_down(self, name: str, **kwargs) -> "EventScript":
        return self.add("key_down", canonical_name=name, **kwargs)

    def key_up(self, name: str, **kwargs) -> "EventScript":
        return self.add("key_up", canonical_name=name, **kwargs)

    def key_repeat(self, name: str, **kwargs) -> "EventScript":
        return self.add("key_repeat", canonical_name=name, **kwargs)

    def tap(self, name: str, **kwargs) -> "EventScript":
        return self.key_down(name, **kwargs).key_up(name, **kwargs)

    def chord(self, *names: str) -> "EventScript":
        for name in names:
            self.key_down(name)
        for name in reversed(names):
            self.key_up(name)
        return self

    def mouse_down(self, button: str = "MouseLeft", **kwargs) -> "EventScript":
        return self.add("mouse_down", canonical_name=button, **kwargs)

    def mouse_up(self, button: str = "MouseLeft", **kwargs) -> "EventScript":
        return self.add("mouse_up", canonical_name=button, **kwargs)

    def click(self, button: str = "MouseLeft") -> "EventScript":
        return self.mouse_down(button).mouse_up(button)

    def motion(self, dx: float, dy: float, *, unit: str = "normalized") -> "EventScript":
        return self.add("relative_motion", relative_x=dx, relative_y=dy, relative_unit=unit)

    def wheel(self, direction: str) -> "EventScript":
        return self.add("wheel_up" if direction == "up" else "wheel_down")

    def focus_loss(self) -> "EventScript":
        return self.add("focus_lost")

    def focus_gain(self) -> "EventScript":
        return self.add("focus_gained")

    def connect(self) -> "EventScript":
        return self.add("device_connected")

    def disconnect(self) -> "EventScript":
        return self.add("device_disconnected")

    def build(self) -> list[dict]:
        return [dict(step) for step in self.steps]


class SimulatedInputProvider(InputProvider):
    """Fila de eventos simulados com IDs e timestamps determinísticos."""

    def __init__(
        self,
        *,
        clock: Clock | None = None,
        device_id: str = "simulated-input",
        max_queue: int = 4096,
    ) -> None:
        self.clock: Clock = clock or time.monotonic
        self.device_id = device_id
        self.max_queue = max(1, int(max_queue))
        self._queue: deque[InputEvent] = deque()
        self._next_id = 1
        self._running = False
        self._normalizer = Normalizer()

    # -- ciclo de vida ------------------------------------------------------

    def start(self) -> None:
        self._running = True

    def stop(self) -> None:
        self._running = False

    @property
    def running(self) -> bool:
        return self._running

    def describe(self) -> Capability:
        return Capability(
            "Provider simulado",
            Support.SUPPORTED,
            "Eventos simulados/sinteticos em memoria; nenhum dispositivo fisico e lido.",
            "Usar apenas em testes e simulacoes.",
        )

    # -- fila ----------------------------------------------------------------

    def read_events(self) -> list[InputEvent]:
        return self.drain()

    def drain(self) -> list[InputEvent]:
        events = list(self._queue)
        self._queue.clear()
        return events

    def peek(self) -> tuple[InputEvent, ...]:
        return tuple(self._queue)

    def clear(self) -> None:
        self._queue.clear()

    def __len__(self) -> int:
        return len(self._queue)

    # -- emissoes ------------------------------------------------------------

    def emit_raw(self, raw: Mapping[str, object]) -> InputEvent:
        if len(self._queue) >= self.max_queue:
            raise ProviderError("Fila de eventos simulados atingiu o limite.")
        data = dict(raw)
        data.setdefault("event_id", self._next_id)
        data.setdefault("timestamp", self.clock())
        data.setdefault("device_id", self.device_id)
        data.setdefault("source", "simulated")
        event = self._normalizer.normalize(data)
        self._next_id = max(self._next_id, event.event_id + 1)
        self._queue.append(event)
        return event

    def emit_script(
        self,
        script: EventScript,
        *,
        start: float = 1000.0,
        step: float = 0.001,
    ) -> list[InputEvent]:
        emitted: list[InputEvent] = []
        now = float(start)
        for index, spec in enumerate(script.steps):
            raw = dict(spec)
            if "timestamp" not in raw:
                raw["timestamp"] = now + index * float(step)
            emitted.append(self.emit_raw(raw))
        return emitted

    def key_down(self, name: str, *, timestamp: float | None = None, device_id: str | None = None, **kwargs) -> InputEvent:
        return self._emit("key_down", canonical_name=name, timestamp=timestamp, device_id=device_id, **kwargs)

    def key_up(self, name: str, *, timestamp: float | None = None, device_id: str | None = None, **kwargs) -> InputEvent:
        return self._emit("key_up", canonical_name=name, timestamp=timestamp, device_id=device_id, **kwargs)

    def key_repeat(self, name: str, *, timestamp: float | None = None, **kwargs) -> InputEvent:
        return self._emit("key_repeat", canonical_name=name, timestamp=timestamp, **kwargs)

    def mouse_down(self, button: str = "MouseLeft", *, timestamp: float | None = None, **kwargs) -> InputEvent:
        return self._emit("mouse_down", canonical_name=button, timestamp=timestamp, **kwargs)

    def mouse_up(self, button: str = "MouseLeft", *, timestamp: float | None = None, **kwargs) -> InputEvent:
        return self._emit("mouse_up", canonical_name=button, timestamp=timestamp, **kwargs)

    def click(self, button: str = "MouseLeft", *, timestamp: float | None = None, step: float = 0.002) -> list[InputEvent]:
        now = self.clock() if timestamp is None else float(timestamp)
        return [
            self.mouse_down(button, timestamp=now),
            self.mouse_up(button, timestamp=now + step),
        ]

    def left_click(self, **kwargs) -> list[InputEvent]:
        return self.click("MouseLeft", **kwargs)

    def right_click(self, **kwargs) -> list[InputEvent]:
        return self.click("MouseRight", **kwargs)

    def mouse_motion(
        self,
        dx: float,
        dy: float,
        *,
        unit: str = "normalized",
        timestamp: float | None = None,
    ) -> InputEvent:
        return self._emit(
            "relative_motion",
            relative_x=dx,
            relative_y=dy,
            relative_unit=unit,
            timestamp=timestamp,
        )

    def wheel_up(self, *, timestamp: float | None = None) -> InputEvent:
        return self._emit("wheel_up", canonical_name="WheelUp", timestamp=timestamp)

    def wheel_down(self, *, timestamp: float | None = None) -> InputEvent:
        return self._emit("wheel_down", canonical_name="WheelDown", timestamp=timestamp)

    def scroll(self, direction: str, **kwargs) -> InputEvent:
        return self.wheel_up(**kwargs) if direction == "up" else self.wheel_down(**kwargs)

    def focus_lost(self, *, timestamp: float | None = None) -> InputEvent:
        return self._emit("focus_lost", focus=False, timestamp=timestamp)

    def focus_gained(self, *, timestamp: float | None = None) -> InputEvent:
        return self._emit("focus_gained", focus=True, timestamp=timestamp)

    def device_connected(self, *, timestamp: float | None = None) -> InputEvent:
        return self._emit("device_connected", timestamp=timestamp)

    def device_disconnected(self, *, timestamp: float | None = None) -> InputEvent:
        return self._emit("device_disconnected", timestamp=timestamp)

    def reconnect(self, *, timestamp: float | None = None) -> list[InputEvent]:
        now = self.clock() if timestamp is None else float(timestamp)
        return [
            self.device_connected(timestamp=now),
            self.focus_gained(timestamp=now + 0.001),
        ]

    def emit_many(self, events: Iterable[InputEvent]) -> list[InputEvent]:
        result = []
        for event in events:
            if len(self._queue) >= self.max_queue:
                raise ProviderError("Fila de eventos simulados atingiu o limite.")
            self._queue.append(event)
            result.append(event)
            self._next_id = max(self._next_id, event.event_id + 1)
        return result

    def _emit(self, event_type: str, *, timestamp: float | None = None, device_id: str | None = None, **kwargs) -> InputEvent:
        raw = {
            "event_type": event_type,
            "timestamp": self.clock() if timestamp is None else float(timestamp),
            "device_id": device_id or self.device_id,
        }
        raw.update(kwargs)
        return self.emit_raw(raw)


__all__ = ["EventScript", "SimulatedInputProvider"]
