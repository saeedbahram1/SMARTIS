from __future__ import annotations

import json
import re
from typing import Any

from agent import llm
from config import AGENT_TIMEOUT
from agent.ollama_model import ensure_ollama, resolve_model

SYSTEM_PROMPT = r'''
You are the planning brain of a Windows voice assistant called Smartis.
The user may speak Persian or English. Smartis is always listening for commands; there is no wake-word gate. The word "Smartis" is optional and may appear at the beginning of a command. Never require it.
Convert natural language into a small sequence of tool calls.

Available tools:
- open_application(app)
- open_website(url)
- open_chrome_url(url): open the URL in Google Chrome whether it is already running or not.
- open_wikipedia_page(query, language): find and open the best Wikipedia article in Chrome.
- create_project(base, folder, file, ext, open_after, language): create a folder, create a file inside it and optionally open it, as ONE dependent chain. base is desktop/downloads/documents/C:/ or a folder name; ext is a plain extension like py, txt, js.
- search_open_read(query, language): search Google for a topic, open the first result in Chrome and read its content aloud. Use for «جستجو کن X و بعد اولین سایت رو باز کن و بخونش».
- open_chatgpt_chat(language): open ChatGPT in a new chat in Chrome and ask the user what to write.
- type_text(text, language): type the given text into the focused ChatGPT window and send it. Use ONLY when the previous reply asked «چی بنویسم براش؟» and the user's utterance is the text to write.
- write_code(spec, base, zip, language): write a program/script/game/website in any requested language from the user's description, save the files as a project folder (base = desktop/downloads/documents or a known folder) and optionally pack them into a ZIP for delivery. Use for «یک برنامه بنویس»، «کد بزن»، «بازی بساز»، "write a script/game".
- open_folder(path)
- open_file(path)
- open_named(name, kind, root): find and open a named file or folder in common user folders.
- open_windows_settings(): open Windows Settings.
- windows_system_search(query): open Windows Search and optionally type a query.
- system_info()
- close_application(process) [requires confirmation]
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
8. Destructive operations (delete, shutdown, restart, sleep, close_application) are confirmation-gated by the executor; still emit the real action, do not ask the question yourself.
9. No shell commands.
10. Google => https://www.google.com. ChatGPT => https://chatgpt.com. Claude => https://claude.ai.
11. For commands like “open Google, search X, and open its Wikipedia page”, extract ONLY X as the Google query. Never include surrounding navigation or the Wikipedia phrase.
12. You are ONLY called for utterances that look like Windows/tool commands. Plain knowledge or chat questions are answered by a separate chat model, so NEVER turn them into web_research. Use web_research only when the user explicitly asks to research / investigate / look up / search the web about a subject.
13. If the user asks to continue a Wikipedia article, use wikipedia_more. Otherwise web_research may answer normally.
14. For live news requests, use get_news and preserve the user language.
15. For mathematics, use calculate rather than opening a website.
16. Treat the user utterance semantically. Do NOT require exact trigger words or example sentences. Identify the intended action and its target from the whole sentence.
17. If the user asks for research/investigation/checking/finding/learning about something, extract the subject from the sentence regardless of where the action phrase appears, then use web_research.
18. If the utterance is NOT an actionable command (just conversation or a question), return {"reply":"","actions":[],"needs_confirmation":false}. Never invent an action and never answer the question yourself.
19. Do not return the generic “I need a more specific target” response unless the utterance is genuinely impossible to interpret even after semantic analysis.
20. For a direct web search request, use open_chrome_url with a search URL.
21. Do not return an empty actions list for an actionable request just because the exact app/site name was not in the examples; use the closest available tool and explicit URL/search.
22. Multi-action commands MUST preserve every requested action and their order. Split naturally on connectors such as «و», «بعد», «بعدش», «سپس», «و بعد», "and", "then", "after that", commas or semicolons when they clearly separate actions.
23. Extract the semantic target from each action, not the whole sentence. For music, play_media_search query MUST contain only the artist/title/subject to search; never include words such as «بعد», «آهنگ», «پخش کن», "play", "song", "then", or navigation instructions.
24. Natural equivalents such as «برو», «باز کن», «بیار», «انجام بده», «بررسی کن», «پیدا کن», «ببین», «در موردش», «برام» and their English equivalents are intent cues, not required exact phrases.
25. When the user asks to create a folder AND a file inside it (and maybe open it) as one sentence, use create_project — never separate create_folder+create_file actions, because execute the file needs the folder path. «با پسوند پایتونی» means ext=py; map other extension words to their plain extension (متنی=>txt, ورد=>docx, اکسل=>xlsx, پی دی اف=>pdf).
26. When the user asks to search something AND open/read the first result, use search_open_read with ONLY the search subject as query — never include «بعد», «اولین سایت رو باز کن», «بخونش» or other navigation words in the query.
27. When the user asks to open ChatGPT and start a new chat to write something: if they already said what to write, use open_chatgpt_chat first; the follow-up question «چی بنویسم براش؟» is answered by the next user utterance, which must then be typed exactly with type_text — even short replies like «سلام» are the text to write, NOT chat.
28. Destructive gating applies only to delete/shutdown/restart/sleep/close. create_project, search_open_read, open_chatgpt_chat and type_text do not need confirmation.
29. When the user asks YOU (Smartis) to write code — «برنامه/اسکریپت/بازی/سایت/کد بنویس»، «کد بزن»، "write a program/script/game" — use write_code with spec = the user's complete description including the language and every detail. Set zip=true ONLY if the user explicitly asked for a ZIP file («زیپش کن»، "as a zip"); otherwise zip=false. Never paste the generated code into the chat reply; the code-writing step produces and delivers the files.
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
    """Command planner (JSON). Uses the shared LLM gateway: same num_ctx and
    keep_alive as chat, so planning never forces the model to reload."""
    inst = ""
    if language == "fa":
        inst = "\nDETECTED LANGUAGE=Persian. reply MUST be Persian."
    elif language == "en":
        inst = "\nDETECTED LANGUAGE=English. reply MUST be English."
    # The planner prompt is ~1.3k tokens; keep the context tiny so the system
    # prompt is never pushed out of the shared 2048-token window.
    context = str(context or "").strip()[-450:]
    context_block = f"\nRECENT LOCAL CONVERSATION CONTEXT:\n{context}\n" if context else ""
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT + inst + context_block},
        {"role": "user", "content": user_text},
    ]
    try:
        ensure_ollama()
        result = llm.generate(
            resolve_model(),
            messages,
            num_predict=260,
            temperature=0.05,
            think=False,
            json_mode=True,
            total_timeout=AGENT_TIMEOUT,
            first_token_timeout=AGENT_TIMEOUT,
            label="planner",
        )
        if not result.ok:
            return {"ok": False, "error": result.error or "planner failed", "provider": "ollama-local"}
        parsed = _json(result.text)
        return {"ok": True, "plan": parsed, "provider": "ollama-local"} if parsed else {"ok": False, "error": "Invalid JSON", "provider": "ollama-local"}
    except Exception as exc:  # noqa: BLE001
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
    # Never turn an unrecognised command into a Google/web search. Search is
    # only selected by an explicit search/research/knowledge intent in fast_path.
    return {
        "ok": True,
        "plan": {
            "reply": "این درخواست را دقیق‌تر بررسی می‌کنم." if fa else "I need a little more context for that request.",
            "actions": [],
            "needs_confirmation": False,
        },
        "provider": "fallback-local",
    }
