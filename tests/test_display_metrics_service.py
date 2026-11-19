"""Serviço de medição: consultas somente leitura, runner injetado, sem Waydroid."""
import unittest

from linuxdroid.models import CommandResult

try:
    from PySide6.QtCore import QCoreApplication

    from linuxdroid.services.display_metrics_service import DisplayMetricsService

    PYSIDE_AVAILABLE = True
except ImportError:
    PYSIDE_AVAILABLE = False


class FakeRunner:
    """Devolve respostas pré-definidas na ordem das chamadas, sem subprocesso."""

    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []
        self.shutdown_called = False

    def run(self, program, args, callback, timeout_ms=20000):
        self.calls.append((program, tuple(args), timeout_ms))
        response = self.responses.pop(0) if self.responses else CommandResult(program, args)
        callback(response)

    def shutdown(self):
        self.shutdown_called = True


def ok(text):
    return CommandResult("waydroid", [], 0, text, "")


def failed():
    return CommandResult("waydroid", [], 1, "", "no devices", "failed")


@unittest.skipUnless(PYSIDE_AVAILABLE, "PySide6 não está instalado neste interpretador")
class DisplayMetricsServiceTests(unittest.TestCase):
    def test_detects_measured_geometry_with_read_only_commands(self):
        runner = FakeRunner([
            ok("Physical size: 1920x1034\n"),
            ok("Physical density: 180\n"),
            ok('DisplayDeviceInfo{"Built-in", 1920 x 1034, 60.0 fps, density 180}\n'),
        ])
        service = DisplayMetricsService(runner)
        emitted = []
        service.metrics_detected.connect(emitted.append)

        service.detect(timeout_ms=4321)

        self.assertEqual(len(emitted), 1)
        metrics = emitted[0]
        self.assertTrue(metrics.measured)
        self.assertEqual((metrics.width, metrics.height), (1920, 1034))
        self.assertEqual(metrics.dpi, 180)
        self.assertEqual(metrics.refresh_hz, 60.0)
        self.assertEqual(metrics.status_label, "MEDIDA")
        # Nenhum comando mutante é enviado.
        self.assertEqual(runner.calls, [
            ("waydroid", ("shell", "wm", "size"), 4321),
            ("waydroid", ("shell", "wm", "density"), 4321),
            ("waydroid", ("shell", "dumpsys", "display"), 4321),
        ])
        for _program, args, _timeout in runner.calls:
            self.assertNotIn("prop", args)
            self.assertNotIn("start", args)
        service.shutdown()

    def test_failed_queries_are_honestly_unmeasured(self):
        runner = FakeRunner([failed(), failed(), failed()])
        service = DisplayMetricsService(runner)
        emitted = []
        service.metrics_detected.connect(emitted.append)

        service.detect()

        self.assertEqual(len(emitted), 1)
        metrics = emitted[0]
        self.assertFalse(metrics.known)
        self.assertFalse(metrics.measured)
        self.assertEqual(metrics.status_label, "NÃO MEDIDA")
        service.shutdown()

    def test_no_automatic_detection_on_construction(self):
        runner = FakeRunner([])
        service = DisplayMetricsService(runner)
        self.assertEqual(runner.calls, [])
        service.shutdown()
        self.assertTrue(runner.shutdown_called)


if __name__ == "__main__":
    unittest.main()
