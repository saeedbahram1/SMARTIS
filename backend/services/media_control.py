from __future__ import annotations

"""Windows system-audio, media transport and active-player volume controls."""

import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any, Optional
from urllib.parse import quote_plus


MEDIA_PROCESSES = {
    "vlc.exe", "spotify.exe", "wmplayer.exe", "musicbee.exe", "foobar2000.exe", "aimp.exe", "winamp.exe",
    "potplayer.exe", "potplayer64.exe", "mpc-hc.exe", "mpc-be.exe", "mpc-be64.exe", "groove.exe", "itunes.exe",
    "chrome.exe", "msedge.exe", "firefox.exe", "brave.exe", "opera.exe",
}

VK_MEDIA_NEXT_TRACK = 0xB0
VK_MEDIA_PREV_TRACK = 0xB1
VK_MEDIA_STOP = 0xB2
VK_MEDIA_PLAY_PAUSE = 0xB3


def _is_windows() -> bool:
    return os.name == "nt"


def _send_virtual_key(vk: int) -> dict[str, Any]:
    if not _is_windows():
        return {"ok": False, "error": "Windows media controls are only available on Windows."}
    try:
        import ctypes

        user32 = ctypes.windll.user32
        user32.keybd_event(vk, 0, 0, 0)
        user32.keybd_event(vk, 0, 2, 0)
        return {"ok": True}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def _pycaw_device():
    if not _is_windows():
        raise RuntimeError("Core Audio controls require Windows.")
    from pycaw.pycaw import AudioUtilities

    return AudioUtilities.GetSpeakers()


def _clamp_system_percent(value: float) -> float:
    return max(0.0, min(100.0, float(value)))


def system_volume_get() -> dict[str, Any]:
    try:
        endpoint = _pycaw_device().EndpointVolume
        scalar = float(endpoint.GetMasterVolumeLevelScalar())
        return {"ok": True, "volume_percent": round(scalar * 100.0, 1), "muted": bool(endpoint.GetMute())}
    except Exception as exc:
        return {"ok": False, "error": f"System volume unavailable: {exc}"}


def system_volume_set(percent: float) -> dict[str, Any]:
    try:
        requested = float(percent)
        value = _clamp_system_percent(requested)
        endpoint = _pycaw_device().EndpointVolume
        endpoint.SetMasterVolumeLevelScalar(value / 100.0, None)
        actual = float(endpoint.GetMasterVolumeLevelScalar()) * 100.0
        return {"ok": True, "volume_percent": round(actual, 1), "requested_percent": requested, "speak": f"صدای سیستم روی {actual:.0f} درصد تنظیم شد."}
    except Exception as exc:
        return {"ok": False, "error": f"Could not set system volume: {exc}"}


def system_volume_change(delta: float) -> dict[str, Any]:
    try:
        endpoint = _pycaw_device().EndpointVolume
        current = float(endpoint.GetMasterVolumeLevelScalar()) * 100.0
        target = _clamp_system_percent(current + float(delta))
        endpoint.SetMasterVolumeLevelScalar(target / 100.0, None)
        actual = float(endpoint.GetMasterVolumeLevelScalar()) * 100.0
        return {"ok": True, "volume_percent": round(actual, 1), "delta_percent": float(delta), "speak": f"صدای سیستم روی {actual:.0f} درصد تنظیم شد."}
    except Exception as exc:
        return {"ok": False, "error": f"Could not change system volume: {exc}"}


def system_mute(enabled: bool) -> dict[str, Any]:
    try:
        endpoint = _pycaw_device().EndpointVolume
        endpoint.SetMute(bool(enabled), None)
        return {"ok": True, "muted": bool(enabled), "speak": "صدای سیستم قطع شد." if enabled else "صدای سیستم وصل شد."}
    except Exception as exc:
        return {"ok": False, "error": f"Could not change system mute: {exc}"}

