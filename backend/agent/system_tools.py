from __future__ import annotations

import ast
import json
import math
import operator
import os
import re
import shutil
import subprocess
import time
import zipfile
from pathlib import Path
from typing import Any
from urllib.parse import quote

import requests

from services.location_weather import LocationWeatherService

_LOCATION_WEATHER = LocationWeatherService()
_PENDING_WIKIPEDIA: dict[str, Any] | None = None
_PENDING_FOLDER: dict[str, Any] | None = None
_PENDING_FILE: dict[str, Any] | None = None
_PENDING_PROMPT: dict[str, Any] | None = None
_PENDING_PROMPT_AT: float = 0.0
_PENDING_PROMPT_TTL: float = 180.0


def _fa(language: str | None) -> bool:
    return language != "en"


def _special_roots() -> dict[str, Path]:
    home = Path.home()
    desktop = Path(os.environ.get("USERPROFILE", str(home))) / "Desktop"
    downloads = home / "Downloads"
    documents = home / "Documents"
    return {"desktop": desktop, "دسکتاپ": desktop, "downloads": downloads, "download": downloads, "دانلود": downloads, "دانلودها": downloads, "documents": documents, "document": documents, "اسناد": documents, "سی": Path("C:/"), "c": Path("C:/")}


def resolve_user_path(path: str) -> Path:
    raw = str(path or "").strip().strip('"')
    low = raw.lower().replace("\\", "/")
    for alias, root in _special_roots().items():
        if low == alias or low.startswith(alias + "/"):
            rest = raw[len(alias):].lstrip("\\/")
            return root / rest
    expanded = os.path.expandvars(os.path.expanduser(raw))
    return Path(expanded)


def _search_named_path(root: Path, name: str, want_dir: bool | None = None, max_depth: int = 5) -> Path | None:
    target = str(name or "").strip().strip('"').lower()
    if not target or not root.exists(): return None
    try:
        base_depth = len(root.parts)
        for current, dirs, files in os.walk(root):
            p = Path(current)
            if len(p.parts) - base_depth > max_depth:
                dirs[:] = []
                continue
            dirs[:] = [d for d in dirs if d not in {"$Recycle.Bin", "System Volume Information", "Windows", "Program Files", "Program Files (x86)", "AppData"}]
            if want_dir is not False:
                for d in dirs:
                    if d.lower() == target:
                        return p / d
            if want_dir is not True:
                for f in files:
                    if f.lower() == target:
                        return p / f
    except (PermissionError, OSError):
        return None
    return None



def open_named(name: str, root: str | None = None, kind: str | None = None) -> dict[str, Any]:
    target_name = str(name or "").strip().strip('"')
    if not target_name:
        return {"ok": False, "error": "نام فایل یا پوشه مشخص نیست."}
    roots: list[Path] = []
    if root:
        base = resolve_user_path(root)
        if base.exists(): roots.append(base)
    if not roots:
        roots = [_special_roots()["desktop"], _special_roots()["downloads"], _special_roots()["documents"]]
    want_dir = True if kind == "folder" else False if kind == "file" else None
    found = None
    for base in roots:
        found = _search_named_path(base, target_name, want_dir, 6)
        if found: break
    if not found:
        # Also allow a direct path.
        direct = resolve_user_path(target_name)
        if direct.exists(): found = direct
    if not found:
        return {"ok": False, "error": f"«{target_name}» پیدا نشد."}
    try:
        os.startfile(str(found))
        return {"ok": True, "path": str(found), "speak": "باز شد."}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}

def create_folder(path: str) -> dict[str, Any]:
    target = resolve_user_path(path)
    try:
        if target.exists(): return {"ok": False, "error": f"پوشه از قبل وجود دارد: {target}"}
        target.mkdir(parents=True, exist_ok=False)
        return {"ok": True, "message": f"پوشه ساخته شد: {target}", "path": str(target), "speak": "پوشه ساخته شد."}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def create_file(path: str, content: str = "", open_after: bool = False) -> dict[str, Any]:
    target = resolve_user_path(path)
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists(): return {"ok": False, "error": f"فایل از قبل وجود دارد: {target}"}
        target.write_text(content, encoding="utf-8")
        if open_after:
            try: os.startfile(str(target))
            except Exception: pass
        return {"ok": True, "message": f"Created {target}.", "path": str(target), "speak": "فایل ساخته شد."}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


_EXT_WORDS: dict[str, str] = {
    "پایتونی": "py", "پایتون": "py", "python": "py", "پای": "py",
    "متنی": "txt", "متن": "txt", "text": "txt", "txt": "txt",
    "جاوااسکریپت": "js", "جاواسکریپت": "js", "javascript": "js", "js": "js",
    "ورد": "docx", "word": "docx", "docx": "docx",
    "اکسل": "xlsx", "excel": "xlsx", "xlsx": "xlsx",
    "پی دی اف": "pdf", "pdf": "pdf",
    "سی اس اس": "css", "css": "css",
    "اچ تی ام ال": "html", "html": "html",
    "جیسون": "json", "json": "json",
    "مارک داون": "md", "markdown": "md", "md": "md",
    "بچ": "bat", "bat": "bat", "کامند": "cmd", "cmd": "cmd",
    "سی شارپ": "cs", "csharp": "cs", "c#": "cs",
    "سی پلاس پلاس": "cpp", "cpp": "cpp",
    "جاوا": "java", "java": "java",
}


def resolve_extension(word: str) -> str:
    """«پایتونی» -> «py», «پی دی اف» -> «pdf», «py» -> «py»."""
    value = re.sub(r"\s+", " ", str(word or "")).strip().strip(".،,؛;:").lower()
    if not value:
        return ""
    if value in _EXT_WORDS:
        return _EXT_WORDS[value]
    # An already-latin extension can be used verbatim (max 8 chars, letters/digits).
    if re.fullmatch(r"[a-z0-9]{1,8}", value):
        return value
    return ""


