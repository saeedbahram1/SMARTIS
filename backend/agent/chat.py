from __future__ import annotations

"""Conversational layer for Smartis.

This module only answers CONVERSATION. Anything that is a command (open an app,
volume, files, power, weather, research ...) is decided earlier by
``agent.router`` and never reaches the language model as chat.

2.13 changes
------------
* All Ollama traffic goes through ``agent.llm`` (same ``num_ctx`` and
  ``keep_alive`` as the planner and the warm-up) -> the model is no longer
  reloaded on every request and the "model is not up" false alarm is gone.
* No pre-flight residency gate. Ollama loads the model on demand; if the
  request fails the REAL error is reported.
* Real answers: proper system prompt, recent conversation as chat history,
  400-token budget (the old 16/24-token cap cut every answer in half).
* Streaming with a wall-clock budget: a slow machine still returns the text
  produced so far instead of an error.
"""

import re
import threading
import uuid
from datetime import datetime
from typing import Any

from agent import llm
from agent.logbus import logbus
from agent.ollama_model import ensure_ollama, resolve_model
from config import (
    CHAT_KEEP_MODEL_WARM,
    CHAT_MAX_REPLY_CHARS,
    CHAT_MAX_TOKENS,
    CHAT_TEMPERATURE,
    CHAT_THINK_MAX_TOKENS,
    CHAT_TIMEOUT,
)

_PERSIAN = re.compile(r"[\u0600-\u06FF]")
_LATIN = re.compile(r"[A-Za-z]")
_CANCEL_EVENTS: dict[str, threading.Event] = {}
_CANCEL_LOCK = threading.Lock()
_WARM_LOCK = threading.Lock()


# --------------------------------------------------------------------------
# Cancellation (unchanged public API)
# --------------------------------------------------------------------------
def create_request_id() -> str:
    request_id = uuid.uuid4().hex
    with _CANCEL_LOCK:
        _CANCEL_EVENTS[request_id] = threading.Event()
    return request_id


def register_request(request_id: str | None) -> None:
    """Make sure a client-supplied request id can be cancelled."""
    if not request_id:
        return
    with _CANCEL_LOCK:
        _CANCEL_EVENTS.setdefault(str(request_id), threading.Event())


def cancel_request(request_id: str) -> bool:
    with _CANCEL_LOCK:
        event = _CANCEL_EVENTS.get(str(request_id))
        if event is None:
            return False
        event.set()
        return True


def _request_cancelled(request_id: str | None) -> bool:
    if not request_id:
        return False
    with _CANCEL_LOCK:
        event = _CANCEL_EVENTS.get(str(request_id))
        return bool(event and event.is_set())


def _finish_request(request_id: str | None) -> None:
    if not request_id:
        return
    with _CANCEL_LOCK:
        _CANCEL_EVENTS.pop(str(request_id), None)


# --------------------------------------------------------------------------
# Prompt
# --------------------------------------------------------------------------
_FA_DAYS = ("دوشنبه", "سه‌شنبه", "چهارشنبه", "پنجشنبه", "جمعه", "شنبه", "یکشنبه")

_SYSTEM_FA = """تو Smartis هستی؛ دستیار هوشمند و صمیمی ویندوز که تیم سعید بهرامی ساخته است.
شخصیت: دقیق، گرم، مستقیم؛ مثل یک دوست کاربلد صحبت کن، نه مثل ربات.
قواعد پاسخ:
- دقیقاً به زبان کاربر جواب بده (فارسی یا English). فارسی را روان و معیار بنویس.
- پرسش ساده: یک تا سه جمله. پرسش علمی/فنی/توضیحی: کامل ولی فشرده، حداکثر چند پاراگراف کوتاه یا فهرست مرتب.
- اول جواب اصلی را بده، بعد در صورت نیاز توضیح. مقدمه، تعارف و تکرار سؤال ممنوع.
- اگر مطمئن نیستی یا اطلاعاتت قدیمی است، صادقانه بگو؛ حدس را به‌عنوان واقعیت ارائه نکن. عدد، تاریخ و نام را نساز.
- به پیام‌های قبلی همین گفتگو توجه کن و ارجاع‌ها («این»، «همون»، «بیشتر توضیح بده») را از روی آن‌ها بفهم.
- اطلاعات لحظه‌ای (آب‌وهوا، خبر، قیمت، ساعت دقیق) را از خودت نمی‌دانی؛ اگر پرسیدند بگو با دستور مستقیم مثل «هوای تهران» یا «آخرین اخبار» می‌توانی بگیری.
- هرگز ادعا نکن کاری روی سیستم انجام دادی. اجرای دستورها (باز کردن برنامه، صدا، فایل، خاموش کردن...) مسیر جداگانه‌ای دارد؛ اگر درخواستی شبیه دستور بود و اینجا رسید، بخواه واضح‌تر بگوید.
- بدون ایموجی و بدون Markdown سنگین (عنوان، جدول). فهرست ساده با خط تیره مجاز است."""

