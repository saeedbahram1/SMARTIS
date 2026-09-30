from __future__ import annotations

import asyncio
import json
import os
import queue
import re
import tempfile
import threading
import time
from contextlib import asynccontextmanager
from pathlib import Path

import numpy as np
import psutil
import uvicorn
from fastapi import FastAPI, File, Form, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

from agent.command_normalizer import normalize_command_text
from agent.executor import execute_plan, execute_pending_confirmation, pending_confirmation, clear_pending_confirmation
from agent.fast_path import fast_plan
from agent.planner import fallback_plan, plan_with_ollama
from agent.context_memory import memory
from agent import chat as chat_agent
from agent.echo_guard import guard as echo_guard
from agent.logbus import logbus
from config import HOST, PORT, NOISE_GATE_MODE, SPEAK_TAIL_GUARD_SECONDS
from services.internet_service import InternetMonitor
from services.microphone_service import MicrophoneService
from services.sherpa_service import SherpaService
from services.tts_service import TTSService

stt = SherpaService()
internet = InternetMonitor()
tts = TTSService(internet)
microphone = MicrophoneService(stt)

# ---------------------------------------------------------------------------
# Dead-end detection.
#
# The old build replied with "I did not understand / try again" whenever the
# deterministic fast-path and the planner both failed. That is exactly what made
# Smartis feel broken. Such a reply is now treated as a failure and re-routed to
# the conversational layer, which always answers.
# ---------------------------------------------------------------------------
_DEAD_END_PATTERNS = (
    "متوجه نشدم", "نفهمیدم", "نمی‌فهمم", "دوباره امتحان", "دوباره بگو",
    "متاسفم", "متأسفم", "نمیتوانم", "نمی‌توانم", "درخواست شما", "مشخص نیست",
    "پشتیبانی نمی", "قابل انجام نیست", "i did not understand", "i don't understand",
    "i do not understand", "try again", "i cannot", "i can't", "sorry, i",
    "not able to", "unrecognized", "no command",
)


def _is_dead_end(reply: str) -> bool:
    value = str(reply or "").strip().lower()
    if not value:
        return True
    if len(value) > 220:
        return False
    return any(pattern in value for pattern in _DEAD_END_PATTERNS)


def _json_safe(value):
    """Recursively convert numpy/scalar/container values into JSON-native values."""
    if isinstance(value, np.generic):
        return _json_safe(value.item())
    if isinstance(value, np.ndarray):
        return [_json_safe(item) for item in value.tolist()]
    if isinstance(value, dict):
        return {str(k): _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set, frozenset)):
        return [_json_safe(v) for v in value]
    if isinstance(value, Path):
        return str(value)
    return value


def _json_default(value):
    """Last-resort encoder for unusual Windows/NumPy scalar objects."""
    if isinstance(value, np.generic):
        return value.item()
    if isinstance(value, np.ndarray):
        return value.tolist()
    if isinstance(value, Path):
        return str(value)
    item = getattr(value, "item", None)
    if callable(item):
        try:
            return item()
        except Exception:
            pass
    return str(value)


def _json_payload(value) -> str:
    return json.dumps(
        _json_safe(value),
        ensure_ascii=False,
        separators=(",", ":"),
        default=_json_default,
    )


def _effective_language(text: str, language: str | None) -> str | None:
    normalized = normalize_command_text(text)
    # The transcript itself is the final authority for obvious Persian/English.
    # This prevents a noisy STT language hint from making Persian weather/TTS English.
    has_fa = bool(re.search(r"[\u0600-\u06FF]", normalized))
    has_latin = bool(re.search(r"[A-Za-z]", normalized))
    if has_fa:
        return "fa"
    if has_latin:
        return "en"
    return language


# Utterances that are always meaningful, even when they are only one short word.
_SHORT_COMMANDS = {
    "بله", "آره", "اره", "نه", "لغو", "بیخیال", "ادامه", "ادامه بده", "مکث", "توقف",
    "بس", "بسه", "کمک", "سلام", "درود", "تایید", "تأیید", "باشه", "حتما", "حتماً",
    "بخون", "بیشتر بگو", "کاملش کن",
    "yes", "yeah", "yep", "no", "nope", "stop", "cancel", "continue", "ok", "okay",
    "confirm", "read it", "tell me more",
}