def create_project(base: str, folder: str = "", file: str = "", ext: str = "", content: str = "", open_after: bool = False, language: str | None = None) -> dict[str, Any]:
    """Composite of the user's sentence: make a folder, a file inside it, open the file.

    Steps are executed here (not by the executor) because later steps depend on
    earlier results (the file lives inside the folder), which the static planner
    cannot express. Existing folder/file are reused instead of being an error.
    """
    fa = _fa(language)
    base_path = resolve_user_path(base or "desktop")
    folder_name = str(folder or "").strip().strip('"\'')
    file_name = str(file or "").strip().strip('"\'')
    ext_clean = re.sub(r"[^a-zA-Z0-9]", "", str(ext or "").replace(".", ""))
    if not folder_name:
        return {"ok": False, "error": "نام پوشه مشخص نیست." if fa else "The folder name is missing."}
    folder_path = base_path / folder_name
    try:
        folder_created = False
        if folder_path.exists():
            if not folder_path.is_dir():
                return {"ok": False, "error": f"یک فایل هم‌نام با پوشه وجود دارد: {folder_path}" if fa else f"A file already exists with the folder name: {folder_path}"}
        else:
            folder_path.mkdir(parents=True, exist_ok=False)
            folder_created = True
        file_path: Path | None = None
        file_created = False
        if file_name:
            if ext_clean and "." not in file_name:
                file_name = f"{file_name}.{ext_clean}"
            file_path = folder_path / file_name
            if not file_path.exists():
                file_path.write_text(content or ("# Created by Smartis" if ext_clean == "py" else ""), encoding="utf-8")
                file_created = True
        opened = False
        if open_after and file_path and file_path.exists():
            try:
                os.startfile(str(file_path))
                opened = True
            except Exception:
                opened = False
        parts_fa = []
        parts_fa.append(f"پوشه «{folder_name}» {'ساخته شد' if folder_created else 'از قبل بود'}")
        if file_name:
            parts_fa.append(f"فایل «{file_name}» {'ساخته شد' if file_created else 'از قبل بود'}")
        if open_after and opened:
            parts_fa.append("و بازش کردم")
        speak_fa = "، ".join(parts_fa) + "."
        talk_en = []
        talk_en.append(f"Folder '{folder_name}' {'created' if folder_created else 'already existed'}")
        if file_name:
            talk_en.append(f"file '{file_name}' {'created' if file_created else 'already existed'}")
        if open_after and opened:
            talk_en.append("opened")
        return {
            "ok": True,
            "message": " ".join(talk_en) + ".",
            "speak": speak_fa if fa else " ".join(talk_en) + ".",
            "folder_path": str(folder_path),
            "file_path": str(file_path) if file_path else None,
            "folder_created": folder_created,
            "file_created": file_created,
            "opened": opened,
        }
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


# Code writing and ZIP delivery ---------------------------------------------

_CODE_SYSTEM_FA = """تو یک برنامه‌نویس حرفه‌ای هستی که برای دستیار Smartis کد می‌نویسد.
فقط و فقط یک شیء JSON برگردان با این ساختار:
{"name": "project_folder_name_in_snake_case", "files": [{"path": "main.py", "content": "کد کامل"}], "note": "یک جملهٔ فارسی کوتاه دربارهٔ کاری که کد انجام می‌دهد"}
قواعد:
- کد کامل، قابل اجرا و بدون جای خالی (بدون TODO و ...) بنویس؛ درخواست کاربر را دقیق پیاده کن.
- حداقل یک فایل و حداکثر ۴ فایل. فایل اصلی را main با پسوند زبان درخواستی بگذار.
- کد و نام فایل‌ها انگلیسی؛ فقط مقدار note فارسی باشد.
- هیچ متن اضافه‌ای بیرون از JSON ننویس."""

_CODE_SYSTEM_EN = """You are a professional programmer writing code for the Smartis assistant.
Return ONLY one JSON object:
{"name": "project_folder_name_in_snake_case", "files": [{"path": "main.py", "content": "full code"}], "note": "one short sentence about what the code does"}
Rules:
- Complete, runnable code. No TODOs or placeholders; implement exactly what the user asked.
- At least one file, at most 4. Name the main file main with the requested language extension.
- Keep explanations inside the JSON only."""


def _generate_code_project(spec: str, language: str | None = None) -> dict[str, Any] | None:
    """Ask the local model for the project files. Separated so tests can stub it."""
    from agent.llm import generate
    from agent.ollama_model import resolve_model
    from config import CODE_MAX_TOKENS, CODE_TIMEOUT

    result = generate(
        resolve_model(),
        [
            {"role": "system", "content": _CODE_SYSTEM_FA if _fa(language) else _CODE_SYSTEM_EN},
            {"role": "user", "content": str(spec or "").strip()},
        ],
        num_predict=CODE_MAX_TOKENS,
        temperature=0.25,
        json_mode=True,
        total_timeout=CODE_TIMEOUT,
        label="codegen",
    )
    if not result.ok:
        return None
    try:
        data = json.loads(result.text)
    except ValueError:
        return None
    return data if isinstance(data, dict) else None


def _safe_file_name(name: str) -> str:
    """Keep only the basename so a generated path can never escape the folder."""
    base = Path(str(name or "").replace("\\", "/")).name
    base = re.sub(r"[^A-Za-z0-9_.\-]", "_", base).strip("._")
    return base[:80]


def _safe_folder_name(name: str) -> str:
    value = re.sub(r"[^A-Za-z0-9_\-]", "_", str(name or "").strip()).strip("_")
    return value[:60] or "smartis_project"


def _strip_stray_braces(content: str) -> str:
    """Drop trailing '}' the model sometimes appends inside the JSON string.

    In json_mode a small model occasionally closes its answer with an extra
    brace that lands inside the file content (main()\\n}); unbalanced trailing
    closing braces are that artifact, balanced ones (dict/JS literals) stay.
    """
    text = content.rstrip()
    while text.endswith("}") and text.count("}") > text.count("{"):
        text = text[:-1].rstrip()
    return text


