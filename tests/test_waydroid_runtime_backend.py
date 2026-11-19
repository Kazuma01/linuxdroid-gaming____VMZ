"""Adaptador Waydroid com CLI e D-Bus injetados — sem executar nada no host."""
import unittest

from linuxdroid.models import CommandResult
from linuxdroid.runtime import (
    DBUS_INTERFACE,
    DBUS_PATH,
    DBUS_SERVICE,
    RuntimeAvailability,
    RuntimeErrorCode,
    RuntimeFailureError,
    RuntimeManager,
    RuntimeOperation,
    RuntimeState,
    WaydroidRuntimeBackend,
    parse_status_output,
)


class FakeRunner:
    def __init__(self, text="Session:\tRUNNING\nContainer:\tFROZEN\n", error="", code=0):
        self.text = text
        self.error = error
        self.code = code
        self.calls = []

    def run(self, program, args, *, timeout=None):
        self.calls.append((program, tuple(args), timeout))
        return CommandResult(
            program,
            list(args),
            exit_code=self.code,
            stdout=self.text,
            stderr="",
            error=self.error,
        )


class FakeDBus:
    def __init__(self, error=None, on_call=None):
        self.error = error
        self.on_call = on_call
        self.calls = []

    def call(self, **kwargs):
        self.calls.append(kwargs)
        if self.error is not None:
            raise self.error
        if self.on_call is not None:
            self.on_call(kwargs)
        return None


class ParsingTests(unittest.TestCase):
    def test_session_and_container_are_parsed_separately(self):
        session, container, availability, details = parse_status_output(
            "Session:\tRUNNING\nContainer:\tFROZEN\nVendor type:\tMAINLINE\nIP address:\tUNKNOWN\n"
        )
        self.assertIs(session, RuntimeState.RUNNING)
        self.assertIs(container, RuntimeState.FROZEN)
        self.assertIs(availability, RuntimeAvailability.AVAILABLE)
        self.assertEqual(details["vendor_type"], "MAINLINE")
        self.assertEqual(details["ip_address"], "UNKNOWN")

    def test_not_initialized_is_not_a_single_collapsed_state(self):
        session, container, availability, _ = parse_status_output(
            "Session:\tNOT INITIALIZED\nContainer:\tNOT INITIALIZED\n",
            stderr="Waydroid is not initialized",
        )
        self.assertIs(session, RuntimeState.NOT_INITIALIZED)
        self.assertIs(container, RuntimeState.NOT_INITIALIZED)
        self.assertIs(availability, RuntimeAvailability.NOT_INITIALIZED)

    def test_missing_fields_become_unknown(self):
        session, container, availability, _ = parse_status_output("")
        self.assertIs(session, RuntimeState.UNKNOWN)
        self.assertIs(container, RuntimeState.UNKNOWN)
        self.assertIs(availability, RuntimeAvailability.AVAILABLE)

    def test_not_found_and_permission(self):
        _, _, availability, _ = parse_status_output("", error="not_found")
        self.assertIs(availability, RuntimeAvailability.NOT_FOUND)
        _, _, availability, _ = parse_status_output("", error="permission_denied")
        self.assertIs(availability, RuntimeAvailability.PERMISSION_DENIED)


