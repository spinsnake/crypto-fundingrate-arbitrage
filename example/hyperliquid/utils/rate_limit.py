"""Basic rate-limit trackers (placeholder)."""

from __future__ import annotations

import time
from dataclasses import dataclass


@dataclass
class RateLimitTracker:
    interval: float
    max_calls: int
    _calls: int = 0
    _window_start: float = time.time()

    def allow(self) -> bool:
        now = time.time()
        if now - self._window_start >= self.interval:
            self._window_start = now
            self._calls = 0
        if self._calls >= self.max_calls:
            return False
        self._calls += 1
        return True


__all__ = ["RateLimitTracker"]
