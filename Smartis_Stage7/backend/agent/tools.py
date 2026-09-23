from __future__ import annotations

import os
import subprocess
import webbrowser
from pathlib import Path
from typing import Any


def tool_specs() -> list[dict[str, Any]]:
    return [
        {
            "name": "open_application",
            "description": "Open a Windows application by a natural application name.",
            "parameters": {"app": "string"},
        },
        {
            "name": "open_website",
            "description": "Open a website URL in the default browser.",
            "parameters": {"url": "string"},
        },
        {
            "name": "open_folder",
            "description": "Open a local Windows folder.",
            "parameters": {"path": "string"},
        },
        {
            "name": "open_file",
            "description": "Open a local file with its default Windows application.",
            "parameters": {"path": "string"},
        },
        {
            "name": "system_info",
            "description": "Read non-sensitive local system information.",
            "parameters": {},
        },
        {
            "name": "close_application",
            "description": "Close a Windows application by process name. Requires confirmation.",
            "parameters": {"process": "string"},
            "requires_confirmation": True,
        },
        {
            "name": "browser_open",
            "description": "Open a URL in a controllable automation browser (not the system default browser). Use this instead of open_website whenever a later step needs to type into or read the page.",
            "parameters": {"url": "string"},
        },
        {
            "name": "browser_type",
            "description": "Type text into the most relevant input/textarea field on the currently open automation browser page.",
            "parameters": {"text": "string"},
        },
        {
            "name": "browser_submit",
            "description": "Press Enter to submit whatever was just typed in the automation browser.",
            "parameters": {},
        },
        {
            "name": "browser_read_response",
            "description": "Wait for the page to respond and return/speak the newly appeared text. Use as the last step after browser_submit when the user wants the answer read back.",
            "parameters": {},
        },
        {
            "name": "browser_close",
            "description": "Close the automation browser session.",
            "parameters": {},
        },
    ]


APP_ALIASES = {
    "chrome": "chrome.exe",
    "google chrome": "chrome.exe",
    "کروم": "chrome.exe",
    "گوگل کروم": "chrome.exe",
    "edge": "msedge.exe",
    "مایکروسافت اج": "msedge.exe",
    "notepad": "notepad.exe",
    "نوت پد": "notepad.exe",
    "calculator": "calc.exe",
    "ماشین حساب": "calc.exe",
    "explorer": "explorer.exe",
    "فایل اکسپلورر": "explorer.exe",
}


def execute_tool(name: str, args: dict[str, Any]) -> dict[str, Any]:
    if name == "open_application":
        app = str(args.get("app", "")).strip().lower()
        executable = APP_ALIASES.get(app, app)
        if not executable:
            return {"ok": False, "error": "Application name is empty."}
        try:
            subprocess.Popen([executable], shell=False)
            return {"ok": True, "message": f"Opened {app}."}
        except Exception as exc:
            return {"ok": False, "error": f"Could not open application: {exc}"}

    if name == "open_website":
        url = str(args.get("url", "")).strip()
        if not url:
            return {"ok": False, "error": "URL is empty."}
        if not url.startswith(("http://", "https://")):
            url = "https://" + url
        try:
            webbrowser.open(url)
            return {"ok": True, "message": f"Opened {url}."}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    if name == "open_folder":
        path = os.path.expandvars(os.path.expanduser(str(args.get("path", ""))))
        if not os.path.isdir(path):
            return {"ok": False, "error": f"Folder not found: {path}"}
        try:
            os.startfile(path)
            return {"ok": True, "message": f"Opened folder {path}."}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    if name == "open_file":
        path = os.path.expandvars(os.path.expanduser(str(args.get("path", ""))))
        if not os.path.isfile(path):
            return {"ok": False, "error": f"File not found: {path}"}
        try:
            os.startfile(path)
            return {"ok": True, "message": f"Opened file {path}."}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    if name == "system_info":
        import psutil
        return {
            "ok": True,
            "cpu_percent": psutil.cpu_percent(interval=0.1),
            "memory_percent": psutil.virtual_memory().percent,
            "computer": os.environ.get("COMPUTERNAME", ""),
            "username": os.environ.get("USERNAME", ""),
        }

    if name == "close_application":
        process = str(args.get("process", "")).strip().lower()
        if not process:
            return {"ok": False, "error": "Process name is empty."}
        if not process.endswith(".exe"):
            process += ".exe"
        try:
            import psutil
            closed = 0
            for proc in psutil.process_iter(["name"]):
                if (proc.info.get("name") or "").lower() == process:
                    proc.terminate()
                    closed += 1
            return {"ok": True, "message": f"Closed {closed} process(es)."}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    if name in ("browser_open", "browser_type", "browser_submit", "browser_read_response", "browser_close"):
        try:
            from agent import browser_tools
        except Exception as exc:
            return {"ok": False, "error": f"Browser automation unavailable: {exc}"}
        try:
            if name == "browser_open":
                return browser_tools.browser_open(str(args.get("url", "")).strip())
            if name == "browser_type":
                return browser_tools.browser_type(str(args.get("text", "")))
            if name == "browser_submit":
                return browser_tools.browser_submit()
            if name == "browser_read_response":
                return browser_tools.browser_read_response()
            if name == "browser_close":
                return browser_tools.browser_close()
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    return {"ok": False, "error": f"Unknown tool: {name}"}