def _active_audio_sessions() -> list[dict[str, Any]]:
    if not _is_windows():
        return []
    from pycaw.pycaw import AudioUtilities

    sessions: list[dict[str, Any]] = []
    for session in AudioUtilities.GetAllSessions():
        try:
            process = session.Process
            if process is None:
                continue
            name = (process.name() or "").lower()
            if not name or name in {"python.exe", "smartis_desktop.exe"}:
                continue
            state = int(getattr(session, "State", 1))
            if state != 1:
                continue
            volume = session.SimpleAudioVolume
            try:
                peak = float(session.PeakValue)
            except Exception:
                peak = 0.0
            try:
                current = float(volume.GetMasterVolume()) * 100.0
            except Exception:
                current = 0.0
            sessions.append(
                {
                    "session": session,
                    "process": process,
                    "process_name": name,
                    "pid": int(getattr(process, "pid", 0) or 0),
                    "volume": current,
                    "peak": peak,
                    "known_player": name in MEDIA_PROCESSES,
                }
            )
        except Exception:
            continue

    # Prefer a known media player and, among players, the session with the
    # strongest current audio signal. This still falls back to any active
    # audio session so Smartis is not limited to a hard-coded player list.
    sessions.sort(key=lambda item: (bool(item["known_player"]), item["peak"]), reverse=True)
    return sessions


def _window_sliders_for_pid(pid: int):
    if not pid:
        return []
    try:
        from pywinauto import Desktop

        windows = Desktop(backend="uia").windows(visible_only=True)
    except Exception:
        return []

    matches = []
    for window in windows:
        try:
            if int(window.process_id()) != int(pid):
                continue
            for slider in window.descendants(control_type="Slider"):
                matches.append(slider)
        except Exception:
            continue
    return matches


def _choose_volume_slider(sliders):
    for slider in sliders:
        try:
            name = (slider.element_info.name or "").strip().lower()
        except Exception:
            name = ""
        if any(token in name for token in ("volume", "sound", "audio", "میزان صدا", "صدا", "master")):
            return slider
    return None


def _slider_metrics(slider) -> tuple[float, float, float, float] | None:
    try:
        minimum = float(slider.min_value())
        maximum = float(slider.max_value())
        current = float(slider.value())
    except Exception:
        return None
    if maximum <= minimum:
        return None

    # UIA sliders sometimes expose a normalized 0..1.0/1.25/2.0 scale and
    # sometimes expose an explicit percentage-like scale (0..100/125/200).
    if maximum <= 3.0:
        max_percent = (maximum - minimum) * 100.0
        current_percent = (current - minimum) * 100.0
        return minimum, maximum, current_percent, max_percent

    return minimum, maximum, current, maximum - minimum


def _read_ui_player_volume(pid: int) -> dict[str, Any]:
    slider = _choose_volume_slider(_window_sliders_for_pid(pid))
    if slider is None:
        return {"ok": False, "error": "Player volume slider is not accessible."}
    metrics = _slider_metrics(slider)
    if metrics is None:
        return {"ok": False, "error": "Player volume slider has an invalid range."}
    _minimum, _maximum, current, max_percent = metrics
    return {
        "ok": True,
        "volume_percent": round(current, 1),
        "max_percent": round(max_percent, 1),
    }


def _set_ui_player_volume(pid: int, requested: float) -> dict[str, Any]:
    slider = _choose_volume_slider(_window_sliders_for_pid(pid))
    if slider is None:
        return {"ok": False, "error": "Player volume slider is not accessible."}

    metrics = _slider_metrics(slider)
    if metrics is None:
        return {"ok": False, "error": "Player volume slider has an invalid range."}

    minimum, maximum, _current, max_percent = metrics
    if requested < 0 or requested > max_percent + 1e-6:
        return {
            "ok": False,
            "supports_requested": False,
            "max_percent": round(max_percent, 1),
            "error": f"The player exposes a maximum volume of {max_percent:.0f}%.",
        }

    target = minimum + (requested / 100.0 if maximum <= 3.0 else requested)
    try:
        slider.set_value(target)
        new_metrics = _slider_metrics(slider)
        current_percent = new_metrics[2] if new_metrics else requested
        return {
            "ok": True,
            "supports_requested": True,
            "volume_percent": round(current_percent, 1),
            "max_percent": round(max_percent, 1),
        }
    except Exception as exc:
        return {"ok": False, "error": f"Could not set player slider: {exc}"}


