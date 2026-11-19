"""Evento normalizado, proveniencia e conversoes explicitas."""
import unittest

from linuxdroid.controls.keys import (
    EVDEV_CODE_BY_CANONICAL,
    InputBinding,
    canonical_for_code,
)
from linuxdroid.input import (
    InputEvent,
    NormalizationError,
    Normalizer,
    identity_for_event,
    is_button_event,
    is_key_event,
    is_motion_event,
    is_wheel_event,
)
from linuxdroid.input.qt_bridge import (
    binding_from_qt_key,
    binding_from_qt_mouse,
    canonical_for_qt_key,
)


class InputEventTests(unittest.TestCase):
    def test_flags_are_derived_and_exclusive(self):
        down = InputEvent(event_id=1, timestamp=1.0, event_type="key_down", pressed=True, released=True)
        self.assertTrue(down.pressed)
        self.assertFalse(down.released)
        self.assertEqual(down.lifetime, "down")

        up = InputEvent(event_id=2, timestamp=1.1, event_type="key_up", pressed=True)
        self.assertTrue(up.released)
        self.assertFalse(up.pressed)
        self.assertEqual(up.lifetime, "up")

    def test_invalid_events_are_rejected(self):
        with self.assertRaises(ValueError):
            InputEvent(event_id=0, timestamp=1.0, event_type="key_down")
        with self.assertRaises(ValueError):
            InputEvent(event_id=1, timestamp=float("nan"), event_type="key_down")
        with self.assertRaises(ValueError):
            InputEvent(event_id=1, timestamp=1.0, event_type="unknown")
        with self.assertRaises(ValueError):
            InputEvent(event_id=1, timestamp=1.0, event_type="key_down", provenance="captured")

    def test_focus_and_wheel_defaults(self):
        gain = InputEvent(event_id=1, timestamp=1.0, event_type="focus_gained")
        loss = InputEvent(event_id=2, timestamp=1.0, event_type="focus_lost")
        wheel = InputEvent(event_id=3, timestamp=1.0, event_type="wheel_down")
        self.assertTrue(gain.focus)
        self.assertFalse(loss.focus)
        self.assertEqual(wheel.wheel_direction, -1)

    def test_predicates(self):
        key = InputEvent(event_id=1, timestamp=1.0, event_type="key_down")
        button = InputEvent(event_id=2, timestamp=1.0, event_type="mouse_down")
        motion = InputEvent(event_id=3, timestamp=1.0, event_type="relative_motion")
        wheel = InputEvent(event_id=4, timestamp=1.0, event_type="wheel_up")
        self.assertTrue(is_key_event(key))
        self.assertTrue(is_button_event(button))
        self.assertTrue(is_motion_event(motion))
        self.assertTrue(is_wheel_event(wheel))
        self.assertFalse(is_key_event(button))

    def test_identity_includes_modifiers_and_never_promotes_provenance(self):
        event = InputEvent(
            event_id=1,
            timestamp=1.0,
            event_type="key_down",
            canonical_name="W",
            modifiers=("LeftCtrl",),
            provenance="unverified",
        )
        identity = identity_for_event(event)
        self.assertIn("W", identity)
        self.assertIn("LeftCtrl", identity)
        plain = identity_for_event(
            InputEvent(event_id=2, timestamp=1.0, event_type="key_down", canonical_name="W")
        )
        self.assertNotEqual(identity, plain)

    def test_raw_is_immutable_mapping(self):
        event = InputEvent(event_id=1, timestamp=1.0, event_type="key_down", raw={"a": 1})
        with self.assertRaises(TypeError):
            event.raw["a"] = 2  # type: ignore[index]


