"""Modelo interno de perfil versionado, migracao e validacao.

Regras de compatibilidade seguidas aqui:

  * o formato antigo (version 1 do Phantom) continua intacto e legivel;
  * perfis antigos sao migrados sem inventar codigo fisico;
  * resolucao desconhecida permanece desconhecida;
  * repeated bindings entre camadas exclusivas sao permitidos;
  * a regra base/non-base do Phantom e aplicada exatamente como no codigo
    `Profile::validate()` do commit 1a6b7edb423462c1bc546031ed86d9bf2cc1cffd.
"""
from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from typing import Iterable

from .keys import (
    CODE_SPACES,
    EVDEV_CANONICAL_BY_CODE,
    MODIFIER_CANONICAL,
    PHANTOM_CANONICAL_NAMES,
    PROVENANCE_STATES,
    InputBinding,
    kind_for_canonical,
    namespace_for_canonical,
    normalize_phantom_name,
)

SCHEMA_VERSION = 2
LEGACY_VERSION = 1
RESERVED_SLOT = 255  # Phantom: RUNTIME_MOUSE_TOUCH_SLOT = u8::MAX

NODE_TYPES = frozenset({
    "tap", "hold_tap", "toggle_tap", "joystick", "drag", "aim",
    "mouse_camera", "repeat_tap", "wheel", "macro", "layer_shift",
})
BACKEND_PREFERENCES = frozenset({"auto", "phantom", "native"})
TOUCH_BACKENDS = frozenset({"unknown", "android_socket", "uinput"})
CURSOR_MODES = frozenset({"relative_virtual", "absolute_virtual"})
ACTIVATION_MODES = frozenset({"always_on", "while_held", "toggle"})
MACRO_MODES = frozenset({"cancel_on_release", "one_shot"})
LAYER_MODES = frozenset({"hold", "toggle"})
CURVE_PRESETS = frozenset({"linear", "precision", "balanced"})
POSITION_FIELDS = ("pos", "anchor", "start", "end", "up_pos", "down_pos")
TEXT_KEY_FIELDS = ("key", "activation_key", "up", "down", "left", "right")


class ProfileError(ValueError):
    """Perfil invalido ou incompativel com a conversao pedida."""


@dataclass
class ValidationIssue:
    severity: str  # error | warning
    field: str
    message: str

    def to_dict(self) -> dict:
        return {"severity": self.severity, "field": self.field, "message": self.message}


@dataclass
class ScreenContract:
    width: int | None = None
    height: int | None = None
    source: str = "unknown"  # unknown | measured | user | imported | daemon

    @property
    def known(self) -> bool:
        return (
            isinstance(self.width, int) and isinstance(self.height, int)
            and self.width > 0 and self.height > 0
        )

    def to_dict(self) -> dict:
        return {"width": self.width, "height": self.height, "source": self.source}

    @classmethod
    def from_dict(cls, raw: dict | None) -> "ScreenContract":
        raw = raw if isinstance(raw, dict) else {}
        return cls(
            width=_optional_int(raw.get("width")),
            height=_optional_int(raw.get("height")),
            source=str(raw.get("source", "unknown") or "unknown"),
        )


@dataclass
class BackendPreferences:
    preferred: str = "auto"       # auto | phantom | native
    touch_backend: str = "unknown"  # android_socket | uinput | unknown
    notes: str = ""

    def to_dict(self) -> dict:
        return {
            "preferred": self.preferred,
            "touch_backend": self.touch_backend,
            "notes": self.notes,
        }

    @classmethod
    def from_dict(cls, raw: dict | None) -> "BackendPreferences":
        raw = raw if isinstance(raw, dict) else {}
        return cls(
            preferred=str(raw.get("preferred", "auto") or "auto"),
            touch_backend=str(raw.get("touch_backend", "unknown") or "unknown"),
            notes=str(raw.get("notes", "") or ""),
        )


