from __future__ import annotations

import asyncio
import json
import os
import queue
import re
import tempfile
import threading
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
from config import HOST, PORT
from services.internet_service import InternetMonitor
from services.microphone_service import MicrophoneService
from services.sherpa_service import SherpaService
from services.tts_service import TTSService

stt = SherpaService()
internet = InternetMonitor()
tts = TTSService(internet)
microphone = MicrophoneService(stt)


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
    has_fa = bool(__import__("re").search(r"[\u0600-\u06FF]", normalized))
    has_latin = bool(__import__("re").search(r"[A-Za-z]", normalized))
    if has_fa:
        return "fa"
    if has_latin:
        return "en"
    return language


def _should_ignore_transcript(text: str, language: str | None) -> bool:
    """Reject obvious STT noise before invoking Ollama or TTS.

    Smartis is always listening, so reacting to every cough/click is more harmful
    than missing a marginal utterance. Known one-word commands remain accepted.
    """
    value = normalize_command_text(text).strip()
    if not value: return True
    low = value.lower()
    if re.search(r"[\u0600-\u06FF]", value):
        known = {"سلام","درود","گوگل","یوتیوب","اسمارتیز","اسمارتیس","ادامه","ادامه بده","بله","آره","نه","لغو","کمک","توقف","بس","مکث"}
        if low in known: return False
    # English one-word noise/hallucinations are common on non-speech sounds.
    words = re.findall(r"[A-Za-z]+|[\u0600-\u06FF]+", value)
    if len(words) == 1 and not re.search(r"(?:[?؟]|چی|چیه|کیه|what|who|how|open|play|search|google|volume|weather|time|date|start|stop|pause|cancel|yes|no)$", low, re.I):
        return True
    # A very short transcript without a command/question cue is usually a noise hypothesis.
    if len(words) <= 2 and len(value) < 7 and not re.search(r"(?:باز|برو|پخش|سرچ|جست|حساب|صدا|هوا|ساعت|تاریخ|زبان|بساز|حذف|تحقیق|بررسی|پیدا|play|open|search|find|calculate|weather|time|language|create|delete|research|investigate)", low, re.I):
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
        return fast

    # Anything that is not a high-confidence deterministic fast path goes to the
    # LOCAL Ollama model. This is the semantic layer: it understands paraphrases,
    # sentence structure and targets instead of requiring a fixed trigger phrase.
    result = plan_with_ollama(contextual, language, memory.context_text())
    if result.get("ok"):
        return result
    fallback = fallback_plan(contextual)
    return fallback


def _affirmative_text(text: str) -> bool:
    value = re.sub(r"\s+", " ", str(text or "").strip().lower())
    if value in {"بله","آره","اره","تایید","تأیید","تایید میکنم","تأیید می‌کنم","حتما","حتماً","باشه","yes","yeah","yep","sure","okay","ok","confirm","confirmed"}:
        return True
    return bool(re.fullmatch(r"(?:بله|آره|اره|حتما|حتماً|باشه)(?:\s+(?:انجام(?:ش)?|تأیید(?:ش)?))?(?:\s+(?:بده|بدهش|کن|کنش|بکن))?", value, re.I))


def _negative_text(text: str) -> bool:
    value = re.sub(r"\s+", " ", str(text or "").strip().lower())
    if value in {"نه","نخیر","لغو","بیخیال","no","nope","cancel","stop"}:
        return True
    if re.search(r"^(?:نه|نخیر|بیخیال|نمیخوام|نمی‌خوام|no|nope|cancel|stop)\b", value, re.I):
        return True
    return bool(re.search(r"(?:لغو|بیخیال|cancel|stop)\s*(?:کن|کنش|بده|بدهش|شو)?$", value, re.I))


