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
# sherpa-onnx decodes on the CPU, so the thread budget is the single biggest
# knob for STT latency. The old hard cap of 4 left half of a normal 8-core
# laptop idle during every decode. Default to "all cores, capped at 8" and let
# SHERPA_NUM_THREADS in .env override it (0 = auto).
_CPU_COUNT = max(1, os.cpu_count() or 4)
_SHERPA_THREADS_CAP = min(_CPU_COUNT, 8)
SHERPA_NUM_THREADS = max(
    1, min(int(os.getenv("SHERPA_NUM_THREADS", "0")) or _SHERPA_THREADS_CAP, _SHERPA_THREADS_CAP)
)
MICROPHONE_DEVICE = os.getenv("SMARTIS_MIC_DEVICE", "").strip()

OLLAMA_URL = os.getenv("OLLAMA_URL", "http://127.0.0.1:11434")
# qwen3.5:4b: the 1.5B model was too weak for real conversation and code, and
# the 4B quant (~3.4 GB) still fits an 8 GB machine with the 2048-token context.
# `ollama pull qwen3.5:4b` is required; resolve_model() falls back to
# an installed Qwen (then any installed model) if this exact tag is missing.
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "qwen3.5:4b")
# Command planner (JSON) timeout. The old 8 s default was shorter than a cold
# prompt-eval of the planner prompt on a CPU-only machine, so the planner
# silently failed and everything fell through to a canned reply.
AGENT_TIMEOUT = max(6.0, min(float(os.getenv("AGENT_TIMEOUT", "25.0")), 90.0))

# ONE context size for EVERY Ollama request (chat, think, planner, warm-up).
# Ollama restarts its runner whenever num_ctx changes between requests. The
# old code used 192 / 256 / 512 / 2048 in different places, so the model was
# reloaded again and again -> "the model is not up" even though it was loaded.
# Default 2048: MEASURED on this machine, a typical 1351-char attachment block
# costs 948 prompt tokens, and a maxed (2600-char) block would overflow 1536.
OLLAMA_NUM_CTX = max(768, min(int(os.getenv("SMARTIS_NUM_CTX", "2048")), 8192))

# CPU thread budget for the Ollama runner. 0 = auto (Ollama picks the physical
# core count, which is the right default). SMARTIS_OLLAMA_THREADS caps it on
# shared/low-power CPUs so the assistant stays responsive during generation.
OLLAMA_NUM_THREAD = max(0, min(int(os.getenv("SMARTIS_OLLAMA_THREADS", "0")), 32))

# ---------------------------------------------------------------------------
# Conversational ("human-like") layer.
# ---------------------------------------------------------------------------
# Smartis answers every utterance instead of replying with a dead-end
# "I did not understand" message. This runs on the SAME local Ollama model as
# the planner, so no paid cloud API (OpenAI / Gemini / ...) is required.
CHAT_MODEL = os.getenv("SMARTIS_CHAT_MODEL", OLLAMA_MODEL)
# Total wall-clock budget of one chat answer (streamed, so partial text is kept).
# MEASURED on the target 8 GB / i3-1315U machine with qwen3.5:4b and a full
# attachment prompt: 132.6 s to the first token and 178.2 s worst total. The old
# 45 s default aborted every attachment answer while the prompt was still
# prefilling; the model was never the problem.
CHAT_TIMEOUT = max(12.0, min(float(os.getenv("SMARTIS_CHAT_TIMEOUT", "240.0")), 300.0))
# Max wait for the FIRST token: covers a cold model load plus the full prefill
# of the system prompt + attachment block (~130 s measured, ~40% headroom).
CHAT_FIRST_TOKEN_TIMEOUT = max(8.0, min(float(os.getenv("SMARTIS_CHAT_FIRST_TOKEN_TIMEOUT", "180.0")), 300.0))
CHAT_THINK_MAX_TOKENS = max(256, min(int(os.getenv("SMARTIS_THINK_MAX_TOKENS", "700")), 4000))
CHAT_TEMPERATURE = max(0.0, min(float(os.getenv("SMARTIS_CHAT_TEMPERATURE", "0.65")), 1.5))
CHAT_MAX_TOKENS = max(80, min(int(os.getenv("SMARTIS_CHAT_MAX_TOKENS", "260")), 2000))
CHAT_MAX_REPLY_CHARS = max(400, min(int(os.getenv("SMARTIS_CHAT_MAX_CHARS", "1800")), 8000))
CHAT_KEEP_MODEL_WARM = os.getenv("SMARTIS_CHAT_KEEP_WARM", "1").strip() not in {"0", "false", "no"}
# Code generation ("write any code I ask for, deliver a ZIP if requested").
CODE_MAX_TOKENS = max(300, min(int(os.getenv("SMARTIS_CODE_MAX_TOKENS", "1024")), 4000))
CODE_TIMEOUT = max(60.0, min(float(os.getenv("SMARTIS_CODE_TIMEOUT", "240.0")), 900.0))

# The old gate dropped any short utterance, which is exactly what made Smartis
# answer "I did not understand" so often. "relaxed" keeps every plausible
# sentence and only removes the classic STT hallucinations.
_noise_gate_env = os.getenv("SMARTIS_NOISE_GATE", "strict").strip().lower()
# 2.2 used "relaxed", which caused cough/background transcripts to reach the
# planner. Keep backward compatibility with old .env files but use the safer
# gate unless the user explicitly disables it.
NOISE_GATE_MODE = "off" if _noise_gate_env in {"off", "false", "0", "disabled"} else "strict"

# ---------------------------------------------------------------------------
# Self-voice (echo) protection.
# ---------------------------------------------------------------------------
# While Smartis is speaking, the microphone must not be able to turn its own
# TTS output into a new command (this caused the Wikipedia read-aloud loop).
SPEAK_TAIL_GUARD_SECONDS = max(0.0, min(float(os.getenv("SMARTIS_SPEAK_TAIL_GUARD", "0.55")), 10.0))
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

# Destructive actions are confirmation-gated: power actions, deleting files /
# folders and force-closing applications.
REQUIRE_CONFIRMATION_FOR = {
    "shutdown_windows",
    "restart_windows",
    "sleep_windows",
    "delete_file",
    "delete_named",
    "close_application",
}
CONFIRMATION_TTL_SECONDS = max(15.0, min(float(os.getenv("SMARTIS_CONFIRM_TTL", "90")), 600.0))
