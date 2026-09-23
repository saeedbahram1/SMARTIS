import asyncio
import math
import os
import tempfile
import wave
from pathlib import Path

try:
    import audioop
except Exception:
    audioop = None

import psutil
from fastapi import FastAPI, File, Form, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
import uvicorn

from config import HOST, PORT, MODEL_PATH, WAKE_REPLY_FA, WAKE_REPLY_EN
from services.whisper_service import WhisperService
from services.wake_word import detect_wake_word
from services.speech_router import SpeechRouter
from services.tts_service import TTSService
from services.google_voice import GoogleVoiceSession
from agent.planner import plan_with_ollama, fallback_plan
from agent.executor import execute_plan
from agent.fast_path import fast_plan


def audio_diagnostics(path) -> str:
    if audioop is None:
        return "n/a"
    try:
        with wave.open(str(path), "rb") as wf:
            channels = wf.getnchannels()
            width = wf.getsampwidth()
            rate = wf.getframerate()
            n = wf.getnframes()
            frames = wf.readframes(n)
        duration = n / rate if rate else 0
        if not frames:
            return f"ch={channels} width={width}B rate={rate}Hz dur={duration:.2f}s -> no audio data"
        peak = audioop.max(frames, width)
        rms = audioop.rms(frames, width)
        peak_db = 20 * math.log10(peak / 32768.0) if peak > 0 else float("-inf")
        rms_db = 20 * math.log10(rms / 32768.0) if rms > 0 else float("-inf")
        return (
            f"ch={channels} width={width}B rate={rate}Hz dur={duration:.2f}s "
            f"peak={peak_db:.1f}dB rms={rms_db:.1f}dB"
        )
    except Exception as exc:
        return f"n/a ({exc})"


def trim_wav_edges(path, lead_ms=150, tail_ms=120) -> str:
    try:
        with wave.open(str(path), "rb") as wf:
            channels = wf.getnchannels()
            width = wf.getsampwidth()
            rate = wf.getframerate()
            n = wf.getnframes()
            frames = wf.readframes(n)
        lead = int(rate * lead_ms / 1000) * channels * width
        tail = int(rate * tail_ms / 1000) * channels * width
        if n <= 0 or lead + tail >= len(frames):
            return str(path)
        trimmed = frames[lead : len(frames) - tail]
        if not trimmed:
            return str(path)
        out_path = str(path) + ".trim.wav"
        with wave.open(out_path, "wb") as out:
            out.setnchannels(channels)
            out.setsampwidth(width)
            out.setframerate(rate)
            out.writeframes(trimmed)
        return out_path
    except Exception:
        return str(path)


