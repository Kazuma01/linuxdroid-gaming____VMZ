"""Fabrica compartilhada de perfis para testes do nucleo V3 (sem Qt/hardware)."""
from __future__ import annotations

from linuxdroid.controls.keys import InputBinding
from linuxdroid.controls.model import (
    ControlProfileV2,
    ProfileNode,
    ScreenContract,
)


def binding(name: str, ref: str | None = None, **kwargs) -> tuple[str, InputBinding]:
    return ref or name.lower(), InputBinding.from_canonical(
        name, capture_source="unit-test", **kwargs
    )


def make_profile(name: str = "perfil-teste", **kwargs) -> ControlProfileV2:
    screen = kwargs.pop("screen_contract", ScreenContract(1920, 1080, "measured"))
    return ControlProfileV2(
        name=name,
        game_package="com.example.game",
        screen_contract=screen,
        **kwargs,
    )


def add_node(
    profile: ControlProfileV2,
    *,
    node_id: str,
    node_type: str,
    slot: int | None = 0,
    refs: dict[str, str] | None = None,
    keys: dict[str, str] | None = None,
    geometry: dict | None = None,
    parameters: dict | None = None,
    layer: str = "",
    up_slot: int | None = None,
    down_slot: int | None = None,
    sequence: list | None = None,
) -> ProfileNode:
    binding_refs = dict(refs or {})
    for role, key in (keys or {}).items():
        ref = f"{node_id}_{role}"
        profile.bindings[ref] = InputBinding.from_canonical(
            key, capture_source="unit-test"
        )
        binding_refs[role] = ref
    node = ProfileNode(
        id=node_id,
        type=node_type,
        layer=layer,
        slot=slot,
        up_slot=up_slot,
        down_slot=down_slot,
        binding_refs=binding_refs,
        geometry=geometry or {},
        parameters=parameters or {},
        sequence=sequence or [],
    )
    profile.nodes.append(node)
    return node


def tap_profile(key: str = "W", pos: tuple[float, float] = (0.2, 0.8)) -> ControlProfileV2:
    profile = make_profile()
    add_node(
        profile,
        node_id="tap",
        node_type="tap",
        slot=0,
        keys={"key": key},
        geometry={"pos": {"x": pos[0], "y": pos[1]}},
    )
    return profile
