from __future__ import annotations

"""Single gateway to the local Ollama server.

Why this exists
---------------
Before 2.13 the chat path, the planner and the warm-up each built their own
payload with a DIFFERENT ``num_ctx`` (192 / 256 / 512 / 2048) and only some of
them set ``keep_alive``. Ollama restarts its runner whenever ``num_ctx``
changes, and a request without ``keep_alive`` resets the unload timer to the
default 5 minutes. The result: the model was reloaded over and over and
Smartis kept reporting that the model was "not up" although it had answered a
moment earlier.

Rules enforced here for every request:
  * identical ``num_ctx`` everywhere (config.OLLAMA_NUM_CTX)
  * ``keep_alive = -1`` always
  * no pre-flight "is it resident?" gate - Ollama loads on demand
  * streaming, so a slow machine still returns the text produced so far
  * real error text is returned (never a vague "model not ready")
"""

import json
import re
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable

import requests

from agent.logbus import logbus
from config import CHAT_FIRST_TOKEN_TIMEOUT, CHAT_KEEP_MODEL_WARM, OLLAMA_NUM_CTX, OLLAMA_NUM_THREAD, OLLAMA_URL

_THINK_BLOCK = re.compile(r"<think>.*?</think>", re.S | re.I)
_THINK_OPEN = re.compile(r"<think>.*$", re.S | re.I)


@dataclass
class LLMResult:
    ok: bool
    text: str = ""
    thinking: str = ""
    error: str | None = None
    partial: bool = False
    cancelled: bool = False
    load_seconds: float = 0.0
    total_seconds: float = 0.0
    tokens: int = 0
    meta: dict[str, Any] = field(default_factory=dict)


_inflight_lock = threading.Lock()

# Models without a reasoning head (qwen2.5:1.5b, ...) answer HTTP 400 to
# think=true. The verdict never changes for a given tag, so remember it and skip
# the doomed round-trip on every later "thinking" request.
_think_unsupported: set[str] = set()
_think_lock = threading.Lock()


def _think_rejected(model: str) -> bool:
    key = normalize_model_name(model)
    with _think_lock:
        return key in _think_unsupported


def _remember_think_unsupported(model: str) -> None:
    key = normalize_model_name(model)
    with _think_lock:
        _think_unsupported.add(key)


def keep_alive_value() -> int:
    return -1 if CHAT_KEEP_MODEL_WARM else 0


def normalize_model_name(name: str) -> str:
    value = str(name or "").strip().lower()
    return value[:-7] if value.endswith(":latest") else value


def strip_think(text: str) -> str:
    value = _THINK_BLOCK.sub("", text or "")
    value = _THINK_OPEN.sub("", value)
    return value.strip()


def _options(num_predict: int, temperature: float, extra: dict[str, Any] | None = None) -> dict[str, Any]:
    options: dict[str, Any] = {
        "temperature": temperature,
        "top_p": 0.85,
        "repeat_penalty": 1.08,
        "num_ctx": OLLAMA_NUM_CTX,  # MUST stay identical for every request
        "num_predict": int(num_predict),
    }
    if OLLAMA_NUM_THREAD > 0:
        options["num_thread"] = OLLAMA_NUM_THREAD
    if extra:
        options.update(extra)
    return options


