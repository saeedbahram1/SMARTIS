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


def affirmative_text(text: str) -> bool:
    value = re.sub(r"\s+", " ", str(text or "").strip().lower())
    value = re.sub(r"[.!؟?،,]+$", "", value).strip()
    if value in {
        "بله", "آره", "اره", "تایید", "تأیید", "تایید میکنم", "تأیید می‌کنم", "حتما", "حتماً", "باشه",
        "حتما انجام بده", "حتماً انجام بده", "بله انجام بده", "آره انجام بده", "اره انجام بده",
        "تأییدش می‌کنم", "تاییدش می‌کنم", "انجامش بده", "انجام بده", "بله انجامش بده", "آره انجامش بده",
        "تایید", "تایید کن", "تأیید کن", "اوکی", "اوکی انجام بده", "درسته", "بزن بره", "بکن",
        "yes", "yeah", "yep", "sure", "okay", "ok", "confirm", "confirmed", "do it", "go ahead", "yes do it",
    }:
        return True
    return bool(re.fullmatch(
        r"(?:بله|آره|اره|حتما|حتماً|باشه|تایید|تأیید)(?:\s+(?:انجام(?:ش)?|تأیید(?:ش)?|تایید(?:ش)?))?(?:\s+(?:بده|بدهش|کن|کنش|بکن))?",
        value, re.I,
    ))


def negative_text(text: str) -> bool:
    value = re.sub(r"\s+", " ", str(text or "").strip().lower())
    value = re.sub(r"[.!؟?،,]+$", "", value).strip()
    if value in {"نه", "نخیر", "لغو", "بیخیال", "نکن", "ولش کن", "منصرف شدم", "no", "nope", "cancel", "stop", "don't", "dont"}:
        return True
    if re.search(r"^(?:نه|نخیر|بیخیال|نمیخوام|نمی‌خوام|نکن|no|nope|cancel|stop)\b", value, re.I):
        return True
    return bool(re.search(r"(?:لغو|بیخیال|cancel|stop)\s*(?:کن|کنش|بده|بدهش|شو)?$", value, re.I))


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


_COMMAND_CUES = (
    "باز کن", "بازش کن", "اجرا کن", "برو به", "برو تو", "بیاور", "بیار",
    "open ", "launch ", "go to ",
    "صدا", "ولوم", "volume", "mute", "بی صدا", "بی‌صدا",
    "پخش", "آهنگ", "موزیک", "فیلم", "پلیر", "play ", "pause", "next track", "previous track",
    "بساز", "ایجاد کن", "create ", "حذف", "پاک کن", "delete", "remove",
    "خاموش", "ری استارت", "راه‌اندازی مجدد", "restart", "shutdown", "shut down", "reboot",
    "حالت خواب", "ببند", "close ", "quit ",
    "تنظیمات", "settings", "زبان ویندوز", "windows language",
    "ویندوز سرچ", "windows search", "سرچ کن", "جستجو کن", "search for", "look up",
    "تحقیق کن", "بررسی کن", "پیدا کن", "هوای", "آب و هوا", "آب‌وهوا", "weather",
    "ساعت", "تاریخ", "اخبار", "news",
)


def looks_like_command(text: str) -> bool:
    low = normalize_command_text(text).lower()
    return any(cue in low for cue in _COMMAND_CUES)


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


def should_ignore_transcript(text: str, language: str | None = None) -> bool:
    """Reject only clear STT noise."""
    value = normalize_command_text(text).strip()
    if not value:
        return True
    low = value.lower()

    if NOISE_GATE_MODE == "strict":
        if _FA.search(value):
            known = {"سلام", "درود", "گوگل", "یوتیوب", "کروم", "اسمارتیز", "اسمارتیس", "ادامه", "ادامه بده",
                     "بله", "آره", "نه", "لغو", "کمک", "توقف", "بس", "مکث",
                     "hi", "hello", "hey", "google", "youtube", "chrome", "search", "stop", "pause", "cancel",
                     "yes", "no", "open", "play", "weather", "time", "volume"}
            if low in known:
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
    execution = execute_plan(plan, False)
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


def _plan_command(contextual: str, lang: str | None) -> tuple[dict[str, Any] | None, str]:
    """Return (plan, provider) when the text is an executable command, else (None, why)."""
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
) -> dict[str, Any]:
    value = str(text or "").strip()
    if not value:
        return {"ok": False, "error": "Text is empty."}
    voice = source == "voice"

    if voice and echo_guard.is_echo(value):
        logbus.emit("STT", "Self-voice detected and discarded (echo guard).", _brief(value))
        return _ignored("echo-guard")

    normalized = normalize_command_text(value)
    lang = effective_language(normalized, language)

    consumed = _handle_pending(normalized, lang)
    if consumed is not None:
        return consumed

    if voice and should_ignore_transcript(value, lang):
        logbus.emit("STT", "Transcript discarded as background noise.", _brief(value))
        return _ignored("noise-gate")

    contextual = memory.resolve_references(normalized)
    plan, provider = _plan_command(contextual, lang)
    if plan is not None:
        logbus.emit("ROUTER", f"{source}: command ({provider})", _brief(value, 160))
        return _execute_command(value, plan, provider, lang)

    logbus.emit("ROUTER", f"{source}: chat{' + thinking' if thinking else ''}", _brief(value, 160))
    reply = chat_agent.respond(value, lang, "", request_id=request_id, thinking=thinking)
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