def write_code_project(spec: str, base: str = "desktop", want_zip: bool = False, open_after: bool = True, language: str | None = None) -> dict[str, Any]:
    """Write the requested code as a project folder and deliver it (optionally as ZIP).

    The model answers with JSON {name, files[], note}; file paths are reduced to
    safe basenames and a fresh folder name is picked when one already exists so
    an existing project of the user is never overwritten.
    """
    fa = _fa(language)
    from agent.logbus import logbus

    logbus.emit("CODEGEN", f"Generating code ({'zip' if want_zip else 'folder'}):", str(spec or "")[:200])
    data = _generate_code_project(spec, language)
    if not data:
        return {"ok": False, "error": "تولید کد ناموفق بود؛ دوباره امتحان کن." if fa else "Code generation failed; please try again."}

    files: dict[str, str] = {}
    for item in (data.get("files") or [])[:8]:
        if not isinstance(item, dict):
            continue
        clean = _safe_file_name(item.get("path") or item.get("name") or "")
        content = _strip_stray_braces(str(item.get("content") or ""))
        if clean and content and len(content) <= 200_000:
            files[clean] = content
    if not files:
        return {"ok": False, "error": "مدل کد معتبری برنگرداند؛ دوباره امتحان کن." if fa else "The model returned no usable files; please try again."}

    base_path = resolve_user_path(base or "desktop")
    folder_root = _safe_folder_name(data.get("name"))
    folder_path = base_path / folder_root
    counter = 2
    while folder_path.exists():
        folder_path = base_path / f"{folder_root}_{counter}"
        counter += 1
    try:
        folder_path.mkdir(parents=True, exist_ok=False)
        for fname, content in files.items():
            (folder_path / fname).write_text(content, encoding="utf-8")
        zip_path: Path | None = None
        if want_zip:
            zip_path = base_path / f"{folder_path.name}.zip"
            with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
                for fname in files:
                    zf.write(folder_path / fname, arcname=f"{folder_path.name}/{fname}")
        opened = False
        if open_after:
            try:
                if zip_path is not None:
                    subprocess.Popen(f'explorer /select,"{zip_path}"')
                else:
                    os.startfile(str(folder_path))
                opened = True
            except Exception:
                opened = False
    except Exception as exc:
        return {"ok": False, "error": str(exc)}

    count = len(files)
    note = str(data.get("note") or "").strip()
    if fa:
        speak = f"کد را نوشتم؛ {count} فایل در پوشهٔ «{folder_path.name}» ساخته شد."
        if zip_path is not None:
            speak += f" فایل زیپ «{zip_path.name}» هم کنار آن تحویل داده شد."
    else:
        speak = f"Done; {count} files were written to the folder '{folder_path.name}'."
        if zip_path is not None:
            speak += f" The ZIP file '{zip_path.name}' was delivered next to it."
    logbus.emit("CODEGEN", f"Wrote {count} files to {folder_path}" + (f" + {zip_path.name}" if zip_path else ""), note)
    return {
        "ok": True,
        "message": f"Wrote {count} files to {folder_path}" + (f" and packed {zip_path}" if zip_path else ""),
        "speak": speak,
        "note": note,
        "folder_path": str(folder_path),
        "zip_path": str(zip_path) if zip_path else None,
        "files": sorted(files.keys()),
        "opened": opened,
    }


# Chat-window typing --------------------------------------------------------

_CHAT_WINDOW_HINTS = ("chatgpt", "chat gpt", "chat\u200cجی\u200cپی\u200cتی", "چت جی پی تی", "openai")


def _chat_window_hint() -> int | None:
    """Find a visible ChatGPT-like top-level window and return its hwnd."""
    if os.name != "nt":
        return None
    try:
        import ctypes
        from ctypes import wintypes
        user32 = ctypes.windll.user32
        found: list[int] = []

        @ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)
        def _enum(hwnd, _lparam):
            try:
                if not user32.IsWindowVisible(hwnd):
                    return True
                length = user32.GetWindowTextLengthW(hwnd)
                if length <= 0:
                    return True
                buf = ctypes.create_unicode_buffer(length + 1)
                user32.GetWindowTextW(hwnd, buf, length + 1)
                title = (buf.value or "").lower()
                if any(hint in title for hint in _CHAT_WINDOW_HINTS):
                    found.append(int(hwnd))
                    return False
            except Exception:
                pass
            return True

        user32.EnumWindows(_enum, 0)
        return found[0] if found else None
    except Exception:
        return None


def _focus_window(hwnd: int) -> bool:
    """Best-effort foreground switch; returns True only when it actually worked."""
    if os.name != "nt" or not hwnd:
        return False
    try:
        import ctypes
        user32 = ctypes.windll.user32
        kernel32 = ctypes.windll.kernel32
        user32.ShowWindow(hwnd, 9)  # SW_RESTORE
        try:
            fg = user32.GetForegroundWindow()
            fg_thread = user32.GetWindowThreadProcessId(fg, None)
            my_thread = kernel32.GetCurrentThreadId()
            if fg_thread != my_thread:
                user32.AttachThreadInput(my_thread, fg_thread, True)
                user32.SetForegroundWindow(hwnd)
                user32.AttachThreadInput(my_thread, fg_thread, False)
            else:
                user32.SetForegroundWindow(hwnd)
        except Exception:
            try:
                user32.SetForegroundWindow(hwnd)
            except Exception:
                return False
        time.sleep(0.15)
        return int(user32.GetForegroundWindow() or 0) == int(hwnd)
    except Exception:
        return False


def _paste_clipboard() -> bool:
    """Ctrl+V then Enter via keybd_event, sent only when the target is focused."""
    if os.name != "nt":
        return False
    try:
        import ctypes
        user32 = ctypes.windll.user32
        VK_CONTROL, VK_V, VK_RETURN, KEYUP = 0x11, 0x56, 0x0D, 0x0002
        user32.keybd_event(VK_CONTROL, 0, 0, 0)
        user32.keybd_event(VK_V, 0, 0, 0)
        user32.keybd_event(VK_V, 0, KEYUP, 0)
        user32.keybd_event(VK_CONTROL, 0, KEYUP, 0)
        time.sleep(0.25)
        user32.keybd_event(VK_RETURN, 0, 0, 0)
        user32.keybd_event(VK_RETURN, 0, KEYUP, 0)
        return True
    except Exception:
        return False


def _set_clipboard(text: str) -> bool:
    try:
        script = "$q=[Console]::In.ReadToEnd(); Set-Clipboard -Value $q"
        proc = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", script], input=text.encode("utf-8"), capture_output=True, timeout=8)
        return proc.returncode == 0
    except Exception:
        return False


