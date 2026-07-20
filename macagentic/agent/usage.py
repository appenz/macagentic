from __future__ import annotations

import threading
from dataclasses import dataclass


@dataclass(frozen=True)
class UsageSnapshot:
    input_tokens: int = 0
    cached_input_tokens: int = 0
    cache_write_tokens: int = 0
    output_tokens: int = 0
    cost: float = 0.0


class UsageTracker:
    """Thread-safe cumulative model usage for one conversation."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._totals = UsageSnapshot()

    def add_response(self, response: dict) -> UsageSnapshot | None:
        usage = response.get("usage")
        extra = response.get("extra") or {}
        if not isinstance(usage, dict) and "cost" not in extra:
            return None

        usage = usage if isinstance(usage, dict) else {}
        input_details = usage.get("input_tokens_details") or {}
        if not isinstance(input_details, dict):
            input_details = {}

        increment = UsageSnapshot(
            input_tokens=_integer(usage.get("input_tokens")),
            cached_input_tokens=_integer(
                input_details.get("cached_tokens")
            ),
            cache_write_tokens=_integer(
                input_details.get("cache_write_tokens")
            ),
            output_tokens=_integer(usage.get("output_tokens")),
            cost=_number(extra.get("cost")),
        )
        with self._lock:
            current = self._totals
            self._totals = UsageSnapshot(
                input_tokens=current.input_tokens + increment.input_tokens,
                cached_input_tokens=(
                    current.cached_input_tokens
                    + increment.cached_input_tokens
                ),
                cache_write_tokens=(
                    current.cache_write_tokens
                    + increment.cache_write_tokens
                ),
                output_tokens=current.output_tokens + increment.output_tokens,
                cost=current.cost + increment.cost,
            )
            return self._totals

    def snapshot(self) -> UsageSnapshot:
        with self._lock:
            return self._totals


def _integer(value: object) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _number(value: object) -> float:
    try:
        return float(value or 0.0)
    except (TypeError, ValueError):
        return 0.0
