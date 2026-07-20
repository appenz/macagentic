from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from threading import RLock
from typing import Any


@dataclass(frozen=True)
class ConversationEvent:
    kind: str
    payload: Any


class ConversationLog:
    """Thread-safe, append-only application ledger for one conversation."""

    def __init__(self) -> None:
        self._events: list[ConversationEvent] = []
        self._lock = RLock()

    def append_message(self, message: dict) -> None:
        self.append("message", message)

    def append(self, kind: str, payload: Any) -> None:
        event = ConversationEvent(kind=kind, payload=deepcopy(payload))
        with self._lock:
            self._events.append(event)

    def snapshot(self) -> tuple[ConversationEvent, ...]:
        with self._lock:
            return tuple(deepcopy(self._events))

    def __len__(self) -> int:
        with self._lock:
            return len(self._events)