def type_text(text: str, language: str | None = None) -> dict[str, Any]:
    """Paste text into the focused chat window, or hand it to the clipboard.

    Keystrokes are only sent after verifying the ChatGPT window really is the
    foreground window; otherwise the text stays on the clipboard so it can
    never leak into an unrelated app the user is using.
    """
    fa = _fa(language)
    body = str(text or "").strip()
    if not body:
        return {"ok": False, "error": "متنی برای نوشتن مشخص نیست." if fa else "There is no text to type."}
    copied = _set_clipboard(body)
    if not copied:
        return {"ok": False, "error": "نتونستم متن را در کلیپ‌بورد بذارم." if fa else "I couldn't put the text on the clipboard."}
    hwnd = _chat_window_hint()
    if hwnd and _focus_window(hwnd):
        _paste_clipboard()
        speak = "نوشتم و فرستادم." if fa else "Typed and sent."
        return {"ok": True, "method": "paste", "speak": speak}
    speak = ("متن را کپی کردم؛ پنجرهٔ چت را باز کن و Ctrl+V و اینتر بزن." if fa else "I copied the text; open the chat window and press Ctrl+V then Enter.")
    return {"ok": True, "method": "clipboard", "speak": speak}


def open_chatgpt_chat(language: str | None = None) -> dict[str, Any]:
    """Open a fresh ChatGPT chat tab and ask what to write."""
    fa = _fa(language)
    try:
        from agent.tools import _open_in_chrome

        result = _open_in_chrome("https://chatgpt.com/?new")
        if not (result or {}).get("ok"):
            return {"ok": False, "error": f"نتونستم چت جی پی تی را باز کنم: {(result or {}).get('error', '')}" if fa else f"I couldn't open ChatGPT: {(result or {}).get('error', '')}"}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}
    set_pending_prompt("chatgpt")
    speak = "چت جی پی تی را باز کردم. چی بنویسم براش؟" if fa else "ChatGPT is open. What should I write for it?"
    return {"ok": True, "message": speak, "speak": speak, "await_prompt": True}


def delete_file(path: str) -> dict[str, Any]:
    target = resolve_user_path(path)
    try:
        if target.is_dir(): shutil.rmtree(target)
        elif target.exists(): target.unlink()
        else: return {"ok": False, "error": f"پیدا نشد: {target}"}
        return {"ok": True, "message": f"Deleted {target}.", "path": str(target), "speak": "حذف شد."}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def delete_named(name: str, root: str | None = None) -> dict[str, Any]:
    roots = []
    if root:
        base = resolve_user_path(root)
        if base.exists(): roots.append(base)
    if not roots:
        roots = [Path("C:/"), _special_roots()["downloads"], _special_roots()["desktop"]]
    for base in roots:
        found = _search_named_path(base, name, None, 5)
        if found:
            return delete_file(str(found)) | {"found": str(found)}
    return {"ok": False, "error": f"فایل یا پوشه «{name}» پیدا نشد."}


def set_pending_folder(base_path: str) -> None:
    global _PENDING_FOLDER
    _PENDING_FOLDER = {"base": str(resolve_user_path(base_path))}


def take_pending_folder() -> dict[str, Any] | None:
    global _PENDING_FOLDER
    result = dict(_PENDING_FOLDER) if _PENDING_FOLDER else None
    _PENDING_FOLDER = None
    return result


def has_pending_folder() -> bool:
    return _PENDING_FOLDER is not None

def set_pending_file(base: str = "desktop") -> None:
    global _PENDING_FILE
    _PENDING_FILE = {"base": base or "desktop"}

def take_pending_file() -> dict[str, Any] | None:
    global _PENDING_FILE
    value = _PENDING_FILE
    _PENDING_FILE = None
    return value

def has_pending_file() -> bool:
    return _PENDING_FILE is not None


def set_pending_prompt(kind: str = "chatgpt") -> None:
    """Queue the «چی بنویسم براش؟» question when Smartis opens a chat box.

    The very next utterance is treated as message text (typed into the open
    window) instead of being routed as a normal command. A TTL keeps a stale
    prompt from swallowing an unrelated later request.
    """
    global _PENDING_PROMPT, _PENDING_PROMPT_AT
    _PENDING_PROMPT = {"kind": str(kind or "chatgpt")}
    _PENDING_PROMPT_AT = time.monotonic()


def take_pending_prompt() -> dict[str, Any] | None:
    global _PENDING_PROMPT, _PENDING_PROMPT_AT
    if not has_pending_prompt():
        return None
    value = dict(_PENDING_PROMPT or {})
    _PENDING_PROMPT = None
    _PENDING_PROMPT_AT = 0.0
    return value


def has_pending_prompt() -> bool:
    if not _PENDING_PROMPT:
        return False
    if (time.monotonic() - _PENDING_PROMPT_AT) > _PENDING_PROMPT_TTL:
        # Expired: a much later sentence must not be swallowed as chat text.
        take_pending_prompt()
        return False
    return True


def clear_all_pendings() -> bool:
    """Drop every queued follow-up (reading, file name, folder name, prompt) at once.

    A plain «نه»/«لغو» must answer whatever Smartis is waiting for, so all
    pending slots are cleared together. Returns True when something was waiting.
    """
    global _PENDING_WIKIPEDIA, _PENDING_FOLDER, _PENDING_FILE, _PENDING_PROMPT, _PENDING_PROMPT_AT
    had = bool(_PENDING_WIKIPEDIA or _PENDING_FOLDER or _PENDING_FILE or has_pending_prompt())
    _PENDING_WIKIPEDIA = None
    _PENDING_FOLDER = None
    _PENDING_FILE = None
    _PENDING_PROMPT = None
    _PENDING_PROMPT_AT = 0.0
    return had


def set_reading_pending(title: str, text: str, language: str | None = None, url: str | None = None) -> None:
    """Queue raw source text so «ادامه بده» can keep reading after a research answer."""
    global _PENDING_WIKIPEDIA
    body = str(text or "").strip()
    if not body:
        return
    _PENDING_WIKIPEDIA = {
        "title": str(title or "").strip() or ("تحقیق" if language != "en" else "Research"),
        "language": "fa" if _fa(language) else "en",
        "text": body[:2600],
        "full_text": body,
        "url": url,
        "offset": 0,
    }


