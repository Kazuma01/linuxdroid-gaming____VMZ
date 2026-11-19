"""Vocabulario de entrada fisica e identificacao canonica.

Os nomes e codigos abaixo NAO foram inventados: foram extraidos do codigo real
do Phantom no commit 1a6b7edb423462c1bc546031ed86d9bf2cc1cffd:

  phantom/src/input.rs :: Key::parse_name()
  phantom/src/input.rs :: Key::evdev_code()

Pontos importantes de compatibilidade:

  * `parse_name()` aceita aliases (CTRL, SHIFT, WIN, '[', '0', ...).
  * `evdev_code()` nao existe para WheelUp/WheelDown.
  * `nativeScanCode()` do Qt NAO e garantido igual ao codigo evdev. Em Wayland
    ele costuma vir do xkb keycode; em X11 do keycode X. Nao ha conversao
    implicita neste modulo: o espaco de codigo e sempre explicito.
  * Um nome canonical e uma apresentacao localizada sao campos diferentes.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable

PHANTOM_COMMIT = "1a6b7edb423462c1bc546031ed86d9bf2cc1cffd"
PHANTOM_SOURCE = (
    "https://github.com/oliviermugishak/phantom/blob/" + PHANTOM_COMMIT
)

NAMESPACES = ("keyboard", "mouse", "wheel", "other")
BINDING_KINDS = ("key", "button", "scroll", "motion", "unknown")
CODE_SPACES = ("evdev", "qt_native_scan_code", "qt_virtual_key", "phantom_name", "unknown")
VALIDATION_STATUSES = ("verified", "unverified", "invalid", "unsupported")

# Proveniencia e uma dimensao independente de `validation`:
#   validated_by_vocabulary  -> nome aceito pela tabela Phantom (NAO e captura)
#   captured_from_device     -> identidade observada por backend de captura real
#   validated_by_backend     -> backend especifico aceitou o binding
#   unverified               -> identidade ainda nao comprovada
# `validation` continua descrevendo compatibilidade com o schema/vocabulario
# para nao quebrar perfis antigos; NUNCA deve ser lido como prova de captura.
PROVENANCE_STATES = (
    "validated_by_vocabulary",
    "captured_from_device",
    "validated_by_backend",
    "unverified",
)

# Nomes canonicos aceitos por Key::parse_name. Digitos usam "0".."9" porque
# "Key0" nao e aceito pelo parser do Phantom.
_CANONICAL: list[str] = list("ABCDEFGHIJKLMNOPQRSTUVWXYZ")
_CANONICAL += [str(n) for n in range(10)]
_CANONICAL += [f"F{n}" for n in range(1, 13)]
_CANONICAL += [
    "LeftCtrl", "RightCtrl", "LeftShift", "RightShift",
    "LeftAlt", "RightAlt", "LeftMeta", "RightMeta",
    "Up", "Down", "Left", "Right", "Home", "End", "PageUp", "PageDown",
    "Space", "Enter", "Backspace", "Delete", "Insert", "Tab", "Esc",
    "Minus", "Equal", "LeftBrace", "RightBrace", "Semicolon", "Apostrophe",
    "Grave", "Backslash", "Comma", "Dot", "Slash",
    "CapsLock", "NumLock", "ScrollLock", "SysRq", "Pause",
]
_CANONICAL += [f"KP{n}" for n in range(10)]
_CANONICAL += [
    "MouseLeft", "MouseRight", "MouseMiddle", "MouseBack", "MouseForward",
    "WheelUp", "WheelDown",
]
PHANTOM_CANONICAL_NAMES = frozenset(_CANONICAL)

# Aliases literais encontrados em parse_name(). A chave e sempre upper().
_ALIASES: dict[str, str] = {
    "CTRL": "LeftCtrl",
    "SHIFT": "LeftShift",
    "ALT": "LeftAlt",
    "WIN": "LeftMeta",
    "SUPER": "LeftMeta",
    "ENTER": "Enter",
    "ESC": "Esc",
    "SPACE": "Space",
    "TAB": "Tab",
    "BACKSPACE": "Backspace",
    "DELETE": "Delete",
    "INSERT": "Insert",
    "UP": "Up",
    "DOWN": "Down",
    "LEFT": "Left",
    "RIGHT": "Right",
    "HOME": "Home",
    "END": "End",
    "PAGEUP": "PageUp",
    "PAGEDOWN": "PageDown",
    "CAPSLOCK": "CapsLock",
    "MOUSELEFT": "MouseLeft",
    "MOUSERIGHT": "MouseRight",
    "MOUSEMIDDLE": "MouseMiddle",
    "MOUSEBACK": "MouseBack",
    "MOUSEFORWARD": "MouseForward",
    "WHEELUP": "WheelUp",
    "WHEELDOWN": "WheelDown",
    "LEFTCTRL": "LeftCtrl",
    "RIGHTCTRL": "RightCtrl",
    "LEFTSHIFT": "LeftShift",
    "RIGHTSHIFT": "RightShift",
    "LEFTALT": "LeftAlt",
    "RIGHTALT": "RightAlt",
    "LEFTMETA": "LeftMeta",
    "RIGHTMETA": "RightMeta",
    "-": "Minus",
    "=": "Equal",
    "[": "LeftBrace",
    "]": "RightBrace",
    ";": "Semicolon",
    "'": "Apostrophe",
    "`": "Grave",
    "\\": "Backslash",
    ",": "Comma",
    ".": "Dot",
    "/": "Slash",
    "NUMLOCK": "NumLock",
    "SCROLLLOCK": "ScrollLock",
    "SYSRQ": "SysRq",
    "PAUSE": "Pause",
}
for _ch in "ABCDEFGHIJKLMNOPQRSTUVWXYZ":
    _ALIASES.setdefault(_ch, _ch)

# Codigos evdev exatos de Key::evdev_code(). WheelUp/WheelDown ficam de fora
# porque o proprios Phantom devolve None para eles.
_EVDEV_BY_CANONICAL: dict[str, int] = {
    "Esc": 1,
    "1": 2, "2": 3, "3": 4, "4": 5, "5": 6, "6": 7, "7": 8, "8": 9, "9": 10, "0": 11,
    "Minus": 12, "Equal": 13, "Backspace": 14, "Tab": 15,
    "Q": 16, "W": 17, "E": 18, "R": 19, "T": 20, "Y": 21, "U": 22, "I": 23,
    "O": 24, "P": 25, "LeftBrace": 26, "RightBrace": 27, "Enter": 28,
    "LeftCtrl": 29,
    "A": 30, "S": 31, "D": 32, "F": 33, "G": 34, "H": 35, "J": 36, "K": 37,
    "L": 38, "Semicolon": 39, "Apostrophe": 40, "Grave": 41, "LeftShift": 42,
    "Backslash": 43,
    "Z": 44, "X": 45, "C": 46, "V": 47, "B": 48, "N": 49, "M": 50,
    "Comma": 51, "Dot": 52, "Slash": 53, "RightShift": 54,
    "LeftAlt": 56, "Space": 57, "CapsLock": 58,
    "F1": 59, "F2": 60, "F3": 61, "F4": 62, "F5": 63, "F6": 64,
    "F7": 65, "F8": 66, "F9": 67, "F10": 68,
    "NumLock": 69, "ScrollLock": 70,
    "KP7": 71, "KP8": 72, "KP9": 73, "KP4": 74, "KP5": 75, "KP6": 76,
    "KP1": 77, "KP2": 78, "KP3": 79, "KP0": 80,
    "F11": 87, "F12": 88,
    "RightCtrl": 97, "SysRq": 99, "RightAlt": 100,
    "Home": 102, "Up": 103, "PageUp": 104, "Left": 105, "Right": 106,
    "End": 107, "Down": 108, "PageDown": 109, "Insert": 110, "Delete": 111,
    "Pause": 119, "LeftMeta": 125, "RightMeta": 126,
    "MouseLeft": 0x110, "MouseRight": 0x111, "MouseMiddle": 0x112,
    "MouseBack": 0x113, "MouseForward": 0x114,
}
EVDEV_CODE_BY_CANONICAL = dict(_EVDEV_BY_CANONICAL)
EVDEV_CANONICAL_BY_CODE = {code: name for name, code in _EVDEV_BY_CANONICAL.items()}

MODIFIER_CANONICAL = frozenset(
    {"LeftCtrl", "RightCtrl", "LeftShift", "RightShift",
     "LeftAlt", "RightAlt", "LeftMeta", "RightMeta"}
)


def normalize_phantom_name(value: str | None) -> str | None:
    """Converte um nome/alias em canonico; None quando o Phantom nao aceita."""
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    canonical = _ALIASES.get(text.upper())
    if canonical is not None:
        return canonical
    if text in PHANTOM_CANONICAL_NAMES:
        return text
    return None


def is_phantom_name(value: str | None) -> bool:
    return normalize_phantom_name(value) is not None


def canonical_for_code(code: int | None, code_space: str = "unknown") -> str | None:
    """Resolve codigo apenas no espaco evdev. Nunca adivinha outros espacos."""
    if code_space != "evdev" or code is None:
        return None
    return EVDEV_CANONICAL_BY_CODE.get(int(code))


def namespace_for_canonical(canonical: str | None) -> str:
    if not canonical:
        return "other"
    if canonical.startswith("Mouse"):
        return "mouse"
    if canonical in ("WheelUp", "WheelDown"):
        return "wheel"
    if canonical in PHANTOM_CANONICAL_NAMES:
        return "keyboard"
    return "other"


def kind_for_canonical(canonical: str | None) -> str:
    if not canonical:
        return "unknown"
    if canonical in ("WheelUp", "WheelDown"):
        return "scroll"
    if canonical.startswith("Mouse"):
        return "button"
    return "key"


@dataclass
class InputBinding:
    """Identidade de uma entrada fisica. Nao e um texto de teclado."""

    namespace: str = "other"
    event_type: str = "unknown"
    code: int | None = None
    code_space: str = "unknown"
    canonical_name: str = ""
    modifiers: tuple[str, ...] = ()
    capture_source: str = "unknown"
    label: str = ""
    validation: str = "unverified"
    provenance: str = "unverified"
    notes: str = ""

    def to_dict(self) -> dict:
        return {
            "namespace": self.namespace,
            "event_type": self.event_type,
            "code": self.code,
            "code_space": self.code_space,
            "canonical_name": self.canonical_name,
            "modifiers": list(self.modifiers),
            "capture_source": self.capture_source,
            "label": self.label,
            "validation": self.validation,
            "provenance": self.provenance,
            "notes": self.notes,
        }

    @classmethod
    def from_dict(cls, raw: dict) -> "InputBinding":
        raw = raw if isinstance(raw, dict) else {}
        mods = raw.get("modifiers") or ()
        if isinstance(mods, str):
            mods = (mods,)
        return cls(
            namespace=str(raw.get("namespace", "other")),
            event_type=str(raw.get("event_type", "unknown")),
            code=raw.get("code"),
            code_space=str(raw.get("code_space", "unknown")),
            canonical_name=str(raw.get("canonical_name", "") or ""),
            modifiers=tuple(str(m) for m in mods),
            capture_source=str(raw.get("capture_source", "unknown")),
            label=str(raw.get("label", "") or ""),
            validation=str(raw.get("validation", "unverified")),
            provenance=str(raw.get("provenance", "unverified") or "unverified"),
            notes=str(raw.get("notes", "") or ""),
        )

    @classmethod
    def from_legacy_text(cls, text: str) -> "InputBinding":
        """Migra texto antigo SEM inventar codigo fisico.

        O nome pode ser reconhecido pelo vocabulario do Phantom, mas a
        identidade fisica permanece nao verificada porque nao houve captura.
        """
        raw = str(text or "").strip()
        canonical = normalize_phantom_name(raw) or ""
        return cls(
            namespace=namespace_for_canonical(canonical),
            event_type=kind_for_canonical(canonical),
            code=None,
            code_space="unknown",
            canonical_name=canonical,
            modifiers=(),
            capture_source="legacy_text",
            label=raw,
            validation="unverified" if canonical else "invalid",
            provenance="unverified",
            notes="Texto herdado; sem codigo fisico medido.",
        )

    @classmethod
    def from_canonical(
        cls,
        canonical: str,
        *,
        capture_source: str,
        code: int | None = None,
        code_space: str = "unknown",
        provenance: str = "validated_by_vocabulary",
        validation: str | None = None,
    ) -> "InputBinding":
        """Cria binding a partir de nome canonico.

        O codigo so e preenchido se o chamador fornecer um codigo medido e o
        seu espaco. A tabela evdev existe para *validar* codigos, nao para
        inventar uma captura que nao aconteceu.

        Por padrao a proveniencia e `validated_by_vocabulary`: o nome foi
        reconhecido, mas nenhuma captura fisica foi observada. Backends reais
        devem informar explicitamente `captured_from_device` ou
        `validated_by_backend` quando houver evidencia.
        """
        name = normalize_phantom_name(canonical)
        if name is None:
            raise ValueError(f"nome canonico desconhecido: {canonical!r}")
        if provenance not in PROVENANCE_STATES:
            raise ValueError(f"proveniencia desconhecida: {provenance!r}")
        return cls(
            namespace=namespace_for_canonical(name),
            event_type=kind_for_canonical(name),
            code=code,
            code_space=code_space if code is not None else "unknown",
            canonical_name=name,
            modifiers=(),
            capture_source=capture_source,
            label=name,
            validation=validation or "verified",
            provenance=provenance,
        )

    def is_physically_captured(self) -> bool:
        """Verdadeiro apenas se a identidade veio de captura real comprovada."""
        return self.provenance in ("captured_from_device", "validated_by_backend")

    def identity(self) -> str:
        """Chave de conflito. Bindings nao verificados nao sao promovidos."""
        base = self.canonical_name or f"legacy:{self.label.upper()}"
        mods = ",".join(sorted(self.modifiers))
        return f"{base}|{mods}" if mods else base

    def export_name(self) -> str | None:
        """Nome seguro para o schema Phantom, ou None se nao aceito."""
        if self.validation == "invalid":
            return None
        return normalize_phantom_name(self.canonical_name)
