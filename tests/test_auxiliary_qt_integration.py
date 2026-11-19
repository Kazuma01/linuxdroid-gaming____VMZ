"""Integração Qt das operações auxiliares — backend falso, nenhum comando real."""
import importlib.util
import os
import threading
import time
import unittest

from linuxdroid.runtime import (
    FakeRuntimeBackend,
    RuntimeErrorCode,
    RuntimeOperation,
    RuntimeState,
)

PYSIDE_AVAILABLE = importlib.util.find_spec("PySide6") is not None
if PYSIDE_AVAILABLE:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    from linuxdroid.runtime.qt_bridge import RuntimeManagerBridge
    from linuxdroid.services.waydroid_service import WaydroidService


def pump(condition, seconds=3.0):
    app = QApplication.instance() or QApplication([])
    deadline = time.monotonic() + seconds
    while not condition() and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.005)
    return condition()


def make_backend():
    backend = FakeRuntimeBackend(
        session=RuntimeState.RUNNING, container=RuntimeState.RUNNING
    )
    backend.apps = [("Jogo", "com.example.jogo")]
    return backend


@unittest.skipUnless(PYSIDE_AVAILABLE, "PySide6 não está instalado neste interpretador")
class AuxiliaryQtIntegrationTests(unittest.TestCase):
    def test_bridge_forwards_named_arguments_to_manager(self):
        backend = make_backend()
        bridge = RuntimeManagerBridge(backend)
        results = []
        event = threading.Event()

        def done(result):
            results.append(result)
            event.set()

        bridge.request(
            RuntimeOperation.LAUNCH_APP,
            done,
            package_id="com.example.jogo",
        )
        self.assertTrue(pump(event.is_set))
        self.assertTrue(results[0].ok)
        self.assertEqual(backend.launched, ["com.example.jogo"])
        bridge.shutdown()

    def test_bridge_rejects_invalid_argument_without_touching_backend(self):
        backend = make_backend()
        bridge = RuntimeManagerBridge(backend)
        results = []
        event = threading.Event()

        def done(result):
            results.append(result)
            event.set()

        bridge.request(RuntimeOperation.LAUNCH_APP, done, package_id="invalido")
        self.assertTrue(pump(event.is_set))
        self.assertFalse(results[0].ok)
        self.assertEqual(results[0].failure.code, RuntimeErrorCode.INVALID_ARGUMENT)
        self.assertEqual(backend.launched, [])
        bridge.shutdown()

    def test_service_list_apps_emits_parsed_pairs(self):
        service = WaydroidService(backend=make_backend())
        seen = []
        event = threading.Event()

        def on_apps(apps):
            seen.append(apps)
            event.set()

        service.apps_loaded.connect(on_apps)
        service.list_apps()
        self.assertTrue(pump(event.is_set))
        self.assertEqual(seen[0], [("Jogo", "com.example.jogo")])
        service.shutdown()

    def test_service_install_uses_manager_with_named_path(self):
        backend = make_backend()
        service = WaydroidService(backend=backend)
        results = []
        event = threading.Event()

        def done(result):
            results.append(result)
            event.set()

        service.install_app("/tmp/jogo.apk", done)
        self.assertTrue(pump(event.is_set))
        self.assertTrue(results[0].ok)
        self.assertEqual(backend.installed, ["/tmp/jogo.apk"])
        service.shutdown()

    def test_service_get_multi_windows_keeps_value_in_stdout(self):
        backend = make_backend()
        backend.properties["persist.waydroid.multi_windows"] = "true"
        service = WaydroidService(backend=backend)
        results = []
        event = threading.Event()

        def done(result):
            results.append(result)
            event.set()

        service.get_multi_windows(done)
        self.assertTrue(pump(event.is_set))
        self.assertTrue(results[0].ok)
        self.assertEqual(results[0].stdout, "true")
        service.shutdown()

    def test_service_adb_and_surface_use_manager(self):
        backend = make_backend()
        service = WaydroidService(backend=backend)
        results = []
        event = threading.Event()

        def done(result):
            results.append(result)
            if len(results) == 2:
                event.set()

        service.adb_connect(done)
        service.show_full_ui(done)
        self.assertTrue(pump(event.is_set))
        self.assertTrue(all(r.ok for r in results))
        self.assertEqual(backend.adb_connects, 1)
        self.assertEqual(backend.full_ui_shown, 1)
        service.shutdown()

    def test_service_set_multi_windows_and_remove_app_use_manager(self):
        backend = make_backend()
        service = WaydroidService(backend=backend)
        results = []
        event = threading.Event()

        def done(result):
            results.append(result)
            if len(results) == 2:
                event.set()

        service.set_multi_windows(False, done)
        service.remove_app("com.example.jogo", done)
        self.assertTrue(pump(event.is_set))
        self.assertTrue(all(r.ok for r in results))
        self.assertEqual(backend.properties["persist.waydroid.multi_windows"], "false")
        self.assertEqual(backend.removed, ["com.example.jogo"])
        service.shutdown()


if __name__ == "__main__":
    unittest.main()
