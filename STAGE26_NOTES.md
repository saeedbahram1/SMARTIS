# Smartis Stage 26

- Complex/multi-action utterances are routed to local Ollama semantic planning first.
- Natural connectors: و، بعد، بعدش، سپس، و بعد، and, then, after that.
- Fast-path multi-action splitter supports the same connectors.
- Music query extraction keeps artist/title separate from command words.
- Online music playback restored to the simpler direct yt-dlp -> VLC path used by the earlier build.
- No local Music/Downloads fallback and no normal browser fallback.
- SETUP_MEDIA_PLAYBACK keeps an already-installed yt-dlp version instead of blindly upgrading it.
- No OpenAI API is added; semantic planning remains local Ollama.
