from __future__ import annotations

import json
import sys
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from config import OLLAMA_MODEL, OLLAMA_URL  # noqa: E402


def main() -> int:
    print("SMARTIS OLLAMA DIAGNOSTIC")
    print(f"URL   : {OLLAMA_URL}")
    print(f"MODEL : {OLLAMA_MODEL}")
    try:
        r = requests.get(f"{OLLAMA_URL}/api/tags", timeout=3)
        print(f"TAGS  : HTTP {r.status_code}")
        r.raise_for_status()
        models = [str(x.get("name")) for x in (r.json().get("models") or []) if isinstance(x, dict)]
        print(f"MODELS: {models}")
        # Ollama may report "qwen2.5:1.5b:latest"; that is the same model.
        norm = lambda n: str(n or "").strip().lower().removesuffix(":latest")  # noqa: E731
        if norm(OLLAMA_MODEL) not in {norm(m) for m in models}:
            print("RESULT: FAIL — configured model is not installed.")
            print(f"FIX   : ollama pull {OLLAMA_MODEL}")
            return 2

        try:
            ps = requests.get(f"{OLLAMA_URL}/api/ps", timeout=3)
            loaded = []
            if ps.ok:
                loaded = [str(x.get("name") or x.get("model")) for x in (ps.json().get("models") or []) if isinstance(x, dict)]
            print(f"LOADED: {loaded}")
        except Exception as exc:
            print(f"LOADED: unavailable ({exc})")

        payload = {
            "model": OLLAMA_MODEL,
            "messages": [{"role": "user", "content": "Reply with exactly: OK"}],
            "stream": False,
            "think": False,
            "options": {"temperature": 0, "num_ctx": 512, "num_predict": 8},
        }
        r = requests.post(f"{OLLAMA_URL}/api/chat", json=payload, timeout=30)
        print(f"CHAT  : HTTP {r.status_code}")
        if r.status_code >= 400:
            print("BODY  :", r.text[:1200])
            print("RESULT: FAIL — chat API rejected the request.")
            return 3
        data = r.json()
        content = str((data.get("message") or {}).get("content") or "").strip()
        print("ANSWER:", content)
        print("RESULT: OK — model and /api/chat are working with think=false.")
        return 0
    except Exception as exc:
        print(f"ERROR : {type(exc).__name__}: {exc}")
        print("RESULT: FAIL — see the exact exception above.")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
