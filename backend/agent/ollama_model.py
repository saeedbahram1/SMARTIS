from __future__ import annotations

"""Reliable local Ollama discovery for Smartis.

Smartis must work whether Ollama was already running before Smartis started or
was started later. On Windows, if the Ollama service is not reachable, Smartis
tries to start `ollama serve` itself and then verifies the installed model.
"""

import os
import shutil
import subprocess
import threading
import time
from typing import Any

import requests

from config import OLLAMA_MODEL, OLLAMA_URL

_PREFERRED = (
    "qwen3.5:4b",
    "qwen3.5:2b",
    "qwen3:4b",
    "qwen3:1.7b",
    "qwen2.5:1.5b",
)
_lock = threading.Lock()
_cached_model: str | None = None
_cached_at = 0.0
# tag -> capabilities reported by /api/tags (e.g. {"completion", "tools"})
_CAPABILITIES: dict[str, set[str]] = {}
_ensure_lock = threading.Lock()
_ensure_last = 0.0
_ensure_ok = False
_OLLAMA_PROCESS = None
_OLLAMA_STARTED_BY_SMARTIS = False
_OLLAMA_SERVER_PIDS: set[int] = set()
_CACHE_SECONDS = 20.0
_ENSURE_RETRY_SECONDS = 8.0


def _norm_tag(name: str) -> str:
    return str(name or "").strip().lower().removesuffix(":latest")


def _names(timeout: float = 0.8) -> set[str]:
    try:
        response = requests.get(f"{OLLAMA_URL}/api/tags", timeout=timeout)
        response.raise_for_status()
        data: dict[str, Any] = response.json()
        out: set[str] = set()
        for item in data.get("models") or []:
            if isinstance(item, dict):
                name = str(item.get("name") or "").strip()
                if not name:
                    continue
                out.add(name)
                caps = item.get("capabilities")
                if isinstance(caps, list):
                    _CAPABILITIES[_norm_tag(name)] = {str(c).strip().lower() for c in caps}
        return out
    except Exception:
        return set()


def supports_thinking(model: str) -> bool:
    """True only when Ollama advertises a `thinking` capability for this tag.

    qwen2.5:1.5b reports ["completion", "tools"] and answers HTTP 400 to
    think=true, so callers must not budget for a reasoning channel it never
    produces. An Ollama too old to report capabilities is treated as supportive
    and llm.generate's own 400 retry stays as the safety net.
    """
    if not _CAPABILITIES:
        _names()
    caps = _CAPABILITIES.get(_norm_tag(model))
    if caps is None:
        return True
    return "thinking" in caps


def _listening_pids(port: int = 11434) -> set[int]:
    """Return Windows PIDs currently listening on the Ollama API port."""
    if os.name != "nt":
        return set()
    try:
        completed = subprocess.run(
            ["netstat", "-ano", "-p", "tcp"],
            capture_output=True, text=True, errors="ignore",
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            timeout=2, check=False,
        )
        pids: set[int] = set()
        for line in completed.stdout.splitlines():
            parts = line.split()
            if len(parts) >= 5 and parts[0].upper() == "TCP":
                local = parts[1]
                state = parts[3].upper()
                if state == "LISTENING" and local.endswith(f":{port}"):
                    try:
                        pids.add(int(parts[4]))
                    except ValueError:
                        pass
        return pids
    except Exception:
        return set()


def _start_ollama_process() -> bool:
    """Start Ollama only when the API is actually unreachable."""
    global _OLLAMA_PROCESS, _OLLAMA_STARTED_BY_SMARTIS, _OLLAMA_SERVER_PIDS
    if os.name != "nt":
        return False
    exe = shutil.which("ollama")
    if not exe:
        return False
    try:
        before = _listening_pids()
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        _OLLAMA_PROCESS = subprocess.Popen(
            [exe, "serve"],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=flags,
            close_fds=True,
        )
        _OLLAMA_STARTED_BY_SMARTIS = True
        # ollama.exe may spawn a separate llama-server.exe which owns port 11434.
        # Record the actual listener after startup so shutdown can terminate the
        # real server tree rather than only the launcher PID.
        deadline = time.monotonic() + 6.0
        while time.monotonic() < deadline:
            current = _listening_pids()
            new_pids = current - before
            if new_pids:
                _OLLAMA_SERVER_PIDS.update(new_pids)
                break
            time.sleep(0.15)
        return True
    except Exception:
        return False


