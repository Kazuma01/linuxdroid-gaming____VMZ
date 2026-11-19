"""Runtime Manager: estados separados, transições, concorrência e recuperação.

Todos os testes usam FakeRuntimeBackend. Nenhum freeze/unfreeze real é feito.
"""
import threading
import unittest

from linuxdroid.runtime import (
    FakeRuntimeBackend,
    OperationResult,
    OperationStatus,
    RuntimeAvailability,
    RuntimeCapabilities,
    RuntimeErrorCode,
    RuntimeEventType,
    RuntimeFailureError,
    RuntimeFeature,
    RuntimeManager,
    RuntimeOperation,
    RuntimeState,
)
from linuxdroid.runtime.models import CORE_FEATURES


def manager_with(session=RuntimeState.STOPPED, container=RuntimeState.STOPPED, **kwargs):
    backend = FakeRuntimeBackend(session=session, container=container)
    manager = RuntimeManager(backend, **kwargs)
    return manager, backend


class SnapshotSeparationTests(unittest.TestCase):
    def test_running_and_running(self):
        backend = FakeRuntimeBackend(
            session=RuntimeState.RUNNING, container=RuntimeState.RUNNING
        )
        manager = RuntimeManager(backend)
        result = manager.status()
        self.assertTrue(result.ok)
        snap = manager.snapshot
        self.assertIs(snap.session_state, RuntimeState.RUNNING)
        self.assertIs(snap.container_state, RuntimeState.RUNNING)
        self.assertIs(snap.effective_state, RuntimeState.RUNNING)
        self.assertTrue(snap.is_running)
        self.assertFalse(snap.is_frozen)
        self.assertEqual(
            set(snap.to_dict()),
            {
                "session_state",
                "container_state",
                "runtime_availability",
                "active_operation",
                "last_error",
                "capabilities",
                "effective_state",
                "taken_at",
            },
        )

    def test_running_and_frozen_are_independent(self):
        backend = FakeRuntimeBackend(
            session=RuntimeState.RUNNING, container=RuntimeState.FROZEN
        )
        manager = RuntimeManager(backend)
        manager.status()
        snap = manager.snapshot
        self.assertIs(snap.session_state, RuntimeState.RUNNING)
        self.assertIs(snap.container_state, RuntimeState.FROZEN)
        self.assertIs(snap.effective_state, RuntimeState.FROZEN)
        self.assertTrue(snap.is_frozen)
        self.assertFalse(snap.is_running)
        self.assertEqual(snap.to_dict()["container_state"], "FROZEN")

    def test_stopped(self):
        manager, _ = manager_with()
        manager.status()
        self.assertIs(manager.snapshot.effective_state, RuntimeState.STOPPED)
        self.assertTrue(manager.snapshot.is_stopped)

    def test_starting(self):
        backend = FakeRuntimeBackend(
            session=RuntimeState.STARTING, container=RuntimeState.STOPPED
        )
        manager = RuntimeManager(backend)
        manager.status()
        self.assertIs(manager.snapshot.session_state, RuntimeState.STARTING)
        self.assertIs(manager.snapshot.effective_state, RuntimeState.STARTING)

    def test_stopping(self):
        backend = FakeRuntimeBackend(
            session=RuntimeState.STOPPING, container=RuntimeState.RUNNING
        )
        manager = RuntimeManager(backend)
        manager.status()
        self.assertIs(manager.snapshot.session_state, RuntimeState.STOPPING)
        self.assertIs(manager.snapshot.effective_state, RuntimeState.STOPPING)

    def test_unknown(self):
        backend = FakeRuntimeBackend(
            session=RuntimeState.UNKNOWN, container=RuntimeState.UNKNOWN
        )
        manager = RuntimeManager(backend)
        manager.status()
        self.assertIs(manager.snapshot.effective_state, RuntimeState.UNKNOWN)
        self.assertIs(
            manager.snapshot.runtime_availability, RuntimeAvailability.AVAILABLE
        )

    def test_snapshot_does_not_do_io(self):
        manager, backend = manager_with()
        before = list(backend.calls)
        _ = manager.snapshot
        self.assertEqual(backend.calls, before)


