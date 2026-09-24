from pathlib import Path
import os

try:
    from dotenv import load_dotenv
except ImportError:
    load_dotenv = None

BACKEND_DIR = Path(__file__).resolve().parent
PROJECT_DIR = BACKEND_DIR.parent

if load_dotenv is not None:
    try:
        load_dotenv(BACKEND_DIR / ".env")
    except Exception:
        pass

    try:
        load_dotenv(PROJECT_DIR / ".env")
    except Exception:
        pass


def _env_str(key: str, default: str) -> str:
    """Read an environment variable as string with fallback if unset or empty."""
    val = os.getenv(key)
    if val is None:
        return default
    cleaned = val.strip()
    return cleaned if cleaned else default


def _env_int(key: str, default: int) -> int:
    """Read an environment variable as integer with fallback if unset, empty, or invalid."""
    val = os.getenv(key)
    if val is None:
        return default
    cleaned = val.strip()
    if not cleaned:
        return default
    try:
        return int(cleaned)
    except (ValueError, TypeError):
        return default


def _env_float(key: str, default: float) -> float:
    """Read an environment variable as float with fallback if unset, empty, or invalid."""
    val = os.getenv(key)
    if val is None:
        return default
    cleaned = val.strip()
    if not cleaned:
        return default
    try:
        return float(cleaned)
    except (ValueError, TypeError):
        return default


def _parse_mic_index(key: str = "SMARTIS_MIC_DEVICE_INDEX") -> int | None:
    """
    Parse microphone device index.
    If unset, blank, or non-numeric/negative, returns None (uses OS Default Microphone).
    """
    val = os.getenv(key)
    if val is None:
        return None
    cleaned = val.strip().lower()
    if not cleaned or cleaned in ("none", "default", "auto", "-1", "null"):
        return None
    try:
        idx = int(cleaned)
        return idx if idx >= 0 else None
    except (ValueError, TypeError):
        return None


# ==========================================
# Network & Server Configuration
# ==========================================
# For local execution on Windows, Backend listens on 127.0.0.1:8765.
# AI Studio Preview does not depend on a local machine backend.
HOST = _env_str("SMARTIS_HOST", "127.0.0.1")
PORT = _env_int("SMARTIS_PORT", 8765)

# ==========================================
# Microphone & Audio Configuration
# ==========================================
# Unset or empty value means default Windows microphone
SMARTIS_MIC_DEVICE_INDEX = _env_str("SMARTIS_MIC_DEVICE_INDEX", "")
MIC_DEVICE_INDEX = _parse_mic_index("SMARTIS_MIC_DEVICE_INDEX")

# Google Speech Recognition Languages (Online STT via recognize_google)
SMARTIS_GOOGLE_FA_LANGUAGE = _env_str("SMARTIS_GOOGLE_FA_LANGUAGE", "fa-IR")
SMARTIS_GOOGLE_EN_LANGUAGE = _env_str("SMARTIS_GOOGLE_EN_LANGUAGE", "en-US")

# SpeechRecognizer Calibration, Silence & Time Limits
SMARTIS_ENERGY_THRESHOLD = _env_float("SMARTIS_ENERGY_THRESHOLD", 75.0)
SMARTIS_AMBIENT_CALIBRATION_SECONDS = _env_float("SMARTIS_AMBIENT_CALIBRATION_SECONDS", 0.3)
SMARTIS_PHRASE_TIME_LIMIT_SECONDS = _env_float("SMARTIS_PHRASE_TIME_LIMIT_SECONDS", 18.0)
SMARTIS_PAUSE_THRESHOLD = _env_float("SMARTIS_PAUSE_THRESHOLD", 0.7)
SMARTIS_NON_SPEAKING_DURATION = _env_float("SMARTIS_NON_SPEAKING_DURATION", 0.35)
SMARTIS_PHRASE_THRESHOLD = _env_float("SMARTIS_PHRASE_THRESHOLD", 0.08)

# Timeouts
SMARTIS_GOOGLE_TIMEOUT = _env_float("SMARTIS_GOOGLE_TIMEOUT", 3.0)
GOOGLE_STT_TIMEOUT = SMARTIS_GOOGLE_TIMEOUT

SMARTIS_WAKE_TIME_LIMIT = _env_float("SMARTIS_WAKE_TIME_LIMIT", 3.5)
WAKE_PHRASE_TIME_LIMIT_SECONDS = SMARTIS_WAKE_TIME_LIMIT

# ==========================================
# Offline STT (faster-whisper) Fallback
# ==========================================
WHISPER_MODEL = _env_str("WHISPER_MODEL", "")
MODEL_PATH = Path(WHISPER_MODEL) if WHISPER_MODEL else (BACKEND_DIR / "models" / "whisper-small")
WHISPER_DEVICE = _env_str("WHISPER_DEVICE", "cpu")
WHISPER_COMPUTE_TYPE = _env_str("WHISPER_COMPUTE_TYPE", "int8")

# ==========================================
# Ollama LLM (Local Execution)
# ==========================================
OLLAMA_URL = _env_str("OLLAMA_URL", "http://127.0.0.1:11434")
OLLAMA_MODEL = _env_str("OLLAMA_MODEL", "qwen2.5:7b")
AGENT_TIMEOUT = _env_float("AGENT_TIMEOUT", 30.0)

# ==========================================
# Wake Words & Standard Responses
# ==========================================
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

# ==========================================
# TTS Settings (Edge TTS & SAPI fallback)
# ==========================================
ONLINE_TTS_FA_VOICE = _env_str("SMARTIS_TTS_FA_VOICE", "fa-IR-DilaraNeural")
ONLINE_TTS_EN_VOICE = _env_str("SMARTIS_TTS_EN_VOICE", "en-US-GuyNeural")
SMARTIS_TTS_RATE = _env_str("SMARTIS_TTS_RATE", "+0%")
SMARTIS_TTS_VOLUME = _env_str("SMARTIS_TTS_VOLUME", "+0%")
SMARTIS_TTS_PITCH = _env_str("SMARTIS_TTS_PITCH", "+0Hz")
ONLINE_TTS_RATE = SMARTIS_TTS_RATE
ONLINE_TTS_VOLUME = SMARTIS_TTS_VOLUME
ONLINE_TTS_PITCH = SMARTIS_TTS_PITCH

# ==========================================
# Connectivity & Internet Cache
# ==========================================
SMARTIS_INTERNET_TIMEOUT = _env_float("SMARTIS_INTERNET_TIMEOUT", 1.5)
SMARTIS_INTERNET_CACHE = _env_float("SMARTIS_INTERNET_CACHE", 4.0)
INTERNET_CHECK_TIMEOUT = SMARTIS_INTERNET_TIMEOUT
INTERNET_CACHE_SECONDS = SMARTIS_INTERNET_CACHE

# Actions requiring explicit user confirmation
REQUIRE_CONFIRMATION_FOR = {"close_application", "delete_file", "shutdown_windows", "restart_windows"}
