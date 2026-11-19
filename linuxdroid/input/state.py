"""Maquina de estados explicita do runtime e do cursor virtual."""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum

from ..controls.cursor import CAPTURE_STATES


class RuntimeState(str, Enum):
    STOPPED = "STOPPED"
    STARTING = "STARTING"
    READY = "READY"
    PROFILE_LOADING = "PROFILE_LOADING"
    PROFILE_READY = "PROFILE_READY"
    CAPTURE_ACTIVE = "CAPTURE_ACTIVE"
    MENU_TOUCH = "MENU_TOUCH"
    AIM_ACTIVE = "AIM_ACTIVE"
    PAUSED = "PAUSED"
    FOCUS_LOST = "FOCUS_LOST"
    SAFE_RELEASE = "SAFE_RELEASE"
    BACKEND_DISCONNECTED = "BACKEND_DISCONNECTED"
    ERROR = "ERROR"
    STOPPING = "STOPPING"


ALLOWED_TRANSITIONS: dict[RuntimeState, frozenset[RuntimeState]] = {
    RuntimeState.STOPPED: frozenset({RuntimeState.STARTING}),
    RuntimeState.STARTING: frozenset({
        RuntimeState.READY, RuntimeState.ERROR, RuntimeState.STOPPING, RuntimeState.SAFE_RELEASE,
    }),
    RuntimeState.READY: frozenset({
        RuntimeState.PROFILE_LOADING, RuntimeState.CAPTURE_ACTIVE,
        RuntimeState.STOPPING, RuntimeState.SAFE_RELEASE, RuntimeState.ERROR,
    }),
    RuntimeState.PROFILE_LOADING: frozenset({
        RuntimeState.PROFILE_READY, RuntimeState.ERROR, RuntimeState.SAFE_RELEASE,
    }),
    RuntimeState.PROFILE_READY: frozenset({
        RuntimeState.CAPTURE_ACTIVE, RuntimeState.PROFILE_LOADING,
        RuntimeState.STOPPING, RuntimeState.SAFE_RELEASE, RuntimeState.ERROR,
    }),
    RuntimeState.CAPTURE_ACTIVE: frozenset({
        RuntimeState.CAPTURE_ACTIVE, RuntimeState.MENU_TOUCH, RuntimeState.AIM_ACTIVE,
        RuntimeState.PAUSED, RuntimeState.FOCUS_LOST, RuntimeState.SAFE_RELEASE,
        RuntimeState.BACKEND_DISCONNECTED, RuntimeState.ERROR, RuntimeState.STOPPING,
        RuntimeState.PROFILE_LOADING,
    }),
    RuntimeState.MENU_TOUCH: frozenset({
        RuntimeState.CAPTURE_ACTIVE, RuntimeState.AIM_ACTIVE, RuntimeState.PAUSED,
        RuntimeState.FOCUS_LOST, RuntimeState.SAFE_RELEASE,
        RuntimeState.BACKEND_DISCONNECTED, RuntimeState.ERROR, RuntimeState.STOPPING,
        RuntimeState.PROFILE_LOADING,
    }),
    RuntimeState.AIM_ACTIVE: frozenset({
        RuntimeState.CAPTURE_ACTIVE, RuntimeState.MENU_TOUCH, RuntimeState.PAUSED,
        RuntimeState.FOCUS_LOST, RuntimeState.SAFE_RELEASE,
        RuntimeState.BACKEND_DISCONNECTED, RuntimeState.ERROR, RuntimeState.STOPPING,
        RuntimeState.PROFILE_LOADING,
    }),
    RuntimeState.PAUSED: frozenset({
        RuntimeState.CAPTURE_ACTIVE, RuntimeState.MENU_TOUCH, RuntimeState.AIM_ACTIVE,
        RuntimeState.SAFE_RELEASE, RuntimeState.STOPPING,
        RuntimeState.PROFILE_LOADING, RuntimeState.ERROR,
    }),
    RuntimeState.FOCUS_LOST: frozenset({
        RuntimeState.CAPTURE_ACTIVE, RuntimeState.SAFE_RELEASE,
        RuntimeState.STOPPING, RuntimeState.ERROR,
    }),
    RuntimeState.SAFE_RELEASE: frozenset({
        RuntimeState.READY, RuntimeState.PROFILE_READY, RuntimeState.STOPPING,
        RuntimeState.ERROR, RuntimeState.STOPPED, RuntimeState.PROFILE_LOADING,
        RuntimeState.PAUSED, RuntimeState.CAPTURE_ACTIVE,
        RuntimeState.FOCUS_LOST, RuntimeState.BACKEND_DISCONNECTED,
    }),
    RuntimeState.BACKEND_DISCONNECTED: frozenset({
        RuntimeState.SAFE_RELEASE, RuntimeState.READY, RuntimeState.STOPPING, RuntimeState.ERROR,
    }),
    RuntimeState.ERROR: frozenset({
        RuntimeState.SAFE_RELEASE, RuntimeState.STOPPING, RuntimeState.READY,
    }),
    RuntimeState.STOPPING: frozenset({RuntimeState.STOPPED, RuntimeState.ERROR}),
}