class OperationTests(unittest.TestCase):
    def test_start_success_updates_snapshot_and_history(self):
        manager, backend = manager_with()
        events = []
        manager.subscribe(lambda event: events.append(event))
        result = manager.start()
        self.assertTrue(result.ok)
        self.assertIs(manager.snapshot.session_state, RuntimeState.RUNNING)
        self.assertIs(manager.snapshot.container_state, RuntimeState.RUNNING)
        self.assertIsNone(manager.snapshot.active_operation)
        self.assertEqual(
            backend.calls,
            [RuntimeOperation.STATUS, RuntimeOperation.START, RuntimeOperation.STATUS],
        )
        self.assertEqual(manager.history()[-1].status, OperationStatus.SUCCEEDED)
        self.assertIn(RuntimeEventType.OPERATION_STARTED, [e.kind for e in events])
        self.assertIn(RuntimeEventType.SNAPSHOT_UPDATED, [e.kind for e in events])
        manager.shutdown()

    def test_permission_denied_on_start(self):
        manager, backend = manager_with()
        backend.queue_failure(
            RuntimeOperation.START,
            RuntimeErrorCode.PERMISSION_DENIED,
            "Permissão negada ao iniciar.",
        )
        result = manager.start()
        self.assertFalse(result.ok)
        self.assertIs(result.failure.code, RuntimeErrorCode.PERMISSION_DENIED)
        self.assertIs(manager.last_error.code, RuntimeErrorCode.PERMISSION_DENIED)
        self.assertIs(
            manager.snapshot.runtime_availability, RuntimeAvailability.PERMISSION_DENIED
        )
        self.assertEqual(manager.history()[-1].status, OperationStatus.FAILED)
        self.assertFalse(manager.is_busy)
        manager.shutdown()

    def test_timeout_is_structured_and_cancels_cooperatively(self):
        manager, backend = manager_with(default_timeout=0.03)
        entered = threading.Event()

        def slow(context):
            entered.set()
            context.cancel_event.wait(2.0)
            context.raise_if_cancelled()

        backend.queue_effect(RuntimeOperation.START, slow)
        events = []
        manager.subscribe(lambda event: events.append(event))
        result = manager.start()
        self.assertTrue(entered.is_set())
        self.assertFalse(result.ok)
        self.assertIs(result.failure.code, RuntimeErrorCode.TIMEOUT)
        self.assertTrue(result.failure.retryable)
        self.assertIn(RuntimeEventType.OPERATION_TIMED_OUT, [e.kind for e in events])
        self.assertEqual(manager.history()[-1].status, OperationStatus.TIMED_OUT)
        self.assertFalse(manager.is_busy)
        manager.shutdown()

    def test_service_not_found(self):
        backend = FakeRuntimeBackend(availability=RuntimeAvailability.NOT_FOUND)
        manager = RuntimeManager(backend)
        result = manager.status()
        self.assertFalse(result.ok)
        self.assertIs(result.failure.code, RuntimeErrorCode.NOT_FOUND)
        self.assertIs(manager.snapshot.runtime_availability, RuntimeAvailability.NOT_FOUND)
        self.assertEqual(manager.snapshot.effective_state, RuntimeState.NOT_INSTALLED)

    def test_invalid_response(self):
        manager, backend = manager_with()
        backend.queue_response(RuntimeOperation.STATUS, {"session": "RUNNING"})
        result = manager.status()
        self.assertFalse(result.ok)
        self.assertIs(result.failure.code, RuntimeErrorCode.INVALID_RESPONSE)
        self.assertFalse(manager.is_busy)
        manager.shutdown()

    def test_invalid_mutation_response(self):
        manager, backend = manager_with()
        backend.queue_response(
            RuntimeOperation.START, OperationResult(RuntimeOperation.STOP, True)
        )
        result = manager.start()
        self.assertFalse(result.ok)
        self.assertIs(result.failure.code, RuntimeErrorCode.INVALID_RESPONSE)
        self.assertFalse(manager.is_busy)
        manager.shutdown()

    def test_duplicate_operation_is_rejected(self):
        manager, backend = manager_with()
        duplicates = []

        def on_started(event):
            if event.kind is not RuntimeEventType.OPERATION_STARTED:
                return
            if event.operation is not RuntimeOperation.START:
                return
            duplicates.append(manager.start())
            manager.cancel(RuntimeOperation.START)

        manager.subscribe(on_started)
        backend.queue_effect(
            RuntimeOperation.START, lambda context: context.cancel_event.wait(1.0)
        )
        result = manager.start()
        self.assertEqual(len(duplicates), 1)
        self.assertIs(duplicates[0].failure.code, RuntimeErrorCode.DUPLICATE_OPERATION)
        self.assertEqual(backend.calls.count(RuntimeOperation.START), 1)
        self.assertFalse(result.ok)
        self.assertIs(result.failure.code, RuntimeErrorCode.CANCELED)
        manager.shutdown()

    def test_repeated_freeze_is_skipped(self):
        manager, backend = manager_with(
            session=RuntimeState.RUNNING, container=RuntimeState.RUNNING
        )
        first = manager.freeze()
        self.assertTrue(first.ok)
        self.assertIs(manager.snapshot.container_state, RuntimeState.FROZEN)
        second = manager.freeze()
        self.assertTrue(second.ok)
        self.assertTrue(second.skipped)
        self.assertIn("já congelado", second.message.lower())
        self.assertEqual(backend.calls.count(RuntimeOperation.FREEZE), 1)
        self.assertEqual(manager.history()[-1].status, OperationStatus.SKIPPED)
        manager.shutdown()

    def test_repeated_unfreeze_is_skipped(self):
        manager, backend = manager_with(
            session=RuntimeState.RUNNING, container=RuntimeState.FROZEN
        )
        first = manager.unfreeze()
        self.assertTrue(first.ok)
        self.assertIs(manager.snapshot.container_state, RuntimeState.RUNNING)
        second = manager.unfreeze()
        self.assertTrue(second.ok)
        self.assertTrue(second.skipped)
        self.assertEqual(backend.calls.count(RuntimeOperation.UNFREEZE), 1)
        manager.shutdown()

    def test_freeze_requires_running_container(self):
        manager, backend = manager_with()
        result = manager.freeze()
        self.assertFalse(result.ok)
        self.assertIs(result.failure.code, RuntimeErrorCode.INVALID_TRANSITION)
        self.assertEqual(backend.calls, [RuntimeOperation.STATUS])
        self.assertNotIn(RuntimeOperation.FREEZE, backend.calls)
        manager.shutdown()

    def test_start_on_frozen_container_hints_unfreeze(self):
        manager, _ = manager_with(
            session=RuntimeState.RUNNING, container=RuntimeState.FROZEN
        )
        result = manager.start()
        self.assertIs(result.failure.code, RuntimeErrorCode.INVALID_TRANSITION)
        self.assertIn("reativar", result.failure.detail.lower())

    def test_unsupported_operation(self):
        capabilities = RuntimeCapabilities(
            backend="limitado",
            supported=CORE_FEATURES - {RuntimeFeature.FREEZE},
        )
        backend = FakeRuntimeBackend(capabilities=capabilities)
        manager = RuntimeManager(backend)
        result = manager.freeze()
        self.assertIs(result.failure.code, RuntimeErrorCode.UNSUPPORTED_OPERATION)
        manager.shutdown()

    def test_recovery_after_error(self):
        backend = FakeRuntimeBackend(availability=RuntimeAvailability.NOT_FOUND)
        manager = RuntimeManager(backend)
        first = manager.status()
        self.assertFalse(first.ok)
        self.assertIsNotNone(manager.last_error)

        backend.set_states(
            RuntimeState.RUNNING,
            RuntimeState.RUNNING,
            RuntimeAvailability.AVAILABLE,
        )
        events = []
        manager.subscribe(lambda event: events.append(event))
        recovered = manager.recover()
        self.assertTrue(recovered.ok)
        self.assertIs(recovered.operation, RuntimeOperation.RECOVER)
        self.assertIsNone(manager.last_error)
        self.assertIn(RuntimeEventType.RECOVERED, [e.kind for e in events])
        self.assertIn(RuntimeEventType.ERROR_CLEARED, [e.kind for e in events])
        self.assertEqual(manager.history()[-1].status, OperationStatus.SUCCEEDED)
        manager.shutdown()

    def test_explicit_cancel(self):
        manager, backend = manager_with()
        backend.set_states(RuntimeState.RUNNING, RuntimeState.RUNNING)
        backend.queue_effect(
            RuntimeOperation.STOP, lambda context: context.cancel_event.wait(1.0)
        )
        events = []
        manager.subscribe(lambda event: events.append(event))
        thread = threading.Thread(target=manager.stop, name="test-stop")
        thread.start()
        for _ in range(200):
            if manager.is_busy:
                break
            threading.Event().wait(0.001)
        self.assertTrue(manager.cancel(RuntimeOperation.STOP))
        thread.join(timeout=1.0)
        self.assertFalse(thread.is_alive())
        self.assertIn(RuntimeEventType.OPERATION_CANCELED, [e.kind for e in events])
        manager.shutdown()

    def test_listener_error_does_not_break_manager(self):
        manager, _ = manager_with()

        def broken(_event):
            raise RuntimeError("observador com bug")

        manager.subscribe(broken)
        result = manager.status()
        self.assertTrue(result.ok)
        manager.shutdown()

    def test_capabilities_advertise_only_implemented_auxiliary_operations(self):
        manager, _ = manager_with()
        caps = manager.capabilities()
        self.assertTrue(caps.supports(RuntimeFeature.FREEZE))
        self.assertTrue(caps.supports(RuntimeFeature.LIST_APPS))
        self.assertTrue(caps.supports(RuntimeFeature.LAUNCH_APP))
        self.assertTrue(caps.supports(RuntimeFeature.INSTALL_APP))
        self.assertTrue(caps.supports(RuntimeFeature.DIAGNOSTICS))
        self.assertFalse(caps.supports(RuntimeFeature.CREATE_INSTANCE))
        manager.shutdown()

    def test_unimplemented_extensions_fail_closed(self):
        backend = FakeRuntimeBackend()
        for name, args in (
            ("create_instance", ("instancia",)),
            ("clone_instance", ("origem",)),
            ("backup", ("/tmp/backup",)),
            ("restore", ("/tmp/backup",)),
        ):
            with self.subTest(operation=name), self.assertRaises(RuntimeFailureError) as ctx:
                getattr(backend, name)(*args)
            self.assertIs(ctx.exception.code, RuntimeErrorCode.NOT_IMPLEMENTED)


if __name__ == "__main__":
    unittest.main()
