from __future__ import annotations

"""One entry point for EVERY user utterance (typed chat and voice).

Order of decisions
------------------
1. echo guard / noise gate                      (voice only)
2. pending confirmation  -> yes / no / something else
3. deterministic command engine (fast_path)     -> execute
4. command-looking text the engine could not parse -> Ollama JSON planner
5. everything else                                -> Ollama chat

A command is NEVER sent to the chat model, and a plain question is NEVER
turned into a command. Questions such as "how do I restart my router?" or
"what is knowledge?" contain command words but are answered as chat; only
"information tools" (time, weather, news, math, research) may answer a
question-shaped sentence.

Confirmation-gated commands (power, delete, close application) are queued by
the executor; the next utterance is consumed as yes / no BEFORE anything else,
so the answer is understood as a decision about that command, never as a chat
message.
"""

import re
from typing import Any

from agent import chat as chat_agent
from agent import system_tools
from agent.command_normalizer import normalize_command_text
from agent.context_memory import memory
from agent.echo_guard import guard as echo_guard
from agent.executor import (
    clear_pending_confirmation,
    describe_action,
    execute_pending_confirmation,
    execute_plan,
    pending_confirmation,
    pending_summary,
)
from agent.fast_path import fast_plan
from agent.logbus import logbus
from agent.planner import plan_with_ollama
from agent.tools import tool_specs
from config import NOISE_GATE_MODE, REQUIRE_CONFIRMATION_FOR

# --------------------------------------------------------------------------
# Small helpers
# --------------------------------------------------------------------------
_FA = re.compile(r"[\u0600-\u06FF]")
_LATIN = re.compile(r"[A-Za-z]")

_INFO_TOOLS = {
    "get_time_date", "get_weather", "get_location_weather", "get_news",
    "calculate", "web_research", "system_dashboard", "hardware_temperatures",
    "wikipedia_answer", "wikipedia_lookup", "wikipedia_more", "active_player",
    "system_info", "get_installed_languages",
}

