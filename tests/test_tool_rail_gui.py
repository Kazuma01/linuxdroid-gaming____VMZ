"""Barra lateral direita: só ferramentas com backend real podem agir."""
from __future__ import annotations

import importlib.util
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from linuxdroid import storage
from linuxdroid.models import CommandResult, GameEntry, WaydroidState

PYSIDE_AVAILABLE = importlib.util.find_spec("PySide6") is not None
if PYSIDE_AVAILABLE:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    from linuxdroid.main_window import MainWindow
    from linuxdroid.widgets.tool_rail import ALWAYS_DISABLED, TOOLS, ToolRail


class FakeToolService:
    def __init__(self):
        self.fullscreen = 0
        self.launched = []

    def show_full_ui(self, callback=None):
        self.fullscreen += 1
        if callback is not None:
            callback(CommandResult("waydroid", ["show-full-ui"], 0))

    def launch_app(self, package_id, callback=None):
        self.launched.append(package_id)
        if callback is not None:
            callback(CommandResult("waydroid", ["app", "launch", package_id], 0))

    def shutdown(self):
        return None


@unittest.skipUnless(PYSIDE_AVAILABLE, "PySide6 não está instalado neste interpretador")
class ToolRailTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_unimplemented_tools_are_disabled_with_reason(self):
        rail = ToolRail()
        self.assertEqual(len(rail.buttons), len(TOOLS))
        for key in ALWAYS_DISABLED:
            button = rail.buttons[key]
            self.assertFalse(button.isEnabled(), key)
            self.assertIn("NÃO IMPLEMENTADO", button.toolTip(), key)

    def test_contextual_tools_follow_state_and_last_game(self):
        rail = ToolRail()
        self.assertFalse(rail.buttons["fullscreen"].isEnabled())
        self.assertFalse(rail.buttons["restart_app"].isEnabled())

        rail.set_runtime_state(WaydroidState.RUNNING)
        self.assertTrue(rail.buttons["fullscreen"].isEnabled())
        self.assertFalse(rail.buttons["restart_app"].isEnabled())

        rail.set_last_game(True)
        self.assertTrue(rail.buttons["restart_app"].isEnabled())

        rail.set_runtime_state(WaydroidState.FROZEN)
        self.assertFalse(rail.buttons["fullscreen"].isEnabled())
        self.assertFalse(rail.buttons["restart_app"].isEnabled())

    def test_click_emits_only_for_enabled_tools(self):
        rail = ToolRail()
        received = []
        rail.tool_requested.connect(received.append)
        rail.buttons["controls"].click()
        self.assertEqual(received, ["controls"])
        rail.buttons["screenshot"].click()
        self.assertEqual(received, ["controls"])


@unittest.skipUnless(PYSIDE_AVAILABLE, "PySide6 não está instalado neste interpretador")
class ToolRailMainWindowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.old_data_dir = storage.DATA_DIR
        self.temp = tempfile.TemporaryDirectory()
        storage.DATA_DIR = Path(self.temp.name)

    def tearDown(self):
        storage.DATA_DIR = self.old_data_dir
        self.temp.cleanup()

    def _window(self):
        window = MainWindow()
        window._original_service = window.waydroid.service
        window.waydroid.service = FakeToolService()
        return window

    def _close(self, window):
        window.waydroid.service = window._original_service
        window.close()

    def test_navigation_tools_switch_screen(self):
        window = self._window()
        try:
            window._handle_tool("settings")
            self.assertIs(window.stack.currentWidget(), window.settings)
            window._handle_tool("controls")
            self.assertIs(window.stack.currentWidget(), window.controls)
            window._handle_tool("adb")
            self.assertIs(window.stack.currentWidget(), window.waydroid)
        finally:
            self._close(window)

    def test_fullscreen_uses_service_when_running(self):
        window = self._window()
        try:
            window.waydroid.state = WaydroidState.FROZEN
            with patch("linuxdroid.main_window.QMessageBox.warning"):
                window._handle_tool("fullscreen")
            self.assertEqual(window.waydroid.service.fullscreen, 0)

            window.waydroid.state = WaydroidState.RUNNING
            window._handle_tool("fullscreen")
            self.assertEqual(window.waydroid.service.fullscreen, 1)
            self.assertIn("resolução não alterada", window.status_label.text())
        finally:
            self._close(window)

    def test_restart_tool_requires_an_accepted_last_game(self):
        window = self._window()
        try:
            window.waydroid.state = WaydroidState.RUNNING
            window._handle_tool("restart_app")
            self.assertEqual(window.waydroid.service.launched, [])

            game = GameEntry("Jogo", "com.example.jogo", installed_status="installed")
            window._last_game = game
            window.tool_rail.set_last_game(True)
            window._handle_tool("restart_app")
            self.assertEqual(window.waydroid.service.launched, [game.package_id])
        finally:
            self._close(window)


if __name__ == "__main__":
    unittest.main()
