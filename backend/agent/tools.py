from __future__ import annotations

import os
import subprocess
import webbrowser
from pathlib import Path
from typing import Any
from urllib.parse import quote_plus

APP_ALIASES = {
    "chrome": "chrome.exe", "google chrome": "chrome.exe", "کروم": "chrome.exe", "گوگل کروم": "chrome.exe",
    "edge": "msedge.exe", "مایکروسافت اج": "msedge.exe", "اج": "msedge.exe",
    "firefox": "firefox.exe", "فایرفاکس": "firefox.exe", "brave": "brave.exe", "بریو": "brave.exe",
    "notepad": "notepad.exe", "نوت پد": "notepad.exe", "نوت‌پد": "notepad.exe", "calculator": "calc.exe", "ماشین حساب": "calc.exe",
    "explorer": "explorer.exe", "فایل اکسپلورر": "explorer.exe", "vlc": "vlc.exe", "وی ال سی": "vlc.exe",
    "spotify": "spotify.exe", "اسپاتیفای": "spotify.exe", "potplayer": "PotPlayerMini64.exe", "پات پلیر": "PotPlayerMini64.exe",
}


def tool_specs() -> list[dict[str, Any]]:
    return [
        {"name":"open_application","description":"Open a Windows application.","parameters":{"app":"string"}},
        {"name":"open_website","description":"Open a website in the default browser.","parameters":{"url":"string"}},
        {"name":"open_chrome_url","description":"Open a URL in Google Chrome whether Chrome is running or not.","parameters":{"url":"string"}},
        {"name":"open_wikipedia_page","description":"Open a Wikipedia article in Chrome.","parameters":{"query":"string","language":"string"}},
        {"name":"open_windows_settings","description":"Open Windows Settings.","parameters":{}},
        {"name":"windows_system_search","description":"Open Windows Search, optionally with a query.","parameters":{"query":"string"}},
        {"name":"close_application","description":"Close a running application by process/app name. Requires confirmation.","parameters":{"process":"string"}},
        {"name":"open_folder","description":"Open a Windows folder.","parameters":{"path":"string"}},
        {"name":"open_file","description":"Open a Windows file.","parameters":{"path":"string"}},
        {"name":"open_named","description":"Find and open a named file or folder in common user folders.","parameters":{"name":"string","kind":"string","root":"string"}},
        {"name":"system_info","description":"Read local system information.","parameters":{}},
        {"name":"system_volume_set","description":"Set Windows master volume to an absolute percentage.","parameters":{"percent":"number"}},
        {"name":"system_volume_change","description":"Change Windows master volume by percentage points.","parameters":{"delta":"number"}},
        {"name":"system_mute","description":"Mute/unmute Windows master audio.","parameters":{"enabled":"boolean"}},
        {"name":"media_play_pause","description":"Toggle play/pause for the active media player.","parameters":{}},
        {"name":"media_stop","description":"Stop active media playback.","parameters":{}},
        {"name":"media_next","description":"Next track.","parameters":{}},
        {"name":"media_previous","description":"Previous track.","parameters":{}},
        {"name":"player_volume_set","description":"Set active player's own volume. Never the system volume.","parameters":{"percent":"number"}},
        {"name":"player_volume_change","description":"Change active player's own volume.","parameters":{"delta":"number"}},
        {"name":"player_volume_max","description":"Set active player to maximum supported UI volume.","parameters":{}},
        {"name":"player_mute","description":"Mute/unmute active player's own audio session.","parameters":{"enabled":"boolean"}},
        {"name":"play_media_search","description":"Search online media and play the best result directly in VLC; do not search local folders or open a browser for normal playback.","parameters":{"query":"string"}},
        {"name":"active_player","description":"Identify active player.","parameters":{}},
        {"name":"create_folder","description":"Create a local folder.","parameters":{"path":"string"}},
        {"name":"create_file","description":"Create a local file.","parameters":{"path":"string","content":"string","open_after":"boolean"}},
        {"name":"delete_file","description":"Delete a local file or folder directly.","parameters":{"path":"string"}},
        {"name":"delete_named","description":"Find an exact named file/folder in common roots and delete it directly.","parameters":{"name":"string","root":"string"}},
        {"name":"shutdown_windows","description":"Shut down Windows. Requires confirmation.","parameters":{}},
        {"name":"restart_windows","description":"Restart Windows. Requires confirmation.","parameters":{}},
        {"name":"sleep_windows","description":"Put Windows to sleep. Requires confirmation.","parameters":{}},
        {"name":"cancel_shutdown","description":"Cancel pending shutdown/restart.","parameters":{}},
        {"name":"get_weather","description":"Get weather for a city.","parameters":{"city":"string","language":"string"}},
        {"name":"get_location_weather","description":"Get weather using Windows device location.","parameters":{"language":"string"}},
        {"name":"get_time_date","description":"Get exact local time/date.","parameters":{}},
        {"name":"get_news","description":"Get recent reputable news.","parameters":{"topic":"string","language":"string"}},
        {"name":"wikipedia_lookup","description":"Look up a Wikipedia article.","parameters":{"query":"string","language":"string"}},
        {"name":"wikipedia_answer","description":"Answer from Wikipedia without opening a browser.","parameters":{"query":"string","language":"string"}},
        {"name":"wikipedia_more","description":"Continue the pending Wikipedia article.","parameters":{"language":"string"}},
        {"name":"web_research","description":"Research a topic on the public web: Wikipedia first, then other accessible web sources, and return a synthesized answer.","parameters":{"query":"string","language":"string"}},
        {"name":"calculate","description":"Solve math safely.","parameters":{"expression":"string","language":"string"}},
        {"name":"set_windows_language","description":"Set an installed Windows user language.","parameters":{"language_name":"string","language":"string"}},
        {"name":"get_installed_languages","description":"List installed Windows user languages.","parameters":{}},
        {"name":"system_dashboard","description":"Get system and Smartis resource statistics.","parameters":{}},
        {"name":"hardware_temperatures","description":"Get CPU/RAM temperatures when hardware sensors expose them.","parameters":{}},
    ]


