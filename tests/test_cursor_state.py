"""Cursor virtual, maquina de estados e distincao de captura virtual/fisica."""
import unittest

from linuxdroid.controls.cursor import CursorVirtual
from linuxdroid.controls.model import CursorModelConfig, ScreenContract
from linuxdroid.input import (
    CaptureStateMachine,
    EventScript,
    InputRuntime,
    InvalidTransition,
    RuntimeState,
)
from tests.input_helpers import add_node, make_profile


class CaptureStateMachineTests(unittest.TestCase):
    def test_all_required_states_exist(self):
        expected = {
            "STOPPED", "STARTING", "READY", "PROFILE_LOADING", "PROFILE_READY",
            "CAPTURE_ACTIVE", "MENU_TOUCH", "AIM_ACTIVE", "PAUSED", "FOCUS_LOST",
            "SAFE_RELEASE", "BACKEND_DISCONNECTED", "ERROR", "STOPPING",
        }
        self.assertEqual({state.value for state in RuntimeState}, expected)

    def test_nominal_and_invalid_transitions(self):
        machine = CaptureStateMachine(clock=lambda: 1.0)
        self.assertEqual(machine.state, RuntimeState.STOPPED)
        machine.transition(RuntimeState.STARTING)
        machine.transition(RuntimeState.READY)
        machine.transition(RuntimeState.PROFILE_LOADING)
        machine.transition(RuntimeState.PROFILE_READY)
        machine.transition(RuntimeState.CAPTURE_ACTIVE)
        with self.assertRaises(InvalidTransition):
            machine.transition(RuntimeState.STOPPED)

    def test_priority_transitions_from_any_active_state(self):
        for state in (RuntimeState.CAPTURE_ACTIVE, RuntimeState.MENU_TOUCH, RuntimeState.AIM_ACTIVE):
            machine = CaptureStateMachine(clock=lambda: 1.0)
            machine.transition(RuntimeState.STARTING)
            machine.transition(RuntimeState.READY)
            if state != RuntimeState.CAPTURE_ACTIVE:
                machine.transition(RuntimeState.CAPTURE_ACTIVE)
                machine.transition(state)
            else:
                machine.transition(state)
            machine.transition(RuntimeState.SAFE_RELEASE, "teste")
            self.assertEqual(machine.state, RuntimeState.SAFE_RELEASE)

    def test_virtual_and_physical_capture_are_different(self):
        machine = CaptureStateMachine(clock=lambda: 1.0)
        machine.set_virtual_capture(True)
        machine.set_physical_capture(True, backend_confirmed=False)
        snapshot = machine.snapshot()
        self.assertEqual(snapshot["virtual_capture_state"], "captured")
        self.assertEqual(snapshot["physical_pointer_capture_state"], "unknown")

        machine.set_physical_capture(True, backend_confirmed=True)
        self.assertEqual(machine.snapshot()["physical_pointer_capture_state"], "captured")

    def test_safe_release_priority_and_idempotence(self):
        machine = CaptureStateMachine(clock=lambda: 1.0)
        machine.transition(RuntimeState.STARTING)
        machine.transition(RuntimeState.READY)
        machine.set_virtual_capture(True)
        machine.set_physical_capture(True, backend_confirmed=True)
        first = machine.safe_release("TESTE", ["unpause"])
        second = machine.safe_release("TESTE", ["unpause"])
        self.assertFalse(first.idempotent)
        self.assertTrue(second.idempotent)
        self.assertEqual(first.actions, ["unpause"])
        self.assertEqual(len(machine.history), 3)
        self.assertEqual(machine.snapshot()["virtual_capture_state"], "released")
        self.assertEqual(machine.snapshot()["physical_pointer_capture_state"], "released")

    def test_pause_after_safe_release_is_allowed(self):
        machine = CaptureStateMachine(clock=lambda: 1.0)
        machine.transition(RuntimeState.STARTING)
        machine.transition(RuntimeState.READY)
        machine.safe_release("PAUSE")
        machine.transition(RuntimeState.PAUSED)
        self.assertEqual(machine.state, RuntimeState.PAUSED)


class CursorTests(unittest.TestCase):
    def test_virtual_cursor_is_not_compositor_pointer(self):
        cursor = CursorVirtual(CursorModelConfig(), ScreenContract(1920, 1080, "measured"))
        cursor.set_capture(True)
        self.assertTrue(cursor.captured)
        self.assertEqual(cursor.config.capture_state, "captured")
        cursor.set_aim(True)
        cursor.set_menu_touch(True)
        self.assertTrue(cursor.aim_active)
        self.assertTrue(cursor.menu_touch_active)
        cursor.reset()
        self.assertFalse(cursor.captured)
        self.assertFalse(cursor.aim_active)
        self.assertFalse(cursor.menu_touch_active)

    def test_pixels_require_known_screen(self):
        cursor = CursorVirtual(CursorModelConfig(), ScreenContract(None, None, "unknown"))
        with self.assertRaises(ValueError):
            cursor.apply_relative(10, 10, unit="pixels")
        cursor.apply_relative(0.1, -0.1, unit="normalized")
        self.assertAlmostEqual(cursor.position[0], 0.6)
        self.assertAlmostEqual(cursor.position[1], 0.4)

    def test_engine_menu_touch_uses_virtual_cursor(self):
        profile = make_profile()
        add_node(profile, node_id="tap", node_type="tap", keys={"key": "W"},
                 geometry={"pos": {"x": 0.25, "y": 0.75}})
        runtime = InputRuntime()
        runtime.start()
        runtime.load_profile(profile)
        runtime.activate()
        runtime.engine.enter_menu_touch()
        self.assertEqual(runtime.state.value, "MENU_TOUCH")
        self.assertTrue(runtime.cursor.menu_touch_active)
        self.assertEqual(
            runtime.engine.state_machine.snapshot()["virtual_capture_state"], "captured"
        )
        runtime.provider.mouse_down("MouseLeft")
        runtime.provider.mouse_up("MouseLeft")
        runtime.pump()
        self.assertEqual(runtime.backend.actions(), ("down", "up"))
        runtime.engine.exit_menu_touch()
        self.assertEqual(runtime.state.value, "CAPTURE_ACTIVE")
        self.assertFalse(runtime.cursor.menu_touch_active)

    def test_safe_release_resets_cursor_and_capture(self):
        runtime = InputRuntime()
        runtime.start()
        runtime.load_profile(make_profile())
        runtime.activate()
        runtime.engine.enter_menu_touch()
        runtime.cursor.apply_relative(0.2, 0.2, unit="normalized")
        runtime.safe_release("TESTE")
        self.assertFalse(runtime.cursor.captured)
        self.assertFalse(runtime.cursor.menu_touch_active)
        self.assertEqual(runtime.cursor.position, (0.5, 0.5))
        self.assertEqual(
            runtime.engine.state_machine.snapshot()["virtual_capture_state"], "released"
        )

    def test_focus_event_transitions_state(self):
        runtime = InputRuntime()
        runtime.start()
        runtime.load_profile(make_profile())
        runtime.activate()
        runtime.run_script(EventScript().focus_loss())
        self.assertEqual(runtime.state.value, "FOCUS_LOST")
        runtime.run_script(EventScript().focus_gain())
        self.assertEqual(runtime.state.value, "CAPTURE_ACTIVE")


if __name__ == "__main__":
    unittest.main()
