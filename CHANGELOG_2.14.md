# Smartis 2.14 – Turbo Voice & Chat UI Fix

## Voice latency
- Command silence/end-of-speech thresholds were reduced to shorten the wait before STT starts.
- Microphone audio callback blocks were reduced to 50 ms.
- Mic-level events are emitted more frequently and the level curve is compressed for stronger visual response.
- Sherpa STT thread default increased from 2 to 4.
- STT elapsed time is now attached to command results as `stt_elapsed_ms` for diagnostics.

## Orb synchronization
- Listening animation now uses the real microphone level as its dominant amplitude driver instead of a large independent fake waveform.
- Orb animation cycle was shortened from 4200 ms to 2600 ms.
- Speaking animation was tightened so it reacts more directly to the current level.

## Voice Stop behavior
- Voice processing now sets the UI busy state with `setState`, so the Stop action can become visible.
- Chat/voice operations share a Stop action in the composer.
- Voice Stop invalidates the active operation generation to suppress late STT/LLM/TTS results.
- Backend now accepts `speak_stop` to immediately release the microphone safety hold.
- Speech-tail guard defaults were reduced to shorten post-TTS microphone dead time.

## Chat UI
- “Smartis is writing…” is now an assistant bubble directly after the latest user message.
- Composer controls (plus, Think, microphone, Send/Stop) are inside the rounded input container.
- Send control changes to Stop while a response is being processed.
- Message direction is detected from the text so Persian and English bubbles align naturally.
- Message editing continues to use resend-new-turn behavior: the old message remains in history and the edited text is placed only in the composer.

## Ollama responsiveness
- Default context size: 1536.
- Default chat timeout: 45 s.
- Default first-token timeout: 25 s.
- Default normal response limit: 260 tokens.
- Default thinking response limit: 700 tokens.

These are defaults. An existing `backend/.env` file can override them.

### 2.14.1 Windows build hotfix
- Fixed Flutter compile error caused by the invalid `Colors.white20` constant in `smartis_chat_panel.dart`. Replaced it with `Colors.white.withOpacity(.20)`.
