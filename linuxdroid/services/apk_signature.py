"""Identidade de assinatura de splits APK, sem dependências externas.

**O que este módulo FAZ**

* localiza o APK Signing Block (esquemas v2/v3);
* extrai a chave pública ``SubjectPublicKeyInfo`` DER de cada assinante;
* usa o SHA-256 dessa chave como *fingerprint do assinante*;
* confirma que todos os splits de um XAPK declaram o mesmo assinante.

**O que este módulo NÃO FAZ**

* não valida criptograficamente a assinatura sobre os bytes do APK;
* não substitui a verificação feita pelo ``PackageManager`` do Android;
* não aceita APKs assinados apenas com v1 (sem bloco v2/v3): a leitura é
  reportada como inconclusiva e a verificação **falha fechada**.

A comparação de identidade é uma checagem antecipada de coerência: um XAPK
cujos splits tenham assinantes diferentes é rejeitado antes de qualquer
instalação. Nenhuma operação de instalação é executada aqui.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
from pathlib import Path
import struct
from typing import Iterable, Optional, Sequence

SIGNING_BLOCK_MAGIC = b"APK Sig Block 42"
V2_BLOCK_ID = 0x7109871A
V3_BLOCK_ID = 0xF05368C0
V31_BLOCK_ID = 0x1B93AD61
_EOCD_SIGNATURE = b"PK\x05\x06"
_MAX_TAIL = 65557
_MAX_PUBLIC_KEY_BYTES = 4096
_MIN_PUBLIC_KEY_BYTES = 32

__all__ = [
    "SignerIdentity",
    "SignatureVerification",
    "inspect_apk",
    "verify_split_signatures",
]


@dataclass(frozen=True)
class SignerIdentity:
    """Chave pública de um assinante, identificada por SHA-256 do SPKI DER."""

    fingerprint: str
    scheme: str
    note: str = ""

    @property
    def key(self) -> str:
        return self.fingerprint


@dataclass(frozen=True)
class SignatureVerification:
    """Resultado da comparação de assinantes entre splits."""

    ok: bool
    identities: tuple
    message: str
    paths: tuple

    def to_dict(self) -> dict:
        return {
            "ok": self.ok,
            "identities": [
                {"fingerprint": i.fingerprint, "scheme": i.scheme, "note": i.note}
                for i in self.identities
            ],
            "message": self.message,
            "paths": [str(p) for p in self.paths],
        }


def _read_u32(data: bytes, offset: int) -> int:
    if offset < 0 or offset + 4 > len(data):
        raise ValueError("u32 fora dos limites")
    return struct.unpack_from("<I", data, offset)[0]


def _read_u64(data: bytes, offset: int) -> int:
    if offset < 0 or offset + 8 > len(data):
        raise ValueError("u64 fora dos limites")
    return struct.unpack_from("<Q", data, offset)[0]


def _length_prefixed(data: bytes, offset: int) -> tuple[bytes, int]:
    length = _read_u32(data, offset)
    start = offset + 4
    end = start + length
    if length < 0 or end > len(data):
        raise ValueError("campo com prefixo de tamanho inválido")
    return data[start:end], end


def _find_signing_block_pairs(path: Path) -> Optional[bytes]:
    """Devolve a região de pares ID→valor do APK Signing Block, se houver."""
    size = path.stat().st_size
    if size < 4096:
        return None
    with path.open("rb") as handle:
        handle.seek(max(0, size - _MAX_TAIL))
        tail = handle.read()
        eocd = tail.rfind(_EOCD_SIGNATURE)
        if eocd < 0 or eocd + 22 > len(tail):
            return None
        cd_offset = _read_u32(tail, eocd + 16)
        if cd_offset == 0xFFFFFFFF or cd_offset < 24 or cd_offset > size:
            return None
        handle.seek(cd_offset - 24)
        trailer = handle.read(24)
        if len(trailer) != 24 or trailer[8:] != SIGNING_BLOCK_MAGIC:
            return None
        block_size = _read_u64(trailer, 0)
        if block_size < 24 or block_size > cd_offset - 8:
            return None
        block_start = cd_offset - block_size - 8
        handle.seek(block_start)
        header = handle.read(8)
        if len(header) != 8 or _read_u64(header, 0) != block_size:
            return None
        handle.seek(block_start + 8)
        pairs = handle.read(block_size - 24)
    return pairs if len(pairs) == block_size - 24 else None


def _iter_block_values(pairs: bytes) -> Iterable[tuple[int, bytes]]:
    offset = 0
    while offset < len(pairs):
        pair_length = _read_u64(pairs, offset)
        offset += 8
        if pair_length < 4 or offset + pair_length > len(pairs):
            raise ValueError("par do signing block inválido")
        block_id = _read_u32(pairs, offset)
        yield block_id, pairs[offset + 4 : offset + pair_length]
        offset += pair_length


def _fingerprints_from_value(value: bytes, *, with_sdk: bool) -> list[str]:
    """Extrai SPKI DER dos assinantes; `with_sdk` selects v3 layout."""
    signers, offset = _length_prefixed(value, 0)
    if offset != len(value):
        raise ValueError("sobra de bytes no bloco do assinante")
    fingerprints = []
    cursor = 0
    while cursor < len(signers):
        signer, cursor = _length_prefixed(signers, cursor)
        try:
            position = 0
            _signed_data, position = _length_prefixed(signer, position)
            if with_sdk:
                # v3/v3.1: minSdkVersion e maxSdkVersion (uint32 cada).
                position += 8
            _signatures, position = _length_prefixed(signer, position)
            public_key, position = _length_prefixed(signer, position)
            if (
                public_key[:1] == b"\x30"
                and _MIN_PUBLIC_KEY_BYTES <= len(public_key) <= _MAX_PUBLIC_KEY_BYTES
            ):
                fingerprints.append(hashlib.sha256(public_key).hexdigest())
        except ValueError:
            continue
    return fingerprints


def _fingerprints_from_block(value: bytes) -> list[str]:
    for with_sdk in (False, True):
        try:
            found = _fingerprints_from_value(value, with_sdk=with_sdk)
        except ValueError:
            continue
        if found:
            return found
    return []


def inspect_apk(path) -> Optional[SignerIdentity]:
    """Lê a identidade do assinante; ``None`` significa inconclusivo."""
    path = Path(path)
    try:
        pairs = _find_signing_block_pairs(path)
        if pairs is None:
            return None
        values = list(_iter_block_values(pairs))
    except (OSError, ValueError, struct.error):
        return None

    for wanted, scheme in ((V2_BLOCK_ID, "v2"), (V3_BLOCK_ID, "v3"), (V31_BLOCK_ID, "v3.1")):
        for block_id, value in values:
            if block_id != wanted:
                continue
            fingerprints = sorted(set(_fingerprints_from_block(value)))
            if fingerprints:
                return SignerIdentity(
                    fingerprint="+".join(fingerprints),
                    scheme=scheme,
                    note="Identidade da chave pública; não é verificação criptográfica do arquivo.",
                )
    return None


def verify_split_signatures(paths: Sequence) -> SignatureVerification:
    """Exige que todos os splits tenham a mesma identidade de assinante.

    Um split inconclusivo (por exemplo, assinado apenas com v1) faz a
    verificação falhar: ausência de evidência nunca é tratada como sucesso.
    """
    paths = tuple(Path(p) for p in paths)
    if not paths:
        return SignatureVerification(False, (), "Nenhum split foi informado.", paths)
    identities = []
    for path in paths:
        identity = inspect_apk(path)
        if identity is None:
            return SignatureVerification(
                False,
                tuple(identities),
                f"Assinatura inconclusiva em '{path.name}' (sem bloco v2/v3 legível).",
                paths,
            )
        identities.append(identity)
    unique = {identity.key for identity in identities}
    if len(unique) != 1:
        return SignatureVerification(
            False,
            tuple(identities),
            "Splits têm assinantes diferentes; instalação recusada.",
            paths,
        )
    return SignatureVerification(
        True,
        tuple(identities),
        f"Todos os {len(identities)} splits têm o mesmo assinante ({identities[0].scheme}).",
        paths,
    )