def _should_ignore_transcript(text: str, language: str | None) -> bool:
    """Reject only clear STT noise.

    `NOISE_GATE_MODE=relaxed` (default) keeps every plausible sentence so Smartis
    can answer it conversationally. `strict` restores the old aggressive gate.
    """
    value = normalize_command_text(text).strip()
    if not value:
        return True

    low = value.lower()

    if NOISE_GATE_MODE == "strict":
        if re.search(r"[\u0600-\u06FF]", value):
            known = {"سلام", "درود", "گوگل", "یوتیوب", "اسمارتیز", "اسمارتیس", "ادامه", "ادامه بده",
                     "بله", "آره", "نه", "لغو", "کمک", "توقف", "بس", "مکث"}
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

    # ---- relaxed (default) -------------------------------------------------
    # Short confirmations/continuations are real commands, never noise.
    if low in _SHORT_COMMANDS:
        return False
    # Persian one/two letter fragments are almost always noise.
    if re.fullmatch(r"[\u0600-\u06FF\s]{1,2}", value):
        return True
    # Classic English STT hallucinations on silence/background noise.
    if low in {"you", "yeah", "uh", "um", "hmm", "mm", "oh", "ah", "the", "a", "i", "it",
               "so", "ok", "okay", "bye", "thank you", "thanks for watching", "subscribe"}:
        return True
    # A single latin token with no command/question cue is a noise hypothesis.
    words = re.findall(r"[A-Za-z]+|[\u0600-\u06FF]+", value)
    if len(words) == 1 and len(value) <= 3 and not re.search(r"[?؟]", value):
        return True
    return False


_LOG_MEDIA_TOOLS = {
    "media_play_pause", "media_stop", "media_next", "media_previous",
    "player_volume_set", "player_volume_change", "player_volume_max", "player_mute",
    "play_media_search", "active_player", "system_volume_set", "system_volume_change",
    "system_mute",
}
_LOG_SYSTEM_TOOLS = {
    "shutdown_windows", "restart_windows", "sleep_windows", "cancel_shutdown",
    "set_windows_language", "open_windows_settings", "windows_system_search",
    "system_dashboard", "hardware_temperatures",
}


def _log_category_for_tool(tool: str) -> str:
    name = str(tool or "")
    if name in _LOG_MEDIA_TOOLS:
        return "MEDIA"
    if name in _LOG_SYSTEM_TOOLS:
        return "SYSTEM"
    return "EXECUTOR"


def _brief(value, limit: int = 420) -> str:
    text = str(value)
    return text if len(text) <= limit else text[:limit] + "..."


def build_agent_plan(text: str, language: str | None) -> dict:
    normalized = normalize_command_text(text)
    contextual = memory.resolve_references(normalized)
    language = _effective_language(normalized, language)
    # Always give the deterministic engine first chance. Its semantic splitter
    # validates each side as an independent action, so ordinary query words such
    # as «و» are not blindly treated as action boundaries. Ollama remains the
    # fallback for genuinely ambiguous/unsupported multi-step requests.
    fast = fast_plan(contextual, language)
    if fast is not None:
        plan = fast.get("plan") or {}
        actions = plan.get("actions") or []
        logbus.emit(
            "FAST_PATH",
            f"Deterministic match: {len(actions)} action(s) planned.",
            _brief({"provider": fast.get("provider"), "actions": actions}),
        )
        return fast

    # Anything that is not a high-confidence deterministic fast path goes to the
    # LOCAL Ollama model. This is the semantic layer: it understands paraphrases,
    # sentence structure and targets instead of requiring a fixed trigger phrase.
    result = plan_with_ollama(contextual, language, memory.context_text())
    if result.get("ok"):
        plan = result.get("plan") or {}
        actions = plan.get("actions") or []
        reply = str(plan.get("reply") or "")
        # A plan with real actions, or a genuine non-dead-end reply, is accepted.
        if actions or not _is_dead_end(reply):
            logbus.emit(
                "PLANNER",
                f"Constructed semantic plan with {len(actions)} action(s).",
                _brief({"reply": reply, "actions": actions}),
            )
            return result
        logbus.emit(
            "PLANNER",
            "Planner returned a dead-end reply; routing to the conversational layer.",
            _brief(reply),
        )

    # ------------------------------------------------------------------
    # Conversational fallback: Smartis answers like a human instead of
    # saying "I did not understand". Local model only, no paid cloud API.
    # ------------------------------------------------------------------
    conversational = chat_agent.respond(contextual, language, memory.context_text())
    if conversational.get("ok") and str(conversational.get("reply") or "").strip():
        logbus.emit(
            "PLANNER",
            f"Conversational answer generated ({conversational.get('provider')}).",
            _brief(conversational.get("reply")),
        )
        return {
            "ok": True,
            "provider": conversational.get("provider", "chat-local"),
            "conversational": True,
            "plan": {
                "reply": str(conversational.get("reply") or "").strip(),
                "actions": [],
                "needs_confirmation": False,
            },
        }

    # Absolute last resort — still never a dead end.
    fallback = fallback_plan(contextual)
    plan = fallback.get("plan") or {}
    if _is_dead_end(plan.get("reply")):
        plan = {
            "reply": "بگو در خدمتم؛ هر دستوری روی ویندوز یا هر سؤالی داشتی، همین‌جا جواب می‌دم.",
            "actions": [],
            "needs_confirmation": False,
        }
        fallback["plan"] = plan
    return fallback