def shutdown_windows() -> dict[str, Any]:
    try:
        subprocess.Popen(["shutdown", "/s", "/t", "5"])
        return {"ok": True, "message": "Shutting down.", "speak": "سیستم تا چند ثانیه دیگر خاموش می‌شود."}
    except Exception as exc: return {"ok": False, "error": str(exc)}


def restart_windows() -> dict[str, Any]:
    try:
        subprocess.Popen(["shutdown", "/r", "/t", "5"])
        return {"ok": True, "message": "Restarting.", "speak": "سیستم تا چند ثانیه دیگر راه‌اندازی مجدد می‌شود."}
    except Exception as exc: return {"ok": False, "error": str(exc)}


def sleep_windows() -> dict[str, Any]:
    try:
        subprocess.Popen(["rundll32.exe", "powrprof.dll,SetSuspendState", "0", "1", "0"])
        return {"ok": True, "message": "Sleeping.", "speak": "سیستم وارد حالت خواب می‌شود."}
    except Exception as exc: return {"ok": False, "error": str(exc)}


def cancel_shutdown() -> dict[str, Any]:
    try:
        subprocess.Popen(["shutdown", "/a"])
        return {"ok": True, "speak": "خاموش یا ری‌استارت لغو شد."}
    except Exception as exc: return {"ok": False, "error": str(exc)}


def get_weather(city: str, language: str | None = None) -> dict[str, Any]:
    return _LOCATION_WEATHER.weather(city, "fa" if _fa(language) else "en", False)


def get_location_weather(language: str | None = None) -> dict[str, Any]:
    return _LOCATION_WEATHER.weather(None, "fa" if _fa(language) else "en", True)


def get_time_date(language: str | None = None) -> dict[str, Any]:
    return _LOCATION_WEATHER.time_date("fa" if _fa(language) else "en")


def get_dashboard() -> dict[str, Any]:
    import psutil
    proc = psutil.Process(os.getpid())
    try: proc_cpu = proc.cpu_percent(interval=0.04)
    except Exception: proc_cpu = 0.0
    ram = psutil.virtual_memory()
    return {"ok": True, "cpu_percent": round(psutil.cpu_percent(interval=0.04),1), "ram_percent": round(ram.percent,1), "ram_used_gb": round(ram.used/1024**3,1), "ram_total_gb": round(ram.total/1024**3,1), "smartis_cpu_percent": round(proc_cpu,1), "smartis_memory_mb": round(proc.memory_info().rss/1024**2,1), "smartis_threads": proc.num_threads()}


def _sensor_temperature(kind: str) -> float | None:
    if os.name != "nt": return None
    # Works when LibreHardwareMonitor/OpenHardwareMonitor exposes WMI sensors.
    try:
        import win32com.client
        for namespace in (r"winmgmts:\\.\root\LibreHardwareMonitor", r"winmgmts:\\.\root\OpenHardwareMonitor"):
            try:
                wmi = win32com.client.GetObject(namespace)
                rows = wmi.ExecQuery("SELECT Name, SensorType, Value FROM Sensor WHERE SensorType='Temperature'")
                candidates=[]
                for row in rows:
                    name=str(getattr(row,"Name","")).lower(); value=float(getattr(row,"Value",0))
                    if kind=="cpu" and any(x in name for x in ("cpu package","cpu core","cpu tdie","processor")): candidates.append(value)
                    if kind=="ram" and any(x in name for x in ("memory","ram","dimm")): candidates.append(value)
                if candidates: return round(max(candidates),1) if kind=="cpu" else round(sum(candidates)/len(candidates),1)
            except Exception: continue
    except Exception: pass
    if kind=="cpu":
        try:
            import win32com.client
            wmi=win32com.client.GetObject(r"winmgmts:\\.\root\wmi")
            rows=wmi.ExecQuery("SELECT CurrentTemperature FROM MSAcpi_ThermalZoneTemperature")
            vals=[(float(r.CurrentTemperature)/10.0)-273.15 for r in rows if float(r.CurrentTemperature)>0]
            if vals: return round(max(vals),1)
        except Exception: pass
    return None


def get_hardware_temperatures() -> dict[str, Any]:
    return {"ok":True,"cpu_temp_c":_sensor_temperature("cpu"),"ram_temp_c":_sensor_temperature("ram")}

# Wikipedia helpers ---------------------------------------------------------

def _wiki_search_title(query: str, lang: str) -> str | None:
    r=requests.get(f"https://{lang}.wikipedia.org/w/api.php", params={"action":"opensearch","search":query,"limit":1,"namespace":0,"format":"json"}, timeout=6, headers={"User-Agent":"Smartis/2.0"})
    r.raise_for_status(); data=r.json(); return data[1][0] if data and len(data)>1 and data[1] else None


def _wiki_summary(query: str, lang: str):
    title=_wiki_search_title(query,lang) or query
    r=requests.get(f"https://{lang}.wikipedia.org/api/rest_v1/page/summary/{quote(title)}", timeout=6, headers={"User-Agent":"Smartis/2.0"})
    if r.status_code==404: return None,None,None
    r.raise_for_status(); data=r.json(); return data.get("title") or title,data.get("extract") or "",data.get("content_urls",{}).get("desktop",{}).get("page")


def _wiki_full_extract(title: str, lang: str)->str:
    r=requests.get(f"https://{lang}.wikipedia.org/w/api.php", params={"action":"query","prop":"extracts","explaintext":1,"redirects":1,"titles":title,"format":"json"}, timeout=8, headers={"User-Agent":"Smartis/2.0"})
    r.raise_for_status(); pages=r.json().get("query",{}).get("pages",{}); page=next(iter(pages.values()),{})
    return (page.get("extract") or "").strip()


def _set_pending(title:str,lang:str,text:str,url:str|None)->None:
    global _PENDING_WIKIPEDIA; _PENDING_WIKIPEDIA={"title":title,"language":lang,"text":text,"url":url,"offset":0}

def wikipedia_more_available()->bool: return bool(_PENDING_WIKIPEDIA)
def wikipedia_clear_pending()->bool:
    global _PENDING_WIKIPEDIA
    had=bool(_PENDING_WIKIPEDIA); _PENDING_WIKIPEDIA=None; return had

