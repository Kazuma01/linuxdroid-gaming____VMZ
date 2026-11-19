"""Remoção de apps e propriedades via RuntimeManager — sem comandos reais."""
import unittest

from linuxdroid.models import CommandResult
from linuxdroid.runtime import (
    FakeRuntimeBackend,
    RuntimeErrorCode,
    RuntimeManager,
    RuntimeOperation,
    RuntimeState,
    WaydroidRuntimeBackend,
)


class ScriptedRunner:
    def __init__(self, responses=None):
        self.responses = responses or {}
        self.calls = []

    def run(self, program, args, *, timeout=None):
        args = tuple(str(a) for a in args)
        self.calls.append((program, args, timeout))
        text = self.responses.get(args, "")
        return CommandResult(program, list(args), exit_code=0, stdout=text)


class PropertyManagerTests(unittest.TestCase):
    def make(self, container=RuntimeState.RUNNING):
        backend = FakeRuntimeBackend(
            session=RuntimeState.RUNNING, container=container
        )
        manager = RuntimeManager(backend, default_timeout=2.0)
        return manager, backend

    def test_remove_app_requires_valid_package_and_active_android(self):
        manager, backend = self.make()
        bad = manager.remove_app("jogo; rm -rf /")
        self.assertFalse(bad.ok)
        self.assertEqual(bad.failure.code, RuntimeErrorCode.INVALID_ARGUMENT)
        self.assertEqual(backend.removed, [])

        backend.set_states(RuntimeState.RUNNING, RuntimeState.FROZEN)
        frozen = manager.remove_app("com.example.jogo")
        self.assertFalse(frozen.ok)
        self.assertEqual(frozen.failure.code, RuntimeErrorCode.INVALID_TRANSITION)

        backend.set_states(RuntimeState.RUNNING, RuntimeState.RUNNING)
        ok = manager.remove_app("com.example.jogo")
        self.assertTrue(ok.ok)
        self.assertEqual(backend.removed, ["com.example.jogo"])
        manager.shutdown()

    def test_prop_get_is_refused_with_frozen_container(self):
        manager, backend = self.make(container=RuntimeState.FROZEN)
        result = manager.get_property("persist.waydroid.multi_windows")
        self.assertFalse(result.ok)
        self.assertEqual(result.failure.code, RuntimeErrorCode.INVALID_TRANSITION)
        self.assertIn("congelado", result.failure.message)
        self.assertTrue(result.failure.retryable)
        self.assertEqual(
            backend.calls, [RuntimeOperation.STATUS]
        )  # somente a consulta prévia; nenhum `prop get`
        manager.shutdown()

    def test_prop_set_is_refused_with_frozen_container(self):
        manager, backend = self.make(container=RuntimeState.FROZEN)
        result = manager.set_property("persist.waydroid.multi_windows", "false")
        self.assertFalse(result.ok)
        self.assertEqual(result.failure.code, RuntimeErrorCode.INVALID_TRANSITION)
        self.assertEqual(backend.calls, [RuntimeOperation.STATUS])
        manager.shutdown()

    def test_property_arguments_are_validated_before_execution(self):
        manager, backend = self.make()
        for call in (
            lambda: manager.get_property("chave com espaco"),
            lambda: manager.set_property("", "x"),
            lambda: manager.set_property("chave.valida", "linha\nquebrada"),
        ):
            result = call()
            self.assertFalse(result.ok)
            self.assertEqual(result.failure.code, RuntimeErrorCode.INVALID_ARGUMENT)
        self.assertEqual(backend.calls, [])
        manager.shutdown()

    def test_property_round_trip_records_history(self):
        manager, backend = self.make()
        self.assertTrue(manager.set_property("persist.waydroid.multi_windows", "true").ok)
        got = manager.get_property("persist.waydroid.multi_windows")
        self.assertTrue(got.ok)
        self.assertEqual(got.data["value"], "true")
        self.assertEqual(
            [op for op in (r.operation for r in manager.history())],
            [RuntimeOperation.SET_PROPERTY, RuntimeOperation.GET_PROPERTY],
        )
        manager.shutdown()


class PropertyBackendTests(unittest.TestCase):
    def test_cli_contract_for_remove_and_properties(self):
        runner = ScriptedRunner(
            {
                ("prop", "get", "persist.waydroid.multi_windows"): "true\n",
            }
        )
        backend = WaydroidRuntimeBackend(command_runner=runner)

        self.assertTrue(backend.remove_app("com.example.jogo").ok)
        self.assertTrue(backend.set_property("persist.waydroid.multi_windows", "false").ok)
        got = backend.get_property("persist.waydroid.multi_windows")
        self.assertEqual(got.data["value"], "true")
        self.assertEqual(
            runner.calls,
            [
                ("waydroid", ("app", "remove", "com.example.jogo"), None),
                ("waydroid", ("prop", "set", "persist.waydroid.multi_windows", "false"), None),
                ("waydroid", ("prop", "get", "persist.waydroid.multi_windows"), None),
            ],
        )

    def test_invalid_arguments_do_not_reach_runner(self):
        runner = ScriptedRunner()
        backend = WaydroidRuntimeBackend(command_runner=runner)
        with self.assertRaises(Exception):
            backend.remove_app("comando; id")
        with self.assertRaises(Exception):
            backend.get_property("chave invalida")
        with self.assertRaises(Exception):
            backend.set_property("chave", "valor\nnulo")
        self.assertEqual(runner.calls, [])


class SurfaceManagerTests(unittest.TestCase):
    def make(self, container=RuntimeState.RUNNING):
        backend = FakeRuntimeBackend(
            session=RuntimeState.RUNNING, container=container
        )
        return RuntimeManager(backend, default_timeout=2.0), backend

    def test_adb_and_surface_require_active_android(self):
        manager, backend = self.make(container=RuntimeState.FROZEN)
        self.assertEqual(
            manager.adb_connect().failure.code, RuntimeErrorCode.INVALID_TRANSITION
        )
        self.assertEqual(backend.adb_connects, 0)
        self.assertEqual(
            manager.show_full_ui().failure.code, RuntimeErrorCode.INVALID_TRANSITION
        )
        self.assertEqual(backend.full_ui_shown, 0)
        manager.shutdown()

        manager, backend = self.make()
        self.assertTrue(manager.adb_connect().ok)
        self.assertTrue(manager.show_full_ui().ok)
        self.assertEqual(backend.adb_connects, 1)
        self.assertEqual(backend.full_ui_shown, 1)
        manager.shutdown()

    def test_injected_cli_contract(self):
        runner = ScriptedRunner()
        backend = WaydroidRuntimeBackend(command_runner=runner)
        self.assertTrue(backend.adb_connect().ok)
        self.assertTrue(backend.show_full_ui().ok)
        self.assertEqual(
            runner.calls,
            [
                ("waydroid", ("adb", "connect"), None),
                ("waydroid", ("show-full-ui",), None),
            ],
        )


if __name__ == "__main__":
    unittest.main()
