"""Cursor virtual testavel, sem captura real de ponteiro.

O cursor trabalha em coordenadas normalizadas [0, 1]. Movimento relativo em
pixels so pode ser convertido quando o contrato de tela e conhecido: uma
resolucao desconhecida NAO e presumida como 1280x720.

Este modulo nao usa Qt, nao abre dispositivos e nao injeta eventos Android.
"""
from __future__ import annotations

import math
from typing import Iterable

from .model import CursorModelConfig, ScreenContract

CAPTURE_STATES = frozenset({"released", "captured"})
AIM_STATES = frozenset({"off", "active"})
MENU_TOUCH_STATES = frozenset({"off", "active"})
ACCELERATION_REFERENCE_PX = 500.0


class CursorError(ValueError):
    """Operacao de cursor impossivel com o estado atual."""


class CursorVirtual:
    """Estado logico de mira/navegacao por toque em coordenadas normalizadas."""

    def __init__(
        self,
        config: CursorModelConfig | None = None,
        screen: ScreenContract | None = None,
    ) -> None:
        self.config = config or CursorModelConfig()
        self.screen = screen
        self.x = float(self.config.initial_x)
        self.y = float(self.config.initial_y)
        self.last_delta_normalized = (0.0, 0.0)
        self.last_unit = "normalized"

    @classmethod
    def from_profile(cls, profile) -> "CursorVirtual":
        return cls(profile.cursor_model, profile.screen_contract)

    # -- estado -------------------------------------------------------------

    def set_screen_contract(self, screen: ScreenContract | None) -> None:
        self.screen = screen
        if self.screen is not None and not self.screen.known:
            raise CursorError("Contrato de tela desconhecido; resolucao nao pode ser usada.")

    @property
    def in_bounds(self) -> bool:
        return 0 <= self.x <= 1 and 0 <= self.y <= 1

    def _screen_size(self) -> tuple[float, float]:
        if self.screen is None or not self.screen.known:
            raise CursorError("Resolucao desconhecida; nao ha conversao implicita de pixels.")
        return float(self.screen.width), float(self.screen.height)

    def set_position_normalized(self, x: float, y: float) -> tuple[float, float]:
        nx, ny = float(x), float(y)
        if not (math.isfinite(nx) and math.isfinite(ny)):
            raise CursorError("Coordenadas precisam ser finitas.")
        if self.config.clamp_to_screen:
            nx, ny = _clamp(nx), _clamp(ny)
        self.x, self.y = nx, ny
        self.last_delta_normalized = (0.0, 0.0)
        return self.position

    def set_position_pixels(self, px: float, py: float) -> tuple[float, float]:
        width, height = self._screen_size()
        return self.set_position_normalized(float(px) / width, float(py) / height)

    @property
    def position(self) -> tuple[float, float]:
        return self.x, self.y

    def position_pixels(self) -> tuple[float, float]:
        width, height = self._screen_size()
        return self.x * width, self.y * height

    # -- movimento ----------------------------------------------------------

    def apply_relative(
        self,
        dx: float,
        dy: float,
        *,
        unit: str = "pixels",
    ) -> tuple[float, float]:
        """Aplica um delta simulado.

        `unit="pixels"` exige tela conhecida. `unit="normalized"` permite
        testar a logica sem resolucao, sem inventar uma conversao.
        """
        dx, dy = float(dx), float(dy)
        if not (math.isfinite(dx) and math.isfinite(dy)):
            raise CursorError("Delta de cursor precisa ser finito.")
        if unit not in ("pixels", "normalized"):
            raise CursorError(f"Unidade de delta desconhecida: {unit!r}")

        dx_norm, dy_norm = dx, dy
        if unit == "pixels":
            width, height = self._screen_size()
            dx_norm, dy_norm = dx / width, dy / height

        if self.config.acceleration:
            magnitude = math.hypot(dx, dy)
            factor = 1.0 + min(magnitude / ACCELERATION_REFERENCE_PX, 1.0)
            dx_norm *= factor
            dy_norm *= factor

        sensitivity = float(self.config.sensitivity)
        dx_norm *= sensitivity
        dy_norm *= sensitivity

        self.x += dx_norm
        self.y += dy_norm
        if self.config.clamp_to_screen:
            self.x, self.y = _clamp(self.x), _clamp(self.y)
        self.last_delta_normalized = (dx_norm, dy_norm)
        self.last_unit = unit
        return self.position

    def apply_absolute(self, x: float, y: float, *, unit: str = "normalized") -> tuple[float, float]:
        if unit == "normalized":
            return self.set_position_normalized(x, y)
        if unit == "pixels":
            return self.set_position_pixels(x, y)
        raise CursorError(f"Unidade de posicao desconhecida: {unit!r}")

    def reset(self) -> None:
        self.x = float(self.config.initial_x)
        self.y = float(self.config.initial_y)
        self.last_delta_normalized = (0.0, 0.0)
        self.set_capture("released")
        self.set_aim(False)
        self.set_menu_touch(False)

    # -- estados ------------------------------------------------------------

    def set_capture(self, state: str | bool) -> None:
        if isinstance(state, bool):
            state = "captured" if state else "released"
        if state not in CAPTURE_STATES:
            raise CursorError(f"Estado de captura invalido: {state!r}")
        self.config.capture_state = state

    def set_aim(self, active: bool) -> None:
        self.config.aim_state = "active" if bool(active) else "off"

    def set_menu_touch(self, active: bool) -> None:
        self.config.menu_touch_state = "active" if bool(active) else "off"

    @property
    def aim_active(self) -> bool:
        return self.config.aim_state == "active"

    @property
    def menu_touch_active(self) -> bool:
        return self.config.menu_touch_state == "active"

    @property
    def captured(self) -> bool:
        return self.config.capture_state == "captured"

    # -- simulacao e serializacao ------------------------------------------

    def simulate_events(self, events: Iterable[dict]) -> tuple[float, float]:
        """Aplica uma sequencia de eventos simulados, sem hardware.

        Eventos aceitos:
            {"type": "relative", "dx": 10, "dy": -2, "unit": "pixels"}
            {"type": "absolute", "x": 0.5, "y": 0.4, "unit": "normalized"}
            {"type": "capture", "state": "captured"}
            {"type": "aim", "active": true}
            {"type": "menu_touch", "active": true}
        """
        for event in events:
            if not isinstance(event, dict):
                raise CursorError("Evento simulado precisa ser um objeto.")
            kind = str(event.get("type", ""))
            if kind == "relative":
                self.apply_relative(
                    event.get("dx", 0.0),
                    event.get("dy", 0.0),
                    unit=str(event.get("unit", "pixels")),
                )
            elif kind == "absolute":
                self.apply_absolute(
                    event.get("x", 0.0),
                    event.get("y", 0.0),
                    unit=str(event.get("unit", "normalized")),
                )
            elif kind == "capture":
                self.set_capture(event.get("state", "released"))
            elif kind == "aim":
                self.set_aim(bool(event.get("active", False)))
            elif kind == "menu_touch":
                self.set_menu_touch(bool(event.get("active", False)))
            else:
                raise CursorError(f"Tipo de evento simulado desconhecido: {kind!r}")
        return self.position

    def to_dict(self) -> dict:
        return {
            "x": self.x,
            "y": self.y,
            "last_delta_normalized": list(self.last_delta_normalized),
            "last_unit": self.last_unit,
            "in_bounds": self.in_bounds,
            "config": self.config.to_dict(),
        }

    @classmethod
    def from_dict(cls, raw: dict) -> "CursorVirtual":
        raw = raw if isinstance(raw, dict) else {}
        cursor = cls(
            CursorModelConfig.from_dict(raw.get("config")),
            ScreenContract.from_dict(raw.get("screen")),
        )
        cursor.x = float(raw.get("x", cursor.x))
        cursor.y = float(raw.get("y", cursor.y))
        cursor.last_unit = str(raw.get("last_unit", "normalized"))
        delta = raw.get("last_delta_normalized") or [0.0, 0.0]
        if isinstance(delta, (list, tuple)) and len(delta) == 2:
            cursor.last_delta_normalized = (float(delta[0]), float(delta[1]))
        return cursor


def _clamp(value: float) -> float:
    return min(1.0, max(0.0, value))