@dataclass
class CursorModelConfig:
    """Configuracao do cursor virtual. Posicao viva fica em controls.cursor."""

    mode: str = "relative_virtual"
    initial_x: float = 0.5
    initial_y: float = 0.5
    sensitivity: float = 1.0
    acceleration: bool = False
    clamp_to_screen: bool = True
    capture_state: str = "released"     # released | captured
    aim_state: str = "off"              # off | active
    menu_touch_state: str = "off"       # off | active

    def to_dict(self) -> dict:
        return {
            "mode": self.mode,
            "initial_x": self.initial_x,
            "initial_y": self.initial_y,
            "sensitivity": self.sensitivity,
            "acceleration": self.acceleration,
            "clamp_to_screen": self.clamp_to_screen,
            "capture_state": self.capture_state,
            "aim_state": self.aim_state,
            "menu_touch_state": self.menu_touch_state,
        }

    @classmethod
    def from_dict(cls, raw: dict | None) -> "CursorModelConfig":
        raw = raw if isinstance(raw, dict) else {}
        return cls(
            mode=str(raw.get("mode", "relative_virtual") or "relative_virtual"),
            initial_x=_optional_float(raw.get("initial_x"), 0.5),
            initial_y=_optional_float(raw.get("initial_y"), 0.5),
            sensitivity=_optional_float(raw.get("sensitivity"), 1.0),
            acceleration=bool(raw.get("acceleration", False)),
            clamp_to_screen=bool(raw.get("clamp_to_screen", True)),
            capture_state=str(raw.get("capture_state", "released") or "released"),
            aim_state=str(raw.get("aim_state", "off") or "off"),
            menu_touch_state=str(raw.get("menu_touch_state", "off") or "off"),
        )


@dataclass
class Layer:
    id: str
    name: str = ""
    exclusive: bool = False  # default de suspend_base para shifts desta camada

    def to_dict(self) -> dict:
        return {"id": self.id, "name": self.name, "exclusive": self.exclusive}

    @classmethod
    def from_dict(cls, raw: dict) -> "Layer":
        raw = raw if isinstance(raw, dict) else {}
        return cls(
            id=str(raw.get("id", "") or ""),
            name=str(raw.get("name", "") or ""),
            exclusive=bool(raw.get("exclusive", False)),
        )


@dataclass
class ProfileNode:
    id: str
    type: str
    layer: str = ""
    slot: int | None = None
    up_slot: int | None = None
    down_slot: int | None = None
    binding_refs: dict[str, str] = field(default_factory=dict)
    geometry: dict[str, dict] = field(default_factory=dict)
    parameters: dict = field(default_factory=dict)
    sequence: list[dict] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "type": self.type,
            "layer": self.layer,
            "slot": self.slot,
            "up_slot": self.up_slot,
            "down_slot": self.down_slot,
            "binding_refs": dict(self.binding_refs),
            "geometry": {k: dict(v) for k, v in self.geometry.items()},
            "parameters": dict(self.parameters),
            "sequence": [dict(step) for step in self.sequence],
        }

    @classmethod
    def from_dict(cls, raw: dict) -> "ProfileNode":
        raw = raw if isinstance(raw, dict) else {}
        geometry = {
            key: dict(value)
            for key, value in (raw.get("geometry") or {}).items()
            if isinstance(value, dict)
        }
        return cls(
            id=str(raw.get("id", "") or ""),
            type=str(raw.get("type", "") or ""),
            layer=str(raw.get("layer", "") or ""),
            slot=_optional_int(raw.get("slot")),
            up_slot=_optional_int(raw.get("up_slot")),
            down_slot=_optional_int(raw.get("down_slot")),
            binding_refs={str(k): str(v) for k, v in (raw.get("binding_refs") or {}).items()},
            geometry=geometry,
            parameters=dict(raw.get("parameters") or {}),
            sequence=[dict(step) for step in (raw.get("sequence") or []) if isinstance(step, dict)],
        )


