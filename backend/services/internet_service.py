from __future__ import annotations

import threading
import time

import requests

from config import INTERNET_CACHE_SECONDS, INTERNET_CHECK_TIMEOUT


class InternetMonitor:
    """Small cached connectivity check used only for TTS/network features."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._last_check = 0.0
        self._online = False

    def is_online(self, force: bool = False) -> bool:
        now = time.monotonic()
        with self._lock:
            if not force and now - self._last_check < INTERNET_CACHE_SECONDS:
                return self._online

            online = False
            for url in (
                "https://www.google.com/generate_204",
                "https://www.msftconnecttest.com/connecttest.txt",
            ):
                try:
                    response = requests.get(
                        url,
                        timeout=INTERNET_CHECK_TIMEOUT,
                        allow_redirects=True,
                    )
                    if response.status_code in (200, 204):
                        online = True
                        break
                except requests.RequestException:
                    continue

            self._last_check = now
            self._online = online
            return online
