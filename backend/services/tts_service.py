from __future__ import annotations

import asyncio
import base64
import json
import os
import platform
import re
import tempfile
import threading
from collections import OrderedDict
from pathlib import Path

try:
    import pyttsx3
except Exception:
    pyttsx3 = None
try:
    import edge_tts
except Exception:
    edge_tts = None
try:
    import pythoncom
except Exception:
    pythoncom = None

from config import ONLINE_TTS_EN_VOICE, ONLINE_TTS_FA_VOICE, ONLINE_TTS_PITCH, ONLINE_TTS_RATE, ONLINE_TTS_VOLUME, BACKEND_DIR

_IS_WINDOWS = platform.system() == "Windows"
_SETTINGS_FILE = BACKEND_DIR / ".voice_settings.json"

VOICE_CHOICES = {
    "fa_female": ("fa-IR-DilaraNeural", "فارسی — زن"),
    "fa_male": ("fa-IR-FaridNeural", "فارسی — مرد"),
    "en_female": ("en-US-JennyNeural", "English — Female"),
    "en_male": ("en-US-GuyNeural", "English — Male"),
}

# A tiny bounded in-memory cache prevents repeated short replies from invoking
# Edge TTS and base64 encoding again. It is deliberately small so Smartis never
# grows without bound during a long session.
_CACHE_LIMIT = 32


