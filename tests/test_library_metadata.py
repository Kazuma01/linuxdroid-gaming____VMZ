"""Filtro, ordenação e registro de metadados da biblioteca (sem Qt)."""
from datetime import datetime, timezone
import unittest

from linuxdroid.models import GameEntry
from linuxdroid.services.library_metadata import (
    STATE_ALL,
    STATE_INSTALLED,
    STATE_LAUNCHED,
    STATE_UNCONFIRMED,
    STATES,
    categories,
    filtered_games,
    recent_games,
    record_launch,
    sorted_games,
)


def game(name, package="", **kwargs):
    return GameEntry(name=name, package_id=package, **kwargs)


class LibraryMetadataTests(unittest.TestCase):
    def test_categories_are_unique_stripped_and_sorted(self):
        games = [
            game("A", category="  RPG "),
            game("B", category="Corrida"),
            game("C", category="RPG"),
            game("D", category="   "),
            game("E"),
        ]
        self.assertEqual(categories(games), ["Corrida", "RPG"])

    def test_filter_by_name_and_package_is_case_insensitive(self):
        games = [game("Free Fire", "com.dts.freefireth"), game("Outro", "br.empresa.jogo")]
        self.assertEqual([g.name for g in filtered_games(games, term="FREE")], ["Free Fire"])
        self.assertEqual([g.name for g in filtered_games(games, term="DTS")], ["Free Fire"])
        self.assertEqual([g.name for g in filtered_games(games, term="  jogo ")], ["Outro"])

    def test_filter_favorites_and_category_combine(self):
        games = [
            game("A", category="RPG", favorite=True),
            game("B", category="RPG"),
            game("C", category="Ação", favorite=True),
        ]
        self.assertEqual([g.name for g in filtered_games(games, favorites_only=True)], ["A", "C"])
        self.assertEqual(
            [g.name for g in filtered_games(games, favorites_only=True, category="RPG")], ["A"]
        )
        self.assertEqual([g.name for g in filtered_games(games, category="Ação")], ["C"])

    def test_state_filters_use_only_recorded_data(self):
        games = [
            game("Instalado", "a.b.c", installed_status="installed"),
            game("Ausente", "d.e.f", installed_status="missing"),
            game("Sem confirmação", "g.h.i"),
        ]
        self.assertEqual(len(STATES), 4)
        self.assertEqual(STATES[0], STATE_ALL)
        self.assertEqual(
            [g.name for g in filtered_games(games, state=STATE_INSTALLED)], ["Instalado"]
        )
        self.assertEqual(
            [g.name for g in filtered_games(games, state=STATE_UNCONFIRMED)],
            ["Ausente", "Sem confirmação"],
        )
        self.assertEqual([g.name for g in filtered_games(games, state=STATE_ALL)],
                         ["Instalado", "Ausente", "Sem confirmação"])

    def test_launched_filter_means_command_accepted_not_game_running(self):
        games = [
            game("Com Registro", "a.b.c", last_launched_at="2026-11-19T10:00:00+00:00"),
            game("Sem Registro", "d.e.f"),
        ]
        result = filtered_games(games, state=STATE_LAUNCHED)
        self.assertEqual([g.name for g in result], ["Com Registro"])
        # O campo é um registro local; nenhum campo "em execução" é inventado.
        self.assertTrue(result[0].last_launched_at)
        self.assertFalse(hasattr(result[0], "running"))

    def test_state_filter_combines_with_search_and_favorites(self):
        games = [
            game("FF", "com.dts.freefireth", favorite=True, installed_status="installed",
                 last_launched_at="2026-11-19T10:00:00+00:00"),
            game("Outro", "br.empresa.outro", installed_status="installed"),
        ]
        result = filtered_games(
            games, term="free", favorites_only=True, state=STATE_INSTALLED
        )
        self.assertEqual([g.name for g in result], ["FF"])
        self.assertEqual(
            [g.name for g in filtered_games(
                games, term="free", favorites_only=True, state=STATE_LAUNCHED
            )], ["FF"]
        )

    def test_sort_by_name_does_not_mutate_input(self):
        games = [game("Z"), game("A")]
        result = sorted_games(games, order="name")
        self.assertEqual([g.name for g in result], ["A", "Z"])
        self.assertEqual([g.name for g in games], ["Z", "A"])
        self.assertIsNot(result, games)

    def test_sort_by_recent_puts_never_launched_last(self):
        games = [
            game("Sem registro"),
            game("Recente", last_launched_at="2026-11-19T10:00:00+00:00"),
            game("Antigo", last_launched_at="2026-01-01T10:00:00+00:00"),
        ]
        result = sorted_games(games, order="recent")
        self.assertEqual([g.name for g in result], ["Recente", "Antigo", "Sem registro"])

    def test_sort_by_favorites_prefers_favorites_then_recent(self):
        games = [
            game("Favorito antigo", favorite=True, last_launched_at="2026-01-01T00:00:00+00:00"),
            game("Não favorito recente", last_launched_at="2026-11-19T00:00:00+00:00"),
            game("Favorito recente", favorite=True, last_launched_at="2026-11-18T00:00:00+00:00"),
        ]
        result = sorted_games(games, order="favorites")
        self.assertEqual(result[0].name, "Favorito recente")
        self.assertEqual({g.name for g in result[1:]}, {"Favorito antigo", "Não favorito recente"})

    def test_recent_games_respects_limit_and_never_invents_history(self):
        games = [game(f"J{i}") for i in range(12)]
        result = recent_games(games, 8)
        self.assertEqual(len(result), 8)
        self.assertFalse(any(g.last_launched_at for g in result))
        self.assertEqual(recent_games([], 8), [])
        self.assertEqual(recent_games(games, 0), [])

    def test_record_launch_uses_utc_and_is_injectable(self):
        entry = game("Jogo")
        moment = datetime(2026, 11, 19, 12, 34, 56, tzinfo=timezone.utc)
        returned = record_launch(entry, when=moment)
        self.assertIs(returned, entry)
        self.assertEqual(entry.last_launched_at, "2026-11-19T12:34:56+00:00")
        self.assertEqual(entry.launch_count, 1)

        record_launch(entry, when=moment, count=False)
        self.assertEqual(entry.launch_count, 1)
        self.assertEqual(entry.last_launched_at, "2026-11-19T12:34:56+00:00")

    def test_launch_record_is_serializable_by_storage_contract(self):
        entry = game("Jogo", favorite=True, category="Ação")
        record_launch(entry, when=datetime(2026, 11, 19, tzinfo=timezone.utc))
        data = entry.to_dict()
        self.assertEqual(data["favorite"], True)
        self.assertEqual(data["category"], "Ação")
        self.assertEqual(data["launch_count"], 1)
        restored = GameEntry(**data)
        self.assertEqual(restored.last_launched_at, entry.last_launched_at)


if __name__ == "__main__":
    unittest.main()