# --------------------------------------------------------------------------
# Chat "steps" strip: one honest label per tool.
#
# The /ws {"type":"step"} events feed the collapsible activity strip in the
# chat panel (replacing the old "Smartis is typing…" pill). Emission points are
# chosen so the strip always names the work that is ACTUALLY in flight, not a
# plan dump: an action step fires right before its tool runs (sequential
# honesty), never for actions still waiting in the queue.
# --------------------------------------------------------------------------
_ACTION_STEPS: dict[str, tuple[str, str, str]] = {
    "open_application": ("باز کردن برنامه…", "Opening the app…", "open"),
    "open_website": ("باز کردن سایت…", "Opening the website…", "web"),
    "open_chrome_url": ("باز کردن آدرس در مرورگر…", "Opening the URL…", "web"),
    "open_wikipedia_page": ("باز کردن صفحه ویکی‌پدیا…", "Opening the Wikipedia page…", "wiki"),
    "search_open_read": ("جستجو، باز کردن و خواندن نتیجه…", "Searching and reading the page…", "search"),
    "open_chatgpt_chat": ("باز کردن چت ChatGPT در مرورگر…", "Opening a ChatGPT chat…", "web"),
    "type_text": ("تایپ کردن متن در پنجره فعال…", "Typing the text…", "type"),
    "create_project": ("ساخت پروژه و کدنویسی…", "Creating the project and writing code…", "code"),
    "write_code": ("نوشتن کد در فایل…", "Writing the code…", "code"),
    "open_windows_settings": ("باز کردن تنظیمات ویندوز…", "Opening Windows Settings…", "settings"),
    "windows_system_search": ("جستجو در ویندوز…", "Searching in Windows…", "search"),
    "close_application": ("بستن برنامه…", "Closing the app…", "close"),
    "open_folder": ("باز کردن پوشه…", "Opening the folder…", "folder"),
    "open_file": ("باز کردن فایل…", "Opening the file…", "file"),
    "open_named": ("پیدا کردن و باز کردن…", "Finding and opening…", "open"),
    "create_folder": ("ساخت پوشه…", "Creating the folder…", "folder"),
    "create_file": ("ساخت فایل…", "Creating the file…", "file"),
    "delete_file": ("حذف فایل…", "Deleting the file…", "delete"),
    "delete_named": ("حذف آیتم…", "Deleting the item…", "delete"),
    "system_volume_set": ("تنظیم صدای سیستم…", "Setting the system volume…", "volume"),
    "system_volume_change": ("تغییر صدای سیستم…", "Changing the system volume…", "volume"),
    "system_mute": ("قطع/وصل صدای سیستم…", "Toggling system mute…", "volume"),
    "media_play_pause": ("پخش/توقف رسانه…", "Toggling media playback…", "media"),
    "media_stop": ("توقف پخش…", "Stopping playback…", "media"),
    "media_next": ("ترک بعدی…", "Skipping to the next track…", "media"),
    "media_previous": ("ترک قبلی…", "Going to the previous track…", "media"),
    "play_media_search": ("پخش آهنگ درخواستی…", "Playing the requested track…", "media"),
    "player_volume_set": ("تنظیم صدای پخش‌کننده…", "Setting the player volume…", "volume"),
    "player_volume_change": ("تغییر صدای پخش‌کننده…", "Changing the player volume…", "volume"),
    "player_volume_max": ("صدای پخش‌کننده تا حداکثر…", "Maxing the player volume…", "volume"),
    "player_mute": ("قطع/وصل صدای پخش‌کننده…", "Toggling the player mute…", "volume"),
    "active_player": ("بررسی پخش‌کننده فعال…", "Checking the active player…", "media"),
    "get_weather": ("گرفتن وضعیت هوا…", "Fetching the weather…", "weather"),
    "get_location_weather": ("گرفتن هوای این مکان…", "Fetching local weather…", "weather"),
    "get_time_date": ("گرفتن تاریخ و ساعت…", "Fetching time and date…", "time"),
    "get_news": ("خواندن اخبار…", "Reading the news…", "news"),
    "calculate": ("محاسبه…", "Calculating…", "calc"),
    "system_info": ("گرفتن اطلاعات سیستم…", "Reading system info…", "system"),
    "system_dashboard": ("گرفتن وضعیت سیستم…", "Reading the system dashboard…", "system"),
    "hardware_temperatures": ("خواندن دمای سخت‌افزار…", "Reading hardware temperatures…", "system"),
    "wikipedia_lookup": ("جستجو در ویکی‌پدیا…", "Searching Wikipedia…", "wiki"),
    "wikipedia_answer": ("خواندن و خلاصه کردن ویکی‌پدیا…", "Reading and summarizing Wikipedia…", "wiki"),
    "wikipedia_more": ("خواندن ادامه مطلب…", "Reading more of the article…", "wiki"),
    "web_research": ("تحقیق در وب و ویکی‌پدیا…", "Researching the web and Wikipedia…", "web"),
    "set_windows_language": ("تغییر زبان ویندوز…", "Changing the Windows language…", "settings"),
    "get_installed_languages": ("فهرست زبان‌های نصب‌شده…", "Listing installed languages…", "settings"),
    "shutdown_windows": ("خاموش کردن سیستم…", "Shutting down…", "power"),
    "restart_windows": ("ری‌استارت سیستم…", "Restarting…", "power"),
    "sleep_windows": ("بردن سیستم به خواب…", "Putting the PC to sleep…", "power"),
    "cancel_shutdown": ("لغو خاموشی…", "Cancelling the shutdown…", "power"),
}

_DEFAULT_STEP = ("اجرای دستور…", "Running the command…", "run")


def _action_step(action: dict[str, Any], lang: str | None) -> tuple[str, str]:
    tool = str((action or {}).get("tool") or "")
    fa_label, en_label, icon = _ACTION_STEPS.get(tool, _DEFAULT_STEP)
    return (fa_label if lang != "en" else en_label), icon


def _brief(value: Any, limit: int = 420) -> str:
    text = str(value)
    return text if len(text) <= limit else text[:limit] + "..."