def active_player() -> dict[str, Any]:
    try:
        sessions = _active_audio_sessions()
        if not sessions:
            return {"ok": False, "error": "No active media/audio player was found."}
        item = sessions[0]
        result = {
            "ok": True,
            "process": item["process_name"],
            "pid": item["pid"],
            "volume_percent": round(item["volume"], 1),
            "peak": round(item["peak"], 4),
            "known_player": bool(item["known_player"]),
        }
        ui = _read_ui_player_volume(item["pid"])
        if ui.get("ok"):
            result["player_volume_percent"] = ui["volume_percent"]
            result["player_max_percent"] = ui["max_percent"]
        return result
    except Exception as exc:
        return {"ok": False, "error": f"Could not inspect active player: {exc}"}


def _active_player_session() -> dict[str, Any]:
    sessions = _active_audio_sessions()
    if not sessions:
        return {"ok": False, "error": "No active media/audio player was found."}
    return {"ok": True, "item": sessions[0]}


def player_volume_set(percent: float) -> dict[str, Any]:
    requested = float(percent)
    active = _active_player_session()
    if not active.get("ok"):
        return active

    item = active["item"]
    process = str(item["process_name"])
    pid = int(item["pid"] or 0)

    # First use the player's own volume control. This is what lets a player
    # expose values above Windows' 100% session ceiling (for example when VLC's
    # own maximum-volume setting has been configured above 100%).
    if pid:
        ui_result = _set_ui_player_volume(pid, requested)
        if ui_result.get("ok"):
            return {
                "ok": True,
                "player": process,
                "speak": f"صدای {process} روی {requested:.0f} درصد تنظیم شد.",
                **ui_result,
            }
        if requested > float(ui_result.get("max_percent", 100.0)):
            return {
                "ok": False,
                "player": process,
                "supports_requested": False,
                **{k: v for k, v in ui_result.items() if k != "ok"},
            }

    if requested < 0 or requested > 100:
        return {
            "ok": False,
            "player": process,
            "supports_requested": False,
            "error": f"{process} does not expose {requested:.0f}% player volume to Smartis.",
        }

    try:
        item["session"].SimpleAudioVolume.SetMasterVolume(requested / 100.0, None)
        return {
            "ok": True,
            "player": process,
            "volume_percent": round(requested, 1),
            "max_percent": 100.0,
            "supports_requested": True,
            "speak": f"صدای {process} روی {requested:.0f} درصد تنظیم شد.",
        }
    except Exception as exc:
        return {"ok": False, "error": f"Could not set {process} player volume: {exc}"}


def player_volume_max() -> dict[str, Any]:
    active = _active_player_session()
    if not active.get("ok"):
        return active

    item = active["item"]
    process = str(item["process_name"])
    pid = int(item["pid"] or 0)

    if pid:
        current = _read_ui_player_volume(pid)
        if current.get("ok"):
            result = _set_ui_player_volume(pid, float(current["max_percent"]))
            if result.get("ok"):
                return {
                    "ok": True,
                    "player": process,
                    "speak": f"صدای {process} را تا بیشترین مقدار قابل پشتیبانی بالا بردم.",
                    **result,
                }

    return player_volume_set(100.0)


def player_volume_change(delta: float) -> dict[str, Any]:
    active = _active_player_session()
    if not active.get("ok"):
        return active

    item = active["item"]
    process = str(item["process_name"])
    pid = int(item["pid"] or 0)
    amount = float(delta)

    # Read and change the player's own slider when possible. This keeps a
    # 150% VLC volume at 150% instead of accidentally using Windows' 100% session value.
    if pid:
        current = _read_ui_player_volume(pid)
        if current.get("ok"):
            target = max(0.0, min(float(current["max_percent"]), float(current["volume_percent"]) + amount))
            result = _set_ui_player_volume(pid, target)
            if result.get("ok"):
                return {
                    "ok": True,
                    "player": process,
                    "delta_percent": amount,
                    "speak": f"صدای {process} روی {target:.0f} درصد تنظیم شد.",
                    **result,
                }

    current = float(item["volume"])
    target = _clamp_system_percent(current + amount)
    try:
        item["session"].SimpleAudioVolume.SetMasterVolume(target / 100.0, None)
        return {
            "ok": True,
            "player": process,
            "volume_percent": round(target, 1),
            "delta_percent": amount,
            "max_percent": 100.0,
            "speak": f"صدای {process} روی {target:.0f} درصد تنظیم شد.",
        }
    except Exception as exc:
        return {"ok": False, "error": f"Could not change {process} player volume: {exc}"}


