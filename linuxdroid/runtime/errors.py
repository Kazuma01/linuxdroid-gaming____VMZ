"""Erros estruturados do Runtime Manager.

Exceções são usadas somente dentro da camada de runtime. A interface recebe
``OperationResult`` / ``RuntimeFailure``, nunca uma exceção crua de subprocess.
"""
from __future__ import annotations

from typing import Any, Optional

from .models import (
    RuntimeErrorCode,
    RuntimeFailure,
    RuntimeOperation,
)

__all__ = [
    "RuntimeErrorCode",
    "RuntimeFailure",
    "RuntimeFailureError",
    "make_failure",
    "map_exception",
]


class RuntimeFailureError(Exception):
    """Exceção interna que carrega um ``RuntimeFailure`` já normalizado."""

    def __init__(self, failure: RuntimeFailure):
        self.failure = failure
        super().__init__(failure.message)

    @property
    def code(self) -> RuntimeErrorCode:
        return self.failure.code

    @property
    def retryable(self) -> bool:
        return self.failure.retryable

    @property
    def operation(self) -> Optional[RuntimeOperation]:
        return self.failure.operation


def make_failure(
    code: RuntimeErrorCode,
    message: str,
    *,
    operation: Optional[RuntimeOperation] = None,
    detail: str = "",
    retryable: bool = False,
) -> RuntimeFailure:
    """Cria um erro com mensagem curta e detalhe opcional (sanitizado)."""
    return RuntimeFailure(
        code=code,
        message=" ".join(str(message).split()),
        operation=operation,
        detail=" ".join(str(detail).split())[:500] if detail else "",
        retryable=retryable,
    )


def _code_from_text(text: str) -> Optional[RuntimeErrorCode]:
    low = text.lower()
    if "not initialized" in low or "não inicializado" in low:
        return RuntimeErrorCode.NOT_INITIALIZED
    if "permission denied" in low or "permissão negada" in low or "access denied" in low:
        return RuntimeErrorCode.PERMISSION_DENIED
    if "not found" in low or "não encontrado" in low or "não existe" in low:
        return RuntimeErrorCode.NOT_FOUND
    if "service" in low and ("unavailable" in low or "indisponível" in low):
        return RuntimeErrorCode.SERVICE_UNAVAILABLE
    return None


def map_exception(
    exc: BaseException,
    *,
    operation: Optional[RuntimeOperation] = None,
) -> RuntimeFailure:
    """Converte qualquer exceção de adaptador em erro estruturado estável."""
    if isinstance(exc, RuntimeFailureError):
        failure = exc.failure
        if operation and failure.operation is None:
            return make_failure(
                failure.code,
                failure.message,
                operation=operation,
                detail=failure.detail,
                retryable=failure.retryable,
            )
        return failure
    if isinstance(exc, PermissionError):
        return make_failure(
            RuntimeErrorCode.PERMISSION_DENIED,
            "Permissão negada ao acessar o runtime.",
            operation=operation,
            detail=str(exc),
        )
    if isinstance(exc, FileNotFoundError):
        return make_failure(
            RuntimeErrorCode.NOT_FOUND,
            "Serviço ou executável do runtime não encontrado.",
            operation=operation,
            detail=str(exc),
        )
    if isinstance(exc, (ValueError, TypeError, AttributeError, KeyError)):
        return make_failure(
            RuntimeErrorCode.INVALID_RESPONSE,
            "O runtime devolveu uma resposta inválida.",
            operation=operation,
            detail=str(exc),
            retryable=True,
        )
    text = str(exc)
    code = _code_from_text(text) or RuntimeErrorCode.BACKEND_ERROR
    return make_failure(
        code,
        "O adaptador de runtime falhou.",
        operation=operation,
        detail=text,
        retryable=code in (RuntimeErrorCode.SERVICE_UNAVAILABLE, RuntimeErrorCode.BACKEND_ERROR),
    )