def generate(
    model: str,
    messages: list[dict[str, str]],
    *,
    num_predict: int = 400,
    temperature: float = 0.5,
    think: bool = False,
    json_mode: bool = False,
    total_timeout: float = 90.0,
    first_token_timeout: float | None = None,
    is_cancelled: Callable[[], bool] | None = None,
    label: str = "chat",
) -> LLMResult:
    """Stream a completion from Ollama and return everything produced."""
    started = time.monotonic()
    first_timeout = float(first_token_timeout or CHAT_FIRST_TOKEN_TIMEOUT)

    def build(think_flag: bool | None) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "stream": True,
            "keep_alive": keep_alive_value(),
            "options": _options(num_predict, temperature),
        }
        if think_flag is not None:
            payload["think"] = think_flag
        if json_mode:
            payload["format"] = "json"
        return payload

    attempts: list[bool | None] = [bool(think)]
    if think and _think_rejected(model):
        # Already proven unsupported this run: go straight to the plain request.
        attempts = [None]
    elif think:
        # A model without thinking support answers HTTP 400 to think=true.
        attempts.append(None)

    last_error = "unknown error"
    for think_flag in attempts:
        text_parts: list[str] = []
        think_parts: list[str] = []
        meta: dict[str, Any] = {}
        response = None
        try:
            # (connect timeout, read timeout between chunks)
            response = requests.post(
                f"{OLLAMA_URL}/api/chat",
                json=build(think_flag),
                stream=True,
                timeout=(5.0, max(first_timeout, 30.0)),
            )
            if response.status_code >= 400:
                body = response.text[:500].replace("\n", " ")
                last_error = f"HTTP {response.status_code}: {body}"
                if think_flag is True and response.status_code == 400 and "think" in body.lower():
                    _remember_think_unsupported(model)
                    logbus.emit("OLLAMA", "Model does not support thinking; retrying without it.", body)
                    continue
                return LLMResult(False, error=last_error, total_seconds=time.monotonic() - started)

            first_seen = False
            for raw in response.iter_lines(decode_unicode=True):
                now = time.monotonic()
                if is_cancelled and is_cancelled():
                    response.close()
                    return LLMResult(
                        False,
                        text=strip_think("".join(text_parts)),
                        error="cancelled",
                        cancelled=True,
                        total_seconds=now - started,
                    )
                if now - started > total_timeout:
                    response.close()
                    partial = strip_think("".join(text_parts))
                    return LLMResult(
                        bool(partial),
                        text=partial,
                        thinking="".join(think_parts),
                        error=f"timeout after {total_timeout:.0f}s",
                        partial=True,
                        total_seconds=now - started,
                    )
                if not raw:
                    continue
                try:
                    chunk = json.loads(raw)
                except ValueError:
                    continue
                if chunk.get("error"):
                    last_error = str(chunk.get("error"))
                    response.close()
                    return LLMResult(False, error=f"ollama: {last_error}", total_seconds=now - started)
                message = chunk.get("message") or {}
                piece = message.get("content") or ""
                thought = message.get("thinking") or ""
                if piece:
                    text_parts.append(piece)
                if thought:
                    think_parts.append(thought)
                if (piece or thought) and not first_seen:
                    first_seen = True
                if chunk.get("done"):
                    meta = {
                        k: chunk.get(k)
                        for k in ("total_duration", "load_duration", "prompt_eval_count", "eval_count", "eval_duration")
                    }
                    break

            text = strip_think("".join(text_parts))
            elapsed = time.monotonic() - started
            load = float(meta.get("load_duration") or 0) / 1e9
            tokens = int(meta.get("eval_count") or 0)
            if not text:
                reason = "model returned only thinking text" if think_parts else "empty response from model"
                return LLMResult(
                    False,
                    thinking="".join(think_parts),
                    error=reason,
                    total_seconds=elapsed,
                    load_seconds=load,
                    tokens=tokens,
                    meta=meta,
                )
            logbus.emit(
                "OLLAMA",
                f"{label}: {tokens} tokens in {elapsed:.1f}s (model load {load:.1f}s)",
                json.dumps({k: v for k, v in meta.items() if v is not None}, ensure_ascii=False),
            )
            return LLMResult(
                True,
                text=text,
                thinking="".join(think_parts),
                total_seconds=elapsed,
                load_seconds=load,
                tokens=tokens,
                meta=meta,
            )
        except requests.Timeout as exc:
            partial = strip_think("".join(text_parts))
            if partial:
                return LLMResult(True, text=partial, partial=True, error=f"stalled: {exc}", total_seconds=time.monotonic() - started)
            return LLMResult(False, error=f"no response from Ollama within {first_timeout:.0f}s (model still loading?): {exc}", total_seconds=time.monotonic() - started)
        except requests.ConnectionError as exc:
            return LLMResult(False, error=f"cannot reach Ollama at {OLLAMA_URL}: {exc}", total_seconds=time.monotonic() - started)
        except requests.RequestException as exc:
            return LLMResult(False, error=f"ollama request error: {exc}", total_seconds=time.monotonic() - started)
        except Exception as exc:  # noqa: BLE001 - never crash the request thread
            return LLMResult(False, error=f"{type(exc).__name__}: {exc}", total_seconds=time.monotonic() - started)
        finally:
            try:
                if response is not None:
                    response.close()
            except Exception:
                pass

    return LLMResult(False, error=last_error, total_seconds=time.monotonic() - started)


def warm_model(model: str, timeout: float = 120.0) -> LLMResult:
    """Load the model with EXACTLY the options chat will use (same num_ctx)."""
    try:
        response = requests.post(
            f"{OLLAMA_URL}/api/chat",
            json={
                "model": model,
                "messages": [{"role": "user", "content": "hi"}],
                "stream": False,
                "think": False,
                "keep_alive": keep_alive_value(),
                "options": _options(1, 0.0),
            },
            timeout=timeout,
        )
        if response.status_code >= 400:
            return LLMResult(False, error=f"HTTP {response.status_code}: {response.text[:300]}")
        data = response.json()
        return LLMResult(True, text=str((data.get("message") or {}).get("content") or ""), load_seconds=float(data.get("load_duration") or 0) / 1e9)
    except Exception as exc:  # noqa: BLE001
        return LLMResult(False, error=f"{type(exc).__name__}: {exc}")