_SYSTEM_EN = """You are Smartis, a smart, friendly Windows assistant built by Saeed Behrami's team.
Personality: precise, warm, direct - like a capable friend, not a robot.
Answer rules:
- Reply in the user's language (English or Persian).
- Simple question: one to three sentences. Technical/explanatory question: complete but compact, a few short paragraphs or a tidy list at most.
- Lead with the answer, then explain if needed. No preamble, no filler, no repeating the question.
- If unsure or if your knowledge may be outdated, say so honestly. Never invent numbers, dates or names.
- Use the earlier messages of this conversation to resolve references such as "that", "it", "tell me more".
- You do not know live data (weather, news, prices, exact time); say the user can ask directly, e.g. "weather in Tehran" or "latest news".
- Never claim you performed an action on the computer. Commands (open apps, volume, files, power...) use a separate path; if a request looks like a command and reached you, ask the user to phrase it more clearly.
- No emoji and no heavy Markdown (headings, tables). Simple dash lists are fine."""

_MARKDOWN_NOISE = re.compile(r"(\*\*|__|`{1,3}|^#{1,6}\s*)", re.M)
_MULTI_SPACE = re.compile(r"[ \t\u00a0]+")
_MULTI_NEWLINE = re.compile(r"\n{3,}")


def _is_fa(text: str, language: str | None = None) -> bool:
    """The transcript script is the authority; the STT hint is only a tie-break."""
    if _PERSIAN.search(text or ""):
        return True
    if _LATIN.search(text or ""):
        return False
    return language != "en"


def _clean(reply: str) -> str:
    value = llm.strip_think(str(reply or ""))
    value = _MARKDOWN_NOISE.sub("", value)
    value = "\n".join(_MULTI_SPACE.sub(" ", line).strip() for line in value.splitlines())
    value = _MULTI_NEWLINE.sub("\n\n", value).strip()
    # Drop a leading label the model sometimes adds on its own.
    value = re.sub(r"^(?:Smartis|اسمارتیز|دستیار|پاسخ|Assistant)\s*[:：\-]\s*", "", value, flags=re.I)
    if len(value) > CHAT_MAX_REPLY_CHARS:
        cut = value[:CHAT_MAX_REPLY_CHARS]
        stop = max(cut.rfind("."), cut.rfind("؟"), cut.rfind("!"), cut.rfind("؛"), cut.rfind("\n"))
        value = cut[: stop + 1] if stop > 200 else cut
    return value.strip()


def _system_prompt(lang: str, thinking: bool) -> str:
    now = datetime.now()
    if lang == "fa":
        stamp = f"اکنون: {_FA_DAYS[now.weekday()]} {now:%Y-%m-%d} ساعت {now:%H:%M} (زمان سیستم کاربر)."
        tail = "\nزبان پاسخ: فارسی."
        extra = "\nاین پرسش نیاز به استدلال دارد؛ درست فکر کن و جواب نهایی را کامل بده." if thinking else ""
        return f"{_SYSTEM_FA}\n{stamp}{extra}{tail}"
    stamp = f"Now: {now:%A %Y-%m-%d %H:%M} (the user's system time)."
    extra = "\nThis question needs reasoning; think it through, then give the full final answer." if thinking else ""
    return f"{_SYSTEM_EN}\n{stamp}{extra}\nReply language: English."


def _history_messages(budget_chars: int = 1500, max_turns: int = 6) -> list[dict[str, str]]:
    """Recent turns (chat AND commands) as real chat messages, newest kept first."""
    try:
        from agent.context_memory import memory

        turns = list(memory.turns)[-max_turns:]
        fresh = memory._fresh()  # noqa: SLF001 - same package, deliberate
    except Exception:
        return []
    if not fresh:
        return []
    picked: list[tuple[str, str]] = []
    used = 0
    for turn in reversed(turns):
        user = str(getattr(turn, "user", "") or "").strip()[:320]
        reply = str(getattr(turn, "reply", "") or "").strip()[:420]
        size = len(user) + len(reply)
        if not user or used + size > budget_chars:
            break
        picked.append((user, reply))
        used += size
    messages: list[dict[str, str]] = []
    for user, reply in reversed(picked):
        messages.append({"role": "user", "content": user})
        if reply:
            messages.append({"role": "assistant", "content": reply})
    return messages


