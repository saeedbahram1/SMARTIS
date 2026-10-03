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
from agent.executor import execute_plan, execute_pending_confirmation, pending_confirmation, pending_summary, clear_pending_confirmation
from agent.fast_path import fast_plan
from agent.planner import fallback_plan, plan_with_ollama
from agent.context_memory import memory
from agent import attachments
from agent import chat as chat_agent
from agent import router
from agent.echo_guard import guard as echo_guard
from agent.logbus import logbus
from agent.ollama_model import model_status, resolve_model, ensure_ollama, shutdown_ollama
from config import HOST, PORT, NOISE_GATE_MODE, SPEAK_TAIL_GUARD_SECONDS
from services.internet_service import InternetMonitor
from services.microphone_service import MicrophoneService
from services.sherpa_service import SherpaService
from services.tts_service import TTSService

stt = SherpaService()
internet = InternetMonitor()
tts = TTSService(internet)
microphone = MicrophoneService(stt)
UVICORN_SERVER = None

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


# Noise gate, yes/no recognition and command-vs-chat routing live in agent/router.py.
_should_ignore_transcript = router.should_ignore_transcript
_affirmative_text = router.affirmative_text
_negative_text = router.negative_text


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


def _looks_like_command(text: str) -> bool:
    low = normalize_command_text(text).lower()
    command_cues = (
        "باز کن", "بازش کن", "اجرا کن", "برو به", "برو تو", "بیاور",
        "open", "launch", "start", "go to", "volume", "صدا", "میزان صدا",
        "پخش", "آهنگ", "موزیک", "play", "pause", "stop", "next", "previous",
        "ساخت", "بساز", "ایجاد", "create", "delete", "حذف", "پاک",
        "خاموش", "ری استارت", "restart", "shutdown", "sleep", "خواب",
        "تنظیمات", "settings", "زبان ویندوز", "windows language",
        "میکروفون", "microphone", "ویندوز سرچ", "windows search",
    )
    return any(cue in low for cue in command_cues)


def _has_explicit_information_intent(text: str) -> bool:
    low = normalize_command_text(text).lower()
    info_cues = (
        "سرچ", "جستجو", "جست‌وجو", "search", "look up",
        "تحقیق", "بررسی", "درباره", "در مورد", "راجع به",
        "who ", "what ", "why ", "how ", "چیست", "چیه", "کیه",
        "اخبار", "خبر", "news", "weather", "آب و هوا", "هوا",
    )
    return any(cue in low for cue in info_cues)


def _planner_has_spurious_search(text: str, result: dict) -> bool:
    if not _looks_like_command(text) or _has_explicit_information_intent(text):
        return False
    plan = result.get("plan") or {}
    for action in plan.get("actions") or []:
        tool = str(action.get("tool") or "")
        if tool == "web_research":
            return True
        if tool == "open_chrome_url":
            url = str((action.get("args") or {}).get("url") or "").lower()
            if "google.com/search" in url or "bing.com/search" in url:
                return True
    return False


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
    if result.get("ok") and _planner_has_spurious_search(contextual, result):
        logbus.emit(
            "PLANNER",
            "Rejected a planner-generated web search for a command-like utterance.",
            _brief({"text": contextual, "plan": result.get("plan")}),
        )
        result = {"ok": False, "provider": "ollama-local", "error": "spurious_search_for_command"}
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

    # Command mode must never fall through into conversational Chat.
    # If deterministic Fast Path cannot identify the command, only the
    # command planner may be used; its short timeout and JSON-only contract
    # keep execution separate from the Chat/Qwen conversational surface.
    logbus.emit("PLANNER", "Command planner did not produce an executable plan; using deterministic fallback.", _brief({"text": contextual, "error": result.get("error")}))

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


def process_command(text: str, language: str | None, request_id: str | None = None, thinking: bool = False) -> dict:
    """Voice entry point (microphone transcript). Same router as typed chat."""
    return router.handle_input(text, language, source="voice", request_id=request_id, thinking=thinking)


def process_chat(
    text: str,
    language: str | None,
    request_id: str | None = None,
    thinking: bool = False,
    extra_context: str = "",
) -> dict:
    """Typed entry point. Commands are executed, everything else is answered by Ollama."""
    return router.handle_input(
        text, language, source="text", request_id=request_id, thinking=thinking, extra_context=extra_context
    )


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


