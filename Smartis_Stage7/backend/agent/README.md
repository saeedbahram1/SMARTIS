# Agent

مرحله ۳ یک Agent واقعیِ قابل توسعه اضافه می‌کند.

## Local LLM

Agent ابتدا به Ollama روی سیستم محلی وصل می‌شود:

```text
http://127.0.0.1:11434
```

مدل پیش‌فرض:

```text
qwen2.5:7b
```

اگر Ollama یا مدل در دسترس نباشد، برنامه به fallback بسیار محدود برمی‌گردد.

برای فعال کردن مدل محلی، بعد از نصب Ollama:

```bat
ollama pull qwen2.5:7b
```

این دانلود فقط یک‌بار لازم است؛ پس از نصب مدل، پردازش Agent می‌تواند کاملاً محلی باشد.

## معماری

```text
Whisper
  ↓
User text
  ↓
Planner (local LLM)
  ↓
Structured JSON plan
  ↓
Validator
  ↓
Tool Executor
  ↓
Windows / Browser / Files
```

در این مرحله shell آزاد در اختیار مدل قرار داده نشده و ابزارها registry مشخص دارند.
عملیات حساس نیز بدون confirmation اجرا نمی‌شوند.

## Browser automation (Patch)

برای درخواست‌های زنجیره‌ای («برو فلان سایت، این را بنویس، بفرست، جواب را بخوان») یک
مرورگر Selenium جداگانه (`agent/browser_tools.py`) اضافه شده که در طول یک plan
باز می‌ماند: `browser_open` → `browser_type` → `browser_submit` →
`browser_read_response`. این جدا از `open_website` است که فقط مرورگر پیش‌فرض
سیستم را باز می‌کند و دیگر قابل کنترل نیست.
