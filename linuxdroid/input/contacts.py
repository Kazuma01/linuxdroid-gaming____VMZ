"""Gerenciador central de contatos multitouch.

Nenhum tipo de controle administra slots por conta propria. O gerenciador
garante: slots 0..254, 255 reservado, IDs estaveis, DOWN antes de MOVE, UP
exatamente uma vez, nenhum MOVE apos UP e liberacao total apos excecao.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, replace

from ..services.capabilities import TouchInjectBackend

RESERVED_SLOT = 255
MAX_SLOTS = 255  # 0..254


class ContactManagerError(RuntimeError):
    """Violacao das regras de contato ou falha do backend."""


class SlotExhausted(ContactManagerError):
    """Nao ha slot livre para novo contato."""


class InvalidContact(ContactManagerError):
    """Operacao pedida para contato inexistente."""


@dataclass(frozen=True)
class Contact:
    contact_id: int
    key: str
    slot: int
    x: float
    y: float
    started_at: float
    profile_name: str = ""
    source_event_id: int | None = None

    def to_dict(self) -> dict:
        return {
            "contact_id": self.contact_id,
            "key": self.key,
            "slot": self.slot,
            "x": self.x,
            "y": self.y,
            "started_at": self.started_at,
            "profile_name": self.profile_name,
            "source_event_id": self.source_event_id,
        }


class ContactManager:
    """Estado central de todos os contatos logicamente ativos."""

    def __init__(
        self,
        backend: TouchInjectBackend,
        *,
        clock=None,
        profile_name: str = "",
        max_touches: int | None = None,
    ) -> None:
        import time

        self.backend = backend
        self.clock = clock or time.monotonic
        self.profile_name = profile_name
        backend_limit = getattr(backend, "max_concurrent_touches", lambda: MAX_SLOTS)()
        self.max_touches = max(1, min(int(max_touches or MAX_SLOTS), int(backend_limit or MAX_SLOTS), MAX_SLOTS))
        self._active: dict[str, Contact] = {}
        self._slot_owner: dict[int, str] = {}
        self._next_contact_id = 1
        self.stats = {
            "down": 0,
            "move": 0,
            "up": 0,
            "cancel": 0,
            "duplicate_down_ignored": 0,
            "duplicate_up_ignored": 0,
            "move_without_down": 0,
            "exceptions_recovered": 0,
        }

    @property
    def active_contacts(self) -> tuple[Contact, ...]:
        return tuple(sorted(self._active.values(), key=lambda contact: contact.slot))

    @property
    def active_slots(self) -> tuple[int, ...]:
        return tuple(sorted(self._slot_owner))

    def has(self, key: str) -> bool:
        return key in self._active

    def get(self, key: str) -> Contact | None:
        return self._active.get(key)

    def down(
        self,
        key: str,
        x: float,
        y: float,
        *,
        event_id: int | None = None,
        timestamp: float | None = None,
        idempotent: bool = True,
        preferred_slot: int | None = None,
    ) -> Contact:
        """Cria contato. DOWN duplicado e ignorado quando `idempotent`."""
        if key in self._active:
            if idempotent:
                self.stats["duplicate_down_ignored"] += 1
                return self._active[key]
            raise ContactManagerError(f"DOWN duplicado para {key!r}.")
        if len(self._active) >= self.max_touches:
            raise SlotExhausted(
                f"Limite de {self.max_touches} contatos simultaneos atingido; nenhum slot alocado."
            )
        x, y = self._validated_position(x, y)
        slot = self._allocate_slot(preferred_slot)
        contact = Contact(
            contact_id=self._next_contact_id,
            key=key,
            slot=slot,
            x=x,
            y=y,
            started_at=self.clock() if timestamp is None else float(timestamp),
            profile_name=self.profile_name,
            source_event_id=event_id,
        )
        try:
            self.backend.down(
                x,
                y,
                slot,
                timestamp=contact.started_at,
                profile_name=self.profile_name,
                contact_id=contact.contact_id,
                event_id=event_id,
            )
        except Exception:
            self._recover_backend()
            self.stats["exceptions_recovered"] += 1
            raise
        self._next_contact_id += 1
        self._active[key] = contact
        self._slot_owner[slot] = key
        self.stats["down"] += 1
        return contact

    def move(
        self,
        key: str,
        x: float,
        y: float,
        *,
        event_id: int | None = None,
        timestamp: float | None = None,
    ) -> Contact | None:
        """MOVE so e entregue para contato que teve DOWN e ainda nao teve UP."""
        contact = self._active.get(key)
        if contact is None:
            self.stats["move_without_down"] += 1
            raise InvalidContact(f"MOVE sem DOWN ativo para {key!r}.")
        x, y = self._validated_position(x, y)
        moved = replace(contact, x=x, y=y)
        try:
            self.backend.move(
                x,
                y,
                contact.slot,
                timestamp=self.clock() if timestamp is None else float(timestamp),
                profile_name=self.profile_name,
                contact_id=contact.contact_id,
                event_id=event_id,
            )
        except Exception:
            self.release_all(reason="backend_exception")
            self._recover_backend()
            self.stats["exceptions_recovered"] += 1
            raise
        self._active[key] = moved
        self.stats["move"] += 1
        return moved

    def up(
        self,
        key: str,
        *,
        event_id: int | None = None,
        timestamp: float | None = None,
        strict: bool = False,
    ) -> Contact | None:
        """UP exatamente uma vez; repeticoes sao ignoradas com estatistica."""
        contact = self._active.get(key)
        if contact is None:
            if strict:
                raise InvalidContact(f"UP sem DOWN ativo para {key!r}.")
            self.stats["duplicate_up_ignored"] += 1
            return None
        self._remove(key)
        try:
            self.backend.up(
                contact.slot,
                timestamp=self.clock() if timestamp is None else float(timestamp),
                profile_name=self.profile_name,
                contact_id=contact.contact_id,
                event_id=event_id,
            )
        except Exception:
            self._recover_backend()
            self.stats["exceptions_recovered"] += 1
            raise
        self.stats["up"] += 1
        return contact

    def cancel(
        self,
        key: str,
        *,
        reason: str = "safe_release",
        timestamp: float | None = None,
    ) -> Contact | None:
        contact = self._active.get(key)
        if contact is None:
            return None
        self._remove(key)
        cancel_backend = getattr(self.backend, "cancel", None)
        if callable(cancel_backend):
            try:
                cancel_backend(
                    contact.slot,
                    timestamp=self.clock() if timestamp is None else float(timestamp),
                    profile_name=self.profile_name,
                    contact_id=contact.contact_id,
                    reason=reason,
                )
            except Exception:
                self._recover_backend()
                self.stats["exceptions_recovered"] += 1
                raise
        else:
            try:
                self.backend.up(contact.slot)
            except Exception:
                self._recover_backend()
                self.stats["exceptions_recovered"] += 1
                raise
        self.stats["cancel"] += 1
        return contact

    def release_all(self, *, reason: str = "safe_release", timestamp: float | None = None) -> tuple[Contact, ...]:
        """Libera todos os contatos, mesmo se o backend falhar parcialmente."""
        released: list[Contact] = []
        for contact in self.active_contacts:
            try:
                result = self.cancel(contact.key, reason=reason, timestamp=timestamp)
            except Exception:
                self._recover_backend()
                self.stats["exceptions_recovered"] += 1
                break
            if result is not None:
                released.append(result)
        self._clear_all()
        return tuple(released)

    def _remove(self, key: str) -> None:
        contact = self._active.pop(key, None)
        if contact is not None:
            self._slot_owner.pop(contact.slot, None)

    def _clear_all(self) -> None:
        self._active.clear()
        self._slot_owner.clear()

    def _recover_backend(self) -> None:
        """Tenta liberar tambem o lado do backend antes de descartar o estado."""
        try:
            release_all = getattr(self.backend, "release_all", None)
            if callable(release_all):
                release_all()
        except Exception:
            # O estado local ainda e descartado: nunca deixar contato preso no
            # gerenciador, mesmo se o backend tambem estiver falhando.
            pass
        self._clear_all()

    def _allocate_slot(self, preferred: int | None = None) -> int:
        used = set(self._slot_owner)
        if preferred is not None and isinstance(preferred, int) and not isinstance(preferred, bool):
            if preferred == RESERVED_SLOT:
                raise SlotExhausted("Slot 255 e reservado; nao pode ser usado por contato.")
            if 0 <= preferred < MAX_SLOTS and preferred not in used:
                return preferred
        for slot in range(MAX_SLOTS):
            if slot not in used:
                return slot
        raise SlotExhausted("Nenhum slot 0..254 disponivel.")

    @staticmethod
    def _validated_position(x, y) -> tuple[float, float]:
        try:
            fx, fy = float(x), float(y)
        except (TypeError, ValueError) as error:
            raise ContactManagerError("Coordenadas precisam ser numericas.") from error
        if not (math.isfinite(fx) and math.isfinite(fy)) or not (0 <= fx <= 1 and 0 <= fy <= 1):
            raise ContactManagerError("Coordenadas precisam estar em [0, 1].")
        return fx, fy


__all__ = [
    "RESERVED_SLOT",
    "MAX_SLOTS",
    "Contact",
    "ContactManager",
    "ContactManagerError",
    "SlotExhausted",
    "InvalidContact",
]