def effective_language(text: str, language: str | None) -> str | None:
    normalized = normalize_command_text(text)
    if _FA.search(normalized):
        return "fa"
    if _LATIN.search(normalized):
        return "en"
    return language


_POLITE_FILLER = r"(?:لطفا|لطفاً|خواهشا|خواهشاً|please|برام|برای من|میشه|می‌شه)"


def affirmative_text(text: str) -> bool:
    value = re.sub(r"\s+", " ", str(text or "").strip().lower())
    value = re.sub(r"[.!؟?،,؛;]+$", "", value).strip()
    # «آره لطفا» / «بله میشه» are plain yeses; polite fillers never change the meaning.
    value = re.sub(rf"^(?:{_POLITE_FILLER})\s+", "", value).strip()
    value = re.sub(rf"\s+(?:{_POLITE_FILLER})$", "", value).strip()
    if value in {
        "بله", "آره", "اره", "تایید", "تأیید", "تایید میکنم", "تأیید می‌کنم", "حتما", "حتماً", "باشه",
        "حتما انجام بده", "حتماً انجام بده", "بله انجام بده", "آره انجام بده", "اره انجام بده",
        "تأییدش می‌کنم", "تاییدش می‌کنم", "انجامش بده", "انجام بده", "بله انجامش بده", "آره انجامش بده",
        "تایید", "تایید کن", "تأیید کن", "اوکی", "اوکی انجام بده", "درسته", "بزن بره", "بکن",
        "yes", "yeah", "yep", "sure", "okay", "ok", "confirm", "confirmed", "do it", "go ahead", "yes do it",
    }:
        return True
    return bool(re.fullmatch(
        r"(?:بله|آره|اره|حتما|حتماً|باشه|اوکی|تایید|تأیید|درسته|yes|yeah|yep|sure|ok|okay)"
        r"(?:\s+(?:انجام(?:ش)?|تأیید(?:ش)?|تایید(?:ش)?|بده|بدهش|کن|کنش|بکن|بخون|بخوان|ادامه(?:\s+بده)?|می‌?شه)){0,2}",
        value, re.I,
    ))


def negative_text(text: str) -> bool:
    value = re.sub(r"\s+", " ", str(text or "").strip().lower())
    value = re.sub(r"[.!؟?،,؛;]+$", "", value).strip()
    value = re.sub(rf"^(?:{_POLITE_FILLER})\s+", "", value).strip()
    value = re.sub(rf"\s+(?:{_POLITE_FILLER})$", "", value).strip()
    if value in {"نه", "نخیر", "لغو", "بیخیال", "نکن", "ولش کن", "منصرف شدم", "no", "nope", "cancel", "stop", "don't", "dont"}:
        return True
    if re.search(r"^(?:نه|نخیر|بیخیال|نمیخوام|نمی‌خوام|نکن|no|nope|cancel|stop)\b", value, re.I):
        return True
    return bool(re.search(r"(?:لغو|بیخیال|cancel|stop)\s*(?:کن|کنش|بده|بدهش|شو)?$", value, re.I))


# Short continuations of the reading flow («ادامه بده»، «بخون») that must reach
# the pending handler instead of being treated as fresh chat.
_CONTINUE_REPLY = re.compile(
    r"^(?:بخون|بخوان|ادامه|ادامه\s*بده|ادامه‌ش\s*بده|بیشتر\s*بگو|کاملش\s*کن|کامل\s*کن|"
    r"بقیه(?:ش)?(?:\s*(?:رو|را))?\s*(?:بگو|بخون)?|"
    r"read\s+(?:it|more)|continue|go\s+on|more|tell\s+me\s+more|next)$",
    re.I,
)


def _pending_flow_active() -> bool:
    return bool(
        pending_confirmation()
        or system_tools.wikipedia_more_available()
        or system_tools.has_pending_file()
        or system_tools.has_pending_folder()
        or system_tools.has_pending_prompt()
    )


