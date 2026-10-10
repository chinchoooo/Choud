"""Small in-memory rate limiter for the auth endpoints (Phase 10-lite).

A sliding window per (bucket, client IP): at most `max_calls` requests in the
last `window_seconds`, then `429 Too Many Requests` with a `Retry-After`
header. It exists to make password guessing and registration spam slow, not to
be a general DDoS defence - for a personal server that is the right size
(Rule 2: no extra dependency, no Redis).

Limits of this design, deliberately accepted:
- State lives in process memory, so it resets when the backend restarts and is
  per-process (the backend runs a single uvicorn process).
- The client IP comes from `X-Forwarded-For`, which the Caddy reverse proxy
  sets. That is only trustworthy because the backend is reachable *only*
  through the proxy (docker-compose.yml publishes no backend port). If you
  ever expose the backend directly, a client can spoof the header.
"""

import threading
import time
from collections import defaultdict, deque

from fastapi import HTTPException, Request

from app.core.config import get_settings

_lock = threading.Lock()
_hits: dict[tuple[str, str], deque[float]] = defaultdict(deque)


def client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        # "client, proxy1, proxy2": the first entry is the original client.
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def reset() -> None:
    """Forget all recorded requests (used by tests)."""
    with _lock:
        _hits.clear()


def rate_limit(bucket: str, max_calls: int, window_seconds: int):
    """FastAPI dependency factory: `Depends(rate_limit("login", 10, 60))`."""

    def dependency(request: Request) -> None:
        if not get_settings().rate_limit_enabled:
            return
        now = time.monotonic()
        key = (bucket, client_ip(request))
        with _lock:
            window = _hits[key]
            while window and now - window[0] >= window_seconds:
                window.popleft()
            if len(window) >= max_calls:
                retry_after = max(1, int(window_seconds - (now - window[0])) + 1)
                raise HTTPException(
                    status_code=429,
                    detail="Too many requests - slow down and try again shortly.",
                    headers={"Retry-After": str(retry_after)},
                )
            window.append(now)

    return dependency
