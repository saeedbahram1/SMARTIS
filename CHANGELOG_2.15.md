# Smartis 2.15 – Real Chat, Attachments, Steps & Speed

The 2.15 line turns Smartis into a real ChatGPT-style assistant: the smarter
qwen3.5:4b brain, file/ZIP attachments inside the chat, visible step-by-step
progress, true message editing with re-run, and a fully continuous orb.

## Brain: qwen3.5:4b with one context size
- Default chat/planner model is now `qwen3.5:4b` (the 1.5B model was too weak
  for conversation and code). It still fits an 8 GB machine, and a different
  installed Qwen is used automatically if the exact tag is missing.
- ONE context size for every Ollama request (`SMARTIS_NUM_CTX`, default now
  2048). The old code used 192 / 256 / 512 / 2048 in different places, so
  Ollama restarted its runner again and again and reported "the model is not
  up" even while it was loaded. 2048 was chosen after MEASURING an attachment
  prompt on this machine (~948 tokens for a typical block).
- Long real-world timeouts: chat 240 s total / 180 s to the first token
  (measured worst case: 132.6 s first token, 178.2 s total with a full
  attachment prompt). The old 45 s / 25 s defaults aborted answers while the
  model was still prefilling.
- The model stays warm between requests (`SMARTIS_CHAT_KEEP_WARM=1`,
  keep_alive=-1) and the attachment block is sent as a byte-identical SYSTEM
  message so follow-up turns reuse Ollama's KV prefix cache.

## Chat attachments (the "+" button)
- New "+" button in the chat composer uploads files like ChatGPT; the chips
  pin above the composer and can be removed with their X.
- Text, code, images and ZIP files are all accepted (upload guard: empty and
  oversized files are rejected with a clear message).
- ZIPs are fully inspected: folder tree, text excerpts, entry cap, and a
  zip-slip guard so nothing outside the archive ever escapes.
- Follow-up questions keep working: pinned attachment ids travel with every
  message, and the model answers from the file content.
- Attachment-only send (`Send` with no text) makes Smartis inspect and explain
  the file.
- «فایل رو بررسی کن / داخل این زیپ چیه؟» style questions go to the chat model,
  never to web search; demonstrative phrases like «این فایل» are rejected as
  web-research topics even with wrapper verbs.

## Steps strip instead of "در حال نوشتن"
- While Smartis works, the chat shows a compact live strip: mini animated orb
  + the current step + elapsed seconds, with a small rotating triangle.
- Tap the strip to expand the FULL history of steps: past steps get a green
  check, the current step gets its own icon (attach, brain, web, code, time,
  weather, media, settings, power, …).
- Steps are honest and sequential: each label is emitted right before the real
  tool runs (after the confirmation gate), so the strip never claims something
  that did not happen. The frames are ephemeral WS events - they are never
  replayed into a finished conversation.
- Backend step sources: attachment inspection, request analysis, each executor
  action, and the local-model answer/thinking phase.

## The orb never restarts
- The listening/idle/thinking/speaking animation ran on a 2.6 s looping
  controller whose wrap made the phase jump from 2π back to 0 - it visibly
  "restarted" again and again (reported for listening especially).
- The orb now runs on a continuous Ticker clock (seconds), so rotation never
  wraps: identical visual speed, but truly endless motion in every state.

## Message editing runs again
- Editing a message (Telegram-style, the bubble reopens in the composer) now
  REPLACES that bubble in place AND immediately re-runs the edited text
  against the backend - commands and chats alike.

## Chat-only microphone and agent-voice toggles
- Inside the chat, the controls now toggle only the microphone cut/connect and
  Smartis' own spoken replies for the chat, separate from the rest of the app.

## Smarter commands (from the 2.14 line, still current)
- Confirmation flow: «بله / آره / ادامه بده» answers the PENDING confirmation
  or "shall I read more?" question instead of being swallowed by chat, then the
  queued action (e.g. `wikipedia_more`) executes.
- File / folder creation with a spoken name («برو ... بساز با اسم تست»), and
  canceling cleans up the half-made scratch.
- Compound and colloquial commands, unlimited phrasing (not just fixed
  sentences): open Google and search, open the first result and read it,
  open ChatGPT and start a new chat, write code on request and deliver a ZIP
  when the user asks for one.
- Destructive actions remain confirmation-gated: shutdown / restart / sleep /
  delete file / delete named / close application.

## Defaults
All defaults above can be overridden in `backend/.env` (see
`backend/.env.example`, updated to match this release: NUM_CTX 2048,
chat timeout 240 s, first-token 180 s).
