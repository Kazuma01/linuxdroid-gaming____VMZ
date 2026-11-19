"""Provider simulado, backend de gravacao e adaptador Phantom (sem execucao)."""
import unittest

from linuxdroid.services.capabilities import Capability, Support
from linuxdroid.input import (
    EventScript,
    InputRuntime,
    RecordingTouchBackend,
    SimulatedInputProvider,
)
from linuxdroid.input.backends import (
    BackendDisconnected,
    PhantomAdapter,
    RecordingBackendError,
    TouchCommand,
)
from linuxdroid.input.providers import ProviderError
from tests.input_helpers import tap_profile


class SimulatedProviderTests(unittest.TestCase):
    def test_deterministic_ids_and_timestamps(self):
        provider = SimulatedInputProvider(clock=lambda: 50.0)
        script = EventScript().key_down("W").key_up("W")
        events = provider.emit_script(script, start=1000.0, step=0.01)
        self.assertEqual([e.event_id for e in events], [1, 2])
        self.assertEqual([e.timestamp for e in events], [1000.0, 1000.01])
        self.assertEqual([e.event_type for e in events], ["key_down", "key_up"])
        self.assertEqual([e.source for e in events], ["simulated", "simulated"])

    def test_drain_does_not_coalesce_down_and_up(self):
        provider = SimulatedInputProvider(clock=lambda: 1.0)
        provider.left_click(timestamp=1.0)
        self.assertEqual(len(provider), 2)
        self.assertEqual([e.event_type for e in provider.drain()], ["mouse_down", "mouse_up"])
        self.assertEqual(len(provider), 0)

    def test_queue_limit(self):
        provider = SimulatedInputProvider(clock=lambda: 1.0, max_queue=1)
        provider.key_down("W")
        with self.assertRaises(ProviderError):
            provider.key_down("W")

    def test_describe_says_simulated(self):
        description = SimulatedInputProvider().describe()
        self.assertIsInstance(description, Capability)
        self.assertEqual(description.support, Support.SUPPORTED)
        self.assertIn("simul", description.detail.lower())


class RecordingBackendTests(unittest.TestCase):
    def setUp(self):
        self.backend = RecordingTouchBackend(clock=lambda: 10.0, max_touches=3)

    def test_down_move_up_sequence(self):
        self.backend.down(0.2, 0.3, 0)
        self.backend.move(0.4, 0.5, 0)
        self.backend.up(0)
        self.assertEqual(self.backend.actions(), ("down", "move", "up"))
        self.assertEqual(self.backend.active_slots, ())
        self.assertEqual([c.sequence for c in self.backend.commands], [1, 2, 3])
        self.assertTrue(all(isinstance(c, TouchCommand) for c in self.backend.commands))

    def test_move_without_down_and_up_without_down(self):
        with self.assertRaises(RecordingBackendError):
            self.backend.move(0.5, 0.5, 0)
        with self.assertRaises(RecordingBackendError):
            self.backend.up(0)

    def test_reserved_and_invalid_slots(self):
        with self.assertRaises(RecordingBackendError):
            self.backend.down(0.5, 0.5, 255)
        with self.assertRaises(RecordingBackendError):
            self.backend.down(0.5, 0.5, -1)

    def test_max_touches(self):
        for slot in range(3):
            self.backend.down(0.1, 0.1, slot)
        with self.assertRaises(RecordingBackendError):
            self.backend.down(0.1, 0.1, 3)

    def test_cancel_and_release_all(self):
        self.backend.down(0.1, 0.1, 0)
        self.backend.down(0.2, 0.2, 1)
        self.assertEqual(len(self.backend.release_all()), 2)
        self.assertEqual(self.backend.active_slots, ())
        self.assertEqual(self.backend.actions(), ("down", "down", "cancel", "cancel"))

    def test_disconnect_blocks_commands(self):
        self.backend.disconnect()
        with self.assertRaises(BackendDisconnected):
            self.backend.down(0.1, 0.1, 0)

    def test_failure_injection(self):
        self.backend.set_failure("move")
        self.backend.down(0.1, 0.1, 0)
        with self.assertRaises(RecordingBackendError):
            self.backend.move(0.2, 0.2, 0)

    def test_describe_does_not_claim_injection(self):
        description = self.backend.describe()
        self.assertIn("NENHUMA injecao", description.detail)
        self.assertFalse(RecordingTouchBackend.is_real)


class PhantomAdapterTests(unittest.TestCase):
    def test_no_command_without_runner(self):
        adapter = PhantomAdapter(tools={"phantom": "/usr/bin/phantom"}, available=True)
        with self.assertRaises(RuntimeError):
            adapter.status()
        self.assertEqual(adapter.executed, [])

    def test_no_command_when_unavailable(self):
        adapter = PhantomAdapter(tools={"phantom": ""}, runner=lambda args: object())
        with self.assertRaises(RuntimeError):
            adapter.enter_capture()
        self.assertEqual(adapter.executed, [])

    def test_explicit_runner_is_recorded(self):
        executed = []
        adapter = PhantomAdapter(
            tools={"phantom": "/usr/bin/phantom"},
            runner=lambda args: executed.append(args) or "ok",
        )
        self.assertEqual(adapter.status(), "ok")
        self.assertEqual(adapter.executed, [["status"]])
        self.assertEqual(executed, [["status"]])

    def test_readiness_never_claims_operational(self):
        adapter = PhantomAdapter(tools={"phantom": "/usr/bin/phantom"}, runner=lambda args: "ok")
        readiness = adapter.readiness()
        self.assertTrue(readiness["detected"])
        self.assertFalse(readiness["functional"])
        self.assertFalse(readiness["tested"])
        self.assertFalse(readiness["operational"])

    def test_command_allowlist(self):
        adapter = PhantomAdapter(
            tools={"phantom": "/usr/bin/phantom"},
            runner=lambda args: "ok",
        )
        with self.assertRaises(RuntimeError):
            adapter._run(["rm", "-rf", "/"])
        self.assertEqual(adapter.executed, [])


class RuntimeRecordingTests(unittest.TestCase):
    def test_runtime_uses_recording_backend_by_default(self):
        runtime = InputRuntime()
        runtime.start()
        runtime.load_profile(tap_profile())
        runtime.activate()
        runtime.run_script(EventScript().tap("W"), start=1.0)
        snapshot = runtime.snapshot()
        self.assertEqual(snapshot["mode"], "recording_backend")
        self.assertFalse(snapshot["backend_is_real"])
        self.assertFalse(snapshot["injection_claimed"])
        self.assertEqual([c.action for c in runtime.backend.commands], ["down", "up"])


if __name__ == "__main__":
    unittest.main()
