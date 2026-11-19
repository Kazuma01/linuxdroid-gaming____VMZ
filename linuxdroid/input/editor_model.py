"""Logica pura do editor avancado: undo/redo, duplicacao, conflitos e captura.

A GUI (PySide6) delega estas operacoes; nenhuma classe aqui depende de Qt.
O modelo manipulado continua sendo `ControlProfileV2`.
"""
from __future__ import annotations

import copy
from typing import Callable

from ..controls.keys import InputBinding, normalize_phantom_name
from ..controls.model import (
    POSITION_FIELDS,
    ControlProfileV2,
    ProfileNode,
    ScreenContract,
    ValidationIssue,
    validate_profile,
)
from .profile_bridge import LEGACY_PARAM_FIELDS, legacy_payload_to_profile, profile_to_legacy_payload

HISTORY_LIMIT = 100


def _clamped_position(value: tuple[float, float]) -> dict[str, float]:
    return {
        "x": min(1.0, max(0.0, float(value[0]))),
        "y": min(1.0, max(0.0, float(value[1]))),
    }


def binding_from_text(text: str, *, source: str = "editor_manual") -> InputBinding:
    """Texto vira binding com proveniencia explicita, nunca captura falsa."""
    canonical = normalize_phantom_name(text)
    if canonical:
        return InputBinding.from_canonical(canonical, capture_source=source)
    return InputBinding.from_legacy_text(text)


def editor_node_to_profile_node(
    raw: dict,
    profile: ControlProfileV2,
    *,
    node_id: str | None = None,
) -> ProfileNode:
    """Converte um no do canvas em ProfileNode, criando bindings locais."""
    data = copy.deepcopy(raw)
    used = set(profile.bindings)

    def new_binding(text: str) -> str:
        base = "".join(ch if ch.isalnum() or ch in "_-" else "_" for ch in text).strip("_") or "key"
        candidate = base
        counter = 1
        while candidate in used:
            counter += 1
            candidate = f"{base}_{counter}"
        used.add(candidate)
        profile.bindings[candidate] = binding_from_text(text)
        return candidate

    refs: dict[str, str] = {}
    nested_refs = data.get("binding_refs")
    if isinstance(nested_refs, dict):
        # Formato de ProfileNode.to_dict(): preserve a identidade original,
        # inclusive proveniencia/codigo/notes, mas crie refs exclusivas.
        for role, ref in nested_refs.items():
            original = profile.bindings.get(str(ref))
            if original is None:
                continue
            base = str(ref)
            candidate = base
            counter = 1
            while candidate in used:
                counter += 1
                candidate = f"{base}_{counter}"
            used.add(candidate)
            profile.bindings[candidate] = copy.deepcopy(original)
            refs[str(role)] = candidate
    else:
        simple_key = str(data.get("key", "") or "").strip()
        if simple_key and data.get("type") not in ("joystick", "wheel"):
            role = "activation_key" if data.get("type") in ("aim", "mouse_camera") else "key"
            refs[role] = new_binding(simple_key)
        activation = str(data.get("activation_key", "") or "").strip()
        if activation and "activation_key" not in refs:
            refs["activation_key"] = new_binding(activation)
        for role, text in (data.get("keys") or {}).items():
            if isinstance(text, str) and text.strip():
                refs[str(role)] = new_binding(text)

    geometry = {
        name: dict(value)
        for name, value in (data.get("geometry") or data).items()
        if name in POSITION_FIELDS and isinstance(value, dict)
    }
    parameters = {
        name: value for name, value in (data.get("parameters") or data).items()
        if name in LEGACY_PARAM_FIELDS
    }
    sequence = [dict(step) for step in (data.get("sequence") or []) if isinstance(step, dict)]
    for step in sequence:
        ref = step.get("binding_ref")
        original = profile.bindings.get(str(ref)) if ref else None
        if original is None:
            continue
        candidate = str(ref)
        counter = 1
        while candidate in used:
            counter += 1
            candidate = f"{ref}_{counter}"
        used.add(candidate)
        profile.bindings[candidate] = copy.deepcopy(original)
        step["binding_ref"] = candidate

    return ProfileNode(
        id=node_id or str(data.get("id", "") or ""),
        type=str(data.get("type", "tap") or "tap"),
        layer=str(data.get("layer", "") or ""),
        slot=data.get("slot"),
        up_slot=data.get("up_slot"),
        down_slot=data.get("down_slot"),
        binding_refs=refs,
        geometry=geometry,
        parameters=parameters,
        sequence=sequence,
    )


