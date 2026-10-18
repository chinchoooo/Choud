"""A simple upload speed limit, so a backup never saturates a slow connection."""

from __future__ import annotations

import time
from collections.abc import Callable


class Throttle:
    """Keeps the average rate at or under `bytes_per_second`.

    Call `acquire(n)` before sending `n` bytes: the first send goes straight away, and each later
    one waits until the time the previous one "should" have taken has passed. Averaged over a few
    sends the rate is the limit, without needing to meter inside a request.
    """

    def __init__(
        self,
        bytes_per_second: float,
        *,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        if bytes_per_second <= 0:
            raise ValueError("the limit must be positive")
        self.rate = float(bytes_per_second)
        self._clock = clock
        self._sleep = sleep
        self._free_at = 0.0

    def acquire(self, nbytes: int) -> float:
        """Waits if needed; returns how long it waited."""
        now = self._clock()
        start = max(now, self._free_at)
        self._free_at = start + max(0, nbytes) / self.rate
        wait = start - now
        if wait > 0:
            self._sleep(wait)
        return max(0.0, wait)


def from_kbps(kbps: float) -> Throttle | None:
    """A throttle for a limit in KiB/s, or None for "no limit" (0 or less)."""
    return Throttle(kbps * 1024) if kbps and kbps > 0 else None
