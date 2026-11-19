"""Integração da biblioteca com favoritos, filtros e persistência — sem Waydroid real."""
from __future__ import annotations

import importlib.util
import json
import os
import tempfile
import unittest
from pathlib import Path

from linuxdroid import storage
from linuxdroid.models import GameEntry

PYSIDE_AVAILABLE = importlib.util.find_spec("PySide6") is not None
if PYSIDE_AVAILABLE:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication, QLabel, QPushButton

    from linuxdroid.screens.home import HomeScreen
    from linuxdroid.screens.library import LibraryScreen
    from linuxdroid.widgets.game_card import GameCard


@unittest.skipUnless(PYSIDE_AVAILABLE, "PySide6 não está instalado neste interpretador")
class LibraryGuiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.old_data_dir = storage.DATA_DIR
        self.temp = tempfile.TemporaryDirectory()
        storage.DATA_DIR = Path(self.temp.name)
        self.games = [
            GameEntry("Free Fire", "com.dts.freefireth", category="Ação", favorite=True),
            GameEntry("Outro jogo", "br.empresa.outro", category="RPG"),
        ]

    def tearDown(self):
        storage.DATA_DIR = self.old_data_dir
        self.temp.cleanup()

    def _cards(self, screen):
        return screen.scroll.widget().findChildren(GameCard)

    def test_card_has_play_and_favorite_buttons(self):
        card = GameCard(self.games[0], show_package=True)
        self.assertIsNotNone(card.findChild(QPushButton, "primary"))
        self.assertTrue(card.favorite_btn.isChecked())
        card.favorite_btn.setChecked(False)
        self.assertEqual(card.favorite_btn.text(), "☆")

    def test_library_search_filters_cards(self):
        screen = LibraryScreen(self.games)
        self.assertEqual(len(self._cards(screen)), 2)
        screen.search.setText("outro")
        self.assertEqual([c.game.name for c in self._cards(screen)], ["Outro jogo"])
        screen.search.setText("")
        self.assertEqual(len(self._cards(screen)), 2)

    def test_library_favorite_filter_and_order(self):
        screen = LibraryScreen(self.games)
        screen.favorites_only.setChecked(True)
        self.assertEqual([c.game.name for c in self._cards(screen)], ["Free Fire"])
        screen.favorites_only.setChecked(False)
        screen.order_combo.setCurrentIndex(screen.order_combo.findData("recent"))
        self.assertEqual(len(self._cards(screen)), 2)

    def test_library_state_filters(self):
        self.games[0].installed_status = "installed"
        self.games[0].last_launched_at = "2026-11-19T10:00:00+00:00"
        self.games[1].installed_status = "missing"
        screen = LibraryScreen(self.games)

        def select(value):
            screen.state_combo.setCurrentIndex(screen.state_combo.findData(value))

        select("installed")
        self.assertEqual([c.game.name for c in self._cards(screen)], ["Free Fire"])
        select("unconfirmed")
        self.assertEqual([c.game.name for c in self._cards(screen)], ["Outro jogo"])
        select("launched")
        self.assertEqual([c.game.name for c in self._cards(screen)], ["Free Fire"])
        select("all")
        self.assertEqual(len(self._cards(screen)), 2)

    def test_library_columns_adapt_to_available_width(self):
        screen = LibraryScreen(self.games * 3)
        self.assertEqual(screen._columns_for_width(500), 2)
        self.assertEqual(screen._columns_for_width(700), 3)
        self.assertEqual(screen._columns_for_width(1200), 4)

        screen.columns = 2
        screen.refresh()
        layout = screen.scroll.widget().layout()
        self.assertEqual(layout.getItemPosition(4)[:2], (2, 0))

        screen.columns = 4
        screen.refresh()
        layout = screen.scroll.widget().layout()
        self.assertEqual(layout.getItemPosition(4)[:2], (1, 0))

    def test_state_hint_explains_launch_record_is_not_running(self):
        screen = LibraryScreen(self.games)
        labels = [w.text() for w in screen.findChildren(QLabel)]
        self.assertTrue(any("não indica jogo em execução" in text for text in labels))

    def test_favorite_toggle_persists_to_library_json(self):
        screen = LibraryScreen(self.games)
        card = self._cards(screen)[1]
        card.favorite_btn.setChecked(True)
        self.process_events()
        saved = json.loads((storage.DATA_DIR / "library.json").read_text(encoding="utf-8"))
        self.assertEqual([g["favorite"] for g in saved], [True, True])

    def test_home_uses_recent_games_and_emits_change_on_favorite(self):
        screen = HomeScreen(self.games)
        names = [c.game.name for c in self._cards(screen)]
        self.assertEqual(len(names), 2)
        changes = []
        screen.games_changed.connect(lambda: changes.append(True))
        self._cards(screen)[0].favorite_btn.setChecked(False)
        self.assertEqual(len(changes), 1)
        self.assertFalse(self.games[0].favorite)

    def test_storage_ignores_unknown_fields_from_older_library(self):
        (storage.DATA_DIR / "library.json").write_text(
            json.dumps([{"name": "Antigo", "package_id": "a.b", "campo_futuro": 1}]),
            encoding="utf-8",
        )
        loaded = storage.load_library()
        self.assertEqual(len(loaded), 1)
        self.assertEqual(loaded[0].name, "Antigo")
        self.assertEqual(loaded[0].favorite, False)

    def process_events(self):
        self.app.processEvents()
        self.app.processEvents()


if __name__ == "__main__":
    unittest.main()