def _release_microphone_hold() -> None:
    """Immediately release the extra TTS safety hold after Stop is pressed."""
    global _SPEAK_UNTIL, _SPEAK_HELD
    with _SPEAK_LOCK:
        _SPEAK_UNTIL = 0.0
        _SPEAK_HELD = False


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
        seconds = max(0.8, len(str(text or "")) / 13.0)
    return max(0.75, seconds + SPEAK_TAIL_GUARD_SECONDS)


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
    # Load Qwen in the BACKGROUND with exactly the options chat uses. It no
    # longer blocks start-up, and chat does not depend on it: Ollama loads the
    # model on demand if a request arrives before the warm-up has finished.
    ollama = model_status()
    logbus.emit("OLLAMA", "Ollama local model status", _brief(ollama))
    warmup = {"ok": None, "note": "running in background"}

    def _background_warmup() -> None:
        result = chat_agent.warm_up()
        logbus.emit("OLLAMA", f"Model warm-up {'finished' if result.get('ok') else 'failed'}", _brief(result))

    threading.Thread(target=_background_warmup, name="smartis-ollama-warmup", daemon=True).start()

    microphone.start()
    threading.Timer(1.2, microphone.restart).start()
    print(f"  Microphone service started          : {microphone.status_dict()}")
    print("  Direct listening                    : ENABLED")
    print(f"  Noise gate mode                     : {NOISE_GATE_MODE}")
    print(f"  Conversational layer                : local Ollama ({resolve_model()})")
    print("=" * 60)
    logbus.emit(
        "SYSTEM",
        "Smartis backend started: STT loaded, microphone listening, conversational layer ready.",
        _brief({"persian_stt": status["fa_ready"], "english_stt": status["en_ready"],
                "noise_gate": NOISE_GATE_MODE, "chat_model": resolve_model(), "ollama_warmup": warmup.get("ok")}),
    )
    threading.Thread(target=_microphone_watchdog, name="smartis-mic-watchdog", daemon=True).start()
    yield
    microphone.stop()
    ollama_shutdown = shutdown_ollama()
    logbus.emit("SYSTEM", "Smartis shutdown: microphone and Smartis-owned Ollama server stopped.", _brief(ollama_shutdown))


app = FastAPI(title="Smartis Backend", version="2.13.0", lifespan=lifespan)
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
            "chat_model": resolve_model(),
            "ollama": model_status(),
            "noise_gate": NOISE_GATE_MODE,
            "pending_confirmation": pending_summary("fa"),
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


@app.post("/chat/upload")
async def chat_upload(
    files: list[UploadFile] = File(...),
    language: str | None = Form(default=None),
):
    """Chat attachments: store each uploaded file and return a descriptor.

    The client sends attachment IDs (not paths) with the next /chat message;
    the backend turns them into a content block the chat model can read.
    """
    stored = []
    for upload in files:
        try:
            data = await upload.read()
        except Exception as exc:  # noqa: BLE001 - a broken upload must not kill the batch
            stored.append({"ok": False, "name": upload.filename or "?", "error": str(exc)})
            continue
        record = await asyncio.to_thread(attachments.store_upload, upload.filename or "file", data, language)
        if record.get("ok"):
            count = int(record.get("files") or 0)
            suffix = f", {count} entries" if record.get("kind") == "zip" else ""
            logbus.emit(
                "CHAT",
                f"Attachment received: {record.get('name')} ({record.get('size_label')}, {record.get('kind')}{suffix})",
                _brief(str(record.get("name"))),
            )
        stored.append(record)
    return _json_safe({"ok": True, "attachments": stored})


@app.post("/command")
async def command(payload: dict):
    text = str(payload.get("text", "")).strip()
    language = payload.get("language")
    request_id = str(payload.get("request_id") or "").strip() or None
    thinking = bool(payload.get("thinking", False))
    if not text:
        return {"ok": False, "error": "Text is empty."}
    return _json_safe(await asyncio.to_thread(process_command, text, language, request_id, thinking))


