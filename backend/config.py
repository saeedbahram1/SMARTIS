from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

BACKEND_DIR = Path(__file__).resolve().parent
PROJECT_DIR = BACKEND_DIR.parent
load_dotenv(BACKEND_DIR / ".env")

HOST = os.getenv("SMARTIS_HOST", "127.0.0.1")
PORT = int(os.getenv("SMARTIS_PORT", "8765"))

SHERPA_FA_DIR = os.getenv("SHERPA_FA_DIR", str(BACKEND_DIR / "models" / "sherpa-fa"))
SHERPA_EN_DIR = os.getenv("SHERPA_EN_DIR", str(BACKEND_DIR / "models" / "sherpa-en"))
SHERPA_NUM_THREADS = max(1, min(int(os.getenv("SHERPA_NUM_THREADS", "2")), 4))
MICROPHONE_DEVICE = os.getenv("SMARTIS_MIC_DEVICE", "").strip()

OLLAMA_URL = os.getenv("OLLAMA_URL", "http://127.0.0.1:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "qwen2.5:7b")
AGENT_TIMEOUT = min(float(os.getenv("AGENT_TIMEOUT", "3.0")), 3.0)

# ---------------------------------------------------------------------------
# Conversational ("human-like") layer.
# ---------------------------------------------------------------------------
# Smartis answers every utterance instead of replying with a dead-end
# "I did not understand" message. This runs on the SAME local Ollama model as
# the planner, so no paid cloud API (OpenAI / Gemini / ...) is required.
CHAT_MODEL = os.getenv("SMARTIS_CHAT_MODEL", OLLAMA_MODEL)
CHAT_TIMEOUT = max(2.0, min(float(os.getenv("SMARTIS_CHAT_TIMEOUT", "20.0")), 90.0))
CHAT_TEMPERATURE = max(0.0, min(float(os.getenv("SMARTIS_CHAT_TEMPERATURE", "0.65")), 1.5))
CHAT_MAX_TOKENS = max(80, min(int(os.getenv("SMARTIS_CHAT_MAX_TOKENS", "450")), 2000))
CHAT_MAX_REPLY_CHARS = max(400, min(int(os.getenv("SMARTIS_CHAT_MAX_CHARS", "1800")), 8000))
CHAT_KEEP_MODEL_WARM = os.getenv("SMARTIS_CHAT_KEEP_WARM", "1").strip() not in {"0", "false", "no"}

# The old gate dropped any short utterance, which is exactly what made Smartis
# answer "I did not understand" so often. "relaxed" keeps every plausible
# sentence and only removes the classic STT hallucinations.
NOISE_GATE_MODE = os.getenv("SMARTIS_NOISE_GATE", "relaxed").strip().lower()

# ---------------------------------------------------------------------------
# Self-voice (echo) protection.
# ---------------------------------------------------------------------------
# While Smartis is speaking, the microphone must not be able to turn its own
# TTS output into a new command (this caused the Wikipedia read-aloud loop).
SPEAK_TAIL_GUARD_SECONDS = max(0.0, min(float(os.getenv("SMARTIS_SPEAK_TAIL_GUARD", "1.6")), 10.0))
ECHO_WINDOW_SECONDS = max(4.0, min(float(os.getenv("SMARTIS_ECHO_WINDOW", "30.0")), 180.0))
ECHO_SIMILARITY_THRESHOLD = max(0.35, min(float(os.getenv("SMARTIS_ECHO_THRESHOLD", "0.60")), 0.98))

# Edge TTS voices. Microsoft currently lists these Persian and English Neural voices.
ONLINE_TTS_FA_VOICE = os.getenv("SMARTIS_TTS_FA_VOICE", "fa-IR-FaridNeural")
ONLINE_TTS_EN_VOICE = os.getenv("SMARTIS_TTS_EN_VOICE", "en-US-GuyNeural")
ONLINE_TTS_RATE = os.getenv("SMARTIS_TTS_RATE", "+4%")
ONLINE_TTS_VOLUME = os.getenv("SMARTIS_TTS_VOLUME", "+0%")
ONLINE_TTS_PITCH = os.getenv("SMARTIS_TTS_PITCH", "+0Hz")

INTERNET_CHECK_TIMEOUT = float(os.getenv("SMARTIS_INTERNET_TIMEOUT", "1.5"))
INTERNET_CACHE_SECONDS = float(os.getenv("SMARTIS_INTERNET_CACHE", "4"))

# Only destructive power actions are confirmation-gated. File/folder delete keeps
# the existing direct-voice behavior until ambiguity handling is implemented.
REQUIRE_CONFIRMATION_FOR = {
    "shutdown_windows",
    "restart_windows",
    "sleep_windows",
}
