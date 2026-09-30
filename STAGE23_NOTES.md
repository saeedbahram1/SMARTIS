# Smartis Stage 23

- Removed the unused Selenium browser automation layer.
- Removed yt-dlp/YouTube extraction and JavaScript-runtime setup. Smartis no longer depends on YouTube for music playback.
- VLC playback now searches local Music/Downloads/Desktop/Videos and can play an explicit direct HTTP(S) media URL.
- Added `backend/services/research_service.py`: Wikipedia first, then Bing/DuckDuckGo accessible web results, with optional local Ollama synthesis. No OpenAI/ChatGPT API is used.
- Unmatched commands now go to local Ollama semantic planning instead of being rejected by an action-keyword gate.
- Fallback now performs web research instead of returning the generic “more specific target” response.
- Research and factual-question fast paths now use `web_research`, not Wikipedia-only answers.
- Removed generated Python `__pycache__` from the project ZIP.
- No wake-word module exists in this Stage; Smartis remains no-wake-word.
