from __future__ import annotations

import threading
import time
from typing import Optional

import requests

try:
    import speech_recognition as sr
except Exception:
    sr = None

from config import INTERNET_CHECK_TIMEOUT, INTERNET_CACHE_SECONDS
from services.wake_word import detect_wake_word


class InternetMonitor:
    def __init__(self):
        self._lock = threading.Lock()
        self._last_check = 0.0
        self._online = False

    def is_online(self, force: bool = False) -> bool:
        now = time.monotonic()
        with self._lock:
            if not force and now - self._last_check < INTERNET_CACHE_SECONDS:
                return self._online

            online = False
            for url in (
                "https://www.google.com/generate_204",
                "https://www.msftconnecttest.com/connecttest.txt",
            ):
                try:
                    response = requests.get(
                        url,
                        timeout=INTERNET_CHECK_TIMEOUT,
                        allow_redirects=True,
                    )
                    if response.status_code in (200, 204):
                        online = True
                        break
                except requests.RequestException:
                    continue

            self._last_check = now
            self._online = online
            return online


class OnlineSTT:
    """Online speech-to-text using Google's Web Speech API via the
    SpeechRecognition library (the same library/engine PyAudio hands live
    microphone audio to; here it is fed a recorded WAV file instead, which
    is the correct mode when the audio is captured by the Flutter app and
    uploaded to the backend)."""

    def __init__(self):
        self.recognizer = sr.Recognizer() if sr else None
        if self.recognizer:
            self.recognizer.dynamic_energy_threshold = True
            self.recognizer.pause_threshold = 1.15
            self.recognizer.non_speaking_duration = 0.55
            self.recognizer.phrase_threshold = 0.10

    @property
    def ready(self):
        return self.recognizer is not None

    def transcribe_google(self, audio_path, language):
        if not self.ready:
            return {
                "ok": False,
                "error": "SpeechRecognition is unavailable.",
                "provider": "google-speech-recognition",
            }
        tag = "fa-IR" if language == "fa" else "en-US"
        try:
            with sr.AudioFile(audio_path) as source:
                audio = self.recognizer.record(source)
            text = self.recognizer.recognize_google(audio, language=tag).strip()
            if not text:
                return {
                    "ok": False,
                    "error": "Google returned empty text.",
                    "provider": "google-speech-recognition",
                }
            return {
                "ok": True,
                "text": text,
                "language": language,
                "offline": False,
                "provider": "google-speech-recognition",
            }
        except sr.UnknownValueError:
            return {
                "ok": False,
                "error": "Google could not understand the audio.",
                "provider": "google-speech-recognition",
            }
        except sr.RequestError as exc:
            return {
                "ok": False,
                "error": f"Google Speech API request failed: {exc}",
                "provider": "google-speech-recognition",
            }
        except Exception as exc:
            return {"ok": False, "error": str(exc), "provider": "google-speech-recognition"}


class SpeechRouter:
    def __init__(self, whisper):
        self.whisper = whisper
        self.internet = InternetMonitor()
        self.google = OnlineSTT()

    def transcribe(self, audio_path, language_hint: Optional[str] = None, wake=False):
        google_errors = []
        if self.internet.is_online() and self.google.ready:
            languages = [language_hint] if language_hint in ("fa", "en") else ["fa", "en"]

            for language in languages:
                result = self.google.transcribe_google(audio_path, language)
                if result.get("ok"):
                    if wake:
                        result["wake"] = detect_wake_word(result.get("text", ""))
                    return result
                google_errors.append(f"{language}: {result.get('error')}")

        # No internet, Google unavailable, or the online pass failed:
        # use the local (offline) Whisper model instead.
        result = self.whisper.transcribe_file(
            audio_path,
            language_hint=language_hint,
            fast=wake,
        )
        if google_errors:
            # Surfaced only for diagnostics (server console log); the Google
            # attempt(s) failed before we fell back to Whisper.
            result["google_attempted"] = google_errors
        if wake and result.get("ok"):
            result["wake"] = detect_wake_word(result.get("text", ""))
        return result

    def status(self):
        internet = self.internet.is_online(force=True)
        return {
            "internet": internet,
            "online_stt_ready": self.google.ready,
            "offline_stt_ready": self.whisper.ready,
        }
