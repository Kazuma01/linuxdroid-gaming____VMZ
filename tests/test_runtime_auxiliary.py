"""Operações auxiliares no RuntimeManager — backend falso e runner injetado."""
import tempfile
import threading
import unittest
from pathlib import Path

from linuxdroid.models import CommandResult
from linuxdroid.runtime import (
    CORE_FEATURES,
    FakeRuntimeBackend,
    RuntimeCapabilities,
    RuntimeErrorCode,
    RuntimeEventType,
    RuntimeFeature,
    RuntimeFailureError,
    RuntimeManager,
    RuntimeOperation,
    RuntimeState,
    WaydroidRuntimeBackend,
)


class ScriptedRunner:
    """Runner que responde por comando, sem tocar no host."""

    def __init__(self, responses=None):
        self.responses = responses or {}
        self.calls = []

    def run(self, program, args, *, timeout=None):
        args = tuple(str(a) for a in args)
        self.calls.append((program, args, timeout))
        text = self.responses.get(args, "")
        return CommandResult(program, list(args), exit_code=0, stdout=text)


class AuxiliaryManagerTests(unittest.TestCase):
    def make(self, **kwargs):
        backend = FakeRuntimeBackend(
            session=RuntimeState.RUNNING, container=RuntimeState.RUNNING, **kwargs
        )
        manager = RuntimeManager(backend, default_timeout=2.0)
        return manager, backend

    def test_list_apps_is_read_only_and_does_not_refresh_state(self):
        manager, backend = self.make()
        backend.apps = [("Free Fire", "com.dts.freefireth")]
        result = manager.list_apps()
        self.assertTrue(result.ok)
        self.assertEqual(result.data["apps"][0]["package_id"], "com.dts.freefireth")
        self.assertEqual(backend.calls, [RuntimeOperation.LIST_APPS])
        self.assertEqual(backend.session_state, RuntimeState.RUNNING)
        manager.shutdown()

    def test_launch_app_registers_command_and_invalid_package_is_refused(self):
        manager, backend = self.make()
        result = manager.launch_app("com.dts.freefireth")
        self.assertTrue(result.ok)
        self.assertEqual(backend.launched, ["com.dts.freefireth"])

        bad = manager.launch_app("comando; rm -rf /")
        self.assertFalse(bad.ok)
        self.assertEqual(bad.failure.code, RuntimeErrorCode.INVALID_ARGUMENT)
        self.assertEqual(backend.launched, ["com.dts.freefireth"])
        manager.shutdown()

    def test_install_requires_active_android_and_apk_suffix(self):
        manager, backend = self.make()
        backend.set_states(RuntimeState.RUNNING, RuntimeState.FROZEN)
        blocked = manager.install_app("/tmp/jogo.apk")
        self.assertFalse(blocked.ok)
        self.assertEqual(blocked.failure.code, RuntimeErrorCode.INVALID_TRANSITION)
        self.assertEqual(backend.installed, [])

        backend.set_states(RuntimeState.RUNNING, RuntimeState.RUNNING)
        bad_suffix = manager.install_app("/tmp/jogo.xapk")
        self.assertFalse(bad_suffix.ok)
        self.assertEqual(bad_suffix.failure.code, RuntimeErrorCode.INVALID_ARGUMENT)

        good = manager.install_app("/tmp/jogo.apk")
        self.assertTrue(good.ok)
        self.assertEqual(backend.installed, ["/tmp/jogo.apk"])
        manager.shutdown()

    def test_diagnostics_is_read_only(self):
        manager, backend = self.make()
        backend.details = {"ip_address": "192.168.240.112"}
        result = manager.diagnostics()
        self.assertTrue(result.ok)
        self.assertEqual(result.data["availability"], "AVAILABLE")
        self.assertEqual(backend.calls, [RuntimeOperation.DIAGNOSTICS])
        manager.shutdown()

    def test_auxiliary_operations_are_serialized(self):
        manager, backend = self.make()
        backend.set_delay(0.3)
        started = threading.Event()
        done = threading.Event()
        holder = {}

        def on_event(event):
            if (
                event.kind is RuntimeEventType.OPERATION_STARTED
                and event.operation is RuntimeOperation.LAUNCH_APP
            ):
                started.set()

        def run():
            holder["result"] = manager.launch_app("com.dts.freefireth")
            done.set()

        manager.subscribe(on_event)
        thread = threading.Thread(target=run, daemon=True)
        thread.start()
        self.assertTrue(started.wait(2), "a operação não chegou a iniciar")
        duplicate = manager.list_apps()
        self.assertTrue(done.wait(2))
        thread.join(2)
        self.assertTrue(holder["result"].ok)
        self.assertFalse(duplicate.ok)
        self.assertEqual(duplicate.failure.code, RuntimeErrorCode.DUPLICATE_OPERATION)
        manager.shutdown()

    def test_auxiliary_timeout_signals_cancellation(self):
        manager, backend = self.make()
        backend.set_delay(2.0)
        events = []
        manager.subscribe(events.append)
        result = manager.diagnostics(timeout=0.05)
        self.assertFalse(result.ok)
        self.assertEqual(result.failure.code, RuntimeErrorCode.TIMEOUT)
        self.assertTrue(any(e.kind is RuntimeEventType.OPERATION_TIMED_OUT for e in events))
        manager.shutdown()

    def test_auxiliary_operation_requires_advertised_capability(self):
        backend = FakeRuntimeBackend(
            session=RuntimeState.RUNNING,
            container=RuntimeState.RUNNING,
            capabilities=RuntimeCapabilities(
                backend="fake", supported=CORE_FEATURES | frozenset({RuntimeFeature.LAUNCH_APP})
            ),
        )
        manager = RuntimeManager(backend)
        result = manager.list_apps()
        self.assertFalse(result.ok)
        self.assertEqual(result.failure.code, RuntimeErrorCode.UNSUPPORTED_OPERATION)
        manager.shutdown()


class AuxiliaryBackendTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.apk = self.root / "jogo.apk"
        self.apk.write_bytes(b"apk")

    def tearDown(self):
        self.temp.cleanup()

    def test_list_apps_uses_injected_cli_and_parses_output(self):
        runner = ScriptedRunner(
            {("app", "list"): "Name: Jogo\nPackageName: com.example.jogo\n"}
        )
        backend = WaydroidRuntimeBackend(command_runner=runner)
        result = backend.list_apps()
        self.assertTrue(result.ok)
        self.assertEqual(result.data["apps"], [{"name": "Jogo", "package_id": "com.example.jogo"}])
        self.assertEqual(runner.calls[0][:2], ("waydroid", ("app", "list")))

    def test_launch_rejects_invalid_package_before_running_command(self):
        runner = ScriptedRunner()
        backend = WaydroidRuntimeBackend(command_runner=runner)
        with self.assertRaises(RuntimeFailureError) as ctx:
            backend.launch_app("com.example.jogo; id")
        self.assertIs(ctx.exception.code, RuntimeErrorCode.INVALID_ARGUMENT)
        self.assertEqual(runner.calls, [])

        result = backend.launch_app("com.example.jogo")
        self.assertTrue(result.ok)
        self.assertEqual(runner.calls[0][1], ("app", "launch", "com.example.jogo"))

    def test_install_rejects_non_apk_and_uses_same_cli_as_service(self):
        runner = ScriptedRunner()
        backend = WaydroidRuntimeBackend(command_runner=runner)
        with self.assertRaises(RuntimeFailureError) as ctx:
            backend.install_app(str(self.root / "pacote.xapk"))
        self.assertIs(ctx.exception.code, RuntimeErrorCode.INVALID_ARGUMENT)
        with self.assertRaises(RuntimeFailureError) as ctx:
            backend.install_app(str(self.root / "ausente.apk"))
        self.assertIs(ctx.exception.code, RuntimeErrorCode.NOT_FOUND)
        self.assertEqual(runner.calls, [])

        result = backend.install_app(str(self.apk))
        self.assertTrue(result.ok)
        self.assertEqual(runner.calls[0][1], ("app", "install", str(self.apk)))

    def test_diagnostics_runs_status_without_changing_state(self):
        runner = ScriptedRunner(
            {("status",): "Session: RUNNING\nContainer: FROZEN\nIP address: UNKNOWN\n"}
        )
        backend = WaydroidRuntimeBackend(command_runner=runner)
        result = backend.diagnostics()
        self.assertTrue(result.ok)
        self.assertEqual(result.data["container"], "FROZEN")
        self.assertEqual(runner.calls, [("waydroid", ("status",), None)])


if __name__ == "__main__":
    unittest.main()