def _expected_pending_reply(text: str) -> bool:
    """A short yes/no/continue that answers a question Smartis just asked.

    The echo guard compares the transcript with what Smartis said, and the
    confirmation question itself contains «بله» و «لغو» while the article ask
    contains «ادامه بده». A real reply therefore scores 1.0 and used to be
    dropped as a self-echo BEFORE the pending handler could consume it.
    """
    value = re.sub(r"\s+", " ", str(text or "").strip())
    if not value or len(value) > 40 or not _pending_flow_active():
        return False
    return affirmative_text(value) or negative_text(value) or bool(_CONTINUE_REPLY.match(value))


_POLITE = re.compile(
    r"(?:میشه|می‌شه|میتونی|می‌تونی|میتوانی|می‌توانی|امکانش هست|لطفا|لطفاً|"
    r"can you|could you|would you|will you|please)", re.I)
_HOW = re.compile(r"(?:چطور|چگونه|چجوری|چطوری|\bhow\b)", re.I)
_QUESTION_START = re.compile(
    r"^(?:چطور|چگونه|چجوری|چطوری|چرا|چی|چه|کی|کجا|کدام|کدوم|آیا|تفاوت|فرق|معنی|منظور|چقدر|چند|"
    r"how|why|what|who|when|where|which|is it|are there|do you|does|explain|tell me|define)\b", re.I)


def is_question_like(text: str) -> bool:
    """True for questions/explanations; polite requests ("can you open X?") are not."""
    low = normalize_command_text(text).lower().strip()
    if not low:
        return False
    if _POLITE.search(low) and not _HOW.search(low):
        return False
    if "?" in low or "؟" in low:
        return True
    return bool(_QUESTION_START.match(low))


_COMMAND_VERBS = (
    # Imperative verb phrases. These essentially never appear in plain chat, so
    # a single match is enough to pay for the Ollama planner.
    "باز کن", "بازش کن", "باز بذار", "باز بگذار", "بازش بذار", "بازش بگذار",
    "اجرا کن", "برو به", "برو تو", "برو سراغ", "بیاور", "بیار",
    "پخش کن", "پخشش کن", "قطع کن", "متوقف کن", "توقف کن", "ادامه بده", "ادامه‌ش بده",
    "کم کن", "کمش کن", "زیاد کن", "زیادش کن", "بالا ببر", "ببر بالا", "پایین بیار", "بکش پایین",
    "بی صدا کن", "بی‌صدا کن", "صدا دار کن", "آنمیوت کن",
    "بساز", "ایجاد کن", "حذف کن", "پاک کن", "دلیت کن",
    "خاموش کن", "روشن کن", "ری استارت کن", "راه‌اندازی مجدد کن", "به خواب ببر",
    "ببند", "خارج شو",
    "سرچ کن", "جستجو کن", "جست‌وجو کن", "تحقیق کن", "بررسی کن", "پیدا کن", "بگرد",
    "نشون بده", "نمایش بده", "تنظیم کن", "بخوان", "بخون",
    "open ", "launch ", "go to ", "run ", "play ", "pause", "resume", "stop ",
    "next track", "previous track", "turn up", "turn down", "shut down", "shutdown",
    "restart", "reboot", "create ", "delete ", "remove ", "close ", "quit ", "kill ",
    "search for", "look up", "set volume", "mute", "unmute", "show me", "display ",
)

_COMMAND_NOUNS = (
    # Bare nouns from the old cue list. They DO occur in ordinary conversation
    # («صدات خوبه», «این فیلم قشنگیه»), so on their own they only justify the
    # heavy planner when the sentence still reads like a command.
    "صدا", "ولوم", "volume", "بی صدا", "بی‌صدا", "پخش", "آهنگ", "موزیک", "فیلم", "پلیر",
    "حذف", "خاموش", "حالت خواب",
    "تنظیمات", "settings", "زبان ویندوز", "windows language",
    "ویندوز سرچ", "windows search",
    "هوای", "آب و هوا", "آب‌وهوا", "weather",
    "ساعت", "تاریخ", "اخبار", "news",
)

