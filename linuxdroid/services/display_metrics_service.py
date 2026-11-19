"""Serviço Qt que mede a superfície Android sem alterar o container.

Todas as consultas são **somente leitura** (``wm size``, ``wm density``,
``dumpsys display``) e são disparadas apenas por uma ação explícita do usuário
(o botão "Detectar resolução"). Nenhuma medição acontece em segundo plano.

O runner é injetado, então a orquestração é testável sem Qt e sem executar
comandos: basta um objeto com ``run(program, args, callback, timeout_ms)``.
"""
from __future__ import annotations

from typing import Any, Callable, Optional

from PySide6.QtCore import QObject, Signal

from .display_metrics import DisplayMetrics, from_command_outputs, unknown
from .process_runner import ProcessRunner

SHELL_PROGRAM = "waydroid"
SHELL_PREFIX = ("shell",)

__all__ = ["DisplayMetricsService"]


class DisplayMetricsService(QObject):
    """Consulta a superfície e publica o resultado como ``DisplayMetrics``."""

    metrics_detected = Signal(object)
    log_line = Signal(str)

    def __init__(self, runner: Optional[Any] = None, parent: Optional[QObject] = None):
        super().__init__(parent)
        self.runner = runner if runner is not None else ProcessRunner(self)

    def detect(self, timeout_ms: int = 12000) -> None:
        """Dispara a sequência de consultas. O chamador decide quando chamar."""
        self.log_line.emit("$ waydroid shell wm size")
        self._run(SHELL_PREFIX + ("wm", "size"), lambda r: self._on_size(r, timeout_ms), timeout_ms)

    def _run(self, args: tuple, callback: Callable, timeout_ms: int) -> None:
        self.runner.run(SHELL_PROGRAM, list(args), callback, timeout_ms)

    @staticmethod
    def _text(result: Any) -> str:
        if result is None or not getattr(result, "ok", False):
            return ""
        return (getattr(result, "stdout", "") or "").strip()

    def _on_size(self, size_result: Any, timeout_ms: int) -> None:
        size = self._text(size_result)
        self.log_line.emit("$ waydroid shell wm density")
        self._run(
            SHELL_PREFIX + ("wm", "density"),
            lambda r: self._on_density(size, r, timeout_ms),
            timeout_ms,
        )

    def _on_density(self, size: str, density_result: Any, timeout_ms: int) -> None:
        density = self._text(density_result)
        self.log_line.emit("$ waydroid shell dumpsys display")
        self._run(
            SHELL_PREFIX + ("dumpsys", "display"),
            lambda r: self._on_dumpsys(size, density, r),
            timeout_ms,
        )

    def _on_dumpsys(self, size: str, density: str, dumpsys_result: Any) -> None:
        dumpsys = self._text(dumpsys_result)
        metrics = from_command_outputs(size, density, dumpsys)
        if not metrics.known:
            reason = getattr(dumpsys_result, "error", "") or ""
            suffix = f" ({reason})" if reason else ""
            metrics = unknown("Container não respondeu às consultas de resolução" + suffix)
            self.log_line.emit("Resolução NÃO MEDIDA: " + metrics.note)
        else:
            self.log_line.emit(f"Resolução {metrics.status_label}: {metrics.label} ({metrics.source})")
        self.metrics_detected.emit(metrics)

    def shutdown(self) -> None:
        shutdown = getattr(self.runner, "shutdown", None)
        if shutdown is not None:
            shutdown()