class WaydroidBackendTests(unittest.TestCase):
    def test_status_uses_only_injected_runner(self):
        runner = FakeRunner()
        backend = WaydroidRuntimeBackend(command_runner=runner, dbus=FakeDBus())
        snapshot = backend.status()
        self.assertIs(snapshot.session_state, RuntimeState.RUNNING)
        self.assertIs(snapshot.container_state, RuntimeState.FROZEN)
        self.assertEqual(runner.calls, [("waydroid", ("status",), None)])

    def test_session_commands(self):
        runner = FakeRunner()
        backend = WaydroidRuntimeBackend(command_runner=runner, dbus=FakeDBus())
        backend.start()
        backend.stop()
        backend.restart()
        self.assertEqual(
            [call[1] for call in runner.calls],
            [
                ("session", "start"),
                ("session", "stop"),
                ("session", "stop"),
                ("session", "start"),
            ],
        )

    def test_freeze_and_unfreeze_use_official_dbus_contract(self):
        runner = FakeRunner()
        dbus = FakeDBus()
        backend = WaydroidRuntimeBackend(command_runner=runner, dbus=dbus)
        backend.freeze()
        backend.unfreeze()
        self.assertEqual(runner.calls, [])
        self.assertEqual(
            [call["method"] for call in dbus.calls], ["Freeze", "Unfreeze"]
        )
        for call in dbus.calls:
            self.assertEqual(call["bus"], "system")
            self.assertEqual(call["service"], DBUS_SERVICE)
            self.assertEqual(call["path"], DBUS_PATH)
            self.assertEqual(call["interface"], DBUS_INTERFACE)
            self.assertEqual(call["args"], ())
        self.assertEqual(DBUS_SERVICE, "id.waydro.Container")
        self.assertEqual(DBUS_PATH, "/ContainerManager")

    def test_capabilities_without_dbus_do_not_advertise_freeze(self):
        backend = WaydroidRuntimeBackend(command_runner=FakeRunner(), dbus=None)
        caps = backend.capabilities()
        self.assertNotIn("freeze", [feature.value for feature in caps.supported])
        self.assertNotIn("unfreeze", [feature.value for feature in caps.supported])
        manager = RuntimeManager(backend)
        result = manager.freeze()
        self.assertIs(result.failure.code, RuntimeErrorCode.UNSUPPORTED_OPERATION)
        manager.shutdown()

    def test_runner_errors_become_structured_failures(self):
        backend = WaydroidRuntimeBackend(
            command_runner=FakeRunner(text="", error="permission_denied"),
            dbus=FakeDBus(),
        )
        with self.assertRaises(RuntimeFailureError) as ctx:
            backend.status()
        self.assertIs(ctx.exception.code, RuntimeErrorCode.PERMISSION_DENIED)

        backend = WaydroidRuntimeBackend(
            command_runner=FakeRunner(text="", error="not_found"), dbus=FakeDBus()
        )
        with self.assertRaises(RuntimeFailureError) as ctx:
            backend.status()
        self.assertIs(ctx.exception.code, RuntimeErrorCode.NOT_FOUND)

    def test_dbus_permission_denied_is_structured(self):
        backend = WaydroidRuntimeBackend(
            command_runner=FakeRunner(), dbus=FakeDBus(error=PermissionError("negado"))
        )
        with self.assertRaises(RuntimeFailureError) as ctx:
            backend.freeze()
        self.assertIs(ctx.exception.code, RuntimeErrorCode.PERMISSION_DENIED)

    def test_manager_uses_backend_for_freeze_with_fake_dbus(self):
        runner = FakeRunner(
            text="Session:\tRUNNING\nContainer:\tRUNNING\nVendor type:\tMAINLINE\n"
        )

        def update_text(call):
            if call["method"] == "Freeze":
                runner.text = (
                    "Session:\tRUNNING\nContainer:\tFROZEN\nVendor type:\tMAINLINE\n"
                )

        dbus = FakeDBus(on_call=update_text)
        manager = RuntimeManager(
            WaydroidRuntimeBackend(command_runner=runner, dbus=dbus)
        )
        result = manager.freeze()
        self.assertTrue(result.ok)
        self.assertIs(manager.snapshot.container_state, RuntimeState.FROZEN)
        self.assertEqual([call["method"] for call in dbus.calls], ["Freeze"])
        manager.shutdown()

    def test_no_real_freeze_or_unfreeze_was_executed(self):
        # Este módulo só usa FakeDBus; o cliente real exige SystemBus injetado.
        runner = FakeRunner()
        dbus = FakeDBus()
        backend = WaydroidRuntimeBackend(command_runner=runner, dbus=dbus)
        backend.freeze()
        backend.unfreeze()
        self.assertEqual(len(dbus.calls), 2)
        self.assertEqual(runner.calls, [])


if __name__ == "__main__":
    unittest.main()