# Markers of a declarative/conversational sentence rather than an instruction.
_CONVERSATIONAL = re.compile(
    r"(?:فکر می‌?کنم|به نظرم|نظرت|نظر من|دوست دارم|علاقه|خسته|خوبه|خوب بود|خوبی|"
    r"قشنگ|جالب|بد نبود|عالی بود|امروز|دیروز|فردا|پریروز|چون|زیرا|اما|ولی|یعنی|"
    r"مثلاً|مثلا|شاید|احتمالاً|احتمالا|می‌?دونم|نمی‌?دونم|یادم|خاطره|تجربه|"
    r"خیلی|همیشه|هیچ‌وقت|هیچوقت|بعضی وقت|قبلاً|قبلا|"
    r"\bi think\b|\bi believe\b|\bin my opinion\b|\bi like\b|\bi love\b|\bi hate\b|"
    r"\bi feel\b|\bi am\b|\bi was\b|\bwe are\b|\bbecause\b|\bbut\b|\bmaybe\b|"
    r"\bprobably\b|\bactually\b|\byesterday\b|\btomorrow\b|\binteresting\b|\bnice\b|"
    r"\bgood\b|\bgreat\b|\btired\b|\balways\b|\bnever\b|\bsometimes\b)",
    re.I,
)

# A bare-noun match only counts as a command when the utterance is short; long
# sentences that merely mention «صدا»/«فیلم» are conversation.
_WEAK_CUE_MAX_WORDS = 8


def looks_like_command(text: str) -> bool:
    low = normalize_command_text(text).lower()
    if any(cue in low for cue in _COMMAND_VERBS):
        return True
    if not any(cue in low for cue in _COMMAND_NOUNS):
        return False
    if _CONVERSATIONAL.search(low):
        return False
    return len(low.split()) <= _WEAK_CUE_MAX_WORDS


# --------------------------------------------------------------------------
# Voice noise gate (moved here from main.py unchanged in behaviour)
# --------------------------------------------------------------------------
_SHORT_COMMANDS = {
    "بله", "آره", "اره", "نه", "لغو", "بیخیال", "ادامه", "ادامه بده", "مکث", "توقف",
    "بس", "بسه", "کمک", "سلام", "درود", "تایید", "تأیید", "باشه", "حتما", "حتماً",
    "بخون", "بیشتر بگو", "کاملش کن",
    "yes", "yeah", "yep", "no", "nope", "stop", "cancel", "continue", "ok", "okay",
    "confirm", "read it", "tell me more",
}

# Exact short utterances that are requests, not noise. An exact match is never
# STT garbage, so this is checked before the length heuristics below.
#
# Every Persian entry here resolves to a real fast-path action on its own
# («ساعت»/«تاریخ» -> get_time_date, «هوا» -> get_location_weather,
# «اخبار»/«خبر» -> get_news). Words that produce NO action bare («صدا», «سرچ»,
# «زبان») are deliberately absent: admitting them would only push a one-word
# utterance into the heavy Ollama planner.
_KNOWN_SHORT = {
    "سلام", "درود", "گوگل", "یوتیوب", "کروم", "اسمارتیز", "اسمارتیس", "ادامه", "ادامه بده",
    "بله", "آره", "نه", "لغو", "کمک", "توقف", "بس", "مکث",
    "ساعت", "تاریخ", "هوا", "اخبار", "خبر",
    "hi", "hello", "hey", "google", "youtube", "chrome", "search", "stop", "pause", "cancel",
    "yes", "no", "open", "play", "weather", "time", "volume", "date", "news",
}