def _fa_number(n: int) -> str:
    ones = ["صفر","یک","دو","سه","چهار","پنج","شش","هفت","هشت","نه"]
    teens = ["ده","یازده","دوازده","سیزده","چهارده","پانزده","شانزده","هفده","هجده","نوزده"]
    tens = ["","","بیست","سی","چهل","پنجاه","شصت","هفتاد","هشتاد","نود"]
    hundreds = ["","صد","دویست","سیصد","چهارصد","پانصد","ششصد","هفتصد","هشتصد","نهصد"]
    if n < 10: return ones[n]
    if n < 20: return teens[n-10]
    if n < 100:
        return tens[n//10] + ((" و " + ones[n%10]) if n%10 else "")
    if n < 1000:
        return hundreds[n//100] + ((" و " + _fa_number(n%100)) if n%100 else "")
    if n < 1_000_000:
        return _fa_number(n//1000) + " هزار" + ((" و " + _fa_number(n%1000)) if n%1000 else "")
    if n < 1_000_000_000:
        return _fa_number(n//1_000_000) + " میلیون" + ((" و " + _fa_number(n%1_000_000)) if n%1_000_000 else "")
    return str(n)


def _speak_number(match: re.Match[str]) -> str:
    raw = match.group(0).replace(",", "")
    try:
        if "." in raw:
            a, b = raw.split(".", 1)
            return f"{_fa_number(int(a))} ممیز " + " ".join(_fa_number(int(ch)) for ch in b if ch.isdigit())
        return _fa_number(int(raw))
    except Exception:
        return raw


class TTSService:
    def __init__(self, internet_monitor) -> None:
        self.internet_monitor = internet_monitor
        self.lock = threading.Lock()
        self._settings = {"fa": "fa_male", "en": "en_male"}
        self._cache: OrderedDict[tuple[str, str], dict] = OrderedDict()
        self._load_settings()

    def _load_settings(self) -> None:
        try:
            data = json.loads(_SETTINGS_FILE.read_text(encoding="utf-8"))
            if data.get("fa") in VOICE_CHOICES: self._settings["fa"] = data["fa"]
            if data.get("en") in VOICE_CHOICES: self._settings["en"] = data["en"]
        except Exception:
            pass

    def _save_settings(self) -> None:
        try:
            _SETTINGS_FILE.write_text(json.dumps(self._settings, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception:
            pass

    def settings(self) -> dict:
        return {
            "fa": {"key": self._settings["fa"], "voice": VOICE_CHOICES[self._settings["fa"]][0], "label": VOICE_CHOICES[self._settings["fa"]][1]},
            "en": {"key": self._settings["en"], "voice": VOICE_CHOICES[self._settings["en"]][0], "label": VOICE_CHOICES[self._settings["en"]][1]},
            "choices": [{"key": k, "voice": v[0], "label": v[1]} for k, v in VOICE_CHOICES.items()],
            "cache_entries": len(self._cache),
        }

    def set_voice(self, language: str, gender: str) -> dict:
        lang = "fa" if language == "fa" else "en"
        normalized = str(gender).strip().lower()
        key = f"{lang}_{'female' if normalized in {'female','زن','f','woman'} else 'male'}"
        if key not in VOICE_CHOICES: return {"ok": False, "error": "Unknown voice selection."}
        self._settings[lang] = key
        with self.lock: self._cache.clear()
        self._save_settings()
        return {"ok": True, **self.settings()}

    def _voice(self, language: str | None) -> str:
        lang = "fa" if language == "fa" else "en"
        return VOICE_CHOICES[self._settings[lang]][0]

    @staticmethod
    def _fa_normalize(value: str) -> str:
        value = value.replace("ي", "ی").replace("ى", "ی").replace("ك", "ک").replace("ة", "ه").replace("ۀ", "هٔ")
        value = value.replace("٪", " درصد ").replace("%", " درصد ")
        value = value.replace("°C", " درجه سانتی‌گراد ").replace("°", " درجه ")
        value = value.replace("km/h", " کیلومتر بر ساعت ").replace("MB", " مگابایت ").replace("GB", " گیگابایت ")
        value = re.sub(r"\bCPU\b", " سی پی یو ", value, flags=re.I)
        value = re.sub(r"\bRAM\b", " رم ", value, flags=re.I)
        value = re.sub(r"\bGPU\b", " جی پی یو ", value, flags=re.I)
        value = value.replace("Smartis", "اسمارتیز").replace("SMARTIS", "اسمارتیز")
        # Persian TTS pronounces written-out numbers more naturally than mixed
        # decimal punctuation. This only changes the spoken copy, not UI text.
        value = re.sub(r"(?<![\w])\d{1,9}(?:\.\d+)?(?![\w])", _speak_number, value)
        # Common technical tokens that otherwise get read letter-by-letter.
        replacements = {
            "Wi-Fi": "وای فای", "WiFi": "وای فای", "URL": "آدرس اینترنتی", "API": "ای پی آی",
            "HTTP": "اچ تی تی پی", "HTTPS": "اچ تی تی پی اس", "VLC": "وی ال سی", "Google": "گوگل",
            "Wikipedia": "ویکی پدیا", "YouTube": "یوتیوب", "Chrome": "کروم", "Windows": "ویندوز",
            "Edge": "اج", "TTS": "تبدیل متن به گفتار", "STT": "تبدیل گفتار به متن",
        }
        for src, dst in replacements.items(): value = re.sub(rf"\b{re.escape(src)}\b", dst, value, flags=re.I)
        value = re.sub(r"https?://\S+", "لینک", value, flags=re.I)
        value = re.sub(r"\s*[:;]\s*", "؛ ", value)
        value = re.sub(r"\s*[•|]\s*", "؛ ", value)
        value = re.sub(r"\s*[-–—]\s*", "؛ ", value)
        value = re.sub(r"([،؛.!؟])(?=\S)", r"\1 ", value)
        value = re.sub(r"\s+", " ", value).strip()
        return value

    def _prepare_text(self, text: str, language: str | None) -> str:
        value = str(text or "").strip()
        if language != "fa": return value
        return self._fa_normalize(value)

    async def _save(self, text: str, language: str | None, path: str) -> None:
        prepared = self._prepare_text(text, language)
        rate = ONLINE_TTS_RATE if language != "fa" else "-4%"
        await edge_tts.Communicate(prepared, self._voice(language), rate=rate, volume=ONLINE_TTS_VOLUME, pitch=ONLINE_TTS_PITCH).save(path)

    def _cache_get(self, key: tuple[str, str]) -> dict | None:
        with self.lock:
            item = self._cache.get(key)
            if item:
                self._cache.move_to_end(key)
                return dict(item)
        return None

    def _cache_put(self, key: tuple[str, str], item: dict) -> None:
        with self.lock:
            self._cache[key] = dict(item)
            self._cache.move_to_end(key)
            while len(self._cache) > _CACHE_LIMIT: self._cache.popitem(last=False)

    def _offline(self, text: str, language: str | None) -> dict:
        if pyttsx3 is None: return {"ok": False, "error": "Offline TTS unavailable.", "provider": "windows-sapi"}
        com_ready = False
        if _IS_WINDOWS and pythoncom:
            try: pythoncom.CoInitialize(); com_ready = True
            except Exception: pass
        try:
            with self.lock:
                engine = pyttsx3.init(); voices = engine.getProperty("voices") or []
                hints = ("persian", "farsi", "فارسی", "iran", "1065", "0x429") if language == "fa" else ("english", "en-", "david", "zira", "mark", "409", "0x409")
                selected = None
                want_male = self._settings["en" if language != "fa" else "fa"].endswith("male")
                male_hints = ("david", "mark", "guy", "male"); female_hints = ("zira", "jenny", "female")
                for voice in voices:
                    blob = " ".join([str(getattr(voice,"id","")), str(getattr(voice,"name","")), str(getattr(voice,"languages",""))]).lower()
                    gender_hit = any(h in blob for h in (male_hints if want_male else female_hints))
                    if any(h in blob for h in hints) and (gender_hit or selected is None):
                        selected = voice
                        if gender_hit: break
                if selected: engine.setProperty("voice", selected.id)
                engine.setProperty("rate", 172 if language == "fa" else 180); engine.setProperty("volume", 1.0)
                engine.say(self._prepare_text(text, language)); engine.runAndWait(); engine.stop()
            return {"ok": True, "offline": True, "provider": "windows-sapi", "voice_selected": getattr(selected,"name",None), "audio_base64": None, "estimated_duration_ms": max(700, len(text) * 55)}
        except Exception as exc: return {"ok": False, "error": str(exc), "provider": "windows-sapi"}
        finally:
            if com_ready:
                try: pythoncom.CoUninitialize()
                except Exception: pass

    def speak(self, text: str, language: str | None = None) -> dict:
        text = str(text).strip()
        if not text: return {"ok": False, "error": "Text is empty."}
        lang = "fa" if language == "fa" else "en"
        prepared = self._prepare_text(text, lang)
        key = (lang, self._voice(lang) + "\0" + prepared)
        cached = self._cache_get(key)
        if cached is not None: return {**cached, "cached": True}
        if edge_tts and self.internet_monitor.is_online():
            path = None
            try:
                with tempfile.NamedTemporaryFile(delete=False, suffix=".mp3") as handle: path = handle.name
                asyncio.run(self._save(text, lang, path))
                data = Path(path).read_bytes()
                if data:
                    result = {"ok": True, "offline": False, "provider": "edge-tts", "voice": self._voice(lang), "mime_type": "audio/mpeg", "audio_base64": base64.b64encode(data).decode("ascii"), "cached": False}
                    self._cache_put(key, result)
                    return result
            except Exception:
                pass
            finally:
                if path:
                    try: os.remove(path)
                    except OSError: pass
        return self._offline(text, lang)

    def voices(self) -> list[dict]: return [{"key": k, "voice": v[0], "label": v[1]} for k, v in VOICE_CHOICES.items()]
