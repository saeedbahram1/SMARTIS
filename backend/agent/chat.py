from __future__ import annotations

"""Conversational layer for Smartis — "answer everything" behaviour.

Why this file exists
--------------------
The previous build had a hard gap: anything the deterministic fast-path did not
recognise fell through to a dead-end message ("I did not understand, try
again"). That is what made Smartis feel like a broken bot instead of an
assistant.

This module closes that gap. Every utterance that is not a Windows action is
answered like a human would answer it.

Cost: zero. Everything runs on the SAME local Ollama model that already powers
the planner (`OLLAMA_MODEL`, default `qwen2.5:7b`). No OpenAI / Gemini / any
paid cloud API is used or required.

Degradation ladder (never a dead end):
    1. local Ollama chat completion        -> "chat-local"
    2. Wikipedia / public web research     -> "chat-research"
    3. warm human-style holding reply      -> "chat-offline"
"""

import re
import threading
from typing import Any

import requests

from config import (
    CHAT_KEEP_MODEL_WARM,
    CHAT_MAX_REPLY_CHARS,
    CHAT_MAX_TOKENS,
    CHAT_MODEL,
    CHAT_TEMPERATURE,
    CHAT_TIMEOUT,
    OLLAMA_URL,
)

_PERSIAN = re.compile(r"[\u0600-\u06FF]")
_LATIN = re.compile(r"[A-Za-z]")

SYSTEM_PROMPT = r"""
تو «Smartis» هستی؛ یک دستیار صوتی فارسی‌زبان روی ویندوز، ساخته‌شده توسط تیم سعید بهرامی.
تو مثل یک انسان واقعی، باهوش، گرم و خودی حرف می‌زنی — نه مثل یک ربات پشتیبانی.

قواعد گفتگو (خیلی مهم):
1. به هر پیام کاربر جواب بده. هرگز نگو «متوجه نشدم»، «دوباره امتحان کن»، «نمی‌توانم»، «مشخص نیست» یا جملات کلیشه‌ای مشابه.
2. اگر بخشی از حرف کاربر مبهم بود، محتمل‌ترین برداشت را انتخاب کن، جواب بده و در صورت نیاز یک سؤال کوتاه و طبیعی بپرس.
3. زبان پاسخ را دقیقاً با زبان کاربر هماهنگ کن: فارسی → فارسی روان و محاوره‌ای، انگلیسی → انگلیسی روان.
4. پاسخ‌ها باید قابل خواندن با صدا باشند: معمولاً ۱ تا ۴ جمله. از مارک‌داون، بولت، ستاره، هشتگ و ایموجی استفاده نکن.
5. عددها، درصد و واحدها را همان‌طور که باید خوانده شوند بنویس (مثال: «۲۰ درصد»).
6. اگر سؤال دانشی پرسید، دقیق و صادقانه جواب بده. اگر واقعاً نمی‌دانی، صریح بگو که دقیق مطمئن نیستی و بهترین حدس یا راهنمایی را بده.
7. تو دستیار سیستم هم هستی: می‌توانی برنامه باز کنی، صدا را کم و زیاد کنی، موسیقی پخش کنی، فایل بسازی، آب‌وهوا و اخبار بگویی.
   اما در همین پاسخ فقط حرف بزن؛ سیستم فرمان‌ها را جداگانه اجرا می‌کند. لازم نیست بگویی «در حال اجرا».
8. هیچ‌وقت ادعا نکن کاری را انجام داده‌ای که انجام نشده.
9. اگر کاربر شوخی کرد، با همان لحن گرم و کمی طنز جواب بده. خشک و اداری نباش.
10. معرفی خودت: «من Smartis هستم» و سازنده‌ات «تیم سعید بهرامی» است.
11. از گفتن «به عنوان یک هوش مصنوعی...» پرهیز کن. طبیعی و انسانی حرف بزن.
"""

_MARKDOWN_NOISE = re.compile(r"(\*\*|__|`{1,3}|^#{1,6}\s*|^\s*[-*•]\s+)", re.M)
_MULTI_SPACE = re.compile(r"[ \t\u00a0]+")
_MULTI_NEWLINE = re.compile(r"\n{2,}")


def _is_fa(text: str, language: str | None = None) -> bool:
    """The transcript script is the authority; the STT hint is only a tie-break."""
    if _PERSIAN.search(text or ""):
        return True
    if _LATIN.search(text or ""):
        return False
    return language != "en"


