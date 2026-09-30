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
