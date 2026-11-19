"""Adaptador Phantom: valida, converte e consulta, sem iniciar o daemon.

Nenhum comando e executado por padrao. O chamador deve injetar um `runner`
explicito (o servico Qt existente faz isso no launcher). Testes simulados nunca
executam Phantom.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from ...controls.model import ControlProfileV2, ProfileError
from ...controls.phantom import export_phantom_profile
from ...services import capabilities as cap

CommandResult = object
Runner = Callable[[list[str]], CommandResult]


class PhantomUnavailable(RuntimeError):
    """Phantom ausente ou runner nao foi injetado."""


class PhantomCommandError(RuntimeError):
    """Comando Phantom recusado."""


@dataclass
class PhantomValidation:
    accepted: bool
    warnings: list[str]
    profile: dict | None = None


class PhantomAdapter:
    """Integracao segura com os comandos existentes do Phantom."""

    commands = ("status", "audit", "load", "enter-capture", "exit-capture", "toggle-mouse")

    def __init__(
        self,
        *,
        runner: Runner | None = None,
        tools: dict[str, str] | None = None,
        available: bool | None = None,
        path: str = "",
    ) -> None:
        self._runner = runner
        self.tools = dict(tools) if tools is not None else cap.detect_tools()
        self.path = path or self.tools.get("phantom", "")
        self._available = available
        self.executed: list[list[str]] = []

    @property
    def available(self) -> bool:
        if self._available is not None:
            return bool(self._available)
        return bool(self.path)

    def describe(self) -> cap.Capability:
        if self.available:
            return cap.Capability(
                "Backend Phantom",
                cap.Support.PARTIAL,
                f"Executavel candidato em {self.path or 'runner injetado'}.",
                "Disponibilidade nao prova captura ou injecao; exige teste fisico.",
            )
        return cap.Capability(
            "Backend Phantom",
            cap.Support.UNSUPPORTED,
            "Phantom nao detectado.",
            "Instale separadamente se desejar usar este backend.",
        )

    def readiness(self) -> dict:
        """Estados separados conforme a politica de portabilidade."""
        return {
            "detected": self.available,
            "dependencies_available": self.available,
            "prerequisites_met": self.available,
            "initialization_possible": self.available and self._runner is not None,
            "functional": False,
            "tested": False,
            "operational": False,
            "unsupported": not self.available,
        }

    def validate_profile(
        self,
        profile: ControlProfileV2,
        *,
        allow_unverified: bool = False,
    ) -> PhantomValidation:
        try:
            result = export_phantom_profile(profile, allow_unverified=allow_unverified)
        except ProfileError as error:
            return PhantomValidation(False, [str(error)])
        return PhantomValidation(True, list(result.warnings), result.profile)

    def load_profile(
        self,
        profile: ControlProfileV2,
        path: str | Path,
        *,
        allow_unverified: bool = False,
    ) -> object:
        validation = self.validate_profile(profile, allow_unverified=allow_unverified)
        if not validation.accepted:
            raise ProfileError("Perfil rejeitado antes de carregar no Phantom: " + "; ".join(validation.warnings))
        return self._run(["load", str(path)])

    def audit_profile(self, path: str | Path) -> object:
        return self._run(["audit", str(path)])

    def status(self) -> object:
        return self._run(["status"])

    def enter_capture(self) -> object:
        """Ativa captura somente por comando explicito do chamador."""
        return self._run(["enter-capture"])

    def exit_capture(self) -> object:
        return self._run(["exit-capture"])

    def toggle_mouse(self) -> object:
        return self._run(["toggle-mouse"])

    def _run(self, args: list[str]) -> object:
        if not self.available:
            raise PhantomUnavailable("Phantom nao detectado; nenhum comando foi executado.")
        if self._runner is None:
            raise PhantomUnavailable("Runner nao injetado; nenhum comando Phantom foi executado.")
        command = [str(arg) for arg in args]
        if command[0] not in self.commands:
            raise PhantomCommandError(f"Comando nao permitido: {command[0]!r}")
        self.executed.append(list(command))
        return self._runner(command)


__all__ = [
    "PhantomAdapter",
    "PhantomValidation",
    "PhantomUnavailable",
    "PhantomCommandError",
]