def wikipedia_answer(query:str,language:str|None=None)->dict[str,Any]:
    fa=_fa(language); lang="fa" if fa else "en"; query=(query or "").strip()
    if not query: return {"ok":False,"error":"موضوع مشخص نیست." if fa else "The topic is missing."}
    try:
        title,extract,url=_wiki_summary(query,lang)
        if not title or not extract:
            fallback="en" if lang=="fa" else "fa"; title,extract,url=_wiki_summary(query,fallback)
            if title: lang=fallback
        if not title or not extract: return {"ok":False,"error":f"دربارهٔ «{query}» در ویکی‌پدیا مطلبی پیدا نکردم." if fa else f"I couldn't find a Wikipedia article about {query}."}
        short=" ".join(x.strip() for x in re.split(r"\n\s*\n",extract) if x.strip())[:2600].strip()
        _set_pending(title,lang,extract,url); ask="می‌خوای کامل‌تر بخونم؟" if fa else "Would you like me to read more?"
        spoken=f"دربارهٔ «{title}»: {short} {ask}" if fa else f"About {title}: {short} {ask}"
        return {"ok":True,"message":short,"speak":spoken,"title":title,"source":"Wikipedia","url":url}
    except Exception as exc: return {"ok":False,"error":f"نتونستم ویکی‌پدیا را بخونم: {exc}" if fa else f"I couldn't read Wikipedia: {exc}"}

def wikipedia_more(language:str|None=None)->dict[str,Any]:
    global _PENDING_WIKIPEDIA
    fa=_fa(language)
    if not _PENDING_WIKIPEDIA: return {"ok":False,"error":"مطلبی برای ادامه خواندن ندارم." if fa else "There is no article waiting to be continued."}
    try:
        pending=dict(_PENDING_WIKIPEDIA); full=pending.get("full_text") or _wiki_full_extract(pending["title"],pending["language"]) or pending["text"]; offset=int(pending.get("offset",0)); chunk=full[offset:offset+12000].strip(); new_offset=min(len(full),offset+12000); more=new_offset<len(full)
        spoken=chunk + ((" اگر می‌خوای ادامه بدم، بگو ادامه بده." if fa else " Say continue if you want me to keep reading.") if more else "")
        if more: _PENDING_WIKIPEDIA={**pending,"full_text":full,"offset":new_offset}
        else: _PENDING_WIKIPEDIA=None
        return {"ok":True,"message":spoken,"speak":spoken,"title":pending["title"],"source":"Wikipedia","url":pending.get("url"),"has_more":more}
    except Exception as exc: return {"ok":False,"error":f"ادامهٔ مقاله خوانده نشد: {exc}" if fa else f"I couldn't continue the article: {exc}"}

def wikipedia_lookup(query:str,language:str|None=None)->dict[str,Any]:
    result=wikipedia_answer(query,language)
    if result.get("ok"): result["message"]=result.get("speak",result.get("message",""))
    return result

# News ---------------------------------------------------------------------
_TRUSTED_EN=("reuters.com","apnews.com","bbc.com","bbc.co.uk","dw.com","npr.org","aljazeera.com","ft.com","nytimes.com","washingtonpost.com","theguardian.com")
_TRUSTED_FA=("bbc.com/persian","irna.ir","isna.ir","mehrnews.com","tasnimnews.com","khabaronline.ir","farsnews.ir","dw.com/fa-ir","radiofarda.com","voanews.com/persian","بی بی سی فارسی","bbc persian","ایرنا","irna","ایسنا","isna","مهر نیوز","mehr news","مهرنیوز","تسنیم","tasnim","خبرآنلاین","khabar online","فارس","fars news","دویچه وله فارسی","dw فارسی","رادیو فردا","radio farda","صدای آمریکا","voa persian")

def get_news(topic:str|None=None, language:str|None=None, limit:int=5)->dict[str,Any]:
    import xml.etree.ElementTree as ET
    fa=_fa(language); query=(topic or "").strip(); params="hl=fa&gl=IR&ceid=IR:fa" if fa else "hl=en-US&gl=US&ceid=US:en"
    url=f"https://news.google.com/rss/search?q={quote(query)}&{params}" if query else f"https://news.google.com/rss?{params}"
    try:
        root=ET.fromstring(requests.get(url,timeout=8,headers={"User-Agent":"Mozilla/5.0 Smartis/2.2"}).content); items=[]
        trusted_domains=_TRUSTED_FA if fa else _TRUSTED_EN
        for item in root.findall(".//item"):
            title=(item.findtext("title") or "").strip(); link=(item.findtext("link") or "").strip(); pub=(item.findtext("pubDate") or "").strip(); se=item.find("source"); source=(se.text or "").strip() if se is not None else ""; source_url=(se.attrib.get("url") or "").lower() if se is not None else ""
            if not title: continue
            blob=f"{source} {source_url} {link}".lower()
            trusted=any(domain in blob for domain in trusted_domains)
            # Persian mode additionally requires a clearly Persian source unless Google News did not expose source metadata.
            if fa and source and not trusted:
                continue
            if trusted:
                items.append({"title":title,"source":source or "منبع معتبر","link":link,"published":pub})
        if not items:
            return {"ok":False,"error":"خبر معتبر و قابل استفاده‌ای پیدا نکردم." if fa else "I couldn't find a reputable recent story."}
        chosen=items[:limit]
        prefix="آخرین خبرهای معتبر فارسی: " if fa else "Latest news from reputable sources: "
        body="؛ ".join(f"{i+1}. {x['title']} — منبع: {x['source']}" for i,x in enumerate(chosen)) if fa else "; ".join(f"{i+1}. {x['title']} — source: {x['source']}" for i,x in enumerate(chosen))
        return {"ok":True,"message":prefix+body,"speak":prefix+body,"headlines":chosen}
    except Exception as exc:
        return {"ok":False,"error":f"نتونستم اخبار را بگیرم: {exc}" if fa else f"I couldn't fetch the news: {exc}"}

