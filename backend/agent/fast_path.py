from __future__ import annotations

import re
from typing import Any

_CHAR_MAP = str.maketrans({
    "ي": "ی",
    "ى": "ی",
    "ئ": "ی",
    "ك": "ک",
    "ة": "ه",
    "ؤ": "و",
    "أ": "ا",
    "إ": "ا",
    "آ": "ا",
})


def _normalize(text: str) -> str:
    val = str(text or "").lower().translate(_CHAR_MAP).replace("\u200c", " ")
    val = re.sub(r"[^\w\u0600-\u06FF\s]+", " ", val, flags=re.UNICODE)
    return " ".join(val.split())


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
    "یادداشت": "notepad",
    "calculator": "calculator",
    "ماشین حساب": "calculator",
    "حسابداری": "calculator",
    "explorer": "explorer",
    "فایل اکسپلورر": "explorer",
    "مدیریت فایل": "explorer",
    "پوشه": "explorer",
    "فایلها": "explorer",
    "فایل ها": "explorer",
}

WEB_ALIASES = {
    "گوگل": "https://www.google.com",
    "google": "https://www.google.com",
    "یوتیوب": "https://www.youtube.com",
    "youtube": "https://www.youtube.com",
    "چت جی پی تی": "https://chatgpt.com",
    "چت جی‌پی‌تی": "https://chatgpt.com",
    "chatgpt": "https://chatgpt.com",
    "chatgpt.com": "https://chatgpt.com",
    "کلود": "https://claude.ai",
    "claude": "https://claude.ai",
}

OPEN_KEYWORDS = [
    "باز کن",
    "بازش کن",
    "اجرا کن",
    "بازکردن",
    "باز کردن",
    "راه اندازی",
    "راه بنداز",
    "برو به",
    "برو توی",
    "برو تو",
    "برو داخل",
    "برو سایت",
    "open",
    "launch",
    "start",
    "run",
]


def _fa(text: str) -> bool:
    return bool(re.search(r"[\u0600-\u06FF]", text))


def fast_plan(text: str, language: str | None = None) -> dict[str, Any] | None:
    norm = _normalize(text)
    is_fa = language == "fa" or (language is None and _fa(norm))

    has_open_keyword = any(k in norm for k in OPEN_KEYWORDS)
    # If phrase has an open keyword or starts directly with "برو به"
    if not has_open_keyword and not norm.startswith("برو به"):
        return None

    # Check application aliases first
    for alias, app in APP_ALIASES.items():
        clean_alias = _normalize(alias)
        if clean_alias in norm:
            display_name = alias
            return {
                "ok": True,
                "plan": {
                    "reply": (
                        f"{display_name} را باز می‌کنم."
                        if is_fa
                        else f"Opening {display_name}."
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

    # Check web website aliases
    for alias, url in WEB_ALIASES.items():
        clean_alias = _normalize(alias)
        if clean_alias in norm:
            display_name = alias
            return {
                "ok": True,
                "plan": {
                    "reply": (
                        f"{display_name} را باز می‌کنم."
                        if is_fa
                        else f"Opening {display_name}."
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
