from __future__ import annotations

import re
from typing import Any


APP_ALIASES = {
    "chrome": "chrome",
    "google chrome": "chrome",
    "کروم": "chrome",
    "گوگل کروم": "chrome",
    "edge": "edge",
    "مایکروسافت اج": "edge",
    "اج": "edge",
    "notepad": "notepad",
    "نوت پد": "notepad",
    "نوت‌پد": "notepad",
    "calculator": "calculator",
    "ماشین حساب": "calculator",
    "explorer": "explorer",
    "فایل اکسپلورر": "explorer",
}

WEB_ALIASES = {
    "گوگل": "https://www.google.com",
    "google": "https://www.google.com",
    "یوتیوب": "https://www.youtube.com",
    "youtube": "https://www.youtube.com",
    "چت جی پی تی": "https://chatgpt.com",
    "chatgpt": "https://chatgpt.com",
    "chatgpt.com": "https://chatgpt.com",
    "کلود": "https://claude.ai",
    "claude": "https://claude.ai",
}


def _fa(text: str) -> bool:
    return bool(re.search(r"[\u0600-\u06FF]", text))


def fast_plan(text: str, language: str | None = None) -> dict[str, Any] | None:
    value = text.strip()
    lower = value.lower()
    is_fa = language == "fa" or (language is None and _fa(value))

    # Very common open-app commands.
    open_words = ["باز کن", "بازش کن", "اجرا کن", "open", "launch", "start"]
    if any(word in lower for word in open_words):
        for alias, app in APP_ALIASES.items():
            if alias in lower:
                return {
                    "ok": True,
                    "plan": {
                        "reply": (
                            f"{alias} را باز می‌کنم."
                            if is_fa
                            else f"Opening {alias}."
                        ),
                        "actions": [
                            {
                                "tool": "open_application",
                                "args": {"app": app},
                            }
                        ],
                        "needs_confirmation": False,
                    },
                    "provider": "fast-path",
                }

        for alias, url in WEB_ALIASES.items():
            if alias in lower:
                return {
                    "ok": True,
                    "plan": {
                        "reply": (
                            f"{alias} را باز می‌کنم."
                            if is_fa
                            else f"Opening {alias}."
                        ),
                        "actions": [
                            {
                                "tool": "open_website",
                                "args": {"url": url},
                            }
                        ],
                        "needs_confirmation": False,
                    },
                    "provider": "fast-path",
                }

    return None
