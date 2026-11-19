"""Filtro, ordenação e registro de metadados da biblioteca (puro, sem Qt).

``last_launched_at`` registra o momento em que o comando de lançamento foi
**aceito** — não prova que o jogo abriu ou chegou ao lobby. Nenhuma alegação de
desempenho ou compatibilidade é feita a partir destes campos.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Iterable, Optional, Sequence

from ..models import GameEntry

ORDER_NAME = "name"
ORDER_RECENT = "recent"
ORDER_FAVORITES = "favorites"
ORDERS = (ORDER_NAME, ORDER_RECENT, ORDER_FAVORITES)

# Filtros de estado usam apenas dados já presentes no modelo. Não existe hoje
# uma fonte confiável que diga que um jogo específico está "em execução":
# ``last_launched_at`` registra somente que o comando de abertura foi aceito.
STATE_ALL = "all"
STATE_INSTALLED = "installed"
STATE_UNCONFIRMED = "unconfirmed"
STATE_LAUNCHED = "launched"
STATES = (STATE_ALL, STATE_INSTALLED, STATE_UNCONFIRMED, STATE_LAUNCHED)

__all__ = [
    "categories",
    "filtered_games",
    "sorted_games",
    "recent_games",
    "record_launch",
    "STATE_ALL",
    "STATE_INSTALLED",
    "STATE_UNCONFIRMED",
    "STATE_LAUNCHED",
    "STATES",
]


def categories(games: Iterable[GameEntry]) -> list[str]:
    """Categorias não vazias, em ordem alfabética e sem duplicatas."""
    return sorted({g.category.strip() for g in games if g.category and g.category.strip()})


def filtered_games(
    games: Sequence[GameEntry],
    *,
    term: str = "",
    favorites_only: bool = False,
    category: str = "",
    state: str = STATE_ALL,
) -> list[GameEntry]:
    """Filtra a biblioteca por texto, favorito, categoria e estado conhecido.

    ``state=STATE_LAUNCHED`` significa apenas "comando de lançamento aceito";
    não afirma que o jogo está aberto, ativo ou no lobby.
    """
    needle = (term or "").strip().lower()
    wanted = (category or "").strip()
    result = []
    for game in games:
        if needle and needle not in game.name.lower() and needle not in game.package_id.lower():
            continue
        if favorites_only and not game.favorite:
            continue
        if wanted and game.category.strip() != wanted:
            continue
        if state == STATE_INSTALLED and game.installed_status != STATE_INSTALLED:
            continue
        if state == STATE_UNCONFIRMED and game.installed_status == STATE_INSTALLED:
            continue
        if state == STATE_LAUNCHED and not game.last_launched_at:
            continue
        result.append(game)
    return result


def _recent_key(game: GameEntry) -> tuple:
    stamp = game.last_launched_at or ""
    return (bool(stamp), stamp)


def sorted_games(games: Sequence[GameEntry], *, order: str = ORDER_NAME) -> list[GameEntry]:
    """Devolve nova lista; nunca altera a ordem da lista fornecida."""
    result = list(games)
    if order == ORDER_RECENT:
        return sorted(result, key=_recent_key, reverse=True)
    if order == ORDER_FAVORITES:
        return sorted(
            result,
            key=lambda g: (g.favorite, *_recent_key(g), g.name.lower()),
            reverse=True,
        )
    return sorted(result, key=lambda g: g.name.lower())


def recent_games(games: Sequence[GameEntry], limit: int = 8) -> list[GameEntry]:
    """Favoritos e lançamentos recentes primeiro, sem inventar histórico."""
    ordered = sorted(
        games,
        key=lambda g: (g.favorite, *_recent_key(g), g.name.lower()),
        reverse=True,
    )
    return ordered[: max(0, limit)]


def record_launch(
    game: GameEntry,
    *,
    when: Optional[datetime] = None,
    count: bool = True,
) -> GameEntry:
    """Marca o lançamento aceito. `when` é injetável para testes."""
    moment = when or datetime.now(timezone.utc)
    game.last_launched_at = moment.isoformat(timespec="seconds")
    if count:
        game.launch_count += 1
    return game