# Transicoes de seguranca tem prioridade e sao permitidas a partir de qualquer
# estado ativo, independentemente da tabela nominal.
PRIORITY_TARGETS = frozenset({
    RuntimeState.SAFE_RELEASE,
    RuntimeState.BACKEND_DISCONNECTED,
    RuntimeState.FOCUS_LOST,
    RuntimeState.ERROR,
    RuntimeState.STOPPING,
})

ACTIVE_STATES = frozenset({
    RuntimeState.CAPTURE_ACTIVE,
    RuntimeState.MENU_TOUCH,
    RuntimeState.AIM_ACTIVE,
})


class InvalidTransition(RuntimeError):
    """Transicao nao permitida pela maquina de estados."""


@dataclass
class SafeReleaseReport:
    reason: str
    timestamp: float
    state_before: str
    state_after: str
    actions: list[str] = field(default_factory=list)
    idempotent: bool = False

    def to_dict(self) -> dict:
        return {
            "reason": self.reason,
            "timestamp": self.timestamp,
            "state_before": self.state_before,
            "state_after": self.state_after,
            "actions": list(self.actions),
            "idempotent": self.idempotent,
        }


class CaptureStateMachine:
    """Estado do runtime com nocao explicita de captura virtual e fisica."""

    def __init__(self, *, clock=None) -> None:
        self.clock = clock or time.monotonic
        self.state = RuntimeState.STOPPED
        self.history: list[tuple[str, str, float]] = []
        self.virtual_capture_state = "released"
        self.physical_pointer_capture_state = "unknown"
        self._last_release: SafeReleaseReport | None = None

    @property
    def active(self) -> bool:
        return self.state in ACTIVE_STATES

    @property
    def last_release(self) -> SafeReleaseReport | None:
        return self._last_release

    def transition(self, target: RuntimeState | str, reason: str = "") -> bool:
        target = RuntimeState(str(target).upper()) if not isinstance(target, RuntimeState) else target
        if target == self.state:
            return False
        allowed = target in PRIORITY_TARGETS or target in ALLOWED_TRANSITIONS[self.state]
        if not allowed:
            raise InvalidTransition(
                f"Transicao invalida: {self.state.value} -> {target.value} ({reason or 'sem motivo'})."
            )
        before = self.state
        self.state = target
        self.history.append((before.value, target.value, self.clock()))
        if target in (RuntimeState.SAFE_RELEASE, RuntimeState.FOCUS_LOST, RuntimeState.PAUSED):
            self.virtual_capture_state = "released"
            if target == RuntimeState.SAFE_RELEASE:
                self.physical_pointer_capture_state = "released"
        if target == RuntimeState.STOPPED:
            self.virtual_capture_state = "released"
        return True

    def set_virtual_capture(self, active: bool) -> None:
        state = "captured" if active else "released"
        if state not in CAPTURE_STATES:
            raise ValueError(state)
        self.virtual_capture_state = state

    def set_physical_capture(self, active: bool, *, backend_confirmed: bool) -> None:
        """So afirma captura fisica se um backend real confirmar explicitamente."""
        if active and not backend_confirmed:
            self.physical_pointer_capture_state = "unknown"
            return
        self.physical_pointer_capture_state = "captured" if active else "released"

    def safe_release(self, reason: str, actions: list[str] | None = None) -> SafeReleaseReport:
        """Idempotente: uma segunda chamada nao reapaga estado nem duplica acoes."""
        before = self.state
        idempotent = before == RuntimeState.SAFE_RELEASE and self._last_release is not None
        if not idempotent:
            self.transition(RuntimeState.SAFE_RELEASE, reason)
        report = SafeReleaseReport(
            reason=reason,
            timestamp=self.clock(),
            state_before=before.value,
            state_after=self.state.value,
            actions=list(actions or []),
            idempotent=idempotent,
        )
        if not idempotent:
            self._last_release = report
        return report

    def snapshot(self) -> dict:
        return {
            "state": self.state.value,
            "active": self.active,
            "virtual_capture_state": self.virtual_capture_state,
            "physical_pointer_capture_state": self.physical_pointer_capture_state,
            "last_safe_release": self._last_release.to_dict() if self._last_release else None,
            "history_count": len(self.history),
        }


__all__ = [
    "RuntimeState",
    "ALLOWED_TRANSITIONS",
    "PRIORITY_TARGETS",
    "ACTIVE_STATES",
    "InvalidTransition",
    "SafeReleaseReport",
    "CaptureStateMachine",
]