app = FastAPI(title="Smartis Backend", version="0.8.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

whisper = WhisperService()
speech = SpeechRouter(whisper)
tts = TTSService(speech.internet)
voice_session = GoogleVoiceSession(whisper_service=whisper, internet_monitor=speech.internet)


@app.on_event("startup")
def startup():
    whisper.load()
    status = speech.status()
    mics = GoogleVoiceSession.get_microphones()
    print("=" * 60)
    print("SMARTIS backend ready")
    print(f"  Internet reachable  : {status['internet']}")
    print(f"  PyAudio available   : {voice_session.is_pyaudio_available}")
    print(f"  Microphones found   : {len(mics)}")
    print(f"  Google STT ready    : {status['online_stt_ready']} (recognize_google)")
    print(f"  Whisper STT ready   : {status['offline_stt_ready']} (model={MODEL_PATH})")
    print("=" * 60)


@app.on_event("shutdown")
def shutdown():
    print("[Shutdown] Stopping voice session and releasing audio devices...")
    voice_session.stop()


@app.get("/health")
def health():
    return {
        "ok": True,
        "service": "smartis-backend",
        "whisper_ready": whisper.ready,
        "whisper_model": str(MODEL_PATH),
        **speech.status(),
        "pyaudio_available": voice_session.is_pyaudio_available,
        "online_tts_engine": "edge-tts",
        "offline_tts": True,
        "online_tts": True,
    }


@app.get("/status")
def status():
    return {
        "ok": True,
        "speech": speech.status(),
        "whisper_ready": whisper.ready,
        "pyaudio_available": voice_session.is_pyaudio_available,
        "current_voice_mode": voice_session.current_mode,
    }


@app.get("/microphones")
def list_microphones():
    mics = GoogleVoiceSession.get_microphones()
    return {
        "ok": True,
        "pyaudio_available": voice_session.is_pyaudio_available,
        "microphones": mics,
    }


@app.get("/system")
def system_info():
    return {
        "cpu_percent": psutil.cpu_percent(interval=0.1),
        "ram_percent": psutil.virtual_memory().percent,
        "python": os.sys.version.split()[0],
    }


@app.get("/voices")
def voices():
    return {"ok": True, "voices": tts.voices()}


async def save_upload(upload: UploadFile) -> str:
    suffix = Path(upload.filename or ".wav").suffix or ".wav"
    data = await upload.read()
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as handle:
        handle.write(data)
        return handle.name


def cleanup(path: str):
    try:
        os.remove(path)
    except OSError:
        pass


@app.post("/transcribe")
async def transcribe(audio: UploadFile = File(...), language_hint: str | None = Form(default=None)):
    raw_path = await save_upload(audio)
    trimmed_path = trim_wav_edges(raw_path)
    try:
        result = await asyncio.to_thread(speech.transcribe, trimmed_path, language_hint, False)
        return result
    finally:
        cleanup(raw_path)
        if trimmed_path != raw_path:
            cleanup(trimmed_path)


@app.post("/wake_audio")
async def wake_audio(audio: UploadFile = File(...)):
    raw_path = await save_upload(audio)
    trimmed_path = trim_wav_edges(raw_path)
    try:
        result = await asyncio.to_thread(speech.transcribe, trimmed_path, None, True)
        text = str(result.get("text", ""))
        detection = result.get("wake") or detect_wake_word(text)
        return {
            "ok": bool(result.get("ok")),
            "detected": bool(detection.get("detected")),
            "wake": detection,
            "text": text,
            "language": result.get("language"),
            "provider": result.get("provider"),
            "offline": result.get("offline"),
            "error": result.get("error"),
        }
    finally:
        cleanup(raw_path)
        if trimmed_path != raw_path:
            cleanup(trimmed_path)


@app.post("/wake")
async def wake(payload: dict):
    detection = detect_wake_word(str(payload.get("text", "")).strip())
    if not detection.get("detected"):
        return {"ok": True, "detected": False}
    language = detection.get("language") or "fa"
    return {
        "ok": True,
        "detected": True,
        "language": language,
        "wake_word": detection.get("wake_word"),
        "reply": WAKE_REPLY_FA if language == "fa" else WAKE_REPLY_EN,
    }


@app.post("/speak")
async def speak(payload: dict):
    text = str(payload.get("text", "")).strip()
    language = payload.get("language")
    if not text:
        return {"ok": False, "error": "Text is empty."}
    result = await asyncio.to_thread(tts.speak, text, language)
    return result


@app.post("/agent/plan")
async def agent_plan(payload: dict):
    text = str(payload.get("text", "")).strip()
    language = payload.get("language")
    if not text:
        return {"ok": False, "error": "Text is empty."}
    fast = fast_plan(text, language)
    if fast is not None:
        return fast
    result = await asyncio.to_thread(plan_with_ollama, text, language)
    return result if result.get("ok") else fallback_plan(text)


@app.post("/agent/execute")
async def agent_execute(payload: dict):
    plan = payload.get("plan")
    confirmed = bool(payload.get("confirmed", False))
    if not isinstance(plan, dict):
        return {"ok": False, "error": "Invalid plan."}
    return await asyncio.to_thread(execute_plan, plan, confirmed)


# ==========================================
# Dedicated /voice WebSocket (Voice Control)
# ==========================================
@app.websocket("/voice")
async def voice_websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    loop = asyncio.get_running_loop()

    async def send_voice_event(event: dict):
        try:
            await websocket.send_json(event)
        except Exception:
            pass

    # Attach this websocket as the active event listener for the single voice session
    voice_session.set_event_callback(send_voice_event, loop)

    # Initial ready handshake
    await websocket.send_json({
        "type": "voice_ready",
        "pyaudio_available": voice_session.is_pyaudio_available,
        "online_stt_ready": speech.google.ready,
        "offline_stt_ready": whisper.ready,
        "internet": speech.internet.is_online(),
        "mode": voice_session.current_mode,
    })

    try:
        while True:
            message = await websocket.receive_json()
            action = message.get("action")

            if action == "start":
                mode = message.get("mode", "wake")
                lang = message.get("language", "fa")
                if mode == "wake":
                    voice_session.start_wake(language=lang)
                elif mode == "command":
                    voice_session.start_command(language=lang)
                else:
                    await websocket.send_json({
                        "type": "voice_error",
                        "message": f"Unknown voice mode: {mode}",
                    })
            elif action == "stop":
                voice_session.stop()
            elif action == "ping":
                await websocket.send_json({"type": "pong"})
            else:
                await websocket.send_json({
                    "type": "voice_error",
                    "message": f"Unknown voice action: {action}",
                })
    except WebSocketDisconnect:
        print("[/voice] WebSocket client disconnected.")
    finally:
        voice_session.stop()
        voice_session.set_event_callback(None, None)


# ==========================================
# General /ws WebSocket (System & Agent Control)
# ==========================================
@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    await websocket.send_json({
        "type": "backend_ready",
        "whisper_ready": whisper.ready,
        "internet": speech.internet.is_online(),
        "online_stt_ready": speech.google.ready,
        "pyaudio_available": voice_session.is_pyaudio_available,
    })

    try:
        while True:
            message = await websocket.receive_json()
            action = message.get("action")

            if action == "ping":
                await websocket.send_json({"type": "pong"})
            elif action == "status":
                await websocket.send_json({
                    "type": "status",
                    "whisper_ready": whisper.ready,
                    "pyaudio_available": voice_session.is_pyaudio_available,
                    **speech.status(),
                })
            elif action == "speak":
                result = await asyncio.to_thread(
                    tts.speak,
                    str(message.get("text", "")),
                    message.get("language"),
                )
                await websocket.send_json({"type": "tts_result", **result})
            elif action == "agent_plan":
                text = str(message.get("text", "")).strip()
                language = message.get("language")
                fast = fast_plan(text, language)
                if fast is not None:
                    result = fast
                else:
                    result = await asyncio.to_thread(
                        plan_with_ollama,
                        text,
                        language,
                    )
                    if not result.get("ok"):
                        result = fallback_plan(text)
                await websocket.send_json({"type": "agent_plan", **result})
            elif action == "agent_execute":
                result = await asyncio.to_thread(
                    execute_plan,
                    message.get("plan"),
                    bool(message.get("confirmed", False)),
                )
                await websocket.send_json({"type": "agent_execute", **result})
            else:
                await websocket.send_json({
                    "type": "info",
                    "message": "Unknown action.",
                })
    except WebSocketDisconnect:
        pass


if __name__ == "__main__":
    uvicorn.run(app, host=HOST, port=PORT)
