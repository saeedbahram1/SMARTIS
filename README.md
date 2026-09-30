# Smartis — Direct Listening / Jarvis Command Layer

This package contains the current Smartis Windows desktop project.

## What changed in Stage 16

1. **No wake word.** Smartis listens continuously for commands. `Smartis` / `اسمارتیز` is optional and is removed only when it appears at the beginning of a command.
2. **Stable microphone path.** The Python backend owns one continuous `sounddevice` stream. Flutter does not start/stop a Windows recorder for every command.
3. **WebSocket JSON is hardened.** NumPy scalars/arrays are converted before transmission and WebSocket event frames are sent as pre-encoded JSON text, preventing the `Object of type bool is not JSON serializable` crash seen in the previous build.
4. **Separate system vs player audio.** `صدا 20 درصد` targets Windows master volume. `صدای آهنگ 150 درصد` targets the active player's own volume and will not silently fall back to Windows volume when the player cannot expose that range.
5. **Media transport controls.** Next, previous, play/pause and stop use Windows media transport keys, so they can control the active compatible player without requiring Smartis to know the exact app first.
6. **Player volume above 100%.** Smartis first checks the active player's exposed UI slider. If the player exposes a range above 100%, that range is used; otherwise Smartis reports that the requested level is unsupported. VLC documents a configurable maximum volume display in its preferences.
7. **Natural commands.** Fast-path commands cover common Persian/English requests such as opening Google, changing volume by percentage, muting/unmuting, next/previous, pause/stop, player-specific volume, and playing a requested song/video. Unknown/general commands can still fall through to the local planner when Ollama is available.
8. **Multi-step examples.** Common combinations such as `برو تو گوگل و آهنگ شایع ترک عصبانی رو پخش کن` are handled directly as two actions.

## Run

1. Replace your existing `C:\Project\Smartis` project with the contents of this ZIP.
2. Run `SETUP_SHERPA_MODELS.bat` once if the speech model folders are not populated.
3. Start with `START_SMARTIS.bat`, or run `run_backend.bat` and `run_frontend.bat` separately.
4. The microphone starts listening automatically; there is no wake-word step.

## Diagnostics

- `TEST_MICROPHONE.bat` checks the Windows input device and raw PCM level.
- `TEST_COMMAND_ENGINE.bat` checks normalization, the no-wake-word rule, JSON serialization, media commands, volume parsing and the common multi-step example.
- `REPAIR_WINDOWS.bat` repairs the Flutter Windows project and runs a complete Windows build.

## Speech models

Run `SETUP_SHERPA_MODELS.bat` once to install Python dependencies and download the required Sherpa-ONNX speech models. Model files are intentionally not included in the ZIP because of their size.

## Windows shell

Smartis uses a native Windows MethodChannel for its small set of window operations; `window_manager` and `screen_retriever` are intentionally not dependencies.


## Stage 16 رفتار صوتی
- Listening مستقیم بدون Wake Word
- فارسی اولویت اول؛ English فقط وقتی نتیجه فارسی معتبر نباشد
- endpoint سریع‌تر (~0.58s سکوت)
- فرمان‌های fast-path در یک round-trip اجرا می‌شوند؛ TTS فقط بعد از اجرای action انجام می‌شود
- مسیر Ollama فقط برای فرمان‌هایی استفاده می‌شود که fast-path ندارند و timeout پیش‌فرض 4 ثانیه است

## Stage 17 command engine

- Wake word is not required. “Smartis/اسمارتیز” is an optional leading prefix.
- Persian is the first STT path; English is only a fallback.
- Common web commands are deterministic and do not depend on Ollama.
- Google/YouTube/Gmail and search requests open directly in Chrome; music playback is local/direct VLC and does not depend on YouTube.
- Multi-step requests such as “Google → search Tom Hardy → open Wikipedia” execute as a real action chain.
- Smartis has dynamic self-introduction responses and always identifies its creator as the Saeed Behrami team when asked.
- The normal UI label is “در حال اجرا...” rather than “دارم فکر می‌کنم...”.


## Stage 18
- Search parsing extracts only the intended query before the Wikipedia/navigation clause.
- Factual questions use Wikipedia directly without opening a browser, then ask whether to continue reading.
- Live news requests prefer reputable sources and expose source names.
- Natural Persian/English arithmetic is routed to the safe calculator.


## Stage 19 — Daily assistant dashboard + system control

- Full black main window with a live clock, Jalali date, weather card, CPU/RAM usage, Smartis CPU/RAM usage, and sensor temperatures when Windows hardware monitoring exposes them.
- Main-window TTS controls for Persian and English male/female Edge neural voices.
- Windows Location privacy-settings shortcut when automatic location is unavailable.
- Exact system and player volume percentages, with mute/unmute and active-player media transport.
- Power actions (shutdown/restart/sleep) queue a short confirmation; file/folder create/delete do not. Confirmation accepts `بله`, `آره`, `تایید`, `تأیید`, `yes`, `confirm`, and similar direct affirmations.
- Windows user language switching validates the requested language is installed before applying it.
- Direct Windows Settings and Search actions.
- Empty file/folder creation and follow-up naming, plus exact-name deletion under Desktop/Downloads/C:\ roots.
- SymPy-backed calculator for natural Persian/English arithmetic, percentages, roots, trigonometry, powers, and simple equations.
- Persian news mode filters to trusted Persian source domains/source names when metadata is available.
- Weather supports a city such as `هوای همدان` / `هوای کرج` and location-based weather when Windows Location is enabled.
Stage 19 Windows build hotfix
- Fixed frontend/lib/app.dart syntax errors in the MaterialApp build tree and _voiceCard widget.
- No feature logic was changed by this hotfix.
- The corrected app.dart has balanced Dart delimiters.


## Stage 24 architecture

- Unmatched natural-language commands are semantically planned by the local Ollama model; there is no OpenAI/ChatGPT API dependency.
- Research uses Wikipedia first, then accessible public web search/results, with local Ollama synthesis when available.
- Music commands search local Music/Downloads/Desktop/Videos folders and play matches directly in VLC. Explicit direct media URLs are also accepted. YouTube scraping/yt-dlp/Selenium are not used.


## Stage 24 additions
- Bounded local conversation memory and follow-up reference resolution.
- Ollama receives recent local context for semantic multi-turn planning.
- Online music playback restored through yt-dlp direct-stream extraction into VLC.
- Local-folder music playback removed from the media command path.
