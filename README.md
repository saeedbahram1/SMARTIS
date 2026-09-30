# Smartis 2.2 — Conversational layer + self-voice protection

This update is **additive**. Original project files (fast_path, planner, tools,
system_tools, context_memory, conversation, microphone_service, sherpa_service,
tts_service, media_control, smartis_orb, main.dart, windows_window, pubspec) are
**not modified**. You only replace the files listed below.

## 1. Smartis now answers everything (the main request)

**Problem:** any utterance the deterministic engine did not recognise ended in a
dead-end reply ("I did not understand / try again"). That is what made Smartis
feel like a broken bot.

**Fix:** a conversational layer, `backend/agent/chat.py`, backed by the **same
local Ollama model** that already powers the planner (`qwen2.5:7b`).

* **No paid API.** No OpenAI, no Gemini, no cloud key. Everything stays local.
* Every non-command utterance is answered like a human would answer it.
* Degradation ladder — there is never a dead end:
  1. local Ollama chat completion → `chat-local`
  2. Wikipedia / public-web research → `chat-research`
  3. a warm, human holding reply → `chat-offline`
* A dead-end reply coming from the planner is detected and re-routed to the
  conversational layer instead of being spoken to you.
* The model is pre-warmed at startup (`keep_alive: 30m`) so the first real
  answer is fast.

Turn it off or tune it from `backend/.env`:

```
SMARTIS_CHAT_MODEL=qwen2.5:7b
SMARTIS_CHAT_TIMEOUT=20
SMARTIS_CHAT_TEMPERATURE=0.65
SMARTIS_CHAT_MAX_TOKENS=450
SMARTIS_CHAT_KEEP_WARM=1
```

## 2. The Wikipedia read-aloud bug (Smartis listening to itself)

**Root cause (found in the code):** `frontend/lib/app.dart` waited for the audio
with a hard **30-second cap**. A Wikipedia article takes longer than that, so the
microphone was re-enabled while Smartis was still speaking, and it transcribed
its own voice as a new command. A feedback loop.

**Three independent fixes, so it cannot come back:**

1. **The cap is gone.** `_speak()` now waits for the player to really finish.
2. **Backend suppression watchdog.** `/speak` keeps the microphone paused for the
   estimated audio duration plus a tail guard, and a watchdog re-pauses the
   microphone if anything re-enables listening while Smartis is still talking.
3. **Echo guard.** `backend/agent/echo_guard.py` remembers what Smartis said in
   the last 30 s and silently discards any transcript that is basically its own
   words (token-overlap + substring containment).

Tuning in `backend/.env`:

```
SMARTIS_SPEAK_TAIL_GUARD=1.6
SMARTIS_ECHO_WINDOW=30
SMARTIS_ECHO_THRESHOLD=0.60
```

## 3. Noise gate relaxed

The old gate dropped every short utterance, which is a big part of why so many
sentences got "I did not understand". The default mode now keeps every plausible
sentence and only removes classic STT hallucinations.

```
SMARTIS_NOISE_GATE=relaxed   # default
SMARTIS_NOISE_GATE=strict    # restores the old behaviour
```

Short confirmations (`بله`, `آره`, `تایید`, `نه`, `ادامه`, `yes`, ...) are always
accepted, and a pending confirmation is now consumed **before** the gate — a
three-character "بله" can confirm a shutdown.

## 4. Confirmation no longer repeats actions (bug fix)

In `executor.py`, the pending-confirmation state stored the **whole plan**. For
"open Google, then shut down", the already-executed "open Google" step ran a
second time after you confirmed. Only the **remaining** actions are stored now.

## 5. Advanced technical-log panel (matching your screenshot)

New widget `frontend/lib/widgets/smartis_log_panel.dart`:

* Category filter chips: `SYSTEM` `MEDIA` `EXECUTOR` `FAST_PATH` `PLANNER` `STT` `CONFIRMATION` plus `ALL`
* Structured cards with a coloured category badge, right-aligned message and a timestamp
* Collapsible dark payload block (`▼ نمایش کامل` / `▲ بستن`)
* Per-entry copy button (📋)
* Header counter ("N رویداد") and a clear-all button
* Footer with a live green/red connection dot and
  `FastAPI WebSocket: Connected (127.0.0.1:8765)`

The entries come from the backend: `backend/agent/logbus.py` emits structured
events over the existing WebSocket as `{"type": "log", ...}` frames, and
`GET /logs` returns the backlog.

## 6. Chat tab (matching your screenshot, Telegram-style send button)

New widget `frontend/lib/widgets/smartis_chat_panel.dart`:

* Segmented switch at the top of the left column: **پنل لاگ‌های فنی** ⇄ **چت**
* Telegram-style circular gradient send button with a paper-plane icon
  (`Icons.send_rounded`), glow when active, dimmed when empty
* Optional mic button, search icon inside the field, RTL Persian placeholder
* Message bubbles with timestamps and double-check marks
* "Smartis در حال نوشتن..." typing indicator

Typed chat is spoken out loud as well — the answer appears as a bubble **and**
goes through TTS.

New endpoint: `POST /chat` (`{"text": "...", "language": "fa"|"en"}`).

## 7. Orb slightly larger

`smartis_orb.dart` is **not touched**. The orb is scaled 1.08× from `app.dart`
with a paint-only `Transform.scale`, so it reads a little closer to your
reference image without modifying the original widget.

## 8. Bonus: the dashboard "SMARTIS CORE" panel

The orb panel now shows `SMARTIS CORE` / detected-language HUD labels and a
`LISTENING` status line, and the left column is a proper two-tab panel.

---

## Files in this update

**New (backend)**
* `backend/agent/chat.py` — conversational layer
* `backend/agent/echo_guard.py` — self-voice detection
* `backend/agent/logbus.py` — structured log bus

**Replaced (backend)**
* `backend/config.py` — new settings only; every original value kept
* `backend/main.py` — every original endpoint/behaviour kept, plus `/chat`,
  `/logs`, `/history`, log streaming, echo guard and the microphone watchdog
* `backend/agent/executor.py` — one-line confirmation fix
* `backend/.env.example` — new settings appended

**New (frontend)**
* `frontend/lib/widgets/smartis_log_panel.dart`
* `frontend/lib/widgets/smartis_chat_panel.dart`

**Replaced (frontend)**
* `frontend/lib/app.dart`
* `frontend/lib/services/backend_socket.dart`

Everything else in the project is untouched.

## How to install

1. Back up your current `C:\Project\Smartis`.
2. Copy these files over the matching paths (they are already in the right
   folder structure — a plain folder merge is enough).
3. Make sure **Ollama is running** with the model from `OLLAMA_MODEL`
   (default `qwen2.5:7b`): `ollama serve` and `ollama pull qwen2.5:7b`.
   This is the same requirement the planner already had.
4. `flutter pub get` in `frontend` (no new packages were added).
5. Start with `START_SMARTIS.bat`.

No new Python or Dart dependency is required.
