"""Conversões entre RuntimeManager e os modelos antigos da interface."""
import unittest

from linuxdroid.models import WaydroidState
from linuxdroid.runtime import (
    FakeRuntimeBackend,
    OperationResult,
    RuntimeAvailability,
    RuntimeErrorCode,
    RuntimeManager,
    RuntimeOperation,
    RuntimeSnapshot,
    RuntimeState,
    make_failure,
)
from linuxdroid.runtime.presentation import (
    operation_to_command_result,
    snapshot_to_waydroid_status,
)


class PresentationTests(unittest.TestCase):
    def test_running_frozen_snapshot_becomes_frozen_status(self):
        snapshot = RuntimeSnapshot(
            session_state=RuntimeState.RUNNING,
            container_state=RuntimeState.FROZEN,
            runtime_availability=RuntimeAvailability.AVAILABLE,
            details={"ip_address": "192.168.240.1"},
        )
        status = snapshot_to_waydroid_status(snapshot)
        self.assertIs(status.state, WaydroidState.FROZEN)
        self.assertEqual(status.session, "RUNNING")
        self.assertEqual(status.container, "FROZEN")
        self.assertEqual(status.ip, "192.168.240.1")
        self.assertIn("congelado", status.message.lower())

    def test_not_found_and_not_initialized(self):
        status = snapshot_to_waydroid_status(
            RuntimeSnapshot(runtime_availability=RuntimeAvailability.NOT_FOUND)
        )
        self.assertIs(status.state, WaydroidState.NOT_INSTALLED)
        status = snapshot_to_waydroid_status(
            RuntimeSnapshot(runtime_availability=RuntimeAvailability.NOT_INITIALIZED)
        )
        self.assertIs(status.state, WaydroidState.NOT_INITIALIZED)

    def test_last_error_message_is_preserved(self):
        failure = make_failure(RuntimeErrorCode.TIMEOUT, "Tempo limite excedido.")
        status = snapshot_to_waydroid_status(
            RuntimeSnapshot(
                session_state=RuntimeState.STARTING,
                container_state=RuntimeState.STOPPED,
                runtime_availability=RuntimeAvailability.AVAILABLE,
                last_error=failure,
            )
        )
        self.assertIn("Tempo limite", status.message)

    def test_operation_result_keeps_old_callback_contract(self):
        failure = make_failure(RuntimeErrorCode.PERMISSION_DENIED, "Negado.", detail="bus")
        command = operation_to_command_result(
            OperationResult(RuntimeOperation.START, False, "Falha.", failure=failure)
        )
        self.assertFalse(command.ok)
        self.assertIn("Falha", command.text)
        self.assertEqual(command.error, "permission_denied")
        self.assertEqual(command.args, ["start"])

    def test_success_result(self):
        command = operation_to_command_result(
            OperationResult(RuntimeOperation.UNFREEZE, True, "Reativado.")
        )
        self.assertTrue(command.ok)
        self.assertEqual(command.error, "")
        self.assertEqual(command.args, ["unfreeze"])

    def test_manager_snapshot_can_feed_ui_without_commands(self):
        backend = FakeRuntimeBackend(
            session=RuntimeState.RUNNING, container=RuntimeState.FROZEN
        )
        manager = RuntimeManager(backend)
        manager.refresh()
        status = snapshot_to_waydroid_status(manager.snapshot)
        self.assertIs(status.state, WaydroidState.FROZEN)
        self.assertEqual(backend.calls, [RuntimeOperation.STATUS])
        manager.shutdown()


if __name__ == "__main__":
    unittest.main()
