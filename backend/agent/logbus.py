from __future__ import annotations

"""Structured technical-log bus for the Smartis log panel.

The Flutter panel shows categorised entries (SYSTEM / MEDIA / EXECUTOR /
FAST_PATH / PLANNER / STT / CONFIRMATION). Those entries are produced here and
streamed over the existing WebSocket as {"type": "log", ...} frames.

This module is purely additive: if nothing subscribes, it costs almost nothing.
"""

import threading
import time
from collections import deque
from typing import Any

CATEGORIES = ("SYSTEM", "MEDIA", "EXECUTOR", "FAST_PATH", "PLANNER", "STT", "CONFIRMATION", "ROUTER", "CHAT", "OLLAMA")


class LogBus:
    def __init__(self, max_entries: int = 400) -> None:
        self._lock = threading.Lock()
        self._entries: deque[dict[str, Any]] = deque(maxlen=max_entries)
        self._subscribers: set = set()
        self._seq = 0
        # Lets the UI de-duplicate entries re-sent after a WebSocket reconnect.
        self.session = str(int(time.time()))

    def subscribe(self):
        import queue as _queue
        q: "_queue.Queue" = _queue.Queue(maxsize=400)
        with self._lock:
            self._subscribers.add(q)
        return q

    def unsubscribe(self, q) -> None:
        with self._lock:
            self._subscribers.discard(q)

    def emit(self, category: str, message: str, detail: str | None = None) -> dict[str, Any]:
        cat = str(category or "SYSTEM").upper()
        if cat not in CATEGORIES:
            cat = "SYSTEM"
        with self._lock:
            self._seq += 1
            entry = {
                "type": "log",
                "id": self._seq,
                "session": self.session,
                "category": cat,
                "message": str(message or ""),
                "detail": (str(detail) if detail else None),
                "timestamp": time.time(),
                "time": time.strftime("%H:%M:%S"),
            }
            self._entries.append(entry)
            subscribers = tuple(self._subscribers)
        for q in subscribers:
            try:
                q.put_nowait(entry)
            except Exception:
                try:
                    q.get_nowait()
                    q.put_nowait(entry)
                except Exception:
                    pass
        return entry

    def recent(self, limit: int = 200) -> list[dict[str, Any]]:
        with self._lock:
            return list(self._entries)[-max(1, int(limit)):]

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()


logbus = LogBus()