def _affirmative_text(text: str) -> bool:
    value = re.sub(r"\s+", " ", str(text or "").strip().lower())
    if value in {"بله", "آره", "اره", "تایید", "تأیید", "تایید میکنم", "تأیید می‌کنم", "حتما", "حتماً",
                 "باشه", "yes", "yeah", "yep", "sure", "okay", "ok", "confirm", "confirmed"}:
        return True
    return bool(re.fullmatch(r"(?:بله|آره|اره|حتما|حتماً|باشه)(?:\s+(?:انجام(?:ش)?|تأیید(?:ش)?))?(?:\s+(?:بده|بدهش|کن|کنش|بکن))?", value, re.I))


def _negative_text(text: str) -> bool:
    value = re.sub(r"\s+", " ", str(text or "").strip().lower())
    if value in {"نه", "نخیر", "لغو", "بیخیال", "no", "nope", "cancel", "stop"}:
        return True
    if re.search(r"^(?:نه|نخیر|بیخیال|نمیخوام|نمی‌خوام|no|nope|cancel|stop)\b", value, re.I):
        return True
    return bool(re.search(r"(?:لغو|بیخیال|cancel|stop)\s*(?:کن|کنش|بده|بدهش|شو)?$", value, re.I))


def _confirmation_prompt(language: str | None) -> str:
    return "تأیید می‌کنی؟" if language != "en" else "Do you want me to go ahead?"