@app.post("/chat")
async def chat_endpoint(payload: dict):
    text = str(payload.get("text", "")).strip()
    language = payload.get("language")
    request_id = str(payload.get("request_id") or "").strip() or None
    thinking = bool(payload.get("thinking", False))
    attachment_ids = [str(item) for item in (payload.get("attachments") or []) if str(item).strip()][:4]

    extra_context = ""
    if attachment_ids:
        lang_hint = _effective_language(text, language) or "fa"
        logbus.emit_step(
            "بررسی فایل‌های ضمیمه…" if lang_hint != "en" else "Inspecting the attached files…", "attach"
        )
        extra_context = await asyncio.to_thread(attachments.context_for, attachment_ids, lang_hint, text)
        if not text:
            # «فایل رو بفرست» with no question: the user still wants it examined.
            text = "این فایل را کامل بررسی کن و توضیح بده داخلش چیست." if lang_hint != "en" else "Inspect this file fully and explain what is inside."
    if not text:
        return {"ok": False, "error": "Text is empty."}
    result = await asyncio.to_thread(process_chat, text, language, request_id, thinking, extra_context)
    result = _json_safe(result)
    if attachment_ids:
        result["attachments_used"] = True
    return result


@app.post("/chat/cancel")
async def chat_cancel(payload: dict):
    request_id = str(payload.get("request_id") or "").strip()
    if not request_id:
        return {"ok": False, "error": "request_id is required"}
    return {"ok": chat_agent.cancel_request(request_id), "cancelled": True}


@app.post("/shutdown")
async def shutdown_backend():
    global UVICORN_SERVER
    # Do the owned-resource cleanup here as well as in lifespan. This makes
    # the explicit Smartis close button deterministic even if Uvicorn exits
    # before the lifespan finalizer gets a chance to run.
    shutdown_result = await asyncio.to_thread(shutdown_ollama)
    microphone.stop()
    if UVICORN_SERVER is not None:
        UVICORN_SERVER.should_exit = True
    logbus.emit("SYSTEM", "Explicit Smartis shutdown requested", _brief(shutdown_result))
    return {"ok": True, "shutting_down": True, "ollama": shutdown_result}


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
    background_tasks: set = set()

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
            "chat_model": resolve_model(),
            "ollama": model_status(),
            "noise_gate": NOISE_GATE_MODE,
        }
    )

    async def send_events() -> None:
        """Pump both event queues CONCURRENTLY.

        The previous version polled the microphone queue and then the log queue
        in the same loop iteration, each with a 0.25 s blocking get. A mic_level
        or mic_state event that arrived right after the mic poll therefore had
        to wait for the log poll to time out: up to 0.5 s of pure transport lag
        on top of the real audio pipeline. That lag is what made the Orb look
        desynchronised from listening/processing/speaking. Each queue now has
        its own task, so nothing can head-of-line block anything else.
        """
        async def _pump(source: "queue.Queue") -> None:
            while True:
                try:
                    first = await asyncio.to_thread(source.get, True, 0.2)
                except queue.Empty:
                    continue
                batch = [first]
                while len(batch) < 32:
                    try:
                        batch.append(source.get_nowait())
                    except queue.Empty:
                        break
                for payload in batch:
                    await send_json_event(payload)

        await asyncio.gather(_pump(events), _pump(log_events))

    for entry in logbus.recent(200):
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
            elif action == "speak_stop":
                _release_microphone_hold()
                microphone.resume_listening()
                await send_json_event({"type": "speech_stopped"})
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
            elif action in {"command", "chat"}:
                text = str(message.get("text", "")).strip()
                language = message.get("language")
                request_id = str(message.get("request_id") or "").strip() or None
                thinking = bool(message.get("thinking", False))
                fn = process_command if action == "command" else process_chat

                async def run_request(fn=fn, kind=action, text=text, language=language, request_id=request_id, thinking=thinking) -> None:
                    # Own task: a slow model answer must never block the socket
                    # (mic pause/resume, ping, cancel) while Ollama is thinking.
                    try:
                        result = await asyncio.to_thread(fn, text, language, request_id, thinking)
                        await send_json_event({"type": kind, **result})
                    except Exception as exc:  # noqa: BLE001
                        logbus.emit("SYSTEM", f"{kind} request failed: {type(exc).__name__}", _brief(exc))
                        await send_json_event({"type": kind, "ok": False, "error": str(exc)})

                task = asyncio.create_task(run_request())
                background_tasks.add(task)
                task.add_done_callback(background_tasks.discard)
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
        for task in list(background_tasks):
            task.cancel()
        microphone.unsubscribe(events)
        logbus.unsubscribe(log_events)


if __name__ == "__main__":
    config = uvicorn.Config(app, host=HOST, port=PORT, log_level="warning")
    UVICORN_SERVER = uvicorn.Server(config)
    UVICORN_SERVER.run()
