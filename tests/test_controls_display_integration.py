"""Integração do editor com a medição de tela — sem comandos reais."""
from __future__ import annotations

import importlib.util
import os
import tempfile
import unittest
from pathlib import Path

from linuxdroid import storage
from linuxdroid.models import GameEntry
from linuxdroid.services.display_metrics import (
    DisplayMetrics,
    documented_reference,
    unknown,
)

PYSIDE_AVAILABLE = importlib.util.find_spec("PySide6") is not None
if PYSIDE_AVAILABLE:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    from linuxdroid.screens.controls import ControlsScreen


@unittest.skipUnless(PYSIDE_AVAILABLE, "PySide6 não está instalado neste interpretador")
class ControlsDisplayIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.old_data_dir = storage.DATA_DIR
        self.temp = tempfile.TemporaryDirectory()
        storage.DATA_DIR = Path(self.temp.name)
        self.screen = ControlsScreen([GameEntry("Jogo", "com.example.game")])

    def tearDown(self):
        self.screen.shutdown()
        storage.DATA_DIR = self.old_data_dir
        self.temp.cleanup()

    def test_default_uses_documented_reference_not_silent_1280x720(self):
        reference = documented_reference()
        self.assertEqual(self.screen.width_spin.value(), reference.width)
        self.assertEqual(self.screen.height_spin.value(), reference.height)
        self.assertNotEqual((self.screen.width_spin.value(), self.screen.height_spin.value()), (1280, 720))
        self.assertIn("REFERÊNCIA / MANUAL", self.screen.display_status.text())

    def test_measured_metrics_update_spins_and_status(self):
        self.screen.display_metrics_service.metrics_detected.emit(
            DisplayMetrics(width=1600, height=900, dpi=240, refresh_hz=90,
                           source="wm size / wm density", measured=True)
        )
        self.assertEqual(self.screen.width_spin.value(), 1600)
        self.assertEqual(self.screen.height_spin.value(), 900)
        self.assertIn("MEDIDA", self.screen.display_status.text())
        self.assertIn("1600", self.screen.display_status.text())
        self.assertEqual(self.screen.editor.profile.screen_contract.source, "measured")

    def test_unmeasured_result_does_not_erase_manual_resolution(self):
        self.screen.width_spin.setValue(1000)
        self.screen.height_spin.setValue(800)
        self.screen.display_metrics_service.metrics_detected.emit(
            unknown("container congelado")
        )
        self.assertEqual(self.screen.width_spin.value(), 1000)
        self.assertEqual(self.screen.height_spin.value(), 800)
        self.assertIn("NÃO MEDIDA", self.screen.display_status.text())

    def test_detect_button_uses_injected_runner_without_real_commands(self):
        calls = []

        class Runner:
            def run(self, program, args, callback, timeout_ms=20000):
                calls.append((program, tuple(args)))

            def shutdown(self):
                pass

        self.screen.display_metrics_service.runner = Runner()
        self.screen.detect_resolution()
        self.assertEqual(calls, [("waydroid", ("shell", "wm", "size"))])


if __name__ == "__main__":
    unittest.main()
