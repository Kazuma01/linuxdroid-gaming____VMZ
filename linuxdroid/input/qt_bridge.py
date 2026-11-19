"""Traducao explicita de identidades Qt para o vocabulario canonico.

Este modulo NAO importa PySide6 e NAO usa `event.text().upper()`. Ele recebe
apenas numeros inteiros (key/nativeScanCode/nativeVirtualKey) para ser
testavel sem Qt. Codigos Qt nunca sao convertidos em evdev: permanecem no seu
proprio espaco de codigo.
"""
from __future__ import annotations

from typing import Iterable

from ..controls.keys import (
    PROVENANCE_STATES,
    InputBinding,
    kind_for_canonical,
    namespace_for_canonical,
    normalize_phantom_name,
)

QT_SPECIAL: dict[int, str] = {
    0x01000000: "Esc",
    0x01000001: "Tab",
    0x01000003: "Backspace",
    0x01000004: "Enter",
    0x01000005: "Enter",
    0x01000006: "Insert",
    0x01000007: "Delete",
    0x01000010: "Home",
    0x01000011: "End",
    0x01000012: "Left",
    0x01000013: "Up",
    0x01000014: "Right",
    0x01000015: "Down",
    0x01000016: "PageUp",
    0x01000017: "PageDown",
    0x01000020: "LeftShift",
    0x01000021: "LeftCtrl",
    0x01000022: "LeftMeta",
    0x01000023: "LeftAlt",
    0x01000024: "CapsLock",
    0x01000025: "NumLock",
    0x01000026: "ScrollLock",
    0x01000030: "F1", 0x01000031: "F2", 0x01000032: "F3", 0x01000033: "F4",
    0x01000034: "F5", 0x01000035: "F6", 0x01000036: "F7", 0x01000037: "F8",
    0x01000038: "F9", 0x01000039: "F10", 0x0100003A: "F11", 0x0100003B: "F12",
    0x20: "Space",
    0x2D: "Minus", 0x3D: "Equal", 0x5B: "LeftBrace", 0x5D: "RightBrace",
    0x3B: "Semicolon", 0x27: "Apostrophe", 0x60: "Grave", 0x5C: "Backslash",
    0x2C: "Comma", 0x2E: "Dot", 0x2F: "Slash",
}

# nativeVirtualKey Windows/Win32: distingue esquerdo de direito quando
# disponivel. Em Wayland este campo pode ser 0; nesse caso o lado permanece
# "Left*" com aviso explicito em `notes`, nunca como captura física provada.
QT_NATIVE_VIRTUAL_MODIFIERS: dict[int, str] = {
    0xA0: "LeftShift", 0xA1: "RightShift",
    0xA2: "LeftCtrl", 0xA3: "RightCtrl",
    0xA4: "LeftAlt", 0xA5: "RightAlt",
    0x5B: "LeftMeta", 0x5C: "RightMeta",
}

QT_MOUSE_BUTTONS: dict[int, str] = {
    1: "MouseLeft",
    2: "MouseRight",
    4: "MouseMiddle",
    8: "MouseBack",
    16: "MouseForward",
}


def canonical_for_qt_key(key: int, native_virtual_key: int | None = None) -> str:
    """Resolve o nome canonico a partir do codigo Qt, sem usar texto digitado."""
    try:
        value = int(key)
    except (TypeError, ValueError):
        return ""
    if native_virtual_key in QT_NATIVE_VIRTUAL_MODIFIERS:
        return QT_NATIVE_VIRTUAL_MODIFIERS[int(native_virtual_key)]
    if 0x30 <= value <= 0x39:
        return chr(value)
    if 0x41 <= value <= 0x5A:
        return chr(value)
    return QT_SPECIAL.get(value, "")


def binding_from_qt_key(
    key: int,
    *,
    native_scan_code: int | None = None,
    native_virtual_key: int | None = None,
    modifiers: Iterable[str] = (),
    source: str = "qt_local_editor",
) -> InputBinding:
    """Cria binding a partir de uma captura local do editor."""
    canonical = canonical_for_qt_key(key, native_virtual_key)
    code = native_scan_code if native_scan_code not in (None, 0) else native_virtual_key
    code_space = "qt_native_scan_code" if native_scan_code not in (None, 0) else (
        "qt_virtual_key" if native_virtual_key not in (None, 0) else "unknown"
    )
    if code is None:
        code_space = "unknown"
    mods = tuple(str(modifier) for modifier in modifiers)
    notes = []
    if code_space.startswith("qt_"):
        notes.append("Codigo Qt registrado no proprio espaco; nao convertido para evdev.")
    if canonical in ("LeftShift", "LeftCtrl", "LeftAlt", "LeftMeta") and native_virtual_key not in QT_NATIVE_VIRTUAL_MODIFIERS:
        notes.append("Lado do modificador nao observado; canonical assume esquerdo.")
    if not canonical:
        notes.append("Identidade Qt desconhecida; nenhum nome canonico inventado.")
    return InputBinding(
        namespace=namespace_for_canonical(canonical),
        event_type=kind_for_canonical(canonical),
        code=int(code) if code is not None else None,
        code_space=code_space,
        canonical_name=canonical,
        modifiers=mods,
        capture_source=source,
        label=canonical or f"qt:0x{int(key):x}",
        validation="verified" if canonical else "unverified",
        provenance="validated_by_vocabulary" if canonical else "unverified",
        notes=" ".join(notes),
    )


def binding_from_qt_mouse(button_value: int, *, source: str = "qt_local_editor") -> InputBinding:
    name = QT_MOUSE_BUTTONS.get(int(button_value), "")
    return InputBinding(
        namespace=namespace_for_canonical(name),
        event_type=kind_for_canonical(name),
        canonical_name=name,
        capture_source=source,
        label=name or f"qt-mouse:{button_value}",
        validation="verified" if name else "unverified",
        provenance="validated_by_vocabulary" if name else "unverified",
        notes="Botao do mouse identificado localmente; nenhuma captura global." if name else "Botao desconhecido.",
    )


def binding_from_wheel(direction: str, *, source: str = "qt_local_editor") -> InputBinding:
    canonical = normalize_phantom_name("WheelUp" if direction == "up" else "WheelDown") or ""
    return InputBinding(
        namespace=namespace_for_canonical(canonical),
        event_type="scroll",
        canonical_name=canonical,
        capture_source=source,
        label=canonical,
        validation="verified",
        provenance="validated_by_vocabulary",
        notes="Direcao de rolagem informada pelo editor; nao ha codigo evdev para wheel.",
    )


def binding_provenance(value: str) -> str:
    return value if value in PROVENANCE_STATES else "unverified"


__all__ = [
    "QT_SPECIAL",
    "QT_NATIVE_VIRTUAL_MODIFIERS",
    "QT_MOUSE_BUTTONS",
    "canonical_for_qt_key",
    "binding_from_qt_key",
    "binding_from_qt_mouse",
    "binding_from_wheel",
    "binding_provenance",
]