def _safe_eval(node):
    if isinstance(node,ast.Constant) and isinstance(node.value,(int,float)): return node.value
    if isinstance(node,ast.BinOp) and type(node.op) in _OPS: return _OPS[type(node.op)](_safe_eval(node.left),_safe_eval(node.right))
    if isinstance(node,ast.UnaryOp) and type(node.op) in _OPS: return _OPS[type(node.op)](_safe_eval(node.operand))
    raise ValueError("Unsupported expression")

def _build_number_words() -> dict[str,int]:
    units={"صفر":0,"یک":1,"یه":1,"دو":2,"سه":3,"چهار":4,"پنج":5,"شش":6,"شیش":6,"هفت":7,"هشت":8,"نه":9}
    teen={"ده":10,"یازده":11,"دوازده":12,"سیزده":13,"چهارده":14,"پانزده":15,"شانزده":16,"هفده":17,"هجده":18,"نوزده":19}
    tens={"بیست":20,"سی":30,"چهل":40,"پنجاه":50,"شصت":60,"هفتاد":70,"هشتاد":80,"نود":90}
    hundreds={"صد":100,"یکصد":100,"دویست":200,"سیصد":300,"چهارصد":400,"پانصد":500,"ششصد":600,"هفتصد":700,"هشتصد":800,"نهصد":900}
    out={**units,**teen,**tens,**hundreds}
    # 21..99 and 101..999 with a Persian 'و'.
    small={**units,**teen,**tens}
    for a,va in list(tens.items()):
        for b,vb in list(units.items()):
            if vb and f"{a} و {b}" not in out: out[f"{a} و {b}"]=va+vb
    for h,vh in list(hundreds.items()):
        for tail,vt in list(small.items()):
            if vt and vh!=100:
                out[f"{h if h!='یکصد' else 'صد'} و {tail}"]=vh+vt
            elif vt:
                out[f"صد و {tail}"]=100+vt
        for tail,vt in list(out.items()):
            if 0<vt<100 and ' و ' in tail:
                out[f"صد و {tail}"]=100+vt
    # Common Persian standalone English forms.
    eng_units={"zero":0,"one":1,"two":2,"three":3,"four":4,"five":5,"six":6,"seven":7,"eight":8,"nine":9}
    eng_teen={"ten":10,"eleven":11,"twelve":12,"thirteen":13,"fourteen":14,"fifteen":15,"sixteen":16,"seventeen":17,"eighteen":18,"nineteen":19}
    eng_tens={"twenty":20,"thirty":30,"forty":40,"fifty":50,"sixty":60,"seventy":70,"eighty":80,"ninety":90}
    out.update(eng_units); out.update(eng_teen); out.update(eng_tens)
    for a,va in eng_tens.items():
        for b,vb in eng_units.items(): out[f"{a} {b}"]=va+vb
    return out

_NUMBER_WORDS=_build_number_words()

def _replace_number_words(text: str) -> str:
    out=text.lower()
    for phrase,value in sorted(_NUMBER_WORDS.items(), key=lambda kv: len(kv[0]), reverse=True):
        out=re.sub(rf"(?<![\w-]){re.escape(phrase)}(?![\w-])",str(value),out,flags=re.I)
    return out

def _normalize_math_expression(expression: str) -> str:
    t=str(expression or "").strip().lower().translate(str.maketrans("۰۱۲۳۴۵۶۷۸۹","0123456789"))
    t=t.replace("؟","?")
    # Strip natural-language wrappers that should never reach SymPy.
    t=re.sub(r"^(?:جواب|حساب|محاسبه|حسابش|لطفا|لطفاً|می(?:شه|شود)|میشه|میشود|برام|برای من)\s+", "", t)
    t=re.sub(r"(?:چند\s*می(?:شه|شود)|چند\s*میشه|حساب\s*کن|محاسبه\s*کن|حساب\s*کنش|جواب\s*رو\s*بگو|جواب\s*را\s*بگو|جوابش\s*چیه|جوابش\s*چیست|چقدر\s*میشه)\s*[؟?!.,]*$", "", t)
    t=_replace_number_words(t)
    replacements={
        "به علاوه":"+","بعلاوه":"+","جمع":"+","منهای":"-","منها":"-","منفی":"-",
        "ضربدر":"*","ضرب در":"*","ضرب":"*","times":"*","multiplied by":"*",
        "تقسیم بر":"/","تقسیم به":"/","تقسیم":"/","divided by":"/",
        "به توان":"^","توان":"^","to the power of":"^","درصد":"%","percent":"%",
        "ریشه دوم":"sqrt","جذر":"sqrt","square root":"sqrt","سینوس":"sin","کسینوس":"cos","تانژانت":"tan",
        "لگاریتم":"log","logarithm":"log","مساوی":"=","برابر":"=","ایکس":"x","پی":"pi","درجه":"deg",
    }
    for a,b in sorted(replacements.items(), key=lambda kv: -len(kv[0])): t=t.replace(a,b)
    t=re.sub(r"\bof\b", " of ", t)
    t=re.sub(r"\bsqrt\s*([0-9.]+)", r"sqrt(\1)", t)
    t=re.sub(r"(?<=\d)\s+(?=[xyz]\b)", "*", t)
    # Voice transcripts often contain decorative punctuation or a trailing question mark.
    t=re.sub(r"[^0-9a-zA-Z_+\-*/%^().,=\s]", " ", t)
    t=re.sub(r"\s+", " ", t).strip(" ,?.!")
    return t

