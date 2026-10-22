"""A tiny in-memory sliding-window limiter (single API process; resets on restart)."""
from __future__ import annotations

import threading
import time
from collections import defaultdict, deque


class SlidingWindow:
    """Allow at most `limit` events per `window` seconds for each key. limit <= 0 disables it."""

    def __init__(self) -> None:
        self._events: dict[object, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def allow(self, key: object, limit: int, window: float) -> bool:
        if limit <= 0:
            return True
        now = time.monotonic()
        with self._lock:
            q = self._events[key]
            while q and now - q[0] > window:
                q.popleft()
            if len(q) >= limit:
                return False
            q.append(now)
            if len(self._events) > 10_000:  # keep memory bounded
                for k in [k for k, v in self._events.items() if not v or now - v[-1] > window]:
                    self._events.pop(k, None)
            return True

    def retry_after(self, key: object, window: float) -> int:
        with self._lock:
            q = self._events.get(key)
            if not q:
                return 1
            return max(1, int(window - (time.monotonic() - q[0])) + 1)

    def clear(self) -> None:
        with self._lock:
            self._events.clear()


new_sessions = SlidingWindow()