def should_ignore_transcript(text: str, language: str | None = None) -> bool:
    """Reject only clear STT noise."""
    value = normalize_command_text(text).strip()
    if not value:
        return True
    low = value.lower()

    if NOISE_GATE_MODE == "strict":
        # Script-independent on purpose. This check used to sit inside
        # `if _FA.search(value):`, which made every Latin entry in the whitelist
        # dead code ("pause", "stop", "volume" were still discarded by the length
        # heuristics below) and left bare Persian requests like «ساعت» with no way
        # in at all, because the single-word regex only lists Latin keywords.
        if low in _KNOWN_SHORT:
            return False
        words = re.findall(r"[A-Za-z]+|[\u0600-\u06FF]+", value)
        if len(words) == 1 and not re.search(
            r"(?:[?؟]|چی|چیه|کیه|what|who|how|open|play|search|google|volume|weather|time|date|start|stop|pause|cancel|yes|no)$",
            low, re.I,
        ):
            return True
        if len(words) <= 2 and len(value) < 7 and not re.search(
            r"(?:باز|برو|پخش|سرچ|جست|حساب|صدا|هوا|ساعت|تاریخ|زبان|بساز|حذف|تحقیق|بررسی|پیدا|"
            r"play|open|search|find|calculate|weather|time|language|create|delete|research|investigate)",
            low, re.I,
        ):
            return True
        return False

    if low in _SHORT_COMMANDS:
        return False
    if re.fullmatch(r"[\u0600-\u06FF\s]{1,2}", value):
        return True
    if low in {"you", "yeah", "uh", "um", "hmm", "mm", "oh", "ah", "the", "a", "i", "it",
               "so", "ok", "okay", "bye", "thank you", "thanks for watching", "subscribe"}:
        return True
    words = re.findall(r"[A-Za-z]+|[\u0600-\u06FF]+", value)
    if len(words) == 1 and len(value) <= 3 and not re.search(r"[?؟]", value):
        return True
    return False


# --------------------------------------------------------------------------
# Result builders
# --------------------------------------------------------------------------
def _result(
    *,
    mode: str,
    provider: str,
    reply: str,
    ok: bool = True,
    execution: dict[str, Any] | None = None,
    actions: list | None = None,
    needs_confirmation: bool = False,
    spoken_reply: str = "",
    **extra: Any,
) -> dict[str, Any]:
    out: dict[str, Any] = {
        "ok": ok,
        "mode": mode,
        "provider": provider,
        "needs_confirmation": needs_confirmation,
        "plan": {"reply": reply, "actions": actions or [], "needs_confirmation": needs_confirmation},
        "execution": execution or {"ok": True, "needs_confirmation": needs_confirmation, "results": []},
    }
    if spoken_reply:
        out["spoken_reply"] = spoken_reply
    out.update(extra)
    return out


def _ignored(provider: str) -> dict[str, Any]:
    return {
        "ok": True, "ignored": True, "provider": provider, "mode": "ignored",
        "plan": {"reply": "", "actions": [], "needs_confirmation": False},
        "execution": {"ok": True, "results": []},
    }


# --------------------------------------------------------------------------
# Confirmation
# --------------------------------------------------------------------------
def _handle_pending(text: str, lang: str | None) -> dict[str, Any] | None:
    """Consume the utterance if a confirmation is waiting. None = not consumed."""
    if not pending_confirmation():
        return None
    fa = lang != "en"
    summary = pending_summary(lang) or {}

    if affirmative_text(text):
        logbus.emit("CONFIRMATION", "User confirmed the pending command.", _brief(summary))
        step_text, step_icon = _action_step({"tool": summary.get("tool")}, lang)
        logbus.emit_step(step_text, step_icon)
        execution = execute_pending_confirmation()
        ok = execution.get("ok") is True
        for item in execution.get("results") or []:
            tool = str(item.get("tool") or "")
            res = item.get("result") or {}
            logbus.emit("EXECUTOR", f"{'Executed' if res.get('ok') else 'Failed'}: {tool}", _brief(res))
        spoken = "، ".join(
            str((item.get("result") or {}).get("speak") or "").strip()
            for item in execution.get("results") or []
            if str((item.get("result") or {}).get("speak") or "").strip()
        )
        if ok:
            reply = spoken or ("انجام شد." if fa else "Done.")
        else:
            err = execution.get("error") or ("عملیات با خطا مواجه شد." if fa else "the operation returned an error.")
            reply = f"انجام نشد؛ {err}" if fa else f"It failed: {err}"
        return _result(mode="command", provider="confirmation", reply=reply, ok=ok, execution=execution, confirmation="confirmed")

    if negative_text(text):
        logbus.emit("CONFIRMATION", "User cancelled the pending command.", _brief(summary))
        clear_pending_confirmation()
        system_tools.clear_all_pendings()
        return _result(
            mode="command", provider="confirmation",
            reply="باشه، انجامش نمی‌دم." if fa else "Okay, I won't do it.",
            confirmation="cancelled",
        )

    # Neither yes nor no: the user moved on. Cancel the risky command (fail-safe)
    # and let the new utterance be routed normally.
    logbus.emit("CONFIRMATION", "Pending command dropped: the user said something else.", _brief({"said": text, "pending": summary}))
    clear_pending_confirmation()
    return None