def calculate(expression:str, language:str|None=None) -> dict[str,Any]:
    fa=_fa(language); raw=str(expression or "").strip(); normalized=_normalize_math_expression(raw)
    try:
        import sympy as sp
        # Percentage-of forms: "30% of 500" and Persian voice forms like "30 درصد 500".
        m=re.fullmatch(r"\(?\s*([0-9.]+)\s*%\s*(?:of\s*)?([0-9.]+)\s*\)?", normalized)
        if m:
            result=sp.Rational(m.group(1))*sp.Rational(m.group(2))/100
        else:
            # Basic equation solving: 2*x+4 = 10
            eq_match=re.fullmatch(r"(.+?)\s*(?:=|مساوی|برابر)\s*(.+)", normalized)
            if eq_match and re.search(r"\b[a-zA-Z]\b", normalized):
                x=sp.symbols("x y z")
                locals_map={"x":x[0],"y":x[1],"z":x[2],"pi":sp.pi,"e":sp.E,"sqrt":sp.sqrt,"sin":sp.sin,"cos":sp.cos,"tan":sp.tan,"log":sp.log,"ln":sp.log,"abs":sp.Abs}
                lhs=sp.sympify(eq_match.group(1).replace('^','**'),locals=locals_map)
                rhs=sp.sympify(eq_match.group(2).replace('^','**'),locals=locals_map)
                sols=sp.solve(sp.Eq(lhs,rhs),x, dict=True)
                result=sols[0] if sols else sp.solve(sp.Eq(lhs,rhs),x[0])
            else:
                expr=normalized.replace('^','**')
                expr=re.sub(r"(\d+(?:\.\d+)?)\s*deg",r"(\1*pi/180)",expr)
                allowed={"pi":sp.pi,"e":sp.E,"sqrt":sp.sqrt,"sin":sp.sin,"cos":sp.cos,"tan":sp.tan,"log":sp.log,"ln":sp.log,"abs":sp.Abs,"asin":sp.asin,"acos":sp.acos,"atan":sp.atan}
                # Reject anything that is not a math expression/token.
                if re.search(r"[^0-9a-zA-Z_+\-*/%().,\s]",expr): raise ValueError("unsupported characters")
                result=sp.sympify(expr,locals=allowed)
        if isinstance(result, dict):
            text="، ".join(f"{k} = {sp.N(v) if hasattr(v,'evalf') else v}" for k,v in result.items())
        elif isinstance(result,(list,tuple)):
            text="، ".join(str(sp.N(v)) for v in result)
        elif hasattr(result,'evalf'):
            numeric=sp.N(result,12)
            text=str(numeric).rstrip('0').rstrip('.') if isinstance(numeric,sp.Float) else str(numeric)
        else:
            text=str(result)
        speak=f"جواب: {text}" if fa else f"The answer is {text}."
        return {"ok":True,"result":text,"speak":speak,"expression":raw}
    except Exception as exc:
        return {"ok":False,"error":f"نتونستم این عبارت ریاضی را حل کنم: {exc}" if fa else f"I couldn't solve that expression: {exc}"}


def get_installed_languages() -> list[str]:
    if os.name != "nt": return []
    try:
        ps="Get-WinUserLanguageList | ForEach-Object { $_.LanguageTag }"
        out=subprocess.check_output(["powershell","-NoProfile","-Command",ps],text=True,stderr=subprocess.DEVNULL,timeout=8)
        return [x.strip() for x in out.splitlines() if x.strip()]
    except Exception:
        return []


def _language_tag(raw: str) -> str:
    value=str(raw or "").strip().lower()
    aliases={
        "فارسی":"fa-IR","فارسی ایران":"fa-IR","persian":"fa-IR","persian iran":"fa-IR","farsi":"fa-IR","iranian":"fa-IR","fa":"fa-IR","fa-ir":"fa-IR","fa_ir":"fa-IR",
        "انگلیسی":"en-US","انگلیسی امریکا":"en-US","english":"en-US","english us":"en-US","english (united states)":"en-US","en":"en-US","en-us":"en-US","en_us":"en-US",
    }
    return aliases.get(value, str(raw or "").strip())


def set_windows_language(language_name:str, language:str|None=None) -> dict[str,Any]:
    fa=_fa(language); tag=_language_tag(language_name)
    if not tag:
        return {"ok":False,"error":"زبان مشخص نیست." if fa else "The target language is missing."}
    installed=get_installed_languages()
    installed_match=next((x for x in installed if x.lower()==tag.lower() or x.lower().split('-')[0]==tag.lower().split('-')[0]), None)
    if installed_match is None:
        # Windows cannot switch the display language to a language whose pack is
        # absent. Do not silently download a large pack; return the exact next step.
        return {"ok":False,"installed":installed,"language_tag":tag,"open_settings":"ms-settings:regionlanguage","error":f"بستهٔ زبان {tag} روی ویندوز نصب نیست. از تنظیمات Language & region آن را نصب کن؛ بعد Smartis می‌تواند مستقیم آن را فعال کند." if fa else f"The {tag} language pack is not installed. Install it from Windows Language & region, then Smartis can activate it directly."}
    try:
        ps=(
            "$ErrorActionPreference='Stop';"
            f"$tag='{tag}';"
            "$list=Get-WinUserLanguageList;"
            "$selected=$list | Where-Object {$_.LanguageTag -ieq $tag} | Select-Object -First 1;"
            "if(-not $selected){$selected=(New-WinUserLanguageList $tag)[0]; $list=@($selected)+@($list | Where-Object {$_.LanguageTag -ine $tag})} "
            "else {$list=@($selected)+@($list | Where-Object {$_.LanguageTag -ine $tag})};"
            "Set-WinUserLanguageList -LanguageList $list -Force;"
            "Set-WinUILanguageOverride -Language $tag;"
            "try {Set-Culture -CultureInfo $tag}catch{};"
            "try {Set-WinSystemLocale -SystemLocale $tag}catch{};"
            "Write-Output ('ACTIVE=' + $tag);"
            "Write-Output ('LIST=' + ((Get-WinUserLanguageList | ForEach-Object {$_.LanguageTag}) -join ','));"
        )
        out=subprocess.check_output(["powershell","-NoProfile","-ExecutionPolicy","Bypass","-Command",ps],text=True,stderr=subprocess.STDOUT,timeout=25)
        verify=get_installed_languages()
        active=any(x.lower()==tag.lower() for x in verify)
        return {"ok":True,"language_tag":tag,"installed":verify,"verified":active,"speak":f"زبان ویندوز روی {tag} تنظیم شد. برای اعمال کامل رابط کاربری، یک‌بار از حساب ویندوز خارج شو و دوباره وارد شو." if fa else f"Windows language is set to {tag}. Sign out and back in once for the full interface language to apply.","details":out.strip()}
    except subprocess.CalledProcessError as exc:
        detail=exc.output.strip() or str(exc)
        return {"ok":False,"language_tag":tag,"installed":installed,"error":f"تغییر زبان ویندوز شکست خورد: {detail}" if fa else f"Windows language change failed: {detail}"}
    except Exception as exc:
        return {"ok":False,"language_tag":tag,"installed":installed,"error":str(exc)}
