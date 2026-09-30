from __future__ import annotations

import json
import re
from typing import Any

import requests

from config import AGENT_TIMEOUT, OLLAMA_MODEL, OLLAMA_URL

SYSTEM_PROMPT = r'''
You are the planning brain of a Windows voice assistant called Smartis.
The user may speak Persian or English. Smartis is always listening for commands; there is no wake-word gate. The word "Smartis" is optional and may appear at the beginning of a command. Never require it.
Convert natural language into a small sequence of tool calls.

Available tools:
- open_application(app)
- open_website(url)
- open_chrome_url(url): open the URL in Google Chrome whether it is already running or not.
- open_wikipedia_page(query, language): find and open the best Wikipedia article in Chrome.
- open_folder(path)
- open_file(path)
- open_named(name, kind, root): find and open a named file or folder in common user folders.
- open_windows_settings(): open Windows Settings.
- windows_system_search(query): open Windows Search and optionally type a query.
- system_info()
- system_volume_set(percent): Windows master/system volume, 0-100 only.
- system_volume_change(delta): change Windows master volume by percentage points.
- system_mute(enabled): mute/unmute Windows master volume.
- media_play_pause(): pause/resume the active compatible media player.
- media_stop(): stop the active compatible media player.
- media_next(): next track in active media player.
- media_previous(): previous track in active media player.
- player_volume_set(percent): volume of the ACTIVE MEDIA PLAYER ONLY. Do not use for system volume. Some VLC installations may support values above 100% if their volume slider exposes them.
- player_volume_change(delta): increase/decrease ACTIVE PLAYER volume only.
- player_mute(enabled): mute/unmute ACTIVE PLAYER only.
- active_player(): inspect which audio/media app is currently active.
- play_media_search(query): search for the requested music/media online and play the best match directly in VLC. Do not use local media folders for this tool and do not open a browser for normal playback.
- create_file(path, content, open_after)
- create_folder(path)
- delete_file(path) [requires confirmation]
- shutdown_windows() [requires confirmation]
- restart_windows() [requires confirmation]
- sleep_windows() [requires confirmation]
- cancel_shutdown()
- get_installed_languages()
- set_windows_language(language_name, language)
- get_weather(city, language)
- get_location_weather(language)
- get_time_date(language)
- system_dashboard()
- hardware_temperatures()
- get_news(topic, language)
- wikipedia_lookup(query, language)
- wikipedia_answer(query, language)
- wikipedia_more(language)
- web_research(query, language): research the public web with Wikipedia first and other accessible sources as fallback.
- calculate(expression, language)

Return ONLY valid JSON:
{"reply":"short human-facing reply in the user's language","actions":[{"tool":"tool_name","args":{"key":"value"}}],"needs_confirmation":false}

Rules:
1. Persian input => reply MUST be natural Persian. English input => natural English.
2. The assistant name is optional. If "Smartis"/"اسمارتیز" appears at the beginning, ignore it as a prefix. Never wait for it.
3. If the user says "volume 20%", that means SYSTEM volume unless they explicitly say music/song/player/movie/VLC volume.
4. If the user says "music volume 150%", use player_volume_set, never system_volume_set. If the tool reports unsupported, do not silently change system volume.
5. Media phrases like "pause the movie", "stop playback", "next song" must use media_* tools, not system volume.
6. "play the song X" should use play_media_search with query X.
7. Never claim success before execution.
8. Use confirmation for destructive operations.
9. No shell commands.
10. Google => https://www.google.com. ChatGPT => https://chatgpt.com. Claude => https://claude.ai.
11. For commands like “open Google, search X, and open its Wikipedia page”, extract ONLY X as the Google query. Never include surrounding navigation or the Wikipedia phrase.
12. Factual, explanatory, comparison, definition, history, person, movie, product, science, or "what is X" questions should use web_research. Wikipedia is first priority, but if it has no useful result, continue with other accessible web sources. Never answer “not on Wikipedia” as the final answer when the web can provide information.
13. If the user asks to continue a Wikipedia article, use wikipedia_more. Otherwise web_research may answer normally.
14. For live news requests, use get_news and preserve the user language.
15. For mathematics, use calculate rather than opening a website.
16. Treat the user utterance semantically. Do NOT require exact trigger words or example sentences. Identify the intended action and its target from the whole sentence.
17. If the user asks for research/investigation/checking/finding/learning about something, extract the subject from the sentence regardless of where the action phrase appears, then use web_research.
18. If the user asks a normal conversational or knowledge question that needs no Windows action, provide a useful answer in reply instead of asking for a site/app name.
19. Do not return the generic “I need a more specific target” response unless the utterance is genuinely impossible to interpret even after semantic analysis.
20. For a direct web search request, use open_chrome_url with a search URL.
21. Do not return an empty actions list for an actionable request just because the exact app/site name was not in the examples; use the closest available tool and explicit URL/search.
22. Multi-action commands MUST preserve every requested action and their order. Split naturally on connectors such as «و», «بعد», «بعدش», «سپس», «و بعد», "and", "then", "after that", commas or semicolons when they clearly separate actions.
23. Extract the semantic target from each action, not the whole sentence. For music, play_media_search query MUST contain only the artist/title/subject to search; never include words such as «بعد», «آهنگ», «پخش کن», "play", "song", "then", or navigation instructions.
24. Natural equivalents such as «برو», «باز کن», «بیار», «انجام بده», «بررسی کن», «پیدا کن», «ببین», «در موردش», «برام» and their English equivalents are intent cues, not required exact phrases.
'''


