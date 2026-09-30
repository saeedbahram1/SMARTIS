from __future__ import annotations

"""Self-voice (echo) detection.

Root cause of the reported bug
------------------------------
While Smartis read a long Wikipedia article out loud, the Flutter side stopped
waiting for the audio player to finish (it had a hard 30 s cap) and re-enabled
the microphone. The microphone then transcribed Smartis' own voice, which became
a brand-new "command" — a feedback loop.

The primary fix is in the playback/guard path. This module is the safety net:
if a transcript is basically what Smartis just said, it is dropped instead of
being executed.
"""

import re
import threading
import time
from collections import deque
from typing import Any

from config import ECHO_SIMILARITY_THRESHOLD, ECHO_WINDOW_SECONDS

_PERSIAN_STOP = {
    "و", "در", "به", "از", "که", "این", "را", "با", "است", "برای", "آن", "یک", "خود",
    "تا", "کرد", "بر", "هم", "نیز", "می", "شد", "وی", "اما", "یا", "هر", "دارد",
    "های", "شده", "است", "های", "دارند", "بود", "می‌شود", "می‌کند", "شود", "کند",
}
_EN_STOP = {
    "the", "a", "an", "and", "or", "of", "to", "in", "on", "is", "are", "was", "were",
    "it", "this", "that", "for", "with", "as", "at", "by", "from", "be", "been",
}

_TOKEN = re.compile(r"[A-Za-z]{2,}|[\u0600-\u06FF]{2,}")


def _normalize(text: str) -> str:
    value = str(text or "").lower()
    value = value.replace("\u200c", " ").replace("\u200d", " ")
    value = re.sub(r"[^\w\u0600-\u06FF\s]", " ", value)
    return re.sub(r"\s+", " ", value).strip()


def _tokens(text: str) -> set[str]:
    out: set[str] = set()
    for token in _TOKEN.findall(_normalize(text)):
        if token in _PERSIAN_STOP or token in _EN_STOP:
            continue
        if len(token) < 3:
            continue
        out.add(token)
    return out


def _containment(new_text: str, old_text: str) -> float:
    """How much of `new_text` is already contained in `old_text` (0..1)."""
    new_norm = _normalize(new_text)
    old_norm = _normalize(old_text)
    if not new_norm or not old_norm:
        return 0.0
    if len(new_norm) >= 8 and new_norm in old_norm:
        return 1.0
    new_tokens = _tokens(new_norm)
    if not new_tokens:
        return 0.0
    old_tokens = _tokens(old_norm)
    if not old_tokens:
        return 0.0
    return len(new_tokens & old_tokens) / float(len(new_tokens))


class EchoGuard:
    """Remembers what Smartis recently said and recognises it coming back in."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._spoken: deque[tuple[float, str]] = deque(maxlen=24)

    def note_spoken(self, text: str) -> None:
        value = str(text or "").strip()
        if not value:
            return
        with self._lock:
            self._spoken.append((time.time(), value))

    def is_echo(self, text: str) -> bool:
        value = str(text or "").strip()
        if len(value) < 3:
            return False
        now = time.time()
        with self._lock:
            recent = [item for item in self._spoken if now - item[0] <= ECHO_WINDOW_SECONDS]
        for _, spoken in reversed(recent):
            if _containment(value, spoken) >= ECHO_SIMILARITY_THRESHOLD:
                return True
        return False

    def clear(self) -> None:
        with self._lock:
            self._spoken.clear()

    def stats(self) -> dict[str, Any]:
        with self._lock:
            return {"spoken_entries": len(self._spoken), "window_seconds": ECHO_WINDOW_SECONDS,
                    "threshold": ECHO_SIMILARITY_THRESHOLD}


guard = EchoGuard()
