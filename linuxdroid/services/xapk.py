"""Extração segura de splits APK contidos em XAPK.

Não depende de PySide6. Usa streaming, cotas e fechamento garantido para
evitar que um arquivo comprimido pequeno gere consumo ilimitado de memória.
"""
from pathlib import Path
import zipfile

DEFAULT_MAX_MEMBER_BYTES = 2 * 1024 ** 3
DEFAULT_MAX_TOTAL_BYTES = 6 * 1024 ** 3
DEFAULT_MAX_COMPRESSION_RATIO = 500
_CHUNK_SIZE = 1024 * 1024


def extract_apk_members(
    archive_path,
    destination,
    *,
    max_member_bytes=DEFAULT_MAX_MEMBER_BYTES,
    max_total_bytes=DEFAULT_MAX_TOTAL_BYTES,
    max_compression_ratio=DEFAULT_MAX_COMPRESSION_RATIO,
):
    """Extrai apenas membros .apk para ``destination`` e devolve a lista de Paths."""
    destination = Path(destination)
    extracted = []
    total_declared = 0

    with zipfile.ZipFile(archive_path) as archive:
        members = [
            member for member in archive.infolist()
            if not member.is_dir() and member.filename.lower().endswith(".apk")
        ]
        if not members:
            raise ValueError("O XAPK não contém arquivos APK.")

        for index, member in enumerate(members):
            if member.file_size > max_member_bytes:
                raise ValueError(
                    f"Split '{member.filename}' é grande demais "
                    f"({member.file_size} bytes; limite {max_member_bytes})."
                )
            if member.compress_size == 0 and member.file_size > 0:
                raise ValueError(f"Split '{member.filename}' tem razão de compressão inválida.")
            ratio = member.file_size / max(member.compress_size, 1)
            if ratio > max_compression_ratio:
                raise ValueError(
                    f"Split '{member.filename}' tem razão de compressão suspeita "
                    f"({ratio:.0f}:1; limite {max_compression_ratio}:1)."
                )

            total_declared += member.file_size
            if total_declared > max_total_bytes:
                raise ValueError(
                    f"Total dos splits excede o limite de {max_total_bytes} bytes."
                )

            target = destination / f"split_{index:02d}_{Path(member.filename).name}"
            written = 0
            with archive.open(member) as source, target.open("wb") as output:
                while True:
                    chunk = source.read(_CHUNK_SIZE)
                    if not chunk:
                        break
                    written += len(chunk)
                    running_total = total_declared - member.file_size + written
                    if written > max_member_bytes or running_total > max_total_bytes:
                        target.unlink(missing_ok=True)
                        raise ValueError("Split excedeu a cota durante a extração.")
                    output.write(chunk)

            if written != member.file_size:
                target.unlink(missing_ok=True)
                raise ValueError(f"Split '{member.filename}' foi truncado na extração.")
            extracted.append(target)

    return extracted
