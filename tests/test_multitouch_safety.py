"""Regras rigorosas de multitouch e SAFE_RELEASE (sem hardware)."""
import unittest

from linuxdroid.input import (
    ContactManager,
    ContactManagerError,
    EventScript,
    InputRuntime,
    InvalidContact,
    RecordingTouchBackend,
    SlotExhausted,
)
from tests.input_helpers import add_node, make_profile, tap_profile


def multi_profile(count: int):
    profile = make_profile()
    for index in range(count):
        add_node(
            profile,
            node_id=f"t{index}",
            node_type="tap",
            slot=index,
            keys={"key": chr(ord("A") + index)},
            geometry={"pos": {"x": 0.1 + index * 0.05, "y": 0.5}},
        )
    return profile


class ContactManagerTests(unittest.TestCase):
    def setUp(self):
        self.backend = RecordingTouchBackend(clock=lambda: 1.0, max_touches=10)
        self.manager = ContactManager(self.backend, clock=lambda: 1.0)

    def test_slots_are_allocated_from_zero_and_ids_stable(self):
        first = self.manager.down("a", 0.2, 0.3)
        second = self.manager.down("b", 0.4, 0.5)
        self.assertEqual((first.slot, second.slot), (0, 1))
        self.assertEqual((first.contact_id, second.contact_id), (1, 2))
        moved = self.manager.move("a", 0.6, 0.7)
        self.assertEqual(moved.contact_id, first.contact_id)
        self.assertEqual(moved.slot, first.slot)

    def test_down_before_move_and_single_up(self):
        with self.assertRaises(InvalidContact):
            self.manager.move("a", 0.5, 0.5)
        self.manager.down("a", 0.2, 0.2)
        self.manager.up("a")
        self.assertEqual(self.manager.stats["move_without_down"], 1)
        self.assertIsNone(self.manager.up("a"))
        self.assertEqual(self.manager.stats["duplicate_up_ignored"], 1)
        with self.assertRaises(InvalidContact):
            self.manager.move("a", 0.3, 0.3)
        self.assertEqual(self.backend.actions(), ("down", "up"))

    def test_duplicate_down_is_idempotent(self):
        first = self.manager.down("a", 0.2, 0.2)
        second = self.manager.down("a", 0.9, 0.9)
        self.assertIs(first, second)
        self.assertEqual(self.backend.actions(), ("down",))
        self.assertEqual(self.manager.stats["duplicate_down_ignored"], 1)

    def test_reserved_slot_and_preferred_slot(self):
        with self.assertRaises(SlotExhausted):
            self.manager.down("bad", 0.5, 0.5, preferred_slot=255)
        contact = self.manager.down("ok", 0.5, 0.5, preferred_slot=7)
        self.assertEqual(contact.slot, 7)
        self.assertEqual(self.backend.active_slots, (7,))

    def test_phantom_limit_is_ten(self):
        for index in range(10):
            self.manager.down(f"c{index}", 0.1, 0.1)
        with self.assertRaises(SlotExhausted):
            self.manager.down("overflow", 0.1, 0.1)
        self.assertEqual(len(self.manager.active_contacts), 10)
        self.assertEqual(len(self.backend.active_slots), 10)

    def test_positions_must_be_normalized(self):
        for x, y in ((-0.1, 0.5), (1.1, 0.5), (float("nan"), 0.5), ("x", 0.5)):
            with self.assertRaises(ContactManagerError):
                self.manager.down("bad", x, y)

    def test_exception_on_up_does_not_leave_contact_stuck(self):
        self.manager.down("a", 0.2, 0.2)
        self.backend.set_failure("up")
        with self.assertRaises(Exception):
            self.manager.up("a")
        self.assertEqual(self.manager.active_contacts, ())
        self.assertEqual(self.backend.active_slots, ())
        self.assertEqual(self.manager.stats["exceptions_recovered"], 1)

    def test_exception_on_move_releases_everything(self):
        self.manager.down("a", 0.2, 0.2)
        self.manager.down("b", 0.3, 0.3)
        self.backend.set_failure("move")
        with self.assertRaises(Exception):
            self.manager.move("a", 0.4, 0.4)
        self.assertEqual(self.manager.active_contacts, ())
        self.assertEqual(self.backend.active_slots, ())
        self.assertEqual(self.manager.stats["exceptions_recovered"], 1)

    def test_no_move_after_up_in_recorded_stream(self):
        self.manager.down("a", 0.2, 0.2)
        self.manager.move("a", 0.3, 0.3)
        self.manager.up("a")
        actions = self.backend.actions()
        self.assertEqual(actions[:3], ("down", "move", "up"))
        self.assertNotIn("move", actions[3:])