class BindingEditor:
    """Controller de edicao com historico e estado de captura local."""

    def __init__(self, source: ControlProfileV2 | dict, *, package_key: str = "") -> None:
        if isinstance(source, ControlProfileV2):
            self.profile = source
        else:
            self.profile = legacy_payload_to_profile(source, game_package=package_key)
        self._undo: list[str] = []
        self._redo: list[str] = []
        self.clipboard: dict | None = None
        self.dirty = False
        self.capture_target: tuple[str, str] | None = None

    # -- historico -----------------------------------------------------------

    def _snapshot(self) -> str:
        return self.profile.to_json()

    def _mutate(self, operation: Callable[[], object]) -> object:
        before = self._snapshot()
        result = operation()
        if self._snapshot() != before:
            self._undo.append(before)
            if len(self._undo) > HISTORY_LIMIT:
                self._undo.pop(0)
            self._redo.clear()
            self.dirty = True
        return result

    def undo(self) -> bool:
        if not self._undo:
            return False
        self._redo.append(self._snapshot())
        self.profile = ControlProfileV2.from_json(self._undo.pop())
        self.dirty = True
        return True

    def redo(self) -> bool:
        if not self._redo:
            return False
        self._undo.append(self._snapshot())
        self.profile = ControlProfileV2.from_json(self._redo.pop())
        self.dirty = True
        return True

    def mark_saved(self) -> None:
        self.dirty = False

    def restore_default(self, profile: ControlProfileV2) -> None:
        self._mutate(lambda: setattr(self, "profile", profile))

    # -- captura local -------------------------------------------------------

    def start_capture(self, node_id: str, role: str = "key") -> None:
        self.capture_target = (node_id, role)

    def cancel_capture(self) -> None:
        self.capture_target = None

    def finish_capture(self, binding: InputBinding) -> bool:
        if self.capture_target is None:
            return False
        node_id, role = self.capture_target
        self.set_binding(node_id, role, binding)
        self.capture_target = None
        return True

    # -- edicao --------------------------------------------------------------

    def set_binding(self, node_id: str, role: str, binding: InputBinding) -> None:
        def operation() -> None:
            node = self._node(node_id)
            ref = node.binding_refs.get(role)
            if ref and ref in self.profile.bindings:
                self.profile.bindings[ref] = binding
                return
            ref = f"{node_id}_{role}"
            counter = 1
            while ref in self.profile.bindings:
                counter += 1
                ref = f"{node_id}_{role}_{counter}"
            self.profile.bindings[ref] = binding
            node.binding_refs[role] = ref

        self._mutate(operation)

    def remove_binding(self, node_id: str, role: str) -> None:
        def operation() -> None:
            node = self._node(node_id)
            ref = node.binding_refs.pop(role, None)
            if ref:
                self.profile.bindings.pop(ref, None)

        self._mutate(operation)

    def add_node(self, raw: dict) -> str:
        result: dict = {}

        def operation() -> None:
            node_id = str(raw.get("id", "") or self._next_node_id())
            node = editor_node_to_profile_node(raw, self.profile, node_id=node_id)
            self.profile.nodes.append(node)
            result["id"] = node.id

        self._mutate(operation)
        return result.get("id", "")

    def duplicate_node(self, node_id: str) -> str:
        source = self._node(node_id)
        raw = source.to_dict()
        raw["id"] = self._next_node_id(excluding={node_id})
        for field in ("slot", "up_slot", "down_slot"):
            if raw.get(field) is not None:
                raw[field] = self.next_free_slot()
        for step in raw.get("sequence", []):
            if isinstance(step, dict) and "slot" in step:
                step["slot"] = self.next_free_slot()
        return self.add_node(raw)

    def copy_node(self, node_id: str) -> None:
        self.clipboard = copy.deepcopy(self._node(node_id).to_dict())

    def paste_node(self, *, dx: float = 0.02, dy: float = 0.02) -> str:
        if self.clipboard is None:
            return ""
        raw = copy.deepcopy(self.clipboard)
        raw["id"] = self._next_node_id()
        for name, position in list(raw.get("geometry", {}).items()):
            raw["geometry"][name] = {
                "x": min(1.0, float(position.get("x", 0.5)) + dx),
                "y": min(1.0, float(position.get("y", 0.5)) + dy),
            }
        for field in ("slot", "up_slot", "down_slot"):
            if raw.get(field) is not None:
                raw[field] = self.next_free_slot()
        return self.add_node(raw)

    def remove_node(self, node_id: str) -> None:
        def operation() -> None:
            self.profile.nodes = [node for node in self.profile.nodes if node.id != node_id]
            refs = {
                ref
                for node in self.profile.nodes
                for ref in node.binding_refs.values()
            }
            for ref in list(self.profile.bindings):
                if ref not in refs:
                    self.profile.bindings.pop(ref, None)

        self._mutate(operation)

    def move_node(self, node_id: str, geometry_name: str, x: float, y: float) -> None:
        self.update_node_geometry(node_id, {geometry_name: (x, y)})

    def update_node_geometry(
        self,
        node_id: str,
        positions: dict[str, tuple[float, float]],
        *,
        sequence_positions: dict[int, tuple[float, float]] | None = None,
    ) -> None:
        """Aplica varias posicoes em um unico passo de historico."""
        def operation() -> None:
            node = self._node(node_id)
            for name, value in positions.items():
                if name not in POSITION_FIELDS:
                    continue
                node.geometry[name] = _clamped_position(value)
            for index, value in (sequence_positions or {}).items():
                if 0 <= index < len(node.sequence):
                    step = node.sequence[index]
                    if isinstance(step, dict):
                        step["pos"] = _clamped_position(value)

        self._mutate(operation)

    def update_node_properties(
        self,
        node_id: str,
        *,
        parameters: dict | None = None,
        layer: str | None = None,
    ) -> None:
        """Atualiza parametros/camada preservando o resto do no."""
        def operation() -> None:
            node = self._node(node_id)
            if parameters:
                for name, value in parameters.items():
                    if name in LEGACY_PARAM_FIELDS:
                        node.parameters[name] = value
            if layer is not None:
                node.layer = str(layer).strip()

        self._mutate(operation)

    def next_free_slot(self, *, excluding: set[int] | None = None) -> int:
        used = {
            slot
            for node in self.profile.nodes
            for slot in (node.slot, node.up_slot, node.down_slot)
            if slot is not None
        }
        used.update(excluding or set())
        return next(slot for slot in range(255) if slot not in used)

    def set_screen(self, width: int, height: int) -> None:
        def operation() -> None:
            self.profile.screen_contract = ScreenContract(
                int(width), int(height), "user"
            )

        self._mutate(operation)

    def set_sensitivity(self, value: float) -> None:
        self._mutate(lambda: setattr(self.profile.cursor_model, "sensitivity", float(value)))

    def set_name(self, name: str) -> None:
        self._mutate(lambda: setattr(self.profile, "name", str(name)))

    # -- consulta ------------------------------------------------------------

    def conflicts(self) -> list[ValidationIssue]:
        return validate_profile(self.profile)

    def conflict_messages(self) -> list[str]:
        return [issue.message for issue in self.conflicts() if issue.severity in ("error", "warning")]

    def to_payload(self) -> dict:
        return profile_to_legacy_payload(self.profile)

    def _node(self, node_id: str) -> ProfileNode:
        for node in self.profile.nodes:
            if node.id == node_id:
                return node
        raise KeyError(f"No desconhecido: {node_id!r}")

    def _next_node_id(self, *, excluding: set[str] | None = None) -> str:
        used = {node.id for node in self.profile.nodes}
        used.update(excluding or set())
        counter = 1
        while f"control_{counter}" in used:
            counter += 1
        return f"control_{counter}"


__all__ = ["BindingEditor", "binding_from_text", "editor_node_to_profile_node"]