def _chrome_executable() -> str | None:
    candidates = [
        Path(os.environ.get("PROGRAMFILES", r"C:\Program Files")) / "Google/Chrome/Application/chrome.exe",
        Path(os.environ.get("PROGRAMFILES(X86)", r"C:\Program Files (x86)")) / "Google/Chrome/Application/chrome.exe",
        Path(os.environ.get("LOCALAPPDATA", "")) / "Google/Chrome/Application/chrome.exe",
    ]
    for p in candidates:
        try:
            if p.is_file(): return str(p)
        except OSError: pass
    return None


def _open_in_chrome(url: str) -> dict[str, Any]:
    url=str(url or "").strip()
    if not url:return {"ok":False,"error":"URL is empty."}
    if not url.startswith(("http://","https://")):url="https://"+url
    try:
        exe=_chrome_executable()
        if exe: subprocess.Popen([exe,url],shell=False)
        else:webbrowser.open(url)
        return {"ok":True,"message":f"Opened {url} in Chrome.","url":url,"speak":"باز شد."}
    except Exception as exc:return {"ok":False,"error":str(exc)}


def _open_wikipedia(query: str, language: str | None = None) -> dict[str, Any]:
    import requests
    query=str(query or "").strip(); lang="fa" if language=="fa" else "en"
    if not query:return {"ok":False,"error":"Wikipedia query is empty."}
    try:
        data=requests.get(f"https://{lang}.wikipedia.org/w/api.php",params={"action":"opensearch","search":query,"limit":1,"namespace":0,"format":"json"},timeout=4,headers={"User-Agent":"Smartis/2.0"}).json()
        title=data[1][0] if len(data)>1 and data[1] else None
        if not title and lang=="fa":
            data=requests.get("https://en.wikipedia.org/w/api.php",params={"action":"opensearch","search":query,"limit":1,"namespace":0,"format":"json"},timeout=4,headers={"User-Agent":"Smartis/2.0"}).json(); title=data[1][0] if len(data)>1 and data[1] else None; lang="en"
        if not title:return {"ok":False,"error":f"Wikipedia page not found for {query}."}
        url=f"https://{lang}.wikipedia.org/wiki/{quote_plus(title).replace('+','_')}"; result=_open_in_chrome(url); result.update({"title":title,"url":url})
        return result
    except Exception as exc:return {"ok":False,"error":str(exc)}