def shutdown_ollama() -> dict[str, Any]:
    """Stop every Ollama server process that Smartis itself started.

    Ollama can launch a separate llama-server.exe child which owns port 11434.
    Killing only the `ollama serve` launcher therefore leaves the model server
    alive. We track the listener PID created after Smartis startup and terminate
    that process tree too. Pre-existing Ollama instances are never touched.
    """
    global _OLLAMA_PROCESS, _OLLAMA_STARTED_BY_SMARTIS, _OLLAMA_SERVER_PIDS
    # Smartis is a single-user desktop assistant: closing Smartis also releases
    # the local model server. The Windows Ollama launcher may be external to
    # this process, so the actual listener PID is the authoritative resource.
    pids = set(_OLLAMA_SERVER_PIDS)
    proc = _OLLAMA_PROCESS
    if proc is not None:
        try:
            if proc.poll() is None:
                pids.add(int(proc.pid))
        except Exception:
            pass

    # The port listener is the authoritative server PID. It may not be the
    # same PID as the launcher process.
    pids.update(_listening_pids())
    errors: list[str] = []
    if os.name == "nt":
        try:
            subprocess.run(["taskkill", "/IM", "llama-server.exe", "/T", "/F"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0), timeout=4, check=False)
        except Exception as exc:
            errors.append(f"llama-server cleanup: {exc}")
    for pid in sorted(pids):
        try:
            subprocess.run(
                ["taskkill", "/PID", str(pid), "/T", "/F"],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                timeout=4, check=False,
            )
        except Exception as exc:
            errors.append(f"PID {pid}: {exc}")

    deadline = time.monotonic() + 5.0
    remaining: set[int] = set()
    while time.monotonic() < deadline:
        remaining = _listening_pids()
        if not remaining:
            break
        # Ollama may respawn llama-server.exe with a NEW PID. Kill the current
        # listener rather than checking only the PIDs seen at startup.
        for pid in sorted(remaining):
            try:
                subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0), timeout=3, check=False)
            except Exception as exc:
                errors.append(f"listener PID {pid}: {exc}")
        time.sleep(0.20)

    remaining = _listening_pids()
    if remaining and os.name == "nt":
        # Last resort: terminate the Ollama launcher/supervisor, which can
        # otherwise recreate llama-server immediately after taskkill.
        try:
            subprocess.run(["taskkill", "/IM", "ollama.exe", "/T", "/F"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0), timeout=4, check=False)
        except Exception as exc:
            errors.append(f"ollama launcher cleanup: {exc}")
        time.sleep(0.25)
        remaining = _listening_pids()

    if remaining:
        errors.append("Ollama listener still active: " + ", ".join(map(str, sorted(remaining))))

    try:
        if proc is not None and proc.poll() is None:
            proc.kill()
            proc.wait(timeout=2)
    except Exception:
        pass

    _OLLAMA_PROCESS = None
    _OLLAMA_STARTED_BY_SMARTIS = False
    _OLLAMA_SERVER_PIDS.clear()
    return {
        "ok": not errors,
        "stopped": not remaining,
        "tracked_pids": sorted(pids),
        "errors": errors,
    }

def ensure_ollama(force: bool = False) -> dict[str, Any]:
    """Return real local Ollama/model status and auto-start the server on Windows."""
    global _ensure_last, _ensure_ok
    now = time.monotonic()
    with _ensure_lock:
        if not force and now - _ensure_last < _ENSURE_RETRY_SECONDS:
            names = _names(timeout=0.25) if _ensure_ok else set()
            return {"ok": _ensure_ok, "models": sorted(names), "url": OLLAMA_URL}

        names = _names(timeout=0.8)
        if not names:
            _start_ollama_process()
            deadline = time.monotonic() + 4.0
            while time.monotonic() < deadline:
                names = _names(timeout=0.5)
                if names:
                    break
                time.sleep(0.15)

        _ensure_ok = bool(names)
        _ensure_last = time.monotonic()
        return {"ok": _ensure_ok, "models": sorted(names), "url": OLLAMA_URL}


def resolve_model(force: bool = False) -> str:
    global _cached_model, _cached_at
    now = time.monotonic()
    with _lock:
        if not force and _cached_model and now - _cached_at < _CACHE_SECONDS:
            return _cached_model

    installed = _names()
    if not installed:
        installed = set(ensure_ollama(force=force).get("models") or [])

    selected = OLLAMA_MODEL
    if installed and selected not in installed:
        for candidate in _PREFERRED:
            if candidate in installed:
                selected = candidate
                break
        else:
            # Prefer a Qwen model already installed, then any installed model.
            qwen = sorted(x for x in installed if x.lower().startswith("qwen"))
            selected = qwen[0] if qwen else sorted(installed)[0]

    with _lock:
        _cached_model = selected
        _cached_at = time.monotonic()
    return selected



def loaded_models(timeout: float = 1.5) -> list[str]:
    """Return models currently resident in Ollama memory."""
    try:
        response = requests.get(f"{OLLAMA_URL}/api/ps", timeout=timeout)
        response.raise_for_status()
        out: list[str] = []
        for item in response.json().get("models") or []:
            if isinstance(item, dict):
                name = str(item.get("name") or item.get("model") or "").strip()
                if name:
                    out.append(name)
        return out
    except Exception:
        return []

def model_status() -> dict[str, Any]:
    status = ensure_ollama()
    model = resolve_model()
    models = set(status.get("models") or [])
    loaded = loaded_models(timeout=1.2)
    # "qwen2.5:1.5b" and "qwen2.5:1.5b:latest"-style differences must not make a
    # perfectly good model look missing/unloaded.
    norm = lambda n: str(n or "").strip().lower().removesuffix(":latest")  # noqa: E731
    models_n = {norm(m) for m in models}
    loaded_n = {norm(m) for m in loaded}
    return {
        "ok": bool(status.get("ok")) and norm(model) in models_n,
        "url": OLLAMA_URL,
        "model": model,
        "installed_models": sorted(models),
        "loaded_models": loaded,
        "model_loaded": norm(model) in loaded_n,
    }