@dataclass
class ControlProfileV2:
    schema_version: int = SCHEMA_VERSION
    name: str = ""
    game_package: str = ""
    screen_contract: ScreenContract = field(default_factory=ScreenContract)
    backend_preferences: BackendPreferences = field(default_factory=BackendPreferences)
    cursor_model: CursorModelConfig = field(default_factory=CursorModelConfig)
    layers: list[Layer] = field(default_factory=list)
    nodes: list[ProfileNode] = field(default_factory=list)
    bindings: dict[str, InputBinding] = field(default_factory=dict)
    metadata: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "schema_version": self.schema_version,
            "name": self.name,
            "game_package": self.game_package,
            "screen_contract": self.screen_contract.to_dict(),
            "backend_preferences": self.backend_preferences.to_dict(),
            "cursor_model": self.cursor_model.to_dict(),
            "layers": [layer.to_dict() for layer in self.layers],
            "nodes": [node.to_dict() for node in self.nodes],
            "bindings": {key: value.to_dict() for key, value in self.bindings.items()},
            "metadata": dict(self.metadata),
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=2, sort_keys=True)

    @classmethod
    def from_dict(cls, raw: dict) -> "ControlProfileV2":
        if not isinstance(raw, dict):
            raise ProfileError("Perfil precisa ser um objeto JSON.")
        version = raw.get("schema_version")
        if version == LEGACY_VERSION or "version" in raw and "schema_version" not in raw:
            raise ProfileError(
                "Formato antigo detectado. Use migrate_legacy_profile() para converter."
            )
        if version != SCHEMA_VERSION:
            raise ProfileError(
                f"schema_version {version!r} nao suportado; esperado {SCHEMA_VERSION}."
            )
        try:
            return cls(
                schema_version=SCHEMA_VERSION,
                name=str(raw.get("name", "") or ""),
                game_package=str(raw.get("game_package", "") or ""),
                screen_contract=ScreenContract.from_dict(raw.get("screen_contract")),
                backend_preferences=BackendPreferences.from_dict(raw.get("backend_preferences")),
                cursor_model=CursorModelConfig.from_dict(raw.get("cursor_model")),
                layers=[Layer.from_dict(item) for item in (raw.get("layers") or [])],
                nodes=[ProfileNode.from_dict(item) for item in (raw.get("nodes") or [])],
                bindings={
                    str(key): InputBinding.from_dict(value)
                    for key, value in (raw.get("bindings") or {}).items()
                },
                metadata=dict(raw.get("metadata") or {}),
            )
        except (TypeError, ValueError) as error:
            raise ProfileError(f"Perfil malformado: {error}") from error

    @classmethod
    def from_json(cls, text: str) -> "ControlProfileV2":
        try:
            raw = json.loads(text)
        except (json.JSONDecodeError, TypeError) as error:
            raise ProfileError(f"JSON invalido: {error}") from error
        return cls.from_dict(raw)


# ---------------------------------------------------------------------------
# Validacao
# ---------------------------------------------------------------------------