def _open_settings() -> dict[str,Any]:
    try:
        os.startfile("ms-settings:")
        return {"ok":True,"speak":"تنظیمات ویندوز باز شد."}
    except Exception as exc:return {"ok":False,"error":str(exc)}


def _windows_search(query:str|None) -> dict[str,Any]:
    q=str(query or "").strip()
    if os.name != "nt": return {"ok":False,"error":"Windows Search is only available on Windows."}
    try:
        # Win+S opens the real Windows Search UI. Clipboard paste supports Persian/Unicode.
        import time, ctypes
        VK_LWIN, VK_S, KEYEVENTF_KEYUP = 0x5B, 0x53, 0x0002
        user32=ctypes.windll.user32
        user32.keybd_event(VK_LWIN,0,0,0); user32.keybd_event(VK_S,0,0,0); user32.keybd_event(VK_S,0,KEYEVENTF_KEYUP,0); user32.keybd_event(VK_LWIN,0,KEYEVENTF_KEYUP,0)
        time.sleep(0.55)
        if q:
            # PowerShell receives Unicode over stdin, avoiding command-line encoding issues.
            subprocess.run(["powershell","-NoProfile","-Command","$q=[Console]::In.ReadToEnd(); Set-Clipboard -Value $q"], input=q, text=True, timeout=5, check=False)
            user32.keybd_event(0x11,0,0,0); user32.keybd_event(0x56,0,0,0); user32.keybd_event(0x56,0,KEYEVENTF_KEYUP,0); user32.keybd_event(0x11,0,KEYEVENTF_KEYUP,0)
        return {"ok":True,"speak":f"جست‌وجوی ویندوز برای «{q}» را باز کردم." if q else "جست‌وجوی ویندوز را باز کردم."}
    except Exception as exc:
        return {"ok":False,"error":str(exc)}


