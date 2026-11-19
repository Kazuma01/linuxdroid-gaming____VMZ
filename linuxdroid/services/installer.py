"""Planejamento de instalação: extrai splits e verifica identidade de assinante.

Este módulo é puro (sem Qt) e **não instala nada**: ele produz um plano com os
arquivos prontos e o resultado da verificação. A instalação real continua sendo
uma operação explícita do usuário, executada pelo caminho já existente.

Regras de segurança:

* todo plano de XAPK passa pela verificação de assinante;
* verificação inconclusiva (por exemplo, APK assinado só com v1) falha fechada;
* se a verificação falhar, os splits extraídos são removidos — nenhum arquivo
  não verificado permanece no destino;
* nenhuma assinatura é forjada, ignorada ou substituída.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Tuple
import zipfile

from .apk_signature import SignatureVerification, inspect_apk, verify_split_signatures
from .xapk import extract_apk_members

__all__ = ["InstallationPlan", "plan_xapk_installation", "plan_apk_installation"]


@dataclass(frozen=True)
class InstallationPlan:
    """Plano resultante da extração e verificação; não executa instalação."""

    ok: bool
    apks: Tuple[Path, ...]
    verification: Optional[SignatureVerification]
    message: str

    def to_dict(self) -> dict:
        return {
            "ok": self.ok,
            "apks": [str(path) for path in self.apks],
            "verification": self.verification.to_dict() if self.verification else None,
            "message": self.message,
        }


def plan_xapk_installation(archive_path, destination, **extraction_options) -> InstallationPlan:
    """Extrai splits de um XAPK e exige um único assinante entre eles."""
    try:
        apks = extract_apk_members(archive_path, destination, **extraction_options)
    except (ValueError, OSError, zipfile.BadZipFile, KeyError) as exc:
        return InstallationPlan(False, (), None, f"Extração recusada: {exc}")

    verification = verify_split_signatures(apks)
    if not verification.ok:
        # Remove apenas os arquivos que acabaram de ser criados por esta chamada.
        for apk in apks:
            try:
                apk.unlink(missing_ok=True)
            except OSError:
                pass
        return InstallationPlan(False, (), verification, verification.message)

    return InstallationPlan(True, tuple(apks), verification, verification.message)


def plan_apk_installation(apk_path) -> InstallationPlan:
    """Plano para um APK único: ainda exige identidade de assinante legível."""
    path = Path(apk_path)
    identity = inspect_apk(path)
    if identity is None:
        return InstallationPlan(
            False,
            (),
            None,
            f"Assinatura inconclusiva em '{path.name}'; instalação não planejada.",
        )
    verification = SignatureVerification(
        True, (identity,), f"Assinante identificado ({identity.scheme}).", (path,)
    )
    return InstallationPlan(True, (path,), verification, verification.message)