def validate_profile(profile: ControlProfileV2) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []

    def add(severity: str, field_name: str, message: str) -> None:
        issues.append(ValidationIssue(severity, field_name, message))

    if profile.schema_version != SCHEMA_VERSION:
        add("error", "schema_version", f"Versao {profile.schema_version} nao suportada.")

    if not profile.screen_contract.known:
        add("warning", "screen_contract", "Resolucao desconhecida; nao exportar sem medicao.")
    if profile.backend_preferences.preferred not in BACKEND_PREFERENCES:
        add("error", "backend_preferences.preferred",
            f"Preferencia de backend desconhecida: {profile.backend_preferences.preferred!r}")
    if profile.backend_preferences.touch_backend not in TOUCH_BACKENDS:
        add("error", "backend_preferences.touch_backend",
            f"Backend de toque desconhecido: {profile.backend_preferences.touch_backend!r}")
    if profile.cursor_model.mode not in CURSOR_MODES:
        add("error", "cursor_model.mode", f"Modo de cursor desconhecido: {profile.cursor_model.mode!r}")
    if profile.cursor_model.sensitivity <= 0:
        add("error", "cursor_model.sensitivity", "Sensibilidade do cursor precisa ser positiva.")
    if not (0 <= profile.cursor_model.initial_x <= 1 and 0 <= profile.cursor_model.initial_y <= 1):
        add("error", "cursor_model.initial", "Posicao inicial do cursor fora de [0, 1].")

    for name, binding in sorted(profile.bindings.items()):
        field_name = f"bindings.{name}"
        if binding.validation == "unverified":
            add("warning", field_name, "Binding herdado sem codigo fisico verificado.")
        elif binding.validation == "invalid":
            add("error", field_name, "Binding marcado como invalido.")
        elif binding.validation not in ("verified", "unsupported"):
            add("error", field_name, f"Estado de validacao desconhecido: {binding.validation}")

        if binding.provenance not in PROVENANCE_STATES:
            add("error", field_name + ".provenance",
                f"Proveniencia desconhecida: {binding.provenance!r}")
        elif binding.provenance == "unverified" and binding.validation == "verified":
            add("warning", field_name + ".provenance",
                "Binding marcado como verificado sem evidencia de captura ou backend.")

        if binding.canonical_name:
            canonical = normalize_phantom_name(binding.canonical_name)
            if canonical is None:
                add("error", field_name + ".canonical_name",
                    f"Nome nao aceito pelo Phantom: {binding.canonical_name!r}")
            elif canonical != binding.canonical_name:
                add("error", field_name + ".canonical_name",
                    f"Nome nao canonico: {binding.canonical_name!r}; use {canonical!r}")
        elif binding.validation == "verified":
            add("error", field_name + ".canonical_name", "Binding verificado sem nome canonico.")
        elif not binding.label:
            add("error", field_name + ".label", "Binding sem nome e sem rotulo.")

        if binding.code is not None:
            if not isinstance(binding.code, int) or isinstance(binding.code, bool) or binding.code < 0:
                add("error", field_name + ".code", "Codigo numerico invalido.")
            if binding.code_space not in CODE_SPACES or binding.code_space == "unknown":
                add("error", field_name + ".code_space", "Codigo fornecido sem espaco conhecido.")
            expected = EVDEV_CANONICAL_BY_CODE.get(binding.code)
            if binding.code_space == "evdev" and expected and binding.canonical_name:
                if expected != binding.canonical_name:
                    add("error", field_name + ".code",
                        f"Codigo evdev {binding.code} corresponde a {expected}, nao {binding.canonical_name}.")

        for modifier in binding.modifiers:
            canonical_mod = normalize_phantom_name(modifier)
            if canonical_mod not in MODIFIER_CANONICAL:
                add("error", field_name + ".modifiers", f"Modificador desconhecido: {modifier!r}")

        if binding.canonical_name:
            expected_namespace = namespace_for_canonical(normalize_phantom_name(binding.canonical_name))
            expected_kind = kind_for_canonical(normalize_phantom_name(binding.canonical_name))
            if binding.namespace != expected_namespace:
                add("error", field_name + ".namespace",
                    f"Namespace {binding.namespace!r} incompativel com {binding.canonical_name!r}.")
            if binding.event_type != expected_kind:
                add("error", field_name + ".event_type",
                    f"Tipo {binding.event_type!r} incompativel com {binding.canonical_name!r}.")

    node_ids: set[str] = set()
    slots: dict[int, str] = {}
    layer_ids: set[str] = set()
    for layer in profile.layers:
        if not layer.id:
            add("error", "layers.id", "Camada sem identificador.")
        if layer.id in layer_ids:
            add("error", "layers.id", f"Camada duplicada: {layer.id!r}")
        layer_ids.add(layer.id)
        if any(ch.isspace() for ch in layer.name):
            add("error", "layers.name", "Nome de camada nao pode conter espacos.")

    for node in profile.nodes:
        base = f"nodes.{node.id}"
        if not node.id:
            add("error", "nodes.id", "No sem identificador.")
        if node.id in node_ids:
            add("error", base + ".id", f"Identificador duplicado: {node.id!r}")
        node_ids.add(node.id)

        if node.type not in NODE_TYPES:
            add("error", base + ".type", f"Tipo desconhecido: {node.type!r}")
        if any(ch.isspace() for ch in node.layer):
            add("error", base + ".layer", "Nome de camada nao pode conter espacos.")

        for field_name, slot in (
            ("slot", node.slot), ("up_slot", node.up_slot), ("down_slot", node.down_slot)
        ):
            if slot is None:
                continue
            if not isinstance(slot, int) or isinstance(slot, bool) or not 0 <= slot <= 255:
                add("error", f"{base}.{field_name}", "Slot fora de 0..255.")
            elif slot == RESERVED_SLOT:
                add("error", f"{base}.{field_name}", "Slot 255 reservado pelo Phantom para mouse-touch.")
            elif slot in slots:
                add("error", f"{base}.{field_name}",
                    f"Slot {slot} ja usado por {slots[slot]}.")
            else:
                slots[slot] = node.id

        if node.up_slot is not None and node.down_slot is not None and node.up_slot == node.down_slot:
            add("error", base, "up_slot e down_slot devem ser diferentes.")

        if node.type in ("tap", "hold_tap", "toggle_tap", "joystick", "drag", "aim", "mouse_camera", "repeat_tap"):
            if node.slot is None:
                add("error", base + ".slot", f"Tipo {node.type!r} exige slot.")
        if node.type == "wheel":
            if node.up_slot is None or node.down_slot is None:
                add("error", base + ".slots", "Tipo 'wheel' exige up_slot e down_slot.")

        required_roles = {
            "tap": ("key",), "hold_tap": ("key",), "toggle_tap": ("key",),
            "repeat_tap": ("key",), "drag": ("key",),
            "joystick": ("up", "down", "left", "right"),
            "macro": ("key",), "layer_shift": ("key",),
        }.get(node.type, ())
        for role in required_roles:
            if not node.binding_refs.get(role):
                add("error", f"{base}.binding_refs.{role}", f"Papel obrigatorio ausente: {role}.")

        for geometry_name, pos in node.geometry.items():
            _validate_position(add, f"{base}.geometry.{geometry_name}", pos)
        if node.type in ("tap", "hold_tap", "toggle_tap", "repeat_tap", "drag", "joystick", "aim", "mouse_camera", "wheel"):
            required = {
                "tap": ("pos",), "hold_tap": ("pos",), "toggle_tap": ("pos",), "repeat_tap": ("pos",),
                "drag": ("start", "end"), "joystick": ("pos",),
                "aim": ("anchor",), "mouse_camera": ("anchor",),
                "wheel": ("up_pos", "down_pos"),
            }[node.type]
            for name in required:
                if name not in node.geometry:
                    add("error", f"{base}.geometry.{name}", f"Geometria obrigatoria ausente: {name}.")

        params = node.parameters
        if "radius" in params and not (isinstance(params["radius"], (int, float)) and 0 < params["radius"] <= 1):
            add("error", base + ".radius", "Radius precisa estar em (0, 1].")
        if "reach" in params and not (isinstance(params["reach"], (int, float)) and 0 < params["reach"] <= 0.45):
            add("error", base + ".reach", "Reach precisa estar em (0, 0.45].")
        if "sensitivity" in params and not (isinstance(params["sensitivity"], (int, float)) and params["sensitivity"] > 0):
            add("error", base + ".sensitivity", "Sensibilidade precisa ser positiva.")
        if "duration_ms" in params and not (isinstance(params["duration_ms"], int) and params["duration_ms"] > 0):
            add("error", base + ".duration_ms", "duration_ms precisa ser maior que zero.")
        if "interval_ms" in params and not (isinstance(params["interval_ms"], int) and params["interval_ms"] > 0):
            add("error", base + ".interval_ms", "interval_ms precisa ser maior que zero.")

        if node.type in ("aim", "mouse_camera"):
            mode = params.get("activation_mode", "always_on")
            has_key = bool(node.binding_refs.get("activation_key"))
            if mode not in ACTIVATION_MODES:
                add("error", base + ".activation_mode", f"Modo de ativacao desconhecido: {mode!r}.")
            if params.get("curve", "balanced") not in CURVE_PRESETS:
                add("error", base + ".curve", f"Curva desconhecida: {params.get('curve')!r}.")
            if mode == "always_on" and has_key:
                add("error", base + ".activation_key", "always_on nao permite activation_key.")
            if mode in ("while_held", "toggle") and not has_key:
                add("error", base + ".activation_key", f"{mode} exige activation_key.")

        if node.type == "layer_shift":
            if params.get("mode", "hold") not in LAYER_MODES:
                add("error", base + ".mode", f"Modo de camada desconhecido: {params.get('mode')!r}.")
            if not str(params.get("layer_name", "") or "").strip():
                add("error", base + ".layer_name", "layer_shift exige layer_name.")

        for role, binding_id in node.binding_refs.items():
            if binding_id not in profile.bindings:
                add("error", f"{base}.binding_refs.{role}", f"Binding inexistente: {binding_id!r}")

        if node.type == "macro":
            if params.get("mode", "cancel_on_release") not in MACRO_MODES:
                add("error", base + ".mode", f"Modo de macro desconhecido: {params.get('mode')!r}.")
            if not node.sequence:
                add("error", base + ".sequence", "Macro sem passos.")
            macro_slots: set[int] = set()
            for index, step in enumerate(node.sequence):
                action = str(step.get("action", "")).lower()
                if action not in ("down", "up"):
                    add("error", f"{base}.sequence[{index}].action", f"Acao de macro invalida: {step.get('action')!r}.")
                if action == "down" and "pos" not in step:
                    add("error", f"{base}.sequence[{index}].pos", "Passo down exige posicao.")
                if "pos" in step:
                    _validate_position(add, f"{base}.sequence[{index}].pos", step["pos"])
                step_slot = step.get("slot")
                if not isinstance(step_slot, int) or isinstance(step_slot, bool) or not 0 <= step_slot <= 255:
                    add("error", f"{base}.sequence[{index}].slot", "Slot de macro fora de 0..255.")
                elif step_slot == RESERVED_SLOT:
                    add("error", f"{base}.sequence[{index}].slot", "Slot 255 reservado pelo Phantom.")
                elif step_slot in macro_slots:
                    add("error", f"{base}.sequence[{index}].slot", f"Slot de macro duplicado: {step_slot}.")
                else:
                    macro_slots.add(step_slot)
                delay = step.get("delay_ms", 0)
                if not isinstance(delay, int) or isinstance(delay, bool) or delay < 0:
                    add("error", f"{base}.sequence[{index}].delay_ms", "delay_ms precisa ser inteiro >= 0.")
                ref = step.get("binding_ref")
                if ref and ref not in profile.bindings:
                    add("error", f"{base}.sequence[{index}].binding_ref", f"Binding inexistente: {ref!r}")

    _validate_conflicts(add, profile)
    return issues


