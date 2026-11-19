"""Prontidao de backend, capacidades e diagnostico honesto."""
import unittest

from linuxdroid.input import Diagnostics, InputRuntime
from linuxdroid.services import capabilities as cap
from tests.input_helpers import tap_profile


def snapshot(**overrides):
    data = dict(
        distro="Distro Teste",
        kernel="6.0-test",
        arch="any-arch",
        session_type="wayland",
        compositor="compositor-teste",
        wayland_display="wayland-9",
        cpu_model="CPU Generica",
        cpu_count=4,
        memory_kib=8 * 1024 * 1024,
        gpus=[cap.GpuInfo(vendor="Fabricante", driver="driver")],
        input_devices=["/dev/input/event0"],
        input_readable=True,
        uinput_available=True,
        tools={"waydroid": "/usr/bin/waydroid", "adb": "/usr/bin/adb"},
        waydroid_version="1.6.3",
        protocols=["zwp_relative_pointer_manager_v1"],
    )
    data.update(overrides)
    return cap.CapabilitySnapshot(**data)


class BackendReadinessTests(unittest.TestCase):
    def test_missing_phantom_is_unsupported(self):
        readiness = cap.assess_backend("phantom", snapshot())
        self.assertEqual(readiness.stage, cap.BackendStage.UNSUPPORTED)
        self.assertFalse(readiness.operational)

    def test_detected_phantom_is_only_available(self):
        snap = snapshot(tools={"phantom": "/usr/bin/phantom"})
        readiness = cap.assess_backend("phantom", snap)
        self.assertEqual(readiness.stage, cap.BackendStage.AVAILABLE)
        self.assertTrue(readiness.detected)
        self.assertFalse(readiness.tested)
        self.assertFalse(readiness.functional)
        self.assertFalse(readiness.operational)

    def test_tested_is_not_operational_without_explicit_flag(self):
        snap = snapshot(tools={"phantom": "/usr/bin/phantom"})
        readiness = cap.assess_backend("phantom", snap, tested=True)
        self.assertEqual(readiness.stage, cap.BackendStage.TESTED)
        self.assertTrue(readiness.tested)
        self.assertFalse(readiness.operational)

    def test_native_detection_never_implies_functional(self):
        readiness = cap.assess_backend("native", snapshot())
        self.assertIn(readiness.stage, (cap.BackendStage.AVAILABLE, cap.BackendStage.TESTED))
        self.assertFalse(readiness.functional)
        self.assertFalse(readiness.operational)

    def test_detailed_decision_message_states_no_real_input_was_tested(self):
        decision = cap.select_backend_detailed(snapshot())
        self.assertEqual(decision.choice.name, "native")
        self.assertIn("NAO foram testadas", decision.message)
        self.assertFalse(decision.readiness.operational)
        self.assertIn("stage", decision.to_dict()["readiness"])

    def test_unsupported_decision_is_explicit(self):
        decision = cap.select_backend_detailed(
            snapshot(input_devices=[], input_readable=False, uinput_available=False,
                     tools={}, protocols=[])
        )
        self.assertEqual(decision.choice.name, "unsupported")
        self.assertEqual(decision.readiness.stage, cap.BackendStage.UNSUPPORTED)


class DiagnosticsTests(unittest.TestCase):
    def test_simulation_mode_is_labelled(self):
        diag = Diagnostics()
        snap = diag.snapshot()
        self.assertEqual(snap["mode"], "simulation")
        self.assertIn("SIMULACAO", snap["mode_label"])
        self.assertFalse(snap["injection_claimed"])

    def test_recording_backend_does_not_claim_injection(self):
        runtime = InputRuntime()
        runtime.start()
        runtime.load_profile(tap_profile())
        runtime.activate()
        runtime.run_script(__import__(
            "linuxdroid.input", fromlist=["EventScript"]
        ).EventScript().tap("W"))
        snap = runtime.snapshot()
        self.assertEqual(snap["mode"], "recording_backend")
        self.assertIn("nada injetado", snap["mode_label"])
        self.assertFalse(snap["injection_claimed"])
        self.assertGreater(snap["commands_recorded"], 0)

    def test_errors_do_not_store_typed_text(self):
        diag = Diagnostics(clock=lambda: 1.0)
        diag.error("invalid_binding", "digitei-secret")
        detail = diag.snapshot()["errors"][0]
        self.assertEqual(detail["type"], "invalid_binding")
        self.assertNotIn("digitei-secret", detail["detail"])
        self.assertEqual(detail["detail"], "")

    def test_stage_timings_and_event_counts(self):
        diag = Diagnostics(clock=lambda: 1.0)
        diag.record_event("key_down")
        with diag.stage("engine"):
            pass
        snap = diag.snapshot()
        self.assertEqual(snap["events_received"], 1)
        self.assertEqual(snap["event_types"], {"key_down": 1})
        self.assertEqual(snap["stage_timings_ms"]["engine"]["samples"], 1)

    def test_unknown_mode_rejected(self):
        with self.assertRaises(ValueError):
            Diagnostics(mode="magic")


if __name__ == "__main__":
    unittest.main()