# --------------------------------------------------------------------------
# Command execution
# --------------------------------------------------------------------------
_VALID_TOOLS: set[str] | None = None


def _known_tools() -> set[str]:
    global _VALID_TOOLS
    if _VALID_TOOLS is None:
        _VALID_TOOLS = {str(spec.get("name")) for spec in tool_specs()}
    return _VALID_TOOLS


def _plan_is_valid(plan: dict[str, Any] | None) -> bool:
    if not isinstance(plan, dict):
        return False
    actions = plan.get("actions")
    if not isinstance(actions, list) or not actions:
        return False
    known = _known_tools()
    return all(isinstance(a, dict) and str(a.get("tool") or "") in known for a in actions)


def _execute_command(text: str, plan: dict[str, Any], provider: str, lang: str | None) -> dict[str, Any]:
    fa = lang != "en"

    def _report(action: dict[str, Any]) -> None:
        step_text, step_icon = _action_step(action, lang)
        logbus.emit_step(step_text, step_icon)

    execution = execute_plan(plan, False, on_action=_report)
    reply = str(plan.get("reply") or "")

    for item in execution.get("results") or []:
        tool = str(item.get("tool") or "")
        result = item.get("result") or {}
        logbus.emit(
            "EXECUTOR",
            f"{'Executed' if result.get('ok') is True else 'Failed'}: {tool}",
            _brief({"tool": tool, "result": result}),
        )

    if execution.get("needs_confirmation") is True:
        tool = str(execution.get("tool") or "")
        args = execution.get("args") or {}
        question = describe_action(tool, args, lang)
        logbus.emit("CONFIRMATION", f"Waiting for the user's confirmation: {tool}", _brief({"args": args}))
        memory.remember(text, plan, execution, reply=question)
        return _result(
            mode="command", provider=provider, reply=question, execution=execution,
            actions=plan.get("actions") or [], needs_confirmation=True,
            confirmation="required", pending=pending_summary(lang),
        )

    if execution.get("ok") is not True:
        error = str(execution.get("error") or ("عملیات با خطا مواجه شد." if fa else "The operation failed."))
        reply = f"انجام نشد؛ {error}" if fa else f"It failed: {error}"
    if not reply:
        reply = "انجام شد." if fa else "Done."

    spoken_parts = []
    for item in execution.get("results") or []:
        if isinstance(item, dict) and isinstance(item.get("result"), dict):
            spoken = str(item["result"].get("speak") or "").strip()
            if spoken:
                spoken_parts.append(spoken)
    spoken_reply = "، ".join(spoken_parts)

    memory.remember(text, plan, execution, reply=spoken_reply or reply)
    return _result(
        mode="command", provider=provider, reply=reply, ok=execution.get("ok") is True,
        execution=execution, actions=plan.get("actions") or [], spoken_reply=spoken_reply,
    )