def has_errors(issues: Iterable[ValidationIssue]) -> bool:
    return any(issue.severity == "error" for issue in issues)


def _validate_position(add, field_name: str, pos) -> None:
    if not isinstance(pos, dict):
        add("error", field_name, "Posicao precisa ser um objeto com x e y.")
        return
    try:
        x, y = float(pos.get("x")), float(pos.get("y"))
    except (TypeError, ValueError):
        add("error", field_name, "Coordenadas nao numericas.")
        return
    if not (math.isfinite(x) and math.isfinite(y)) or not (0 <= x <= 1 and 0 <= y <= 1):
        add("error", field_name, "Coordenadas precisam estar em [0, 1].")


def _validate_conflicts(add, profile: ControlProfileV2) -> None:
    layer_defaults = {layer.id: layer.exclusive for layer in profile.layers}
    layer_defaults.update({layer.name: layer.exclusive for layer in profile.layers if layer.name})

    switch_keys: dict[str, list[str]] = {}
    shifts_by_layer: dict[str, list[bool]] = {}
    action_keys: dict[str, set[str]] = {}
    action_owners: dict[tuple[str, str], list[str]] = {}
    verified_identities: set[str] = set()

    for node in profile.nodes:
        if node.type == "layer_shift":
            for role, binding_id in node.binding_refs.items():
                binding = profile.bindings.get(binding_id)
                if binding is None:
                    continue
                identity = binding.identity()
                switch_keys.setdefault(identity, []).append(f"{node.id}.{role}")
                if binding.validation == "verified":
                    verified_identities.add(identity)
            target = str(node.parameters.get("layer_name", "")).strip()
            if target:
                suspend = node.parameters.get("suspend_base", layer_defaults.get(target, False))
                shifts_by_layer.setdefault(target, []).append(bool(suspend))
            continue

        for role, binding_id in node.binding_refs.items():
            binding = profile.bindings.get(binding_id)
            if binding is None:
                continue
            identity = binding.identity()
            layer = node.layer.strip()
            action_keys.setdefault(identity, set()).add(layer)
            action_owners.setdefault((identity, layer), []).append(f"{node.id}.{role}")
            if binding.validation == "verified":
                verified_identities.add(identity)
        for index, step in enumerate(node.sequence):
            ref = step.get("binding_ref")
            binding = profile.bindings.get(ref) if ref else None
            if binding is not None:
                identity = binding.identity()
                layer = node.layer.strip()
                action_keys.setdefault(identity, set()).add(layer)
                action_owners.setdefault((identity, layer), []).append(f"{node.id}.sequence[{index}]")
                if binding.validation == "verified":
                    verified_identities.add(identity)

    def severity(identity: str) -> str:
        return "error" if identity in verified_identities else "warning"

    for identity, owners in switch_keys.items():
        if len(owners) > 1:
            add(severity(identity), "nodes.binding_refs",
                f"Tecla de troca de camada usada por mais de um no: {identity} ({', '.join(owners)}).")

    for identity in switch_keys:
        if identity in action_keys:
            add(severity(identity), "nodes.binding_refs",
                f"Tecla nao pode ser simultaneamente troca de camada e acao: {identity}.")

    for (identity, layer), owners in action_owners.items():
        if len(owners) > 1:
            layer_label = layer or "base"
            add(severity(identity), "nodes.binding_refs",
                f"Conflito na mesma camada ({layer_label}): {identity} usado por {', '.join(owners)}.")

    for identity, layers in action_keys.items():
        if "" not in layers or len(layers) <= 1:
            continue
        non_base = sorted(layer for layer in layers if layer)
        protegidas = []
        for layer in non_base:
            modos = shifts_by_layer.get(layer)
            if modos and all(modos):
                protegidas.append(layer)
        if len(protegidas) != len(non_base):
            add(severity(identity), "nodes.binding_refs",
                "Chave usada na base e em camada sem suspend_base em todos os shifts: "
                + identity + "; camadas: " + ", ".join(non_base))


