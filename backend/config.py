from pathlib import Path
import os
from dotenv import load_dotenv

BACKEND_DIR = Path(__file__).resolve().parent
PROJECT_DIR = BACKEND_DIR.parent
load_dotenv(BACKEND_DIR / ".env")

MODEL_PATH = Path(os.getenv("WHISPER_MODEL", str(BACKEND_DIR / "models" / "whisper-small")))
HOST = os.getenv("SMARTIS_HOST", "127.0.0.1")
PORT = int(os.getenv("SMARTIS_PORT", "8765"))

WHISPER_DEVICE = os.getenv("WHISPER_DEVICE", "cpu")
WHISPER_COMPUTE_TYPE = os.getenv("WHISPER_COMPUTE_TYPE", "int8")

OLLAMA_URL = os.getenv("OLLAMA_URL", "http://127.0.0.1:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "qwen2.5:7b")
AGENT_TIMEOUT = float(os.getenv("AGENT_TIMEOUT", "30"))

WAKE_WORDS = ["smartis", "smarties", "smart is", "اسمارتیز", "اسمارتیس", "اسمارتس", "اسمارتی"]
WAKE_REPLY_FA = "جانم"
WAKE_REPLY_EN = "Yes, I'm listening."

ONLINE_TTS_FA_VOICE = os.getenv("SMARTIS_TTS_FA_VOICE", "fa-IR-DilaraNeural")
ONLINE_TTS_EN_VOICE = os.getenv("SMARTIS_TTS_EN_VOICE", "en-US-GuyNeural")
ONLINE_TTS_RATE = os.getenv("SMARTIS_TTS_RATE", "+0%")
ONLINE_TTS_VOLUME = os.getenv("SMARTIS_TTS_VOLUME", "+0%")
ONLINE_TTS_PITCH = os.getenv("SMARTIS_TTS_PITCH", "+0Hz")

INTERNET_CHECK_TIMEOUT = float(os.getenv("SMARTIS_INTERNET_TIMEOUT", "1.5"))
INTERNET_CACHE_SECONDS = float(os.getenv("SMARTIS_INTERNET_CACHE", "4"))

REQUIRE_CONFIRMATION_FOR = {"close_application", "delete_file", "shutdown_windows", "restart_windows"}