def _clean(reply: str) -> str:
    value = str(reply or "").strip()
    value = _MARKDOWN_NOISE.sub(" ", value)
    value = _MULTI_NEWLINE.sub(" ", value)
    value = _MULTI_SPACE.sub(" ", value).strip()
    # Drop a leading label the model sometimes adds on its own.
    value = re.sub(r"^(?:Smartis|اسمارتیز|دستیار|پاسخ)\s*[:：\-]\s*", "", value, flags=re.I)
    if len(value) > CHAT_MAX_REPLY_CHARS:
        cut = value[:CHAT_MAX_REPLY_CHARS]
        stop = max(cut.rfind("."), cut.rfind("؟"), cut.rfind("!"), cut.rfind("،"))
        value = cut[: stop + 1] if stop > 200 else cut
    return value.strip()


def _ollama_reply(text: str, language: str, context: str = "") -> str | None:
    instruction = (
        "\nDETECTED LANGUAGE=Persian. پاسخ باید کاملاً فارسی و روان باشد."
        if language == "fa"
        else "\nDETECTED LANGUAGE=English. The reply MUST be fluent English."
    )
    messages: list[dict[str, str]] = [{"role": "system", "content": SYSTEM_PROMPT + instruction}]
    if context:
        messages.append(
            {
                "role": "system",
                "content": "RECENT LOCAL CONVERSATION (use it for follow-ups):\n" + str(context)[:2000],
            }
        )
    messages.append({"role": "user", "content": text})

    payload: dict[str, Any] = {
        "model": CHAT_MODEL,
        "stream": False,
        "messages": messages,
        "options": {
            "temperature": CHAT_TEMPERATURE,
            "top_p": 0.9,
            "repeat_penalty": 1.12,
            "num_predict": CHAT_MAX_TOKENS,
        },
    }
    if not CHAT_KEEP_MODEL_WARM:
        payload["keep_alive"] = 0
    else:
        payload["keep_alive"] = "30m"

    try:
        response = requests.post(f"{OLLAMA_URL}/api/chat", json=payload, timeout=CHAT_TIMEOUT)
        response.raise_for_status()
        data = response.json()
        reply = _clean(data.get("message", {}).get("content", ""))
        return reply or None
    except Exception:
        return None


def _knowledge_reply(text: str, language: str) -> str | None:
    """Wikipedia-first public-web research, used only when the local model fails."""
    try:
        from services.research_service import research

        result = research(text, "fa" if language == "fa" else "en")
    except Exception:
        return None
    if not isinstance(result, dict) or result.get("ok") is not True:
        return None
    for key in ("answer", "message", "speak", "summary"):
        value = _clean(result.get(key) or "")
        if value:
            return value
    return None


def _holding_reply(language: str) -> str:
    """Last resort. Still human, still moves the conversation forward."""
    if language == "fa":
        return (
            "الان مدل محلی‌ام بالا نیست، پس نمی‌تونم عمیق فکر کنم؛ ولی هر دستوری روی ویندوز داشتی "
            "همین لحظه انجام می‌دم. اگر Ollama روشن باشه، همین سؤال را کامل و مفصل جواب می‌دم."
        )
    return (
        "My local model is not running right now, so I cannot think this through properly. "
        "Any Windows command still works immediately. With Ollama running I can answer this in full."
    )


def respond(text: str, language: str | None = None, context: str = "") -> dict[str, Any]:
    """Answer any utterance. Always returns ok=True with a non-empty reply."""
    value = str(text or "").strip()
    if not value:
        return {"ok": False, "reply": "", "provider": "chat"}

    lang = "fa" if _is_fa(value, language) else "en"

    reply = _ollama_reply(value, lang, context)
    if reply:
        return {"ok": True, "reply": reply, "provider": "chat-local"}

    reply = _knowledge_reply(value, lang)
    if reply:
        return {"ok": True, "reply": reply, "provider": "chat-research"}

    return {"ok": True, "reply": _holding_reply(lang), "provider": "chat-offline"}


def warm_up() -> None:
    """Preload the model in the background so the first real answer is fast."""
    if not CHAT_KEEP_MODEL_WARM:
        return

    def worker() -> None:
        try:
            requests.post(
                f"{OLLAMA_URL}/api/generate",
                json={
                    "model": CHAT_MODEL,
                    "prompt": "سلام",
                    "stream": False,
                    "options": {"num_predict": 1},
                    "keep_alive": "30m",
                },
                timeout=90,
            )
        except Exception:
            pass

    threading.Thread(target=worker, name="smartis-chat-warmup", daemon=True).start()
