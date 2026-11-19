"""Ponte Qt: a interface solicita operações sem executar comandos."""
import threading
import time
import unittest

from linuxdroid.runtime import (
    FakeRuntimeBackend,
    RuntimeOperation,
    RuntimeState,
)

try:
    from PySide6.QtCore import QCoreApplication

    from linuxdroid.runtime.qt_bridge import RuntimeManagerBridge

    PYSIDE_AVAILABLE = True
except ImportError:
    PYSIDE_AVAILABLE = False


def pump(condition, seconds=3.0):
    app = QCoreApplication.instance() or QCoreApplication([])
    deadline = time.monotonic() + seconds
    while not condition() and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.005)
    return condition()


@unittest.skipUnless(PYSIDE_AVAILABLE, "PySide6 não está instalado neste interpretador")
class RuntimeManagerBridgeTests(unittest.TestCase):
    def test_status_goes_through_manager_and_emits_snapshot(self):
        backend = FakeRuntimeBackend(
            session=RuntimeState.RUNNING, container=RuntimeState.FROZEN
        )
        bridge = RuntimeManagerBridge(backend)
        snapshots = []
        results = []
        finished = threading.Event()
        bridge.snapshot_changed.connect(snapshots.append)

        def done(result):
            results.append(result)
            finished.set()

        bridge.request(RuntimeOperation.STATUS, done, timeout=5)
        self.assertTrue(pump(finished.is_set))
        self.assertEqual(len(results), 1)
        self.assertTrue(results[0].ok)
        self.assertTrue(snapshots)
        self.assertIs(snapshots[-1].session_state, RuntimeState.RUNNING)
        self.assertIs(snapshots[-1].container_state, RuntimeState.FROZEN)
        self.assertEqual(backend.calls, [RuntimeOperation.STATUS])
        bridge.shutdown()

    def test_unfreeze_request_updates_snapshot_without_direct_command(self):
        backend = FakeRuntimeBackend(
            session=RuntimeState.RUNNING, container=RuntimeState.FROZEN
        )
        bridge = RuntimeManagerBridge(backend)
        results = []
        finished = threading.Event()

        def done(result):
            results.append(result)
            finished.set()

        bridge.request(RuntimeOperation.UNFREEZE, done, timeout=5)
        self.assertTrue(pump(finished.is_set))
        self.assertTrue(results[0].ok)
        self.assertIs(bridge.manager.snapshot.container_state, RuntimeState.RUNNING)
        self.assertEqual(
            backend.calls, [RuntimeOperation.STATUS, RuntimeOperation.UNFREEZE, RuntimeOperation.STATUS]
        )
        bridge.shutdown()

    def test_invalid_operation_is_never_sent_to_manager(self):
        bridge = RuntimeManagerBridge(FakeRuntimeBackend())
        with self.assertRaises(ValueError):
            bridge.request("operacao_inexistente", timeout=5)
        bridge.shutdown()


if __name__ == "__main__":
    unittest.main()