def process_command(text: str, language: str | None) -> dict:
    """Plan + execute. Confirmation replies are consumed by the backend state."""
    # ------------------------------------------------------------------
    # Echo protection: never treat Smartis' own voice as a new command.
    # ------------------------------------------------------------------
    if echo_guard.is_echo(text):
        logbus.emit("STT", "Self-voice detected and discarded (echo guard).", _brief(text))
        return {
            "ok": True,
            "ignored": True,
            "provider": "echo-guard",
            "plan": {"reply": "", "actions": [], "needs_confirmation": False},
            "execution": {"ok": True, "results": []},
        }

    # A pending confirmation is consumed BEFORE the noise gate: a bare "بله"
    # must be able to confirm, and it is only three characters long.
    awaiting = pending_confirmation()

    if not awaiting and _should_ignore_transcript(text, language):
        logbus.emit("STT", "Transcript discarded as background noise.", _brief(text))
        return {
            "ok": True,
            "ignored": True,
            "provider": "noise-gate",
            "plan": {"reply": "", "actions": [], "needs_confirmation": False},
            "execution": {"ok": True, "results": []},
        }

    if awaiting:
        if _affirmative_text(text):
            logbus.emit("CONFIRMATION", "User confirmed the pending action.", _brief(text))
            execution = execute_pending_confirmation()
            ok = execution.get("ok") is True
            reply = ("انجام شد." if language != "en" else "Done.") if ok else (
                f"انجام نشد؛ {execution.get('error') or 'عملیات با خطا مواجه شد.'}"
                if language != "en"
                else f"It failed: {execution.get('error') or 'the operation returned an error.'}"
            )
            return {
                "ok": ok,
                "provider": "confirmation",
                "plan": {"reply": reply, "actions": [], "needs_confirmation": False},
                "execution": execution,
            }
        if _negative_text(text):
            logbus.emit("CONFIRMATION", "User cancelled the pending action.", _brief(text))
            clear_pending_confirmation()
            return {
                "ok": True,
                "provider": "confirmation",
                "plan": {
                    "reply": "باشه، انجامش نمی‌دم." if language != "en" else "Okay, I won't do it.",
                    "actions": [],
                    "needs_confirmation": False,
                },
                "execution": {"ok": True, "needs_confirmation": False, "results": []},
            }

    planned = build_agent_plan(text, language)
    if planned.get("ok") is not True:
        return planned

    plan = planned.get("plan") or {}
    if plan.get("needs_confirmation") is True:
        prompt = str(plan.get("reply") or "").strip()
        if _is_dead_end(prompt):
            prompt = _confirmation_prompt(language)
        plan = dict(plan)
        plan["reply"] = prompt
        return {
            "ok": True,
            "provider": planned.get("provider", "unknown"),
            "plan": plan,
            "execution": {"ok": True, "needs_confirmation": True, "results": []},
        }

    execution = execute_plan(plan, False)
    reply = str(plan.get("reply") or "")

    for item in execution.get("results") or []:
        tool = str(item.get("tool") or "")
        result = item.get("result") or {}
        ok = result.get("ok") is True
        logbus.emit(
            _log_category_for_tool(tool),
            f"{'Executed' if ok else 'Failed'}: {tool}",
            _brief({"tool": tool, "result": result}),
        )
    if execution.get("needs_confirmation") is True:
        logbus.emit(
            "CONFIRMATION",
            "Destructive action queued; waiting for the user's confirmation.",
            _brief(plan),
        )

    if execution.get("needs_confirmation") is True:
        # Reached when the planner did not flag confirmation but the executor
        # did (e.g. the local model produced a power action directly).
        prompt = _confirmation_prompt(language)
        plan = dict(plan)
        plan["reply"] = prompt
        plan["needs_confirmation"] = True
        return {
            "ok": True,
            "provider": planned.get("provider", "unknown"),
            "plan": plan,
            "execution": execution,
        }

    if execution.get("ok") is not True:
        error = str(execution.get("error") or ("عملیات با خطا مواجه شد." if language != "en" else "The operation failed."))
        reply = (f"انجام نشد؛ {error}" if language != "en" else f"It failed: {error}")

    if not reply:
        reply = "انجام شد." if language != "en" else "Done."

    memory.remember(text, plan, execution, reply=reply)
    response_plan = dict(plan)
    response_plan["reply"] = reply
    return {
        "ok": execution.get("ok") is True,
        "provider": planned.get("provider", "unknown"),
        "plan": response_plan,
        "execution": execution,
    }


def process_chat(text: str, language: str | None) -> dict:
    """Typed-chat entry point. Answers like a human, never a dead end."""
    value = str(text or "").strip()
    if not value:
        return {"ok": False, "error": "Text is empty."}

    language = _effective_language(value, language)

    # A typed message that is clearly a Windows command still executes.
    fast = fast_plan(normalize_command_text(value), language)
    if fast is not None and (fast.get("plan") or {}).get("actions"):
        result = process_command(value, language)
        result["mode"] = "command"
        return result

    reply = chat_agent.respond(value, language, memory.context_text())
    plan = {
        "reply": str(reply.get("reply") or "").strip(),
        "actions": [],
        "needs_confirmation": False,
    }
    execution = {"ok": True, "needs_confirmation": False, "results": []}
    memory.remember(value, plan, execution, reply=plan["reply"])
    return {
        "ok": True,
        "mode": "chat",
        "provider": reply.get("provider", "chat-local"),
        "plan": plan,
        "execution": execution,
    }


# ---------------------------------------------------------------------------
# Self-voice suppression.
#
# Uses only the microphone service's existing public API (state / pause /
# resume), so microphone_service.py itself does not have to change.
#
# The watchdog re-pauses the microphone if anything (e.g. an early client-side
# resume) turns listening back on while Smartis is still speaking. This is the
# backend half of the fix for "Smartis listens to its own Wikipedia reading".
# ---------------------------------------------------------------------------
_SPEAK_LOCK = threading.Lock()
_SPEAK_UNTIL = 0.0
_SPEAK_HELD = False


def _hold_microphone(seconds: float) -> None:
    """Keep the microphone suppressed for `seconds`, and re-arm if needed."""
    global _SPEAK_UNTIL, _SPEAK_HELD
    with _SPEAK_LOCK:
        _SPEAK_UNTIL = max(_SPEAK_UNTIL, time.monotonic() + max(0.5, float(seconds)))
        _SPEAK_HELD = True
    try:
        microphone.pause_listening()
    except Exception:
        pass


