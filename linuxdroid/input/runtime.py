"""Orquestracao segura de provider, engine e backend."""
from __future__ import annotations

from ..controls.model import ControlProfileV2
from .backends import RecordingTouchBackend
from .diagnostics import Diagnostics
from .engine import MappingEngine
from .normalizer import Normalizer
from .providers import SimulatedInputProvider
from .state import RuntimeState


class InputRuntime:
    """Fachada usada por testes e por um futuro daemon independente de Qt."""

    def __init__(
        self,
        provider=None,
        backend=None,
        *,
        diagnostics: Diagnostics | None = None,
        clock=None,
        raise_on_error: bool = False,
    ) -> None:
        import time

        self.clock = clock or time.monotonic
        self.provider = provider or SimulatedInputProvider(clock=self.clock)
        self.backend = backend or RecordingTouchBackend(clock=self.clock)
        self.diagnostics = diagnostics or Diagnostics()
        self.diagnostics.configure(
            provider=type(self.provider).__name__,
            backend=type(self.backend).__name__,
            backend_is_real=bool(getattr(self.backend, "is_real", False)),
            mode="simulation" if isinstance(self.provider, SimulatedInputProvider) else None,
        )
        self.raise_on_error = raise_on_error
        self.normalizer = Normalizer()
        self.engine = MappingEngine(
            backend=self.backend,
            clock=self.clock,
            diagnostics=self.diagnostics,
        )

    @property
    def state(self) -> RuntimeState:
        return self.engine.state_machine.state

    def start(self) -> None:
        self.provider.start()
        if self.state == RuntimeState.STOPPED:
            self.engine.state_machine.transition(RuntimeState.STARTING, "runtime_start")
            self.engine.state_machine.transition(RuntimeState.READY, "runtime_start")

    def load_profile(self, profile: ControlProfileV2) -> None:
        if self.state not in (RuntimeState.STARTING, RuntimeState.READY, RuntimeState.PROFILE_READY):
            self.safe_release("PROFILE_CHANGED")
            self.engine.state_machine.transition(RuntimeState.READY, "profile_reload")
            self.engine.state_machine.transition(RuntimeState.PROFILE_LOADING, "profile_reload")
        self.engine.load_profile(profile)

    def activate(self) -> None:
        self.engine.activate()

    def pump(self) -> list[dict]:
        """Entrega todos os eventos pendentes; DOWN/UP nunca sao coalescidos."""
        produced: list[dict] = []
        try:
            with self.diagnostics.stage("provider"):
                events = self.provider.read_events()
            for raw in events:
                with self.diagnostics.stage("normalize"):
                    event = self.normalizer.normalize(raw)
                try:
                    with self.diagnostics.stage("backend"):
                        produced.extend(self.engine.handle_event(event))
                except Exception as error:
                    self.diagnostics.error(type(error).__name__)
                    self.safe_release("EXCEPTION")
                    if self.raise_on_error:
                        raise
        except Exception as error:
            self.diagnostics.error(type(error).__name__)
            self.safe_release("EXCEPTION")
            if self.raise_on_error:
                raise
        return produced

    def run_script(self, script, *, start: float = 1000.0, step: float = 0.001) -> list[dict]:
        self.provider.emit_script(script, start=start, step=step)
        return self.pump()

    def safe_release(self, reason: str) -> object:
        return self.engine.safe_release(reason)

    def shutdown(self) -> object:
        report = self.safe_release("SHUTDOWN")
        if self.state not in (RuntimeState.STOPPING, RuntimeState.STOPPED):
            self.engine.state_machine.transition(RuntimeState.STOPPING, "shutdown")
        self.engine.state_machine.transition(RuntimeState.STOPPED, "shutdown")
        self.provider.stop()
        return report

    def snapshot(self) -> dict:
        data = self.diagnostics.snapshot()
        data["state_machine"] = self.engine.state_machine.snapshot()
        data["active_contacts"] = [contact.to_dict() for contact in self.engine.contacts.active_contacts]
        data["contact_stats"] = dict(self.engine.contacts.stats)
        data["cursor"] = {
            "position": self.cursor.position,
            "aim_active": self.engine.aim_active,
            "menu_touch": self.engine.state_machine.state == RuntimeState.MENU_TOUCH,
        }
        data["profile"] = self.engine.profile.name if self.engine.profile else ""
        return data

    @property
    def cursor(self):
        return self.engine.cursor


__all__ = ["InputRuntime"]