def _plan_command(contextual: str, lang: str | None, *, allow_planner: bool = True) -> tuple[dict[str, Any] | None, str]:
    """Return (plan, provider) when the text is an executable command, else (None, why).

    With ``allow_planner=False`` only the deterministic fast path runs. The
    chat-with-attachments flow uses this: the user is discussing an attached
    file, and sending «این فایل را بررسی کن» to the Ollama planner would only
    invite it to hallucinate tool calls about a file it cannot see.
    """
    question = is_question_like(contextual)

    fast = fast_plan(contextual, lang, include_conversation=False, include_knowledge=False)
    if fast is not None and fast.get("ok"):
        plan = fast.get("plan") or {}
        actions = plan.get("actions") or []
        if actions:
            tools = {str(a.get("tool") or "") for a in actions if isinstance(a, dict)}
            if question and not tools <= _INFO_TOOLS:
                logbus.emit("ROUTER", "Question-shaped sentence with an action word -> chat, not a command.",
                            _brief({"text": contextual, "tools": sorted(tools)}))
            else:
                logbus.emit("FAST_PATH", f"Deterministic match: {len(actions)} action(s).",
                            _brief({"provider": fast.get("provider"), "actions": actions}))
                return plan, str(fast.get("provider") or "fast-path")
        elif str(fast.get("provider")) == "conversation" and plan.get("reply"):
            # e.g. "what should the file be called?" follow-up of a file/folder command.
            return plan, "fast-path"

    if question or not looks_like_command(contextual):
        return None, "chat"

    if not allow_planner:
        return None, "chat"

    # Command-shaped but not deterministic: let the local model plan it.
    result = plan_with_ollama(contextual, lang, memory.context_text())
    if not result.get("ok"):
        logbus.emit("PLANNER", "Command planner failed; answering as chat.", _brief(result.get("error")))
        return None, "chat"
    plan = result.get("plan") or {}
    if _plan_is_valid(plan):
        logbus.emit("PLANNER", f"Semantic plan with {len(plan['actions'])} action(s).",
                    _brief({"actions": plan["actions"]}))
        return plan, "ollama-planner"
    logbus.emit("PLANNER", "Planner found no executable action; answering as chat.", _brief(plan))
    return None, "chat"


# --------------------------------------------------------------------------
# Public entry point
# --------------------------------------------------------------------------
def handle_input(
    text: str,
    language: str | None = None,
    *,
    source: str = "text",
    request_id: str | None = None,
    thinking: bool = False,
    extra_context: str = "",
) -> dict[str, Any]:
    value = str(text or "").strip()
    if not value:
        return {"ok": False, "error": "Text is empty."}
    voice = source == "voice"
    has_attachments = bool(str(extra_context or "").strip())

    if voice and echo_guard.is_echo(value) and not _expected_pending_reply(value):
        logbus.emit("STT", "Self-voice detected and discarded (echo guard).", _brief(value))
        return _ignored("echo-guard")

    normalized = normalize_command_text(value)
    lang = effective_language(normalized, language)

    consumed = _handle_pending(normalized, lang)
    if consumed is not None:
        return consumed

    # While Smartis is waiting for the text to write into the opened ChatGPT
    # window, ANY transcript is the user's answer — even a single short word
    # («تست») would otherwise be discarded by the short-utterance heuristics.
    if voice and should_ignore_transcript(value, lang) and not _expected_pending_reply(value) and not system_tools.has_pending_prompt():
        logbus.emit("STT", "Transcript discarded as background noise.", _brief(value))
        return _ignored("noise-gate")

    contextual = memory.resolve_references(normalized)
    logbus.emit_step("تحلیل درخواست…" if lang != "en" else "Analyzing the request…", "brain")
    plan, provider = _plan_command(contextual, lang, allow_planner=not has_attachments)
    if plan is not None:
        logbus.emit("ROUTER", f"{source}: command ({provider})", _brief(value, 160))
        return _execute_command(value, plan, provider, lang)

    logbus.emit(
        "ROUTER",
        f"{source}: chat{' + attachments' if has_attachments else ''}{' + thinking' if thinking else ''}",
        _brief(value, 160),
    )
    reply = chat_agent.respond(value, lang, extra_context, request_id=request_id, thinking=thinking)
    if reply.get("cancelled"):
        return _result(mode="chat", provider="chat-cancelled", reply="", ok=False, cancelled=True)
    text_reply = str(reply.get("reply") or "").strip()
    if reply.get("provider") == "chat-local" and text_reply:
        memory.remember(value, {"actions": []}, {"ok": True, "results": []}, reply=text_reply)
    return _result(
        mode="chat",
        provider=str(reply.get("provider", "chat-local")),
        reply=text_reply,
        thinking=bool(reply.get("thinking", thinking)),
        chat_error=reply.get("error"),
        elapsed=reply.get("elapsed"),
    )