# ---------------------------------------------------------------------------
# Migracao do formato antigo
# ---------------------------------------------------------------------------


def _optional_int(value) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _optional_float(value, default: float) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return default
    return result if math.isfinite(result) else default


def _safe_binding_id(node_id: str, role: str, used: set[str]) -> str:
    base = "".join(ch if ch.isalnum() or ch in "_-" else "_" for ch in f"{node_id}_{role}")
    candidate = base or "binding"
    count = 1
    while candidate in used:
        count += 1
        candidate = f"{base}_{count}"
    used.add(candidate)
    return candidate


def migrate_legacy_profile(
    legacy: dict,
    *,
    game_package: str = "",
    screen_source: str = "imported",
) -> ControlProfileV2:
    """Converte version=1 para o formato versionado, sem inventar fisico.

    Bindings antigos viram `unverified`, com `code=None` e `code_space=unknown`,
    mesmo quando o texto e um nome aceito pelo Phantom.
    """
    if not isinstance(legacy, dict):
        raise ProfileError("Perfil antigo precisa ser um objeto JSON.")
    if legacy.get("version") != LEGACY_VERSION:
        raise ProfileError("Formato de entrada nao e um perfil Phantom version=1.")

    raw_screen = legacy.get("screen")
    screen = ScreenContract()
    if isinstance(raw_screen, dict):
        width, height = _optional_int(raw_screen.get("width")), _optional_int(raw_screen.get("height"))
        if width and height and width > 0 and height > 0:
            screen = ScreenContract(width=width, height=height, source=screen_source)

    sensitivity = _optional_float(legacy.get("global_sensitivity"), 1.0)
    if sensitivity <= 0:
        sensitivity = 1.0

    profile = ControlProfileV2(
        schema_version=SCHEMA_VERSION,
        name=str(legacy.get("name", "") or ""),
        game_package=game_package,
        screen_contract=screen,
        backend_preferences=BackendPreferences(preferred="auto"),
        cursor_model=CursorModelConfig(sensitivity=sensitivity),
        metadata={
            "migrated_from_version": LEGACY_VERSION,
            "migration_notes": "Bindings de texto antigo marcados como nao verificados.",
        },
    )

    used_bindings: set[str] = set()
    layer_names: list[str] = []

    for raw_node in legacy.get("nodes") or []:
        if not isinstance(raw_node, dict):
            continue
        node_id = str(raw_node.get("id", "") or "")
        node_type = str(raw_node.get("type", "tap") or "tap")
        geometry = {
            key: dict(value)
            for key, value in raw_node.items()
            if key in POSITION_FIELDS and isinstance(value, dict)
        }
        parameters = {
            key: raw_node[key]
            for key in (
                "radius", "reach", "sensitivity", "curve", "activation_mode",
                "invert_y", "duration_ms", "interval_ms", "mode", "layer_name",
                "suspend_base",
            )
            if key in raw_node
        }
        node = ProfileNode(
            id=node_id,
            type=node_type,
            layer=str(raw_node.get("layer", "") or ""),
            slot=_optional_int(raw_node.get("slot")),
            up_slot=_optional_int(raw_node.get("up_slot")),
            down_slot=_optional_int(raw_node.get("down_slot")),
            geometry=geometry,
            parameters=parameters,
            sequence=[dict(step) for step in (raw_node.get("sequence") or []) if isinstance(step, dict)],
        )
        if node.layer and node.layer not in layer_names:
            layer_names.append(node.layer)

        keys_dict = raw_node.get("keys")
        keys_dict = keys_dict if isinstance(keys_dict, dict) else {}
        texts: dict[str, str] = {}
        for role in TEXT_KEY_FIELDS:
            value = raw_node.get(role)
            if isinstance(value, str) and value.strip():
                texts[role] = value.strip()
        for role, value in keys_dict.items():
            if isinstance(value, str) and value.strip():
                texts[str(role)] = value.strip()

        for role, text in texts.items():
            binding_id = _safe_binding_id(node_id, role, used_bindings)
            profile.bindings[binding_id] = InputBinding.from_legacy_text(text)
            node.binding_refs[role] = binding_id

        if node_type == "layer_shift":
            target = str(parameters.get("layer_name", "") or "").strip()
            if target and target not in layer_names:
                layer_names.append(target)

        profile.nodes.append(node)

    for name in layer_names:
        profile.layers.append(Layer(id=name, name=name, exclusive=False))
    return profile