class NormalizerTests(unittest.TestCase):
    def setUp(self):
        self.normalizer = Normalizer()

    def test_alias_and_evdev_code_are_explicit(self):
        event = self.normalizer.normalize({
            "event_id": 1,
            "timestamp": 10.0,
            "type": "press",
            "canonical": "ctrl",
            "code": 29,
            "code_space": "evdev",
            "source": "unit-test",
        })
        self.assertEqual(event.event_type, "key_down")
        self.assertEqual(event.canonical_name, "LeftCtrl")
        self.assertEqual(event.namespace, "keyboard")
        self.assertEqual(event.code_space, "evdev")
        self.assertEqual(event.provenance, "validated_by_vocabulary")

    def test_evdev_code_resolves_to_canonical_name(self):
        event = self.normalizer.normalize({
            "event_id": 1,
            "timestamp": 1.0,
            "type": "key_down",
            "code": EVDEV_CODE_BY_CANONICAL["W"],
            "code_space": "evdev",
        })
        self.assertEqual(event.canonical_name, "W")

    def test_qt_code_is_never_converted_to_evdev(self):
        event = self.normalizer.normalize({
            "event_id": 1,
            "timestamp": 1.0,
            "type": "key_down",
            "code": 17,
            "code_space": "qt_native_scan_code",
            "canonical_name": "W",
        })
        self.assertEqual(event.code_space, "qt_native_scan_code")
        self.assertEqual(event.canonical_name, "W")
        self.assertIsNone(canonical_for_code(17, "qt_native_scan_code"))

    def test_declared_capture_provenance_is_preserved(self):
        event = self.normalizer.normalize({
            "event_id": 1,
            "timestamp": 1.0,
            "type": "key_down",
            "canonical_name": "W",
            "provenance": "captured_from_device",
            "source": "physical-backend",
        })
        self.assertEqual(event.provenance, "captured_from_device")

    def test_unknown_type_and_provenance_fail(self):
        with self.assertRaises(NormalizationError):
            self.normalizer.normalize({"event_id": 1, "timestamp": 1.0, "type": "teleport"})
        with self.assertRaises(NormalizationError):
            self.normalizer.normalize({
                "event_id": 1, "timestamp": 1.0, "type": "key_down",
                "provenance": "trust-me",
            })

    def test_existing_event_is_returned_unchanged(self):
        event = InputEvent(event_id=1, timestamp=1.0, event_type="key_down")
        self.assertIs(self.normalizer.normalize(event), event)


class QtBridgeTests(unittest.TestCase):
    def test_key_identity_without_event_text(self):
        binding = binding_from_qt_key(0x57, native_scan_code=0x11, native_virtual_key=0x57)
        self.assertEqual(binding.canonical_name, "W")
        self.assertEqual(binding.code_space, "qt_native_scan_code")
        self.assertEqual(binding.code, 0x11)
        self.assertEqual(binding.provenance, "validated_by_vocabulary")
        self.assertIn("nao convertido", binding.notes.lower())

    def test_native_virtual_key_disambiguates_modifier(self):
        self.assertEqual(canonical_for_qt_key(0x01000020, 0xA1), "RightShift")
        binding = binding_from_qt_key(0x01000020, native_virtual_key=0xA1)
        self.assertEqual(binding.canonical_name, "RightShift")

    def test_special_unknown_is_not_invented(self):
        binding = binding_from_qt_key(0xDEAD)
        self.assertEqual(binding.canonical_name, "")
        self.assertEqual(binding.provenance, "unverified")
        self.assertEqual(binding.validation, "unverified")

    def test_mouse_button(self):
        binding = binding_from_qt_mouse(2)
        self.assertEqual(binding.canonical_name, "MouseRight")
        self.assertEqual(binding.namespace, "mouse")


class ProvenanceTests(unittest.TestCase):
    def test_canonical_name_is_not_capture(self):
        binding = InputBinding.from_canonical("W", capture_source="vocabulary")
        self.assertEqual(binding.provenance, "validated_by_vocabulary")
        self.assertFalse(binding.is_physically_captured())

    def test_explicit_backend_provenance(self):
        binding = InputBinding.from_canonical(
            "W", capture_source="physical", provenance="captured_from_device"
        )
        self.assertTrue(binding.is_physically_captured())

    def test_legacy_text_keeps_unverified(self):
        binding = InputBinding.from_legacy_text("W")
        self.assertEqual(binding.canonical_name, "W")
        self.assertEqual(binding.provenance, "unverified")
        self.assertEqual(binding.validation, "unverified")
        self.assertFalse(binding.is_physically_captured())

    def test_roundtrip_preserves_provenance(self):
        binding = InputBinding.from_canonical(
            "W", capture_source="backend", provenance="validated_by_backend"
        )
        self.assertEqual(InputBinding.from_dict(binding.to_dict()).provenance, "validated_by_backend")


if __name__ == "__main__":
    unittest.main()