def _microphone_watchdog() -> None:
    global _SPEAK_HELD
    while True:
        time.sleep(0.3)
        with _SPEAK_LOCK:
            remaining = _SPEAK_UNTIL - time.monotonic()
            held = _SPEAK_HELD
        try:
            if remaining > 0:
                if microphone.state == "listening":
                    # Something re-enabled listening while Smartis is still
                    # speaking -> re-pause so its own voice cannot be captured.
                    microphone.pause_listening()
                    _SPEAK_HELD = True
            elif held:
                if microphone.state == "paused":
                    microphone.resume_listening()
                _SPEAK_HELD = False
        except Exception:
            pass


def _estimate_speech_seconds(result: dict, text: str) -> float:
    """Best-effort duration of the audio that was just synthesised.

    Used as a microphone suppression window so Smartis cannot hear itself.
    """
    data = result.get("audio_base64") or ""
    if data:
        try:
            raw_bytes = int(len(str(data)) * 3 / 4)
            # edge-tts default output is ~48 kbit/s mono mp3 => ~6000 bytes/s.
            seconds = raw_bytes / 6000.0
        except Exception:
            seconds = 0.0
    else:
        seconds = 0.0
    if seconds <= 0.0:
        # Fallback heuristic for offline TTS: ~13 Persian/English chars per second.
        seconds = max(1.5, len(str(text or "")) / 13.0)
    return max(1.5, seconds + SPEAK_TAIL_GUARD_SECONDS)


@asynccontextmanager
async def lifespan(app: FastAPI):
    del app
    stt.load()
    status = stt.status_dict()
    print("=" * 60)
    print("SMARTIS backend ready")
    print(f"  Persian STT (Shenava-Koochik) ready : {status['fa_ready']}")
    print(f"  English STT (Zipformer-large) ready : {status['en_ready']}")
    if not status["fa_ready"]:
        print(f"  -> {stt.fa_error}")
    if not status["en_ready"]:
        print(f"  -> {stt.en_error}")
    microphone.start()
    threading.Timer(1.2, microphone.restart).start()
    print(f"  Microphone service started          : {microphone.status_dict()}")
    print("  Direct listening                    : ENABLED")
    print(f"  Noise gate mode                     : {NOISE_GATE_MODE}")
    print(f"  Conversational layer                : local Ollama ({chat_agent.CHAT_MODEL})")
    print("=" * 60)
    logbus.emit(
        "SYSTEM",
        "Smartis backend started: STT loaded, microphone listening, conversational layer ready.",
        _brief({"persian_stt": status["fa_ready"], "english_stt": status["en_ready"],
                "noise_gate": NOISE_GATE_MODE, "chat_model": chat_agent.CHAT_MODEL}),
    )
    threading.Thread(target=_microphone_watchdog, name="smartis-mic-watchdog", daemon=True).start()
    chat_agent.warm_up()
    yield
    microphone.stop()