def process_command(text: str, language: str | None) -> dict:
    """Plan + execute. Confirmation replies are consumed by the backend state."""
    if _should_ignore_transcript(text, language):
        return {"ok": True, "ignored": True, "provider": "noise-gate", "plan": {"reply": "", "actions": [], "needs_confirmation": False}, "execution": {"ok": True, "results": []}}
    if pending_confirmation():
        if _affirmative_text(text):
            execution = execute_pending_confirmation()
            ok = execution.get("ok") is True
            reply = ("انجام شد." if language != "en" else "Done.") if ok else (f"انجام نشد؛ {execution.get('error') or 'عملیات با خطا مواجه شد.'}" if language != "en" else f"It failed: {execution.get('error') or 'the operation returned an error.'}")
            return {
                "ok": ok,
                "provider": "confirmation",
                "plan": {"reply": reply, "actions": [], "needs_confirmation": False},
                "execution": execution,
            }
        if _negative_text(text):
            clear_pending_confirmation()
            return {
                "ok": True,
                "provider": "confirmation",
                "plan": {"reply": "باشه، انجامش نمی‌دم." if language != "en" else "Okay, I won't do it.", "actions": [], "needs_confirmation": False},
                "execution": {"ok": True, "needs_confirmation": False, "results": []},
            }

    planned = build_agent_plan(text, language)
    if planned.get("ok") is not True:
        return planned

    plan = planned.get("plan") or {}
    if plan.get("needs_confirmation") is True:
        return {
            "ok": True,
            "provider": planned.get("provider", "unknown"),
            "plan": plan,
            "execution": {"ok": True, "needs_confirmation": True, "results": []},
        }

    execution = execute_plan(plan, False)
    reply = str(plan.get("reply") or "")
    if execution.get("ok") is not True:
        error = str(execution.get("error") or "عملیات با خطا مواجه شد." if language != "en" else execution.get("error") or "The operation failed.")
        reply = (f"انجام نشد؛ {error}" if language != "en" else f"It failed: {error}")
    memory.remember(text, plan, execution, reply=reply)
    response_plan = dict(plan)
    response_plan["reply"] = reply
    return {
        "ok": execution.get("ok") is True,
        "provider": planned.get("provider", "unknown"),
        "plan": response_plan,
        "execution": execution,
    }


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
    print("=" * 60)
    yield
    microphone.stop()


app = FastAPI(title="Smartis Backend", version="2.1.0", lifespan=lifespan)
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
    # The Flutter client keeps listening paused until the generated audio has
    # finished playing, but pausing here as well prevents an HTTP-triggered TTS
    # call from immediately feeding its own synthesis back into STT.
    microphone.pause_listening()
    try:
        result = await asyncio.to_thread(tts.speak, text, language)
    finally:
        # The UI explicitly resumes after playback. This is intentionally not
        # auto-resumed here, otherwise the TTS audio could become a new command.
        pass
    result = _json_safe(result)
    print(
        f"[speak] ok={result.get('ok')} provider={result.get('provider')} "
        f"offline={result.get('offline')} error={result.get('error')}"
    )
    return result


@app.post("/command")
async def command(payload: dict):
    text = str(payload.get("text", "")).strip()
    language = payload.get("language")
    if not text:
        return {"ok": False, "error": "Text is empty."}
    return _json_safe(await asyncio.to_thread(process_command, text, language))


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
        }
    )

    async def send_events() -> None:
        while True:
            try:
                event = await asyncio.to_thread(events.get, True, 0.5)
            except queue.Empty:
                continue
            await send_json_event(event)

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
                microphone.pause_listening()
                result = await asyncio.to_thread(
                    tts.speak,
                    str(message.get("text", "")),
                    message.get("language"),
                )
                await send_json_event({"type": "tts_result", **result})
            elif action == "command":
                text = str(message.get("text", "")).strip()
                language = message.get("language")
                result = await asyncio.to_thread(process_command, text, language)
                await send_json_event({"type": "command", **result})
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


if __name__ == "__main__":
    uvicorn.run(app, host=HOST, port=PORT)