class EngineSafetyTests(unittest.TestCase):
    def test_focus_loss_releases_all_and_clears_queue(self):
        runtime = InputRuntime()
        runtime.start()
        runtime.load_profile(multi_profile(3))
        runtime.activate()
        runtime.run_script(EventScript().key_down("A").key_down("B").key_down("C"))
        self.assertEqual(len(runtime.engine.contacts.active_contacts), 3)
        runtime.run_script(EventScript().focus_loss())
        self.assertEqual(runtime.engine.contacts.active_contacts, ())
        self.assertEqual(runtime.backend.active_slots, ())
        self.assertEqual(runtime.state.value, "FOCUS_LOST")
        self.assertEqual(runtime.engine.cursor.captured, False)
        self.assertEqual(runtime.engine.state_machine.snapshot()["virtual_capture_state"], "released")
        self.assertEqual(runtime.engine.state_machine.snapshot()["physical_pointer_capture_state"], "released")

    def test_backend_disconnect_releases_all(self):
        runtime = InputRuntime()
        runtime.start()
        runtime.load_profile(tap_profile())
        runtime.activate()
        runtime.provider.key_down("W")
        runtime.pump()
        self.assertEqual(runtime.backend.active_slots, (0,))
        runtime.provider.device_disconnected()
        runtime.pump()
        self.assertEqual(runtime.backend.active_slots, ())
        self.assertEqual(runtime.state.value, "BACKEND_DISCONNECTED")
        self.assertIn("DEVICE_DISCONNECTED", runtime.snapshot()["safe_release_reasons"])

    def test_safe_release_is_idempotent(self):
        runtime = InputRuntime()
        runtime.start()
        runtime.load_profile(tap_profile())
        runtime.activate()
        runtime.provider.key_down("W")
        runtime.pump()
        first = runtime.safe_release("MANUAL")
        second = runtime.safe_release("MANUAL")
        self.assertFalse(first.idempotent)
        self.assertTrue(second.idempotent)
        self.assertEqual(first.state_after, "SAFE_RELEASE")
        self.assertEqual(second.state_after, "SAFE_RELEASE")
        self.assertEqual(runtime.snapshot()["safe_release_reasons"], ["MANUAL"])

    def test_exception_in_backend_triggers_safe_release(self):
        runtime = InputRuntime()
        runtime.start()
        runtime.load_profile(tap_profile())
        runtime.activate()
        runtime.backend.set_failure("down")
        runtime.run_script(EventScript().key_down("W"))
        snapshot = runtime.snapshot()
        self.assertEqual(snapshot["state_machine"]["state"], "SAFE_RELEASE")
        self.assertIn("EXCEPTION", snapshot["safe_release_reasons"])
        self.assertEqual(runtime.backend.active_slots, ())

    def test_shutdown_leaves_clean_state(self):
        runtime = InputRuntime()
        runtime.start()
        runtime.load_profile(tap_profile())
        runtime.activate()
        runtime.provider.key_down("W")
        runtime.pump()
        runtime.shutdown()
        self.assertEqual(runtime.state.value, "STOPPED")
        self.assertEqual(runtime.engine.contacts.active_contacts, ())
        self.assertEqual(runtime.backend.active_slots, ())
        self.assertFalse(runtime.provider.running)


if __name__ == "__main__":
    unittest.main()