app = FastAPI(title="Smartis Backend", version="2.2.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
async def health():
    return _json_safe(
        {
            "ok": True,
            "service": "smartis-backend",
            "microphone": microphone.status_dict(),
            **stt.status_dict(),
            "online_tts_engine": "edge-tts",
            "offline_tts": True,
            "online_tts": True,
            "direct_listening": True,
            "conversational": True,
            "chat_model": chat_agent.CHAT_MODEL,
            "noise_gate": NOISE_GATE_MODE,
            "echo_guard": echo_guard.stats(),
        }
    )


@app.get("/status")
async def status():
    return _json_safe(
        {
            "ok": True,
            "speech": stt.status_dict(),
            "microphone": microphone.status_dict(),
        }
    )


@app.get("/system")
async def system_info():
    import agent.system_tools as system_tools
    dashboard_data, temps = await asyncio.gather(
        asyncio.to_thread(system_tools.get_dashboard),
        asyncio.to_thread(system_tools.get_hardware_temperatures),
    )
    return _json_safe({**dashboard_data, **temps})


@app.get("/dashboard")
async def dashboard():
    import agent.system_tools as system_tools
    language = "fa"
    result, temps, location, weather = await asyncio.gather(
        asyncio.to_thread(system_tools.get_dashboard),
        asyncio.to_thread(system_tools.get_hardware_temperatures),
        asyncio.to_thread(system_tools._LOCATION_WEATHER.location),
        asyncio.to_thread(system_tools.get_location_weather, language),
    )
    result.update(temps)
    result["time_date"] = system_tools.get_time_date(language)
    result["location"] = location
    result["weather"] = weather
    result["voices"] = tts.settings()
    return _json_safe(result)


@app.get("/voices")
async def voices():
    return _json_safe({"ok": True, "voices": tts.voices(), "settings": tts.settings()})


@app.get("/history")
async def history():
    """Recent turns for the chat UI, oldest first.

    Reads the existing public `memory.turns` deque, so agent/context_memory.py
    itself does not have to be modified.
    """
    turns = []
    for turn in list(memory.turns)[-60:]:
        text = str(getattr(turn, "user", "") or "")
        turns.append(
            {
                "user": text,
                "reply": str(getattr(turn, "reply", "") or ""),
                "subject": str(getattr(turn, "subject", "") or ""),
                "action": str(getattr(turn, "action", "") or ""),
                "timestamp": float(getattr(turn, "timestamp", 0.0) or 0.0),
                "language": "en" if re.search(r"[A-Za-z]", text) and not re.search(r"[\u0600-\u06FF]", text) else "fa",
            }
        )
    return _json_safe({"ok": True, "turns": turns})


@app.get("/logs")
async def logs():
    return _json_safe({"ok": True, "entries": logbus.recent(200)})


@app.post("/voice/settings")
async def voice_settings(payload: dict):
    language = str(payload.get("language", "fa"))
    gender = str(payload.get("gender", "female"))
    return _json_safe(tts.set_voice(language, gender))


async def save_upload(upload: UploadFile) -> str:
    suffix = Path(upload.filename or ".wav").suffix or ".wav"
    data = await upload.read()
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as handle:
        handle.write(data)
        return handle.name


def cleanup(path: str) -> None:
    try:
        os.remove(path)
    except OSError:
        pass


@app.post("/transcribe")
async def transcribe(
    audio: UploadFile = File(...),
    language_hint: str | None = Form(default=None),
):
    raw_path = await save_upload(audio)
    try:
        result = await asyncio.to_thread(
            stt.transcribe_file,
            raw_path,
            language_hint,
            False,
        )
        result = _json_safe(result)
        print(
            f"[transcribe] ok={result.get('ok')} provider={result.get('provider')} "
            f"language={result.get('language')} text={result.get('text')!r} "
            f"error={result.get('error')}"
        )
        return result
    finally:
        cleanup(raw_path)


@app.post("/speak")
async def speak(payload: dict):
    text = str(payload.get("text", "")).strip()
    language = payload.get("language")
    if not text:
        return {"ok": False, "error": "Text is empty."}

    # Remember what Smartis is about to say so its own voice can never be
    # re-interpreted as a new command (the Wikipedia read-aloud loop).
    echo_guard.note_spoken(text)

    # The Flutter client keeps listening paused until the generated audio has
    # finished playing. The hold below is the backend-side guarantee in case the
    # client resumes early (that early resume was the original bug).
    result = await asyncio.to_thread(tts.speak, text, language)
    result = _json_safe(result)

    hold = _estimate_speech_seconds(result, text)
    _hold_microphone(hold)
    result["suppress_seconds"] = round(hold, 2)
    logbus.emit(
        "SYSTEM",
        f"Speech synthesised ({result.get('provider') or 'tts'}); microphone held for {hold:.1f}s.",
        _brief(text),
    )

    print(
        f"[speak] ok={result.get('ok')} provider={result.get('provider')} "
        f"offline={result.get('offline')} suppress={result['suppress_seconds']}s "
        f"error={result.get('error')}"
    )
    return result


@app.post("/command")
async def command(payload: dict):
    text = str(payload.get("text", "")).strip()
    language = payload.get("language")
    if not text:
        return {"ok": False, "error": "Text is empty."}
    return _json_safe(await asyncio.to_thread(process_command, text, language))


@app.post("/chat")
async def chat_endpoint(payload: dict):
    text = str(payload.get("text", "")).strip()
    language = payload.get("language")
    if not text:
        return {"ok": False, "error": "Text is empty."}
    return _json_safe(await asyncio.to_thread(process_chat, text, language))


@app.post("/agent/plan")
async def agent_plan(payload: dict):
    text = str(payload.get("text", "")).strip()
    language = payload.get("language")
    if not text:
        return {"ok": False, "error": "Text is empty."}
    return _json_safe(await asyncio.to_thread(build_agent_plan, text, language))


@app.post("/agent/execute")
async def agent_execute(payload: dict):
    plan = payload.get("plan")
    confirmed = bool(payload.get("confirmed", False))
    if not isinstance(plan, dict):
        return {"ok": False, "error": "Invalid plan."}
    return _json_safe(await asyncio.to_thread(execute_plan, plan, confirmed))


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    events = microphone.subscribe()
    log_events = logbus.subscribe()
    send_lock = asyncio.Lock()

    async def send_json_event(payload: dict) -> None:
        async with send_lock:
            await websocket.send_text(_json_payload(payload))

    await send_json_event(
        {
            "type": "backend_ready",
            "internet": internet.is_online(),
            "online_stt_ready": False,
            "speech": stt.status_dict(),
            "microphone": microphone.status_dict(),
            "direct_listening": True,
            "conversational": True,
            "chat_model": chat_agent.CHAT_MODEL,
            "noise_gate": NOISE_GATE_MODE,
        }
    )

    async def send_events() -> None:
        while True:
            try:
                event = await asyncio.to_thread(events.get, True, 0.25)
                await send_json_event(event)
            except queue.Empty:
                pass
            try:
                entry = await asyncio.to_thread(log_events.get, True, 0.25)
                await send_json_event(entry)
            except queue.Empty:
                pass

    for entry in logbus.recent(80):
        await send_json_event(entry)

    async def receive_actions() -> None:
        while True:
            message = await websocket.receive_json()
            action = message.get("action")

            if action == "ping":
                await send_json_event({"type": "pong"})
            elif action == "status":
                await send_json_event({
                    "type": "status",
                    "speech": stt.status_dict(),
                    "microphone": microphone.status_dict(),
                })
            elif action == "mic_stop_command":
                result = microphone.stop_command()
                await send_json_event({"type": "mic_command_stopped", **result})
            elif action == "mic_pause":
                result = microphone.pause_listening()
                await send_json_event({"type": "mic_paused", **result})
            elif action == "mic_resume":
                result = microphone.resume_listening()
                await send_json_event({"type": "mic_resumed", **result})
            elif action == "mic_restart":
                await asyncio.to_thread(microphone.restart)
                await send_json_event({"type": "mic_restarted", "microphone": microphone.status_dict()})
            elif action == "speak":
                text = str(message.get("text", ""))
                language = message.get("language")
                echo_guard.note_spoken(text)
                result = await asyncio.to_thread(tts.speak, text, language)
                result = _json_safe(result)
                hold = _estimate_speech_seconds(result, text)
                _hold_microphone(hold)
                result["suppress_seconds"] = round(hold, 2)
                await send_json_event({"type": "tts_result", **result})
            elif action == "command":
                text = str(message.get("text", "")).strip()
                language = message.get("language")
                result = await asyncio.to_thread(process_command, text, language)
                await send_json_event({"type": "command", **result})
            elif action == "chat":
                text = str(message.get("text", "")).strip()
                language = message.get("language")
                result = await asyncio.to_thread(process_chat, text, language)
                await send_json_event({"type": "chat", **result})
            elif action == "agent_plan":
                text = str(message.get("text", "")).strip()
                language = message.get("language")
                result = await asyncio.to_thread(build_agent_plan, text, language)
                await send_json_event({"type": "agent_plan", **result})
            elif action == "agent_execute":
                result = await asyncio.to_thread(
                    execute_plan,
                    message.get("plan"),
                    bool(message.get("confirmed", False)),
                )
                await send_json_event({"type": "agent_execute", **result})
            else:
                await send_json_event({"type": "info", "message": "Unknown action."})

    sender = asyncio.create_task(send_events())
    receiver = asyncio.create_task(receive_actions())
    try:
        done, pending = await asyncio.wait(
            {sender, receiver},
            return_when=asyncio.FIRST_EXCEPTION,
        )
        del pending
        for task in done:
            if not task.cancelled():
                error = task.exception()
                if error is not None:
                    raise error
    except WebSocketDisconnect:
        pass
    finally:
        for task in (sender, receiver):
            task.cancel()
        await asyncio.gather(sender, receiver, return_exceptions=True)
        microphone.unsubscribe(events)
        logbus.unsubscribe(log_events)


if __name__ == "__main__":
    uvicorn.run(app, host=HOST, port=PORT)
