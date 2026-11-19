"""Motor de mapeamento puro (sem Qt) para perfis ControlProfileV2.

Fluxo implementado::

    InputEvent -> MappingEngine -> ContactManager -> TouchInjectBackend
                        |-> CursorVirtual / CaptureStateMachine

O motor NAO inicia Phantom, NAO abre dispositivos e NAO executa acoes de jogo
autonomas. Repeticoes so ocorrem com autorizacao explicita no perfil e enquanto
a entrada humana permanecer pressionada.
"""
from __future__ import annotations

import math
from typing import Iterable

from ..controls.cursor import CursorError, CursorVirtual
from ..controls.keys import InputBinding
from ..controls.model import (
    ControlProfileV2,
    ProfileNode,
    has_errors,
    validate_profile,
)
from ..services.capabilities import TouchInjectBackend
from .contacts import Contact, ContactManager, ContactManagerError
from .diagnostics import Diagnostics
from .events import InputEvent, identity_for_event
from .state import ACTIVE_STATES, CaptureStateMachine, RuntimeState

MENU_KEY = "__menu_touch__"
MAX_COMMAND_LOG = 2000
MAX_REPEATS_PER_TICK = 8


class ProfileRejected(ValueError):
    """Perfil invalido: nunca e carregado silenciosamente."""