def player_mute(enabled: bool) -> dict[str, Any]:
    active = _active_player_session()
    if not active.get("ok"):
        return active
    item = active["item"]
    process = str(item["process_name"])
    try:
        item["session"].SimpleAudioVolume.SetMute(bool(enabled), None)
        return {
            "ok": True,
            "player": process,
            "muted": bool(enabled),
            "speak": f"صدای {process} قطع شد." if enabled else f"صدای {process} وصل شد.",
        }
    except Exception as exc:
        return {"ok": False, "error": f"Could not change player mute: {exc}"}


def media_play_pause() -> dict[str, Any]:
    result = _send_virtual_key(VK_MEDIA_PLAY_PAUSE)
    if result.get("ok"):
        result["message"] = "Windows Play/Pause media key sent."
    return result


def media_stop() -> dict[str, Any]:
    result = _send_virtual_key(VK_MEDIA_STOP)
    if result.get("ok"):
        result["message"] = "Windows Stop Media key sent."
    return result


def media_next() -> dict[str, Any]:
    result = _send_virtual_key(VK_MEDIA_NEXT_TRACK)
    if result.get("ok"):
        result["message"] = "Windows Next Track media key sent."
    return result


def media_previous() -> dict[str, Any]:
    result = _send_virtual_key(VK_MEDIA_PREV_TRACK)
    if result.get("ok"):
        result["message"] = "Windows Previous Track media key sent."
    return result


def _find_vlc_exe() -> Optional[str]:
    candidates = [
        shutil.which("vlc.exe"),
        os.path.join(os.environ.get("ProgramFiles", r"C:\Program Files"), "VideoLAN", "VLC", "vlc.exe"),
        os.path.join(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"), "VideoLAN", "VLC", "vlc.exe"),
        os.path.join(os.environ.get("LOCALAPPDATA", ""), "Programs", "VLC", "vlc.exe"),
    ]
    for candidate in candidates:
        if candidate and Path(candidate).is_file():
            return candidate
    return None


def _extract_youtube_audio(query: str) -> tuple[str, str, dict[str, str]]:
    """Use the simple direct yt-dlp extraction path used by the earlier working build."""
    from yt_dlp import YoutubeDL

    options: dict[str, Any] = {
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
        "skip_download": True,
        "format": "bestaudio/best",
        "socket_timeout": 10,
        "retries": 2,
        "extractor_retries": 2,
        "fragment_retries": 2,
    }
    with YoutubeDL(options) as ydl:
        info = ydl.extract_info(f"ytsearch1:{query}", download=False)
    entries = info.get("entries") or []
    if not entries:
        raise RuntimeError("No online result found.")
    entry = entries[0]
    stream_url = str(entry.get("url") or "").strip()
    if not stream_url:
        raise RuntimeError("Online source returned no direct audio URL.")
    title = str(entry.get("title") or query).strip()
    headers = entry.get("http_headers") or {}
    return stream_url, title, {str(k): str(v) for k, v in headers.items()}


def play_online_media(query: str) -> dict[str, Any]:
    """Search online media and pass the direct stream to VLC; no local-media fallback."""
    query = str(query or "").strip()
    if not query:
        return {"ok": False, "error": "Music or media query is empty."}

    vlc = _find_vlc_exe()
    if vlc is None:
        return {"ok": False, "error": "VLC is not installed or vlc.exe could not be found.", "speak": "وی ال سی روی سیستم پیدا نشد."}

    try:
        stream_url, title, headers = _extract_youtube_audio(query)
        referrer = headers.get("Referer") or headers.get("referer") or "https://www.youtube.com/"
        user_agent = headers.get("User-Agent") or headers.get("user-agent") or "Mozilla/5.0"
        command = [
            vlc, "--one-instance", "--playlist-enqueue", stream_url,
        ]
        subprocess.Popen(command, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        return {"ok": True, "player": "vlc.exe", "title": title, "direct": True, "online": True,
                "speak": f"«{title}» را مستقیم در وی ال سی پخش کردم."}
    except Exception as exc:
        print(f"[Smartis media] direct VLC playback failed: {exc}")
        return {"ok": False, "player": "vlc.exe", "direct": False, "online": True,
                "error": str(exc), "speak": "پخش مستقیم در وی ال سی انجام نشد؛ دلیلش را در لاگ ثبت کردم."}