def _close_application(process: str) -> dict[str, Any]:
    """Politely terminate every process of a known application (confirmation-gated upstream)."""
    key = str(process or "").strip().lower()
    if not key:
        return {"ok": False, "error": "No application name was given."}
    exe = APP_ALIASES.get(key, key)
    exe_l = exe.lower() if exe.lower().endswith(".exe") else exe.lower() + ".exe"
    try:
        import psutil
        victims = [p for p in psutil.process_iter(["name"]) if str(p.info.get("name") or "").lower() == exe_l]
        if not victims:
            return {"ok": False, "error": f"{process} is not running."}
        for p in victims:
            try: p.terminate()
            except Exception: pass
        gone, alive = psutil.wait_procs(victims, timeout=3)
        for p in alive:
            try: p.kill()
            except Exception: pass
        return {"ok": True, "closed": len(victims), "speak": f"{process} بسته شد."}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def execute_tool(name: str, args: dict[str, Any]) -> dict[str, Any]:
    if name=="open_application":
        app=str(args.get("app","")).strip().lower(); exe=APP_ALIASES.get(app,app)
        try: subprocess.Popen([exe],shell=False); return {"ok":True,"speak":"باز شد."}
        except Exception as exc:return {"ok":False,"error":str(exc)}
    if name=="open_website":
        url=str(args.get("url","")).strip();
        if not url.startswith(("http://","https://")):url="https://"+url
        try:webbrowser.open(url); return {"ok":True,"speak":"باز شد."}
        except Exception as exc:return {"ok":False,"error":str(exc)}
    if name=="open_chrome_url": return _open_in_chrome(str(args.get("url","")))
    if name=="open_wikipedia_page": return _open_wikipedia(str(args.get("query","")),args.get("language"))
    if name=="close_application": return _close_application(str(args.get("process") or args.get("app") or ""))
    if name=="open_windows_settings": return _open_settings()
    if name=="windows_system_search": return _windows_search(args.get("query"))
    if name=="open_named":
        from agent import system_tools
        return system_tools.open_named(str(args.get("name","")), args.get("root"), args.get("kind"))
    if name in {"open_folder","open_file"}:
        from agent.system_tools import resolve_user_path
        path=resolve_user_path(str(args.get("path","")))
        if name=="open_folder" and not path.is_dir():return {"ok":False,"error":f"Folder not found: {path}"}
        if name=="open_file" and not path.is_file():return {"ok":False,"error":f"File not found: {path}"}
        try:os.startfile(str(path)); return {"ok":True,"speak":"باز شد."}
        except Exception as exc:return {"ok":False,"error":str(exc)}
    if name=="system_info":
        import psutil
        return {"ok":True,"cpu_percent":psutil.cpu_percent(interval=.05),"memory_percent":psutil.virtual_memory().percent,"computer":os.environ.get("COMPUTERNAME","")}
    if name in {"system_volume_set","system_volume_change","system_mute","media_play_pause","media_stop","media_next","media_previous","player_volume_set","player_volume_change","player_volume_max","player_mute","active_player","play_media_search"}:
        from services import media_control
        mapping={
            "system_volume_set":lambda:media_control.system_volume_set(float(args.get("percent",0))),
            "system_volume_change":lambda:media_control.system_volume_change(float(args.get("delta",0))),
            "system_mute":lambda:media_control.system_mute(bool(args.get("enabled",True))),
            "media_play_pause":media_control.media_play_pause,"media_stop":media_control.media_stop,"media_next":media_control.media_next,"media_previous":media_control.media_previous,
            "player_volume_set":lambda:media_control.player_volume_set(float(args.get("percent",0))),"player_volume_change":lambda:media_control.player_volume_change(float(args.get("delta",0))),"player_volume_max":media_control.player_volume_max,"player_mute":lambda:media_control.player_mute(bool(args.get("enabled",True))),"active_player":media_control.active_player,"play_media_search":lambda:media_control.play_online_media(str(args.get("query",""))),
        }
        try:return mapping[name]()
        except Exception as exc:return {"ok":False,"error":str(exc)}
    if name in {"create_folder","create_file","delete_file","delete_named","shutdown_windows","restart_windows","sleep_windows","cancel_shutdown","get_weather","get_location_weather","get_time_date","get_news","wikipedia_lookup","wikipedia_answer","wikipedia_more","web_research","calculate","set_windows_language","get_installed_languages","system_dashboard","hardware_temperatures"}:
        from agent import system_tools
        if name=="create_folder":return system_tools.create_folder(str(args.get("path","")))
        if name=="create_file":return system_tools.create_file(str(args.get("path","")),str(args.get("content","")),bool(args.get("open_after",False)))
        if name=="delete_file":return system_tools.delete_file(str(args.get("path","")))
        if name=="delete_named":return system_tools.delete_named(str(args.get("name","")),args.get("root"))
        if name=="shutdown_windows":return system_tools.shutdown_windows()
        if name=="restart_windows":return system_tools.restart_windows()
        if name=="sleep_windows":return system_tools.sleep_windows()
        if name=="cancel_shutdown":return system_tools.cancel_shutdown()
        if name=="get_weather":return system_tools.get_weather(str(args.get("city","")),args.get("language"))
        if name=="get_location_weather":return system_tools.get_location_weather(args.get("language"))
        if name=="get_time_date":return system_tools.get_time_date(args.get("language"))
        if name=="get_news":return system_tools.get_news(args.get("topic"),args.get("language"))
        if name=="wikipedia_lookup":return system_tools.wikipedia_lookup(str(args.get("query","")),args.get("language"))
        if name=="wikipedia_answer":return system_tools.wikipedia_answer(str(args.get("query","")),args.get("language"))
        if name=="wikipedia_more":return system_tools.wikipedia_more(args.get("language"))
        if name=="web_research":
            from services.research_service import research
            return research(str(args.get("query","")), args.get("language"))
        if name=="calculate":return system_tools.calculate(str(args.get("expression","")),args.get("language"))
        if name=="set_windows_language":return system_tools.set_windows_language(str(args.get("language_name","")),args.get("language"))
        if name=="get_installed_languages":return {"ok":True,"languages":system_tools.get_installed_languages(),"speak":", ".join(system_tools.get_installed_languages())}
        if name=="system_dashboard":return system_tools.get_dashboard()
        if name=="hardware_temperatures":return system_tools.get_hardware_temperatures()
    return {"ok":False,"error":f"Unknown tool: {name}"}
