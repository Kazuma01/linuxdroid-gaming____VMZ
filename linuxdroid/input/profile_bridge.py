"""Ponte entre o payload legacy do editor e ControlProfileV2.

Nao cria segundo modelo: `ControlProfileV2` continua sendo o unico modelo
versionado. Esta camada apenas converte o dicionario que o editor ja usa para
desenhar o canvas, preservando compatibilidade com perfis antigos.
"""
from __future__ import annotations

import math
from typing import Iterable

from ..controls.keys import normalize_phantom_name
from ..controls.model import (
    LEGACY_VERSION,
    POSITION_FIELDS,
    SCHEMA_VERSION,
    ControlProfileV2,
    ProfileError,
    ProfileNode,
    migrate_legacy_profile,
)

LEGACY_PARAM_FIELDS = (
    "radius", "reach", "sensitivity", "curve", "activation_mode",
    "invert_y", "duration_ms", "interval_ms", "mode", "layer_name", "suspend_base",
)


def legacy_payload_to_profile(
    payload: dict,
    *,
    game_package: str = "",
    screen_source: str = "user",
) -> ControlProfileV2:
    """Converte version=1 para V2 usando a migracao auditada da Fatia 2."""
    if not isinstance(payload, dict):
        raise ProfileError("Payload do editor precisa ser um objeto.")
    if payload.get("schema_version") == SCHEMA_VERSION:
        return ControlProfileV2.from_dict(payload)
    if payload.get("version") != LEGACY_VERSION:
        raise ProfileError("Payload do editor nao e um perfil version=1.")
    return migrate_legacy_profile(payload, game_package=game_package, screen_source=screen_source)


def profile_to_legacy_payload(profile: ControlProfileV2) -> dict:
    """Reonstrói o formato que o canvas do editor ja entende."""
    screen = profile.screen_contract
    nodes: list[dict] = []
    for node in profile.nodes:
        converted: dict = {
            "id": node.id,
            "type": node.type,
        }
        if node.layer:
            converted["layer"] = node.layer
        if node.slot is not None:
            converted["slot"] = node.slot
        if node.up_slot is not None:
            converted["up_slot"] = node.up_slot
        if node.down_slot is not None:
            converted["down_slot"] = node.down_slot
        for name, position in node.geometry.items():
            if name in POSITION_FIELDS:
                converted[name] = dict(position)
        for name, value in node.parameters.items():
            if name in LEGACY_PARAM_FIELDS:
                converted[name] = value
        if node.sequence:
            converted["sequence"] = [dict(step) for step in node.sequence]
        keys: dict[str, str] = {}
        for role, ref in node.binding_refs.items():
            binding = profile.bindings.get(ref)
            if binding is None:
                continue
            keys[role] = binding.canonical_name or binding.label
            if role == "key" and node.type not in ("joystick", "wheel"):
                converted["key"] = keys[role]
            if role == "activation_key":
                converted["activation_key"] = keys[role]
        if keys and (node.type == "joystick" or len(keys) > 1):
            converted["keys"] = keys
        nodes.append(converted)
    return {
        "name": profile.name,
        "version": LEGACY_VERSION,
        "screen": {
            "width": screen.width,
            "height": screen.height,
        },
        "global_sensitivity": profile.cursor_model.sensitivity,
        "nodes": nodes,
    }


def normalize_legacy_slots(payload: dict) -> tuple[dict, list[str]]:
    """Corrige slot 255 e duplicatas sem apagar dados do perfil antigo."""
    if not isinstance(payload, dict):
        raise ProfileError("Payload invalido.")
    result = dict(payload)
    nodes = [dict(node) for node in (payload.get("nodes") or []) if isinstance(node, dict)]
    used: set[int] = set()
    warnings: list[str] = []
    for node in nodes:
        for field in ("slot", "up_slot", "down_slot"):
            value = node.get(field)
            if value is None:
                continue
            try:
                slot = int(value)
            except (TypeError, ValueError):
                slot = -1
            if slot == 255 or slot < 0 or slot in used:
                replacement = next((candidate for candidate in range(254) if candidate not in used), None)
                if replacement is None:
                    raise ProfileError("Nao ha slots livres para corrigir o perfil.")
                warnings.append(f"{node.get('id', '?')}.{field}: slot {value} substituido por {replacement}.")
                node[field] = replacement
                slot = replacement
            used.add(slot)
    result["nodes"] = nodes
    return result, warnings


def validate_editor_payload(payload: dict) -> list[str]:
    """Validacao local independente de Qt, usada antes de salvar/importar."""
    errors: list[str] = []
    if not isinstance(payload, dict) or payload.get("version") != LEGACY_VERSION:
        return ["Perfil precisa ser version=1."]
    screen = payload.get("screen")
    if not isinstance(screen, dict):
        errors.append("Perfil sem contrato de tela.")
    else:
        try:
            width, height = int(screen["width"]), int(screen["height"])
            if not (320 <= width <= 7680 and 320 <= height <= 4320):
                errors.append("Resolucao fora do intervalo permitido.")
        except (KeyError, TypeError, ValueError):
            errors.append("Resolucao invalida.")
    nodes = payload.get("nodes")
    if not isinstance(nodes, list):
        return errors + ["Perfil sem lista de nos."]
    ids: set[str] = set()
    slots: set[int] = set()
    for index, node in enumerate(nodes):
        if not isinstance(node, dict):
            errors.append(f"no[{index}] invalido.")
            continue
        node_id = str(node.get("id", "") or "")
        if not node_id or node_id in ids:
            errors.append(f"Identificador invalido ou duplicado: {node_id!r}.")
        ids.add(node_id)
        for field in ("slot", "up_slot", "down_slot"):
            if field not in node:
                continue
            try:
                slot = int(node[field])
            except (TypeError, ValueError):
                errors.append(f"{node_id}.{field}: slot nao numerico.")
                continue
            if slot == 255 or not 0 <= slot < 255:
                errors.append(f"{node_id}.{field}: slot 255 e reservado.")
            elif slot in slots:
                errors.append(f"{node_id}.{field}: slot {slot} duplicado.")
            else:
                slots.add(slot)
        for position in _positions(node):
            try:
                x, y = float(position.get("x")), float(position.get("y"))
            except (TypeError, ValueError, AttributeError):
                errors.append(f"{node_id}: coordenada invalida.")
                continue
            if not (math.isfinite(x) and math.isfinite(y) and 0 <= x <= 1 and 0 <= y <= 1):
                errors.append(f"{node_id}: coordenada fora de [0, 1].")
    return errors


def _positions(node: dict) -> Iterable[dict]:
    for name in POSITION_FIELDS:
        value = node.get(name)
        if isinstance(value, dict):
            yield value
    for step in node.get("sequence", []):
        if isinstance(step, dict) and isinstance(step.get("pos"), dict):
            yield step["pos"]


def canonical_name_for_binding(binding_name: str) -> str:
    return normalize_phantom_name(binding_name) or ""


__all__ = [
    "LEGACY_PARAM_FIELDS",
    "legacy_payload_to_profile",
    "profile_to_legacy_payload",
    "normalize_legacy_slots",
    "validate_editor_payload",
    "canonical_name_for_binding",
]
