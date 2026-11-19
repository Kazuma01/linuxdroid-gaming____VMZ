"""Diagnostico interno do motor, sem logar texto digitado nem fingir injecao."""
from __future__ import annotations

import time
from contextlib import contextmanager
from dataclasses import dataclass, field

MODES = frozenset({"simulation", "recording_backend", "real_backend"})


@dataclass
class Diagnostics:
    mode: str = "simulation"
    provider: str = "none"
    backend: str = "none"
    backend_is_real: bool = False
    profile_name: str = ""
    events_received: int = 0
    events_dropped: int = 0
    commands_recorded: int = 0
    contacts_down: int = 0
    contacts_released: int = 0
    errors: list[dict] = field(default_factory=list)
    safe_release_reasons: list[str] = field(default_factory=list)
    event_types: dict[str, int] = field(default_factory=dict)
    stage_timings_ms: dict[str, list[float]] = field(default_factory=dict)
    clock: object = field(default_factory=lambda: time.monotonic, repr=False, compare=False)

    def __post_init__(self) -> None:
        if self.mode not in MODES:
            raise ValueError(f"Modo de diagnostico desconhecido: {self.mode!r}")

    def configure(
        self,
        *,
        provider: str,
        backend: str,
        backend_is_real: bool = False,
        profile_name: str = "",
        mode: str | None = None,
    ) -> None:
        self.provider = provider
        self.backend = backend
        self.backend_is_real = bool(backend_is_real)
        self.profile_name = profile_name
        if mode is not None:
            self.mode = mode
        elif backend_is_real:
            self.mode = "real_backend"
        else:
            self.mode = "recording_backend" if backend != "none" else "simulation"

    def record_event(self, event_type: str) -> None:
        self.events_received += 1
        self.event_types[event_type] = self.event_types.get(event_type, 0) + 1

    def drop_event(self, reason: str) -> None:
        self.events_dropped += 1
        self.errors.append({"type": "dropped", "detail": str(reason)[:200], "timestamp": self.now()})

    def error(self, kind: str, detail: str = "") -> None:
        """Registra apenas uma categoria curta.

        `detail` e aceito por compatibilidade de assinatura, mas NUNCA e
        persistido: textos digitados, nomes de janela e mensagens livres nao
        podem entrar no diagnostico.
        """
        del detail
        self.errors.append({"type": str(kind)[:120], "detail": "", "timestamp": self.now()})

    def safe_release(self, reason: str) -> None:
        self.safe_release_reasons.append(str(reason)[:200])

    @contextmanager
    def stage(self, name: str):
        start = self.now()
        try:
            yield
        finally:
            elapsed_ms = (self.now() - start) * 1000.0
            self.stage_timings_ms.setdefault(name, []).append(round(elapsed_ms, 4))

    def now(self) -> float:
        return float(self.clock())

    def snapshot(self) -> dict:
        timings = {
            name: {
                "samples": len(values),
                "last_ms": values[-1] if values else 0.0,
                "max_ms": max(values) if values else 0.0,
            }
            for name, values in self.stage_timings_ms.items()
        }
        label = {
            "simulation": "SIMULACAO — nenhum backend real envolvido",
            "recording_backend": "BACKEND DE GRAVACAO — comandos apenas em memoria, nada injetado",
            "real_backend": "BACKEND REAL — exige confirmacao explicita e teste fisico",
        }[self.mode]
        return {
            "mode": self.mode,
            "mode_label": label,
            "injection_claimed": False,
            "provider": self.provider,
            "backend": self.backend,
            "backend_is_real": self.backend_is_real,
            "profile_name": self.profile_name,
            "events_received": self.events_received,
            "events_dropped": self.events_dropped,
            "event_types": dict(self.event_types),
            "commands_recorded": self.commands_recorded,
            "contacts_down": self.contacts_down,
            "contacts_released": self.contacts_released,
            "errors": list(self.errors),
            "safe_release_reasons": list(self.safe_release_reasons),
            "stage_timings_ms": timings,
        }


__all__ = ["Diagnostics", "MODES"]