class MappingEngine:
    """Interpreta eventos normalizados e emite comandos touch abstratos."""

    def __init__(
        self,
        profile: ControlProfileV2 | None = None,
        backend: TouchInjectBackend | None = None,
        *,
        clock=None,
        diagnostics: Diagnostics | None = None,
        state_machine: CaptureStateMachine | None = None,
    ) -> None:
        import time

        self.clock = clock or time.monotonic
        self.backend = backend
        self.diagnostics = diagnostics or Diagnostics()
        self.state_machine = state_machine or CaptureStateMachine(clock=self.clock)
        self.contacts = ContactManager(
            backend, clock=self.clock, profile_name=profile.name if profile else ""
        )
        self.cursor = CursorVirtual(profile.cursor_model, profile.screen_contract) if profile else CursorVirtual()
        self.profile: ControlProfileV2 | None = None
        self.commands: list[dict] = []
        self._actions: dict[str, list[tuple[ProfileNode, str, InputBinding]]] = {}
        self._shifts: dict[str, list[ProfileNode]] = {}
        self._nodes: dict[str, ProfileNode] = {}
        self._pressed: dict[str, InputEvent] = {}
        self._shift_keys: set[str] = set()
        self._active_layer = ""
        self._layer_stack: list[str] = []
        self._toggle_contacts: dict[str, bool] = {}
        self._joystick_state: dict[str, set[str]] = {}
        self._aim_active: dict[str, bool] = {}
        self._aim_seed: dict[str, tuple[float, float]] = {}
        self._repeat_state: dict[str, dict] = {}
        self._menu_contact = False
        self._last_release_reason = ""
        if profile is not None:
            self.load_profile(profile)

    # -- perfil --------------------------------------------------------------

    def load_profile(self, profile: ControlProfileV2) -> None:
        issues = validate_profile(profile)
        if has_errors(issues):
            details = "; ".join(
                f"{issue.field}: {issue.message}" for issue in issues if issue.severity == "error"
            )
            raise ProfileRejected("Perfil incompativel; nao foi carregado. " + details)

        if self._has_live_state():
            self.safe_release("PROFILE_CHANGED")
        self.profile = profile
        self.contacts.profile_name = profile.name
        self.cursor = CursorVirtual(profile.cursor_model, profile.screen_contract)
        self._actions = {}
        self._shifts = {}
        self._nodes = {node.id: node for node in profile.nodes}
        for node in profile.nodes:
            if node.type == "layer_shift":
                for role, ref in node.binding_refs.items():
                    binding = profile.bindings.get(ref)
                    if binding is not None:
                        self._shifts.setdefault(binding.identity(), []).append(node)
                continue
            for role, ref in node.binding_refs.items():
                binding = profile.bindings.get(ref)
                if binding is not None:
                    self._actions.setdefault(binding.identity(), []).append((node, role, binding))
        self._active_layer = ""
        self._layer_stack.clear()
        self._toggle_contacts.clear()
        self._joystick_state.clear()
        self._aim_active.clear()
        self._aim_seed.clear()
        self._repeat_state.clear()
        self._pressed.clear()
        self._menu_contact = False
        self._last_release_reason = ""

        if self.state_machine.state in (RuntimeState.STOPPED, RuntimeState.STARTING):
            self.state_machine.transition(RuntimeState.READY, "profile_loaded")
        elif self.state_machine.state == RuntimeState.PROFILE_LOADING:
            self.state_machine.transition(RuntimeState.PROFILE_READY, "profile_loaded")
        elif self.state_machine.state == RuntimeState.PROFILE_READY:
            pass
        else:
            self.state_machine.transition(RuntimeState.PROFILE_LOADING, "profile_changed")
            self.state_machine.transition(RuntimeState.PROFILE_READY, "profile_loaded")

        self.diagnostics.configure(
            provider=self.diagnostics.provider,
            backend=type(self.backend).__name__ if self.backend else "none",
            backend_is_real=bool(getattr(self.backend, "is_real", False)),
            profile_name=profile.name,
        )
        for node in profile.nodes:
            if node.type in ("aim", "mouse_camera") and str(node.parameters.get("activation_mode", "always_on")) == "always_on":
                self._activate_aim(node, None)

    @property
    def active_layer(self) -> str:
        return self._active_layer

    @property
    def aim_active(self) -> bool:
        return any(self._aim_active.values())

    def activate(self) -> None:
        state = self.state_machine.state
        if state in (RuntimeState.READY, RuntimeState.PROFILE_READY, RuntimeState.CAPTURE_ACTIVE):
            if self.profile is None:
                raise ProfileRejected("Nenhum perfil carregado.")
            if state != RuntimeState.CAPTURE_ACTIVE:
                self.state_machine.transition(RuntimeState.CAPTURE_ACTIVE, "capture_requested")

    def enter_menu_touch(self) -> None:
        if self.state_machine.state not in ACTIVE_STATES:
            raise RuntimeError("Menu touch exige captura ativa.")
        if self._aim_active:
            self._deactivate_all_aim("menu_touch")
        self.state_machine.transition(RuntimeState.MENU_TOUCH, "menu_touch_requested")
        self.cursor.set_menu_touch(True)
        self.cursor.set_aim(False)
        self.cursor.set_capture(True)
        self.state_machine.set_virtual_capture(True)
        self._command("mode", mode="menu_touch")

    def exit_menu_touch(self) -> None:
        if self.state_machine.state != RuntimeState.MENU_TOUCH:
            return
        self._release_menu_contact()
        self.cursor.set_menu_touch(False)
        self.cursor.set_capture(False)
        self.state_machine.set_virtual_capture(False)
        self.state_machine.transition(RuntimeState.CAPTURE_ACTIVE, "menu_touch_exit")

    def pause(self) -> None:
        self.safe_release("PAUSE")
        if self.state_machine.state != RuntimeState.PAUSED:
            self.state_machine.transition(RuntimeState.PAUSED, "pause_requested")

    def resume(self) -> None:
        if self.state_machine.state in (RuntimeState.PAUSED, RuntimeState.SAFE_RELEASE, RuntimeState.FOCUS_LOST):
            self.state_machine.transition(RuntimeState.CAPTURE_ACTIVE, "resume_requested")
            self.cursor.set_capture(False)
            self.state_machine.set_virtual_capture(False)

    # -- despacho de eventos -------------------------------------------------

    def handle_event(self, event: InputEvent) -> list[dict]:
        self.diagnostics.record_event(event.event_type)
        if self.profile is None:
            self.diagnostics.drop_event("no_profile")
            return []
        with self.diagnostics.stage("engine"):
            before = len(self.commands)
            self._dispatch(event)
        self._sync_command_counter()
        return self.commands[before:]

    def handle_events(self, events: Iterable[InputEvent]) -> list[dict]:
        produced: list[dict] = []
        for event in events:
            produced.extend(self.handle_event(event))
        return produced

    def tick(self, now: float | None = None) -> list[dict]:
        """Processa repeticoes explicitamente autorizadas, sem timers."""
        current = self.clock() if now is None else float(now)
        before = len(self.commands)
        for node_id, state in list(self._repeat_state.items()):
            if not state.get("active"):
                continue
            interval = float(state.get("interval", 0.0))
            if interval <= 0:
                continue
            emitted = 0
            while current - state["last"] >= interval and emitted < MAX_REPEATS_PER_TICK:
                self._release_contact(node_id, None, None)
                self._press_contact(node_id, None, None, geometry="pos")
                state["last"] += interval
                state["count"] += 1
                emitted += 1
        self._sync_command_counter()
        return self.commands[before:]

    def _dispatch(self, event: InputEvent) -> None:
        state = self.state_machine.state
        if event.event_type == "focus_lost":
            self.safe_release("FOCUS_LOST")
            if state != RuntimeState.FOCUS_LOST:
                self.state_machine.transition(RuntimeState.FOCUS_LOST, "event")
            return
        if event.event_type == "device_disconnected":
            self.safe_release("DEVICE_DISCONNECTED")
            if state != RuntimeState.BACKEND_DISCONNECTED:
                self.state_machine.transition(RuntimeState.BACKEND_DISCONNECTED, "event")
            return
        if event.event_type in ("focus_gained", "device_connected"):
            if state in (RuntimeState.FOCUS_LOST, RuntimeState.BACKEND_DISCONNECTED):
                self.state_machine.transition(RuntimeState.CAPTURE_ACTIVE, "event")
            return
        if state not in ACTIVE_STATES and state not in (RuntimeState.READY, RuntimeState.PROFILE_READY):
            self.diagnostics.drop_event("inactive_state")
            return

        if event.event_type == "key_repeat":
            self.diagnostics.drop_event("key_repeat_ignored")
            return
        if event.event_type in ("key_down", "mouse_down"):
            self._on_press(event)
        elif event.event_type in ("key_up", "mouse_up"):
            self._on_release(event)
        elif event.event_type in ("relative_motion", "mouse_motion"):
            self._on_motion(event)
        elif event.event_type in ("wheel_up", "wheel_down"):
            self._on_wheel(event)
        else:
            self.diagnostics.drop_event("unhandled_event_type")

    def _on_press(self, event: InputEvent) -> None:
        identity = identity_for_event(event)
        shifts = self._shifts.get(identity, ())
        if shifts:
            if identity in self._pressed:
                return
            for node in shifts:
                self._activate_shift(node, event)
            self._pressed[identity] = event
            return

        if identity in self._pressed:
            self.diagnostics.drop_event("duplicate_down")
            return

        if self.state_machine.state == RuntimeState.MENU_TOUCH and event.canonical_name == "MouseLeft":
            self._menu_mouse_action(event)
            return
        actions = self._visible_actions(identity)
        if not actions:
            self.diagnostics.drop_event("unbound_input")
            return
        self._pressed[identity] = event
        for node, role, binding in actions:
            self._dispatch_action(node, role, event, pressing=True)

    def _on_release(self, event: InputEvent) -> None:
        identity = identity_for_event(event)
        self._pressed.pop(identity, None)
        if identity in self._shift_keys:
            self._release_shifts(identity)
        actions = self._visible_actions(identity)
        if not actions and self._menu_contact:
            self._release_menu_contact()
            return
        for node, role, binding in actions:
            self._dispatch_action(node, role, event, pressing=False)

    def _menu_mouse_action(self, event: InputEvent) -> None:
        """Clique esquerdo em menu_touch gera um toque na posicao do cursor virtual."""
        if self.state_machine.state != RuntimeState.MENU_TOUCH:
            return
        x, y = self.cursor.position
        try:
            self.contacts.down(MENU_KEY, x, y, event_id=event.event_id, timestamp=event.timestamp)
        except ContactManagerError as error:
            self.diagnostics.error("menu_contact_failed", type(error).__name__)
            return
        self._menu_contact = True
        self.diagnostics.contacts_down += 1
        self._command("touch_down", node=MENU_KEY, x=x, y=y)

    def _release_menu_contact(self) -> None:
        if not self._menu_contact:
            return
        self.contacts.up(MENU_KEY)
        self._menu_contact = False
        self.diagnostics.contacts_released += 1

    def _visible_actions(self, identity: str) -> list[tuple[ProfileNode, str, InputBinding]]:
        result: list[tuple[ProfileNode, str, InputBinding]] = []
        for node, role, binding in self._actions.get(identity, ()):
            node_layer = node.layer.strip()
            if node_layer and node_layer != self._active_layer:
                continue
            if self._active_layer and not node_layer and self._base_suspended():
                continue
            result.append((node, role, binding))
        return result

    def _base_suspended(self) -> bool:
        if not self.profile or not self._active_layer:
            return False
        for node in self.profile.nodes:
            if node.type == "layer_shift" and str(node.parameters.get("layer_name", "")).strip() == self._active_layer:
                if bool(node.parameters.get("suspend_base", False)):
                    return True
        return False

    # -- camadas -------------------------------------------------------------

    def _activate_shift(self, node: ProfileNode, event: InputEvent) -> None:
        target = str(node.parameters.get("layer_name", "")).strip()
        if not target:
            return
        mode = str(node.parameters.get("mode", "hold"))
        if mode == "toggle":
            if self._active_layer == target:
                self._active_layer = self._layer_stack.pop() if self._layer_stack else ""
            else:
                self._layer_stack.append(self._active_layer)
                self._active_layer = target
        else:
            self._layer_stack.append(self._active_layer)
            self._active_layer = target
        self._shift_keys.add(identity_for_event(event))
        self._command("layer_shift", node=node.id, layer=self._active_layer, mode=mode)

    def _release_shifts(self, identity: str) -> None:
        self._shift_keys.discard(identity)
        for node in self.profile.nodes if self.profile else ():
            if node.type != "layer_shift":
                continue
            shift_identity = None
            for role, ref in node.binding_refs.items():
                binding = self.profile.bindings.get(ref) if self.profile else None
                if binding is not None and binding.identity() == identity:
                    shift_identity = identity
                    break
            if shift_identity and str(node.parameters.get("mode", "hold")) != "toggle":
                self._active_layer = self._layer_stack.pop() if self._layer_stack else ""
                self._command("layer_shift", node=node.id, layer=self._active_layer, mode="restore")

    # -- acoes ---------------------------------------------------------------

    def _dispatch_action(self, node: ProfileNode, role: str, event: InputEvent, *, pressing: bool) -> None:
        kind = node.type
        if kind in ("tap", "hold_tap"):
            if pressing:
                self._press_contact(node.id, node.slot, event, geometry="pos")
            else:
                self._release_contact(node.id, node.slot, event)
        elif kind == "toggle_tap":
            if pressing:
                if self.contacts.has(node.id):
                    self._release_contact(node.id, node.slot, event)
                else:
                    self._press_contact(node.id, node.slot, event, geometry="pos")
        elif kind == "joystick":
            self._joystick(node, role, event, pressing)
        elif kind == "drag":
            if pressing:
                self._press_contact(node.id, node.slot, event, geometry="start")
                end = node.geometry.get("end", {})
                try:
                    self.contacts.move(
                        node.id,
                        float(end.get("x", 0.5)),
                        float(end.get("y", 0.5)),
                        event_id=event.event_id,
                        timestamp=event.timestamp,
                    )
                except ContactManagerError as error:
                    self.error("drag_move_failed", error)
            else:
                self._release_contact(node.id, node.slot, event)
        elif kind in ("aim", "mouse_camera"):
            self._aim_action(node, event, pressing)
        elif kind == "repeat_tap":
            self._repeat_tap(node, event, pressing)
        elif kind == "wheel":
            self.diagnostics.drop_event("wheel_has_no_binding_role")
        elif kind == "macro":
            self.diagnostics.drop_event("macro_runtime_disabled")
        elif kind == "layer_shift":
            pass
        else:
            self.diagnostics.drop_event("unsupported_node_type")

    def _press_contact(self, key: str, slot: int | None, event: InputEvent | None, *, geometry: str) -> None:
        node = self._nodes.get(key)
        pos = (node.geometry.get(geometry) or {}) if node else {}
        x, y = float(pos.get("x", 0.5)), float(pos.get("y", 0.5))
        try:
            self.contacts.down(
                key,
                x,
                y,
                event_id=event.event_id if event else None,
                timestamp=event.timestamp if event else None,
                preferred_slot=slot,
            )
        except ContactManagerError as error:
            self.error("contact_down_failed", error)
            return
        self.diagnostics.contacts_down += 1
        self._command("touch_down", node=key, slot=slot, x=x, y=y)

    def _release_contact(self, key: str, slot: int | None, event: InputEvent | None) -> None:
        contact = self.contacts.get(key)
        if contact is None:
            return
        try:
            self.contacts.up(
                key,
                event_id=event.event_id if event else None,
                timestamp=event.timestamp if event else None,
            )
        except ContactManagerError as error:
            self.error("contact_up_failed", error)
            return
        self.diagnostics.contacts_released += 1
        self._command("touch_up", node=key, slot=contact.slot)

    # -- joystick ------------------------------------------------------------

    def _joystick(self, node: ProfileNode, role: str, event: InputEvent, pressing: bool) -> None:
        state = self._joystick_state.setdefault(node.id, set())
        if pressing:
            state.add(role)
        else:
            state.discard(role)
        if not state:
            self._joystick_state.pop(node.id, None)
            self._release_contact(node.id, node.slot, event)
            return
        x_axis = (1.0 if "right" in state else 0.0) - (1.0 if "left" in state else 0.0)
        y_axis = (1.0 if "down" in state else 0.0) - (1.0 if "up" in state else 0.0)
        deadzone = float(node.parameters.get("deadzone", 0.15))
        if abs(x_axis) < deadzone:
            x_axis = 0.0
        if abs(y_axis) < deadzone:
            y_axis = 0.0
        magnitude = math.hypot(x_axis, y_axis)
        if magnitude > 1e-9:
            x_axis, y_axis = x_axis / magnitude, y_axis / magnitude
        radius = float(node.parameters.get("radius", 0.075))
        center = node.geometry.get("pos", {})
        cx, cy = float(center.get("x", 0.5)), float(center.get("y", 0.5))
        target_x = min(1.0, max(0.0, cx + x_axis * radius))
        target_y = min(1.0, max(0.0, cy + y_axis * radius))
        if not self.contacts.has(node.id):
            self._press_contact(node.id, node.slot, event, geometry="pos")
        try:
            self.contacts.move(
                node.id,
                target_x,
                target_y,
                event_id=event.event_id,
                timestamp=event.timestamp,
            )
        except ContactManagerError as error:
            self.error("joystick_move_failed", error)
            return
        self._command("touch_move", node=node.id, x=target_x, y=target_y, axis=(x_axis, y_axis))

    # -- mira ----------------------------------------------------------------

    def _aim_action(self, node: ProfileNode, event: InputEvent, pressing: bool) -> None:
        mode = str(node.parameters.get("activation_mode", "always_on"))
        if mode == "always_on":
            if pressing:
                self._activate_aim(node, event)
            return
        activation = identity_for_event(event)
        ref = node.binding_refs.get("activation_key", "")
        binding = self.profile.bindings.get(ref) if self.profile else None
        is_activation = bool(binding and binding.identity() == activation)
        if not is_activation:
            return
        if mode == "while_held":
            if pressing:
                self._activate_aim(node, event)
            else:
                self._deactivate_aim(node, "activation_released")
        elif mode == "toggle" and pressing:
            if self._aim_active.get(node.id):
                self._deactivate_aim(node, "toggle")
            else:
                self._activate_aim(node, event)

    def _activate_aim(self, node: ProfileNode, event: InputEvent | None) -> None:
        if self._aim_active.get(node.id):
            return
        anchor = node.geometry.get("anchor", {})
        ax, ay = float(anchor.get("x", 0.5)), float(anchor.get("y", 0.5))
        self.cursor.set_position_normalized(ax, ay)
        self.cursor.set_aim(True)
        self.cursor.set_capture(True)
        self.state_machine.set_virtual_capture(True)
        self._aim_active[node.id] = True
        self._aim_seed[node.id] = self.cursor.position
        try:
            self.contacts.down(
                node.id,
                ax,
                ay,
                event_id=event.event_id if event else None,
                timestamp=event.timestamp if event else None,
                preferred_slot=node.slot,
            )
        except ContactManagerError as error:
            self.error("aim_contact_failed", error)
            return
        self.diagnostics.contacts_down += 1
        if self.state_machine.state in ACTIVE_STATES:
            self.state_machine.transition(RuntimeState.AIM_ACTIVE, "aim_activated")
        self._command("aim_activate", node=node.id, x=ax, y=ay)

    def _deactivate_aim(self, node: ProfileNode, reason: str) -> None:
        if not self._aim_active.pop(node.id, False):
            return
        self._aim_seed.pop(node.id, None)
        contact = self.contacts.get(node.id)
        if contact is not None:
            self.contacts.up(node.id)
            self.diagnostics.contacts_released += 1
        self.cursor.set_aim(False)
        self.cursor.set_capture(False)
        self.state_machine.set_virtual_capture(False)
        if self.state_machine.state == RuntimeState.AIM_ACTIVE:
            self.state_machine.transition(RuntimeState.CAPTURE_ACTIVE, reason)
        self._command("aim_deactivate", node=node.id, reason=reason)

    def _deactivate_all_aim(self, reason: str) -> None:
        for node_id in list(self._aim_active):
            node = self._nodes.get(node_id)
            if node is not None:
                self._deactivate_aim(node, reason)

    def _on_motion(self, event: InputEvent) -> None:
        if self.state_machine.state == RuntimeState.MENU_TOUCH:
            self._move_cursor(event, 1.0)
            return
        if not self._aim_active:
            self.diagnostics.drop_event("motion_without_aim")
            return
        self._move_cursor(event, 1.0)
        for node_id in list(self._aim_active):
            node = self._nodes.get(node_id)
            if node is None:
                continue
            sensitivity = float(node.parameters.get("sensitivity", 1.0))
            seed_x, seed_y = self._aim_seed.get(node_id, (0.5, 0.5))
            cursor_x, cursor_y = self.cursor.position
            reach = float(node.parameters.get("reach", 0.18))
            invert_y = bool(node.parameters.get("invert_y", False))
            anchor = node.geometry.get("anchor", {})
            ax, ay = float(anchor.get("x", 0.5)), float(anchor.get("y", 0.5))
            dx = (cursor_x - seed_x) * reach * 2.0 * sensitivity
            dy = (cursor_y - seed_y) * reach * 2.0 * sensitivity
            if invert_y:
                dy = -dy
            target_x = min(1.0, max(0.0, ax + dx))
            target_y = min(1.0, max(0.0, ay + dy))
            try:
                self.contacts.move(
                    node_id,
                    target_x,
                    target_y,
                    event_id=event.event_id,
                    timestamp=event.timestamp,
                )
            except ContactManagerError as error:
                self.error("aim_move_failed", error)
                continue
            self._command("touch_move", node=node_id, x=target_x, y=target_y, mode="aim")

    def _move_cursor(self, event: InputEvent, factor: float) -> None:
        dx = event.relative_x * factor
        dy = event.relative_y * factor
        if not (math.isfinite(dx) and math.isfinite(dy)):
            self.diagnostics.drop_event("non_finite_motion")
            return
        try:
            self.cursor.apply_relative(
                dx,
                dy,
                unit=event.relative_unit,
            )
        except CursorError as error:
            # Resolucao desconhecida: nunca converter pixels em normalizado.
            self.diagnostics.drop_event("unknown_screen_no_pixel_conversion")
            self.diagnostics.error("cursor", str(error))

    # -- rolagem -------------------------------------------------------------

    def _on_wheel(self, event: InputEvent) -> None:
        nodes = [
            node for node, _role, _binding in self._visible_actions(identity_for_event(event))
            if node.type == "wheel"
        ]
        if not nodes:
            nodes = [node for node in (self.profile.nodes if self.profile else ()) if node.type == "wheel"]
        if not nodes:
            self.diagnostics.drop_event("unbound_wheel")
            return
        for node in nodes:
            is_up = event.event_type == "wheel_up"
            key = f"{node.id}:{'up' if is_up else 'down'}"
            geometry = "up_pos" if is_up else "down_pos"
            slot = node.up_slot if is_up else node.down_slot
            pos = node.geometry.get(geometry, {})
            x, y = float(pos.get("x", 0.5)), float(pos.get("y", 0.5))
            try:
                self.contacts.down(
                    key, x, y, event_id=event.event_id, timestamp=event.timestamp, preferred_slot=slot
                )
                self.contacts.up(key, event_id=event.event_id, timestamp=event.timestamp)
            except ContactManagerError as error:
                self.error("wheel_failed", error)
                continue
            self.diagnostics.contacts_down += 1
            self.diagnostics.contacts_released += 1
            self._command("wheel_tap", node=node.id, direction="up" if is_up else "down", x=x, y=y)

    # -- repeticao explicita -------------------------------------------------

    def _repeat_tap(self, node: ProfileNode, event: InputEvent, pressing: bool) -> None:
        authorized = bool(self.profile and self.profile.metadata.get("allow_auto_repeat") is True)
        enabled = bool(node.parameters.get("auto_repeat") is True)
        if pressing:
            self._press_contact(node.id, node.slot, event, geometry="pos")
            if authorized and enabled:
                interval = int(node.parameters.get("interval_ms", 100)) / 1000.0
                self._repeat_state[node.id] = {
                    "active": True,
                    "last": float(event.timestamp),
                    "interval": interval,
                    "count": 0,
                }
        else:
            self._repeat_state.pop(node.id, None)
            self._release_contact(node.id, node.slot, event)

    # -- seguranca -----------------------------------------------------------

    def error(self, kind: str, error: Exception) -> None:
        self.diagnostics.error(kind, type(error).__name__)
        self.safe_release("EXCEPTION")

    def safe_release(self, reason: str) -> object:
        actions: list[str] = []
        contacts = self.contacts.release_all(reason=reason)
        if contacts:
            actions.append(f"released_contacts:{len(contacts)}")
        if self.backend is not None:
            # Mesmo sem contatos no gerenciador, notificar o backend e obrigatorio.
            self.backend.release_all()
            actions.append("backend_release_all")
        if self._pressed:
            actions.append(f"cleared_keys:{len(self._pressed)}")
        if self._toggle_contacts:
            actions.append(f"cleared_toggles:{len(self._toggle_contacts)}")
        if self._aim_active:
            actions.append(f"cleared_aim:{len(self._aim_active)}")
        if self._joystick_state:
            actions.append(f"cleared_joystick:{len(self._joystick_state)}")
        if self._repeat_state:
            actions.append(f"cleared_repeat:{len(self._repeat_state)}")
        if self._menu_contact:
            actions.append("released_menu_contact")
        self._pressed.clear()
        self._shift_keys.clear()
        self._layer_stack.clear()
        self._active_layer = ""
        self._toggle_contacts.clear()
        self._aim_active.clear()
        self._aim_seed.clear()
        self._joystick_state.clear()
        self._repeat_state.clear()
        self._menu_contact = False
        self.cursor.set_aim(False)
        self.cursor.set_menu_touch(False)
        self.cursor.set_capture(False)
        self.cursor.reset()
        self.state_machine.set_virtual_capture(False)
        self.state_machine.set_physical_capture(False, backend_confirmed=False)
        self.commands.clear()
        actions.extend(["cleared_queue", "reset_cursor", "released_capture"])
        report = self.state_machine.safe_release(reason, actions)
        if self._last_release_reason != reason:
            self.diagnostics.safe_release(reason)
            self._last_release_reason = reason
        self._command("safe_release", reason=reason)
        self._sync_command_counter()
        return report

    def _has_live_state(self) -> bool:
        return bool(
            self.contacts.active_contacts
            or self._pressed
            or self._aim_active
            or self._joystick_state
            or self._toggle_contacts
            or self._menu_contact
        )

    def _sync_command_counter(self) -> None:
        """Conta comandos realmente entregues ao backend, quando observavel."""
        commands = getattr(self.backend, "commands", None)
        if commands is None:
            return
        try:
            self.diagnostics.commands_recorded = len(commands)
        except TypeError:
            pass

    def _command(self, kind: str, **fields) -> dict:
        command = {"kind": kind, "timestamp": self.clock(), **fields}
        if len(self.commands) >= MAX_COMMAND_LOG:
            self.commands.pop(0)
        self.commands.append(command)
        return command


__all__ = ["MappingEngine", "ProfileRejected"]
