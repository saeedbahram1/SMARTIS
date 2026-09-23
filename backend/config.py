from pathlib import Path
import os
from dotenv import load_dotenv

BACKEND_DIR = Path(__file__).resolve().parent
PROJECT_DIR = BACKEND_DIR.parent
load_dotenv(BACKEND_DIR / ".env")
load_dotenv(PROJECT_DIR / ".env")

# Host / Port
HOST = os.getenv("SMARTIS_HOST", "127.0.0.1")
PORT = int(os.getenv("SMARTIS_PORT", "8765"))

# Microphone & Audio Configuration
SMARTIS_MIC_DEVICE_INDEX = os.getenv("SMARTIS_MIC_DEVICE_INDEX", "").strip()
MIC_DEVICE_INDEX = int(SMARTIS_MIC_DEVICE_INDEX) if SMARTIS_MIC_DEVICE_INDEX.isdigit() else None

SMARTIS_GOOGLE_FA_LANGUAGE = os.getenv("SMARTIS_GOOGLE_FA_LANGUAGE", "fa-IR")
SMARTIS_GOOGLE_EN_LANGUAGE = os.getenv("SMARTIS_GOOGLE_EN_LANGUAGE", "en-US")

SMARTIS_AMBIENT_CALIBRATION_SECONDS = float(os.getenv("SMARTIS_AMBIENT_CALIBRATION_SECONDS", "0.7"))
SMARTIS_PHRASE_TIME_LIMIT_SECONDS = float(os.getenv("SMARTIS_PHRASE_TIME_LIMIT_SECONDS", "18.0"))
SMARTIS_PAUSE_THRESHOLD = float(os.getenv("SMARTIS_PAUSE_THRESHOLD", "1.0"))
SMARTIS_NON_SPEAKING_DURATION = float(os.getenv("SMARTIS_NON_SPEAKING_DURATION", "0.45"))
SMARTIS_PHRASE_THRESHOLD = float(os.getenv("SMARTIS_PHRASE_THRESHOLD", "0.12"))

GOOGLE_STT_TIMEOUT = float(os.getenv("SMARTIS_GOOGLE_TIMEOUT", "6.0"))
WAKE_PHRASE_TIME_LIMIT_SECONDS = float(os.getenv("SMARTIS_WAKE_TIME_LIMIT", "3.5"))

# Whisper Offline STT
MODEL_PATH = Path(os.getenv("WHISPER_MODEL", str(BACKEND_DIR / "models" / "whisper-small")))
WHISPER_DEVICE = os.getenv("WHISPER_DEVICE", "cpu")
WHISPER_COMPUTE_TYPE = os.getenv("WHISPER_COMPUTE_TYPE", "int8")

# Ollama LLM
OLLAMA_URL = os.getenv("OLLAMA_URL", "http://127.0.0.1:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "qwen2.5:7b")
AGENT_TIMEOUT = float(os.getenv("AGENT_TIMEOUT", "30"))

# Wake Words & Default Replies
WAKE_WORDS = [
    "اسمارتیز",
    "اسمارتیس",
    "اسمارتس",
    "اسمارتی",
    "smartis",
    "smarties",
    "smart is",
]
WAKE_REPLY_FA = "جانم"
WAKE_REPLY_EN = "Yes, I'm listening."

# TTS Settings
ONLINE_TTS_FA_VOICE = os.getenv("SMARTIS_TTS_FA_VOICE", "fa-IR-DilaraNeural")
ONLINE_TTS_EN_VOICE = os.getenv("SMARTIS_TTS_EN_VOICE", "en-US-GuyNeural")
ONLINE_TTS_RATE = os.getenv("SMARTIS_TTS_RATE", "+0%")
ONLINE_TTS_VOLUME = os.getenv("SMARTIS_TTS_VOLUME", "+0%")
ONLINE_TTS_PITCH = os.getenv("SMARTIS_TTS_PITCH", "+0Hz")

# Internet Check
INTERNET_CHECK_TIMEOUT = float(os.getenv("SMARTIS_INTERNET_TIMEOUT", "1.5"))
INTERNET_CACHE_SECONDS = float(os.getenv("SMARTIS_INTERNET_CACHE", "4.0"))

REQUIRE_CONFIRMATION_FOR = {"close_application", "delete_file", "shutdown_windows", "restart_windows"}
