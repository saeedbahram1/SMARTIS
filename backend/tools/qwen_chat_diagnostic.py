from __future__ import annotations
import json, sys, time
from pathlib import Path
import requests
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from config import OLLAMA_MODEL, OLLAMA_URL

SYSTEM = "تو Smartis هستی؛ دستیار ویندوزی فارسی‌اول. طبیعی، کوتاه و مستقیم جواب بده. زبان پاسخ دقیقاً زبان کاربر باشد. برای سؤال ساده معمولاً یک یا دو جمله کافی است. در این مسیر فقط پاسخ گفتگویی بده؛ اجرای فرمان‌ها مسیر جداگانه دارد."

CASES = [
    ("درود خوبی", 16, 192),
    ("تفاوت CPU و GPU چیه؟", 24, 256),
]

print("SMARTIS REAL CHAT DIAGNOSTIC")
print(f"URL   : {OLLAMA_URL}")
print(f"MODEL : {OLLAMA_MODEL}")
try:
    ps = requests.get(f"{OLLAMA_URL}/api/ps", timeout=3).json()
    print("PS    :", json.dumps(ps, ensure_ascii=False))
except Exception as exc:
    print("PS ERROR:", repr(exc))
    raise SystemExit(2)

for text, num_predict, num_ctx in CASES:
    payload = {
        "model": OLLAMA_MODEL,
        "stream": False,
        "think": False,
        "keep_alive": -1,
        "messages": [
            {"role": "system", "content": SYSTEM},
            {"role": "user", "content": text},
        ],
        "options": {
            "temperature": 0.20,
            "top_p": 0.8,
            "repeat_penalty": 1.05,
            "num_ctx": num_ctx,
            "num_predict": num_predict,
        },
    }
    print("\nCASE:", text)
    print("OPTIONS:", {"num_predict": num_predict, "num_ctx": num_ctx})
    started = time.perf_counter()
    try:
        r = requests.post(f"{OLLAMA_URL}/api/chat", json=payload, timeout=20)
        elapsed = time.perf_counter() - started
        print(f"HTTP  : {r.status_code} • {elapsed:.2f}s")
        if r.status_code >= 400:
            print("BODY  :", r.text[:1200])
            continue
        data = r.json()
        msg = data.get("message") or {}
        print("REPLY :", str(msg.get("content") or "").strip())
        print("TOTAL :", data.get("total_duration"))
        print("LOAD  :", data.get("load_duration"))
        print("EVAL  :", data.get("eval_duration"))
        print("TOKENS:", data.get("eval_count"))
    except requests.Timeout as exc:
        elapsed = time.perf_counter() - started
        print(f"TIMEOUT after {elapsed:.2f}s:", exc)
        print("RESULT: The model is resident, but this production-shaped completion is too slow.")
    except Exception as exc:
        print("ERROR:", repr(exc))

print("\nDone.")
