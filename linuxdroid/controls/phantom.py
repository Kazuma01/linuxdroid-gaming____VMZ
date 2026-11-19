"""Conversao segura do modelo versionado para o schema Phantom v1.

Esta camada NAO altera o Phantom. Ela apenas produz um dicionario que segue o
schema auditado no commit 1a6b7edb423462c1bc546031ed86d9bf2cc1cffd.

Nada e exportado silenciosamente:

  * erros de validacao bloqueiam a exportacao;
  * tela desconhecida bloqueia a exportacao;
  * binding nao verificado exige `allow_unverified=True` e gera aviso explicito.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field

from .keys import normalize_phantom_name
from .model import (
    ControlProfileV2,
    ProfileError,
    ValidationIssue,
    has_errors,
    validate_profile,
)

PHANTOM_SCHEMA_VERSION = 1


@dataclass
class PhantomConversionResult:
    profile: dict
    warnings: list[str] = field(default_factory=list)

    def to_json(self) -> str:
        return json.dumps(self.profile, ensure_ascii=False, indent=2, sort_keys=True)


def export_phantom_profile(
    profile: ControlProfileV2,
    *,
    allow_unverified: bool = False,
) -> PhantomConversionResult:
    """Converte o perfil interno para o formato Phantom version=1."""
    issues = validate_profile(profile)
    if has_errors(issues):
        details = "; ".join(f"{issue.field}: {issue.message}" for issue in issues if issue.severity == "error")
        raise ProfileError("Perfil invalido; exportacao Phantom bloqueada. " + details)

    if not profile.screen_contract.known:
        raise ProfileError("Resolucao desconhecida; meça/informe a tela antes de exportar.")

    warnings = [
        issue.message for issue in issues
        if issue.severity == "warning" and not issue.field.startswith("bindings.")
    ]

    def binding_name(ref: str, node_id: str, role: str) -> str:
        if not ref:
            raise ProfileError(f"nodes.{node_id}.binding_refs.{role}: referencia vazia.")
        binding = profile.bindings.get(ref)
        if binding is None:
            raise ProfileError(f"nodes.{node_id}.binding_refs.{role}: binding inexistente {ref!r}.")
        name = normalize_phantom_name(binding.canonical_name)
        if name is None:
            raise ProfileError(
                f"nodes.{node_id}.binding_refs.{role}: {binding.canonical_name!r} nao e aceito pelo Phantom."
            )
        if binding.validation == "invalid":
            raise ProfileError(f"nodes.{node_id}.binding_refs.{role}: binding marcado como invalido.")
        if binding.validation == "unsupported":
            raise ProfileError(f"nodes.{node_id}.binding_refs.{role}: entrada nao suportada pelo backend.")
        if binding.validation == "unverified":
            if not allow_unverified:
                raise ProfileError(
                    f"nodes.{node_id}.binding_refs.{role}: binding nao verificado "
                    f"({binding.label!r}); use allow_unverified=True para exportar ciente disso."
                )
            warnings.append(
                f"Binding nao verificado exportado em {node_id}.{role}: {binding.label!r}."
            )
        return name

    nodes: list[dict] = []
    for node in profile.nodes:
        node_id = node.id
        layer = node.layer.strip()
        params = node.parameters
        geometry = node.geometry

        if node.type in ("tap", "hold_tap", "toggle_tap", "repeat_tap"):
            converted = {
                "type": "tap" if node.type == "hold_tap" else node.type,
                "id": node_id,
                "layer": layer,
                "slot": _slot(node.slot, node_id, "slot"),
                "pos": _pos(geometry, "pos", node_id),
                "key": binding_name(node.binding_refs.get("key", ""), node_id, "key"),
            }
            if node.type == "repeat_tap":
                converted["interval_ms"] = _positive_int(params.get("interval_ms"), node_id, "interval_ms")
            nodes.append(converted)

        elif node.type == "joystick":
            nodes.append({
                "type": "joystick",
                "id": node_id,
                "layer": layer,
                "slot": _slot(node.slot, node_id, "slot"),
                "pos": _pos(geometry, "pos", node_id),
                "radius": _number(params.get("radius"), node_id, "radius"),
                "keys": {
                    role: binding_name(node.binding_refs.get(role, ""), node_id, role)
                    for role in ("up", "down", "left", "right")
                },
            })

        elif node.type == "drag":
            nodes.append({
                "type": "drag",
                "id": node_id,
                "layer": layer,
                "slot": _slot(node.slot, node_id, "slot"),
                "start": _pos(geometry, "start", node_id),
                "end": _pos(geometry, "end", node_id),
                "key": binding_name(node.binding_refs.get("key", ""), node_id, "key"),
                "duration_ms": _positive_int(params.get("duration_ms"), node_id, "duration_ms"),
            })

        elif node.type in ("aim", "mouse_camera"):
            mode = str(params.get("activation_mode", "always_on"))
            activation_ref = node.binding_refs.get("activation_key", "")
            converted = {
                "type": "aim",
                "id": node_id,
                "layer": layer,
                "slot": _slot(node.slot, node_id, "slot"),
                "anchor": _pos(geometry, "anchor", node_id),
                "reach": _number(params.get("reach"), node_id, "reach"),
                "sensitivity": _number(params.get("sensitivity"), node_id, "sensitivity"),
                "curve": str(params.get("curve", "balanced")),
                "activation_mode": mode,
                "invert_y": bool(params.get("invert_y", False)),
            }
            if mode != "always_on":
                converted["activation_key"] = binding_name(activation_ref, node_id, "activation_key")
            nodes.append(converted)

        elif node.type == "wheel":
            nodes.append({
                "type": "wheel",
                "id": node_id,
                "layer": layer,
                "up_slot": _slot(node.up_slot, node_id, "up_slot"),
                "up_pos": _pos(geometry, "up_pos", node_id),
                "down_slot": _slot(node.down_slot, node_id, "down_slot"),
                "down_pos": _pos(geometry, "down_pos", node_id),
            })

        elif node.type == "macro":
            sequence = []
            for index, step in enumerate(node.sequence):
                item = {
                    "action": str(step.get("action", "")).lower(),
                    "slot": _slot(step.get("slot"), f"{node_id}.sequence[{index}]", "slot"),
                    "delay_ms": int(step.get("delay_ms", 0)),
                }
                if "pos" in step:
                    item["pos"] = {
                        "x": float(step["pos"].get("x")),
                        "y": float(step["pos"].get("y")),
                    }
                sequence.append(item)
            nodes.append({
                "type": "macro",
                "id": node_id,
                "layer": layer,
                "key": binding_name(node.binding_refs.get("key", ""), node_id, "key"),
                "mode": str(params.get("mode", "cancel_on_release")),
                "sequence": sequence,
            })

        elif node.type == "layer_shift":
            nodes.append({
                "type": "layer_shift",
                "id": node_id,
                "key": binding_name(node.binding_refs.get("key", ""), node_id, "key"),
                "layer_name": str(params.get("layer_name", "")).strip(),
                "mode": str(params.get("mode", "hold")),
                "suspend_base": bool(params.get("suspend_base", False)),
            })

        else:
            raise ProfileError(f"nodes.{node_id}.type: tipo nao conversivel {node.type!r}.")

    result = {
        "name": profile.name,
        "version": PHANTOM_SCHEMA_VERSION,
        "screen": {
            "width": profile.screen_contract.width,
            "height": profile.screen_contract.height,
        },
        "global_sensitivity": float(profile.cursor_model.sensitivity),
        "nodes": nodes,
    }
    return PhantomConversionResult(profile=result, warnings=warnings)


def _slot(value, field_path: str, field_name: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or not 0 <= value <= 254:
        raise ProfileError(f"{field_path}.{field_name}: slot precisa estar em 0..254.")
    return value


def _pos(geometry: dict, name: str, node_id: str) -> dict:
    pos = geometry.get(name)
    if not isinstance(pos, dict):
        raise ProfileError(f"nodes.{node_id}.geometry.{name}: posicao ausente.")
    return {"x": float(pos.get("x")), "y": float(pos.get("y"))}


def _positive_int(value, node_id: str, field_name: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise ProfileError(f"nodes.{node_id}.{field_name}: inteiro positivo obrigatorio.")
    return value


def _number(value, node_id: str, field_name: str) -> float:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise ProfileError(f"nodes.{node_id}.{field_name}: numero obrigatorio.")
    return float(value)
