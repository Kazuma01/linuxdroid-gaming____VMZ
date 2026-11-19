"""Remoção de apps na biblioteca: confirmação, estado ativo e sem comandos reais."""
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
    from PySide6.QtWidgets import QApplication, QPushButton

    from linuxdroid.main_window import MainWindow
    from linuxdroid.screens.library import LibraryScreen
    from linuxdroid.widgets.game_card import GameCard


class FakeRemoveService:
    def __init__(self, ok=True):
        self.ok = ok
        self.calls = []

    def remove_app(self, package_id, callback=None):
        self.calls.append(package_id)
        if callback is not None:
            callback(CommandResult("waydroid", ["app", "remove", package_id], 0 if self.ok else 1))

    def shutdown(self):
        return None


@unittest.skipUnless(PYSIDE_AVAILABLE, "PySide6 não está instalado neste interpretador")
class RemoveAppGuiTests(unittest.TestCase):
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

    def test_remove_button_only_for_confirmed_installed_package(self):
        confirmed = GameEntry("Jogo", "com.example.jogo", installed_status="installed")
        self.assertTrue(GameCard(confirmed).remove_btn.isEnabled())

        unconfirmed = GameEntry("Jogo", "com.example.jogo")
        self.assertFalse(GameCard(unconfirmed).remove_btn.isEnabled())

        no_package = GameEntry("Jogo", installed_status="installed")
        self.assertFalse(GameCard(no_package).remove_btn.isEnabled())

        card = GameCard(confirmed)
        received = []
        card.remove_clicked.connect(received.append)
        card.remove_btn.click()
        self.assertEqual(received, [confirmed])

    def test_library_forwards_remove_request(self):
        game = GameEntry("Jogo", "com.example.jogo", installed_status="installed")
        screen = LibraryScreen([game])
        received = []
        screen.remove_requested.connect(received.append)
        cards = screen.scroll.widget().findChildren(GameCard)
        cards[0].remove_btn.click()
        self.assertEqual(received, [game])

    def _window(self, game, service):
        window = MainWindow()
        window.games = [game]
        window.library.games = window.games
        window.library.refresh()
        window._original_service = window.waydroid.service
        window.waydroid.service = service
        return window

    def _close(self, window):
        # Restaura o serviço real para que a QThread do bridge seja encerrada.
        window.waydroid.service = window._original_service
        window.close()

    def test_decline_does_not_call_service(self):
        game = GameEntry("Jogo", "com.example.jogo", installed_status="installed",
                         last_launched_at="2026-01-01T00:00:00")
        service = FakeRemoveService()
        window = self._window(game, service)
        window.confirm_remove = lambda _game: False
        try:
            with patch("linuxdroid.main_window.QMessageBox.warning"):
                window.remove_game(game)
            self.assertEqual(service.calls, [])
            self.assertEqual(game.installed_status, "installed")
            self.assertTrue(game.last_launched_at)
        finally:
            self._close(window)

    def test_confirmed_removal_updates_local_record(self):
        game = GameEntry("Jogo", "com.example.jogo", installed_status="installed",
                         last_launched_at="2026-01-01T00:00:00")
        service = FakeRemoveService()
        window = self._window(game, service)
        window.waydroid.state = WaydroidState.RUNNING
        window.confirm_remove = lambda _game: True
        try:
            with patch("linuxdroid.main_window.QMessageBox.warning"):
                window.remove_game(game)
            self.assertEqual(service.calls, ["com.example.jogo"])
            self.assertEqual(game.installed_status, "missing")
            self.assertEqual(game.last_launched_at, "")
            self.assertIn("comando de remoção aceito", window.status_label.text())
        finally:
            self._close(window)

    def test_frozen_container_refuses_removal(self):
        game = GameEntry("Jogo", "com.example.jogo", installed_status="installed")
        service = FakeRemoveService()
        window = self._window(game, service)
        window.waydroid.state = WaydroidState.FROZEN
        window.confirm_remove = lambda _game: True
        try:
            with patch("linuxdroid.main_window.QMessageBox.warning"):
                window.remove_game(game)
            self.assertEqual(service.calls, [])
            self.assertEqual(game.installed_status, "installed")
        finally:
            self._close(window)


if __name__ == "__main__":
    unittest.main()
