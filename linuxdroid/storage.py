"""Armazenamento local em JSON (~/.local/share/linuxdroid-gaming).

Os metodos antigos continuam intactos para nao quebrar o launcher. A camada
V2 adicionada aqui usa escrita atomica, backup, migracao explicita e
quarentena de JSON corrompido sem apagar o arquivo original.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import uuid
from pathlib import Path

from .controls.model import ControlProfileV2, ProfileError
from .input.profile_bridge import legacy_payload_to_profile, normalize_legacy_slots
from .models import GameEntry, Settings

DATA_DIR = Path.home() / ".local" / "share" / "linuxdroid-gaming"
PROFILE_V2_DIR = "controls_v2"


def _read(name: str, default):
    try:
        return load_json_recovered(DATA_DIR / name, default)
    except StorageError:
        # Legacy: mantem o comportamento tolerante; a copia em quarentena
        # preserva o conteudo corrompido para diagnostico.
        return default


def _write(name: str, data) -> bool:
    try:
        return atomic_write_json(DATA_DIR / name, data)
    except OSError:
        return False


def load_library() -> list[GameEntry]:
    raw = _read("library.json", None)
    if raw is None:
        return []
    known = frozenset(GameEntry.__dataclass_fields__)
    games = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        games.append(GameEntry(**{k: v for k, v in item.items() if k in known}))
    return games


def save_library(games: list[GameEntry]) -> bool:
    return _write("library.json", [g.to_dict() for g in games])


def load_settings() -> Settings:
    raw = _read("settings.json", {})
    known = {k: v for k, v in raw.items() if k in Settings.__dataclass_fields__}
    return Settings(**known)


def save_settings(s: Settings) -> bool:
    return _write("settings.json", s.__dict__)


def load_profiles() -> dict:
    return _read("profiles.json", {})


def save_profiles(profiles: dict) -> bool:
    return _write("profiles.json", profiles)


def load_game_controls(package_id: str) -> dict:
    profiles = _read("game_controls.json", {})
    return profiles.get(package_id, {}) if isinstance(profiles, dict) else {}


def save_game_controls(package_id: str, profile: dict) -> bool:
    profiles = _read("game_controls.json", {})
    if not isinstance(profiles, dict):
        profiles = {}
    profiles[package_id] = profile
    return _write("game_controls.json", profiles)


# ---------------------------------------------------------------------------
# Persistencia segura do schema V2
# ---------------------------------------------------------------------------


class StorageError(RuntimeError):
    """Falha de persistencia que nao deve ser engolida silenciosamente."""


def slugify(value: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_-]+", "_", str(value or "")).strip("_").lower() or "perfil"


def backup_file(path: Path, suffix: str = ".bak") -> Path | None:
    """Copia o arquivo antes de qualquer substituicao. Nunca apaga o original."""
    path = Path(path)
    if not path.is_file():
        return None
    backup = path.with_name(path.name + suffix)
    shutil.copy2(path, backup)
    return backup


def load_json_recovered(path: Path, default, *, corrupt_suffix: str = ".corrupt"):
    """Le JSON; se corrompido, guarda copia em quarentena e devolve `default`."""
    path = Path(path)
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return default
    try:
        return json.loads(text)
    except json.JSONDecodeError as error:
        quarantine = path.with_name(path.name + corrupt_suffix)
        try:
            backup_file(path, corrupt_suffix)
        except OSError:
            quarantine.write_text(text, encoding="utf-8")
        raise StorageError(
            f"JSON corrompido em {path.name}: {error}; copia em {quarantine.name}"
        ) from error
    except OSError as error:
        raise StorageError(f"Falha ao ler {path.name}: {error}") from error


def atomic_write_json(
    path: Path,
    data,
    *,
    backup: bool = True,
    overwrite: bool = True,
    write_text=None,
    replace=None,
) -> Path:
    """Escreve via temporario no mesmo filesystem e substitui atomicamente.

    `write_text` e `replace` sao injetaveis para testes de falha. `overwrite=False`
    protege contra sobrescrita acidental.
    """
    path = Path(path)
    if path.exists() and not overwrite:
        raise StorageError(f"Arquivo ja existe e sobrescrita foi recusada: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    content = json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True)
    writer = write_text or (lambda target, text: target.write_text(text, encoding="utf-8"))
    replacer = replace or os.replace
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        writer(temporary, content)
        if backup and path.exists():
            backup_file(path)
        replacer(temporary, path)
    except Exception:
        try:
            if temporary.exists():
                temporary.unlink()
        except OSError:
            pass
        raise
    return path


def control_profile_path(package_key: str) -> Path:
    return DATA_DIR / PROFILE_V2_DIR / f"{slugify(package_key)}.json"


def load_control_profile(package_key: str) -> ControlProfileV2 | None:
    """Carrega perfil V2. Formato antigo exige migracao explicita."""
    path = control_profile_path(package_key)
    raw = load_json_recovered(path, None)
    if raw is None:
        return None
    try:
        return ControlProfileV2.from_dict(raw)
    except ProfileError as error:
        raise StorageError(f"Perfil V2 incompativel em {path.name}: {error}") from error


def profile_to_issues(profile: ControlProfileV2) -> list[str]:
    from .controls.model import validate_profile

    return [
        f"{issue.field}: {issue.message}"
        for issue in validate_profile(profile)
        if issue.severity == "error"
    ]


def save_control_profile(
    package_key: str,
    profile: ControlProfileV2,
    *,
    overwrite: bool = True,
) -> Path:
    issues = profile_to_issues(profile)
    if issues:
        raise StorageError("Perfil invalido; nada foi gravado. " + "; ".join(issues))
    return atomic_write_json(
        control_profile_path(package_key),
        profile.to_dict(),
        overwrite=overwrite,
    )


def migrate_game_controls_to_v2(package_key: str, *, overwrite: bool = False) -> ControlProfileV2 | None:
    """Migra o perfil antigo deste jogo, mantendo copia e sem apagar o original."""
    legacy = load_game_controls(package_key)
    if not legacy:
        return None
    normalized, _warnings = normalize_legacy_slots(legacy)
    profile = legacy_payload_to_profile(
        normalized, game_package=package_key, screen_source="imported"
    )
    save_control_profile(package_key, profile, overwrite=overwrite)
    return profile


def demo_library() -> list[GameEntry]:
    """Jogos ficticios so para demonstrar a interface (nao sao reais)."""
    return [
        GameEntry("Jogo Demo 1", "com.exemplo.demo1", architecture="x86_64"),
        GameEntry("Jogo Demo 2", "com.exemplo.demo2", architecture="arm64"),
        GameEntry("Jogo Demo 3", "com.exemplo.demo3", architecture="multi"),
        GameEntry("Jogo Demo 4", "com.exemplo.demo4"),
        GameEntry("Jogo Demo 5", "com.exemplo.demo5", architecture="x86_64"),
    ]