def _json(text: str) -> dict[str, Any] | None:
    try:
        x = json.loads(text)
        return x if isinstance(x, dict) else None
    except Exception:
        pass
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        return None
    try:
        x = json.loads(m.group(0))
        return x if isinstance(x, dict) else None
    except Exception:
        return None


def plan_with_ollama(user_text: str, language: str | None = None, context: str = "") -> dict[str, Any]:
    inst = ""
    if language == "fa":
        inst = "\nDETECTED LANGUAGE=Persian. reply MUST be Persian."
    elif language == "en":
        inst = "\nDETECTED LANGUAGE=English. reply MUST be English."
    context_block = f"\nRECENT LOCAL CONVERSATION CONTEXT:\n{context}\n" if context else ""
    payload = {
        "model": OLLAMA_MODEL,
        "stream": False,
        "format": "json",
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT + inst + context_block},
            {"role": "user", "content": user_text},
        ],
        "options": {"temperature": 0.1},
    }
    try:
        response = requests.post(f"{OLLAMA_URL}/api/chat", json=payload, timeout=AGENT_TIMEOUT)
        response.raise_for_status()
        parsed = _json(response.json().get("message", {}).get("content", ""))
        return {"ok": True, "plan": parsed, "provider": "ollama-local"} if parsed else {"ok": False, "error": "Invalid JSON", "provider": "ollama-local"}
    except Exception as exc:
        return {"ok": False, "error": str(exc), "provider": "ollama-local"}


def fallback_plan(user_text: str) -> dict[str, Any]:
    t = user_text.strip()
    low = t.lower()
    fa = any("\u0600" <= c <= "\u06ff" for c in t)
    # This fallback should still be useful when Ollama is offline. Keep it deterministic.
    from agent.fast_path import fast_plan
    fast = fast_plan(t, "fa" if fa else "en")
    if fast is not None:
        return fast
    # Last useful fallback: treat an otherwise-unclassified utterance as a
    # knowledge/research request instead of returning a dead-end canned reply.
    return {
        "ok": True,
        "plan": {
            "reply": "موضوع را بررسی می‌کنم." if fa else "I'll look into that.",
            "actions": [{"tool": "web_research", "args": {"query": t, "language": "fa" if fa else "en"}}],
            "needs_confirmation": False,
        },
        "provider": "fallback-web-research",
    }