# --------------------------------------------------------------------------
# Errors -> short human message (full error always goes to the log panel)
# --------------------------------------------------------------------------
def _human_error(error: str | None, lang: str) -> str:
    err = str(error or "").lower()
    if "cannot reach ollama" in err or "connection" in err:
        fa = "Ollama روشن نیست یا در دسترس نیست. آن را اجرا کن و دوباره بپرس."
        en = "Ollama is not running or not reachable. Start it and ask again."
    elif "not found" in err and "model" in err:
        fa = "مدل انتخاب‌شده روی Ollama نصب نیست؛ با ollama pull آن را نصب کن."
        en = "The selected model is not installed in Ollama. Install it with ollama pull."
    elif "no response" in err or "timeout" in err or "stalled" in err:
        fa = "مدل دیرتر از حد معمول پاسخ داد و نتیجه‌ای نرسید. دوباره امتحان کن؛ معمولاً بار دوم سریع‌تر است."
        en = "The model took too long and returned nothing. Try again; the second request is usually faster."
    elif "cancelled" in err:
        fa, en = "متوقف شد.", "Stopped."
    else:
        fa = "پاسخی از مدل نگرفتم. جزئیات خطا در پنل لاگ (دستهٔ OLLAMA/CHAT) ثبت شده است."
        en = "I did not get a reply from the model. Details are in the log panel (OLLAMA/CHAT)."
    return fa if lang == "fa" else en


# --------------------------------------------------------------------------
# Public API
# --------------------------------------------------------------------------
def respond(
    text: str,
    language: str | None = None,
    context: str = "",
    request_id: str | None = None,
    thinking: bool = False,
) -> dict[str, Any]:
    """Answer one conversational utterance with the local model."""
    del context  # history now comes from structured memory, not a text blob
    value = str(text or "").strip()
    if not value:
        return {"ok": False, "reply": "", "provider": "chat"}

    lang = "fa" if _is_fa(value, language) else "en"
    register_request(request_id)
    try:
        if _request_cancelled(request_id):
            return {"ok": False, "cancelled": True, "reply": "", "provider": "chat-cancelled", "error": "cancelled"}

        messages = [{"role": "system", "content": _system_prompt(lang, thinking)}]
        messages.extend(_history_messages())
        messages.append({"role": "user", "content": value})

        def attempt() -> llm.LLMResult:
            return llm.generate(
                resolve_model(),
                messages,
                num_predict=CHAT_THINK_MAX_TOKENS if thinking else CHAT_MAX_TOKENS,
                temperature=max(0.2, CHAT_TEMPERATURE) if not thinking else 0.6,
                think=bool(thinking),
                total_timeout=CHAT_TIMEOUT * (1.6 if thinking else 1.0),
                is_cancelled=lambda: _request_cancelled(request_id),
                label="think" if thinking else "chat",
            )

        result = attempt()
        if not result.ok and not result.cancelled and "cannot reach ollama" in str(result.error or "").lower():
            # Ollama was not running: start it (Windows) and retry once.
            status = ensure_ollama(force=True)
            logbus.emit("OLLAMA", "Ollama was unreachable; tried to start it.", str(status)[:300])
            if status.get("ok"):
                result = attempt()

        if result.cancelled or _request_cancelled(request_id):
            return {"ok": False, "cancelled": True, "reply": "", "provider": "chat-cancelled", "error": "cancelled"}

        reply = _clean(result.text) if result.ok else ""
        if reply:
            if result.partial:
                logbus.emit("CHAT", "Reply was cut by the time budget; returned the text produced so far.", result.error)
            return {
                "ok": True,
                "reply": reply,
                "provider": "chat-local",
                "thinking": bool(thinking),
                "elapsed": round(result.total_seconds, 2),
                "tokens": result.tokens,
            }

        logbus.emit("CHAT", "Local chat request failed.", str(result.error)[:600])
        return {
            "ok": True,
            "reply": _human_error(result.error, lang),
            "provider": "chat-error",
            "error": result.error or "local_model_no_reply",
            "thinking": bool(thinking),
        }
    finally:
        _finish_request(request_id)


def warm_up() -> dict[str, Any]:
    """Load the model once, with the SAME options chat uses. Never raises."""
    if not CHAT_KEEP_MODEL_WARM:
        return {"ok": True, "skipped": True}
    with _WARM_LOCK:
        status = ensure_ollama(force=True)
        if not status.get("ok"):
            return {"ok": False, "error": "ollama unavailable during warm-up", "status": status}
        model = resolve_model()
        result = llm.warm_model(model)
        return {
            "ok": result.ok,
            "model": model,
            "load_seconds": round(result.load_seconds, 2),
            "error": result.error,
        }
