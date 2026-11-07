"""Small anti-abuse helpers, free of Telegram and I/O so they are easy to test."""
from __future__ import annotations

import time
from typing import Callable, Hashable

_PRUNE_ABOVE = 1000  # forget expired entries once this many keys are stored


class RateLimiter:
    """Allow one action per key every ``cooldown_seconds``.

    ``is_limited`` both asks and records: it returns True when the key acted less
    than the cooldown ago, otherwise it remembers this moment and returns False.
    A refused call does not restart the cooldown, so a spammer cannot lock
    themselves out forever by hammering the bot.
    """

    def __init__(self, cooldown_seconds: float, clock: Callable[[], float] = time.monotonic) -> None:
        self._cooldown = cooldown_seconds
        self._clock = clock
        self._last: dict[Hashable, float] = {}

    def is_limited(self, key: Hashable) -> bool:
        now = self._clock()
        last = self._last.get(key)
        if last is not None and now - last < self._cooldown:
            return True
        if len(self._last) >= _PRUNE_ABOVE:
            self._last = {k: t for k, t in self._last.items() if now - t < self._cooldown}
        self._last[key] = now
        return False
