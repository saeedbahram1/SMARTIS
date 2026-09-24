from __future__ import annotations

import concurrent.futures
import logging
import os
import threading
import time
from typing import Any, Callable, Optional

try:
    import speech_recognition as sr
except Exception:
    sr = None

try:
    import pyaudio
except Exception:
    pyaudio = None

from config import (
    MIC_DEVICE_INDEX,
    SMARTIS_GOOGLE_FA_LANGUAGE,
    SMARTIS_GOOGLE_EN_LANGUAGE,
    SMARTIS_ENERGY_THRESHOLD,
    SMARTIS_AMBIENT_CALIBRATION_SECONDS,
    SMARTIS_PHRASE_TIME_LIMIT_SECONDS,
    SMARTIS_PAUSE_THRESHOLD,
    SMARTIS_NON_SPEAKING_DURATION,
    SMARTIS_PHRASE_THRESHOLD,
    GOOGLE_STT_TIMEOUT,
    WAKE_PHRASE_TIME_LIMIT_SECONDS,
)
from services.wake_word import detect_wake_word, normalize

logger = logging.getLogger("smartis.voice")


def list_system_microphones() -> list[dict[str, Any]]:
    """List available audio input devices via SpeechRecognition / PyAudio."""
    mics: list[dict[str, Any]] = []
    if sr is None:
        return mics
    try:
        names = sr.Microphone.list_microphone_names()
        for idx, name in enumerate(names):
            mics.append({"index": idx, "name": name})
    except Exception as exc:
        logger.warning(f"Error listing microphones: {exc}")
    return mics


class GoogleVoiceSession:
    """Manages the single active PyAudio microphone session for Smartis.
    
    Guarantees:
    - Exactly ONE active microphone listener session at any time.
    - Online STT via SpeechRecognition.recognize_google (no WAV files on disk).
    - Immediate fallback to local Whisper on network timeout or RequestError.
    - Controlled by WebSocket / internal state machine for wake word and commands.
    """

    def __init__(self, whisper_service, internet_monitor):
        self.whisper = whisper_service
        self.internet = internet_monitor

        self.recognizer: Optional[sr.Recognizer] = None
        self._init_recognizer()

        self._lock = threading.Lock()
        self._mode: str = "idle"  # 'idle', 'wake', 'command'
        self._language: str = "fa"
        self._device_index: Optional[int] = MIC_DEVICE_INDEX

        self._thread: Optional[threading.Thread] = None
        self._stop_requested = threading.Event()
        self._calibrated = False

        self._listeners: list[Callable[[dict[str, Any]], None]] = []
        self._async_callback = None
        self._async_loop = None

    @staticmethod
    def get_microphones() -> list[dict[str, Any]]:
        return list_system_microphones()

    @property
    def is_pyaudio_available(self) -> bool:
        return pyaudio is not None

    @property
    def current_mode(self) -> str:
        return self._mode

    def set_event_callback(self, callback: Optional[Callable[[dict[str, Any]], Any]], loop=None):
        with self._lock:
            self._async_callback = callback
            self._async_loop = loop

    def _init_recognizer(self):
        if sr is None:
            self.recognizer = None
            return
        r = sr.Recognizer()
        r.dynamic_energy_threshold = True
        r.energy_threshold = SMARTIS_ENERGY_THRESHOLD
        r.dynamic_energy_adjustment_damping = 0.15
        r.dynamic_energy_ratio = 1.5
        r.pause_threshold = 0.45
        r.non_speaking_duration = SMARTIS_NON_SPEAKING_DURATION
        r.phrase_threshold = SMARTIS_PHRASE_THRESHOLD
        self.recognizer = r

    def add_listener(self, callback: Callable[[dict[str, Any]], None]):
        with self._lock:
            if callback not in self._listeners:
                self._listeners.append(callback)

    def remove_listener(self, callback: Callable[[dict[str, Any]], None]):
        with self._lock:
            if callback in self._listeners:
                self._listeners.remove(callback)

    def _emit(self, event: dict[str, Any]):
        with self._lock:
            listeners = list(self._listeners)
            async_cb = self._async_callback
            async_loop = self._async_loop
        for listener in listeners:
            try:
                listener(event)
            except Exception as exc:
                logger.debug(f"Error invoking voice listener: {exc}")
        if async_cb and async_loop and not async_loop.is_closed():
            try:
                import asyncio
                if asyncio.iscoroutinefunction(async_cb):
                    asyncio.run_coroutine_threadsafe(async_cb(event), async_loop)
                else:
                    async_loop.call_soon_threadsafe(async_cb, event)
            except Exception as exc:
                logger.debug(f"Error dispatching async voice event: {exc}")

    @property
    def ready(self) -> bool:
        return self.recognizer is not None and sr is not None

    @property
    def mode(self) -> str:
        return self._mode

    def set_device_index(self, index: Optional[int]):
        with self._lock:
            self._device_index = index
            self._calibrated = False

    def start_wake(self, language: str = "fa") -> bool:
        """Start or switch to continuous wake word listening mode."""
        return self._start_session(mode="wake", language=language)

    def start_command(self, language: str = "fa") -> bool:
        """Start listening for a user voice command utterance."""
        return self._start_session(mode="command", language=language)

    def stop(self):
        """Stop listening and release the active microphone stream."""
        self._stop_listening()
        self._emit({"type": "voice_stopped", "mode": "idle"})

    def _stop_listening(self):
        self._stop_requested.set()
        old_thread = None
        with self._lock:
            old_thread = self._thread
            self._mode = "idle"
        if old_thread and old_thread.is_alive() and old_thread != threading.current_thread():
            old_thread.join(timeout=2.0)
        with self._lock:
            self._thread = None

    def _start_session(self, mode: str, language: str) -> bool:
        if not self.ready:
            self._emit({
                "type": "voice_fatal",
                "error": "SpeechRecognition / PyAudio is not available on this system."
            })
            return False

        with self._lock:
            if self._mode == mode and self._language == language and self._thread and self._thread.is_alive():
                self._emit({
                    "type": "voice_ready",
                    "mode": mode,
                    "language": language,
                    "device_index": self._device_index,
                })
                return True

        # Stop existing background listener to satisfy the ONE microphone rule
        self._stop_listening()
        self._stop_requested.clear()

        with self._lock:
            self._mode = mode
            self._language = language
            self._thread = threading.Thread(
                target=self._worker_loop,
                args=(mode, language),
                daemon=True,
                name=f"GoogleVoice-{mode}"
            )
            self._thread.start()

        self._emit({
            "type": "voice_ready",
            "mode": mode,
            "language": language,
            "device_index": self._device_index,
        })
        return True

    def _worker_loop(self, initial_mode: str, initial_language: str):
        mode = initial_mode
        language = initial_language

        mic = None
        try:
            mic = sr.Microphone(device_index=self._device_index)
        except Exception as exc:
            logger.error(f"Cannot initialize microphone: {exc}")
            self._emit({
                "type": "voice_fatal",
                "error": f"Microphone initialization failed: {exc}"
            })
            with self._lock:
                self._mode = "idle"
            return

        try:
            with mic as source:
                # One-time ambient calibration if needed
                if not self._calibrated and not self._stop_requested.is_set():
                    try:
                        self.recognizer.adjust_for_ambient_noise(
                            source,
                            duration=min(0.3, SMARTIS_AMBIENT_CALIBRATION_SECONDS),
                        )
                        # Keep threshold strictly in human voice range:
                        # Floor 40.0, ceiling 110.0 so speech (150-350 RMS) is never blocked!
                        target_cap = max(65.0, min(SMARTIS_ENERGY_THRESHOLD, 110.0))
                        self.recognizer.energy_threshold = max(40.0, min(self.recognizer.energy_threshold, target_cap))
                        self._calibrated = True
                        print(f"[Smartis Voice] Calibrated ambient noise: energy_threshold={self.recognizer.energy_threshold:.1f} (ready for 'اسمارتیز' / 'سعید')")
                    except Exception as exc:
                        print(f"[Smartis Voice] Ambient noise calibration warning: {exc}")
                        self.recognizer.energy_threshold = SMARTIS_ENERGY_THRESHOLD

                    self._emit({
                        "type": "calibrating",
                        "duration": SMARTIS_AMBIENT_CALIBRATION_SECONDS,
                        "mode": mode,
                        "energy_threshold": round(self.recognizer.energy_threshold, 1),
                    })

                while not self._stop_requested.is_set():
                    with self._lock:
                        current_mode = self._mode
                        current_language = self._language

                    if current_mode == "idle":
                        break

                    # Dynamically set pause_threshold: tight for wake word, normal for commands
                    if current_mode == "wake":
                        self.recognizer.pause_threshold = 0.45
                    else:
                        self.recognizer.pause_threshold = SMARTIS_PAUSE_THRESHOLD

                    self._emit({
                        "type": "listening",
                        "mode": current_mode,
                        "language": current_language,
                    })

                    time_limit = (
                        WAKE_PHRASE_TIME_LIMIT_SECONDS
                        if current_mode == "wake"
                        else SMARTIS_PHRASE_TIME_LIMIT_SECONDS
                    )
                    timeout = 4.0 if current_mode == "wake" else 15.0

                    try:
                        audio = self.recognizer.listen(
                            source,
                            timeout=timeout,
                            phrase_time_limit=time_limit,
                        )
                    except sr.WaitTimeoutError:
                        if current_mode == "command":
                            self._emit({
                                "type": "recognition_error",
                                "mode": "command",
                                "error": "timeout",
                                "message": "No speech detected within time limit."
                            })
                            with self._lock:
                                self._mode = "idle"
                            break
                        continue
                    except Exception as exc:
                        if self._stop_requested.is_set():
                            break
                        logger.warning(f"Audio capture error: {exc}")
                        self._emit({
                            "type": "voice_error",
                            "error": str(exc),
                            "mode": current_mode,
                        })
                        time.sleep(0.1)
                        continue

                    if self._stop_requested.is_set():
                        break

                    audio_dur = len(audio.frame_data) / (audio.sample_rate * audio.sample_width)
                    print(f"[Smartis Voice] Audio captured ({audio_dur:.2f}s)! Running STT...")

                    self._emit({
                        "type": "speech_captured",
                        "mode": current_mode,
                        "duration": round(audio_dur, 2),
                    })

                    # Perform STT
                    stt_result = self._transcribe_audio(audio, current_language, fast=(current_mode == "wake"))

                    if not stt_result.get("ok"):
                        err = stt_result.get("error", "")
                        if "UnknownValueError" not in err and "could not understand" not in err:
                            self._emit({
                                "type": "recognition_error",
                                "mode": current_mode,
                                "error": err,
                            })
                        continue

                    text = stt_result.get("text", "").strip()
                    provider = stt_result.get("provider", "google")
                    is_offline = bool(stt_result.get("offline", False))
                    detected_lang = stt_result.get("language") or current_language

                    self._emit({
                        "type": "transcript",
                        "mode": current_mode,
                        "text": text,
                        "provider": provider,
                        "offline": is_offline,
                    })

                    if current_mode == "wake":
                        # Normalize and check wake word
                        wake_check = detect_wake_word(text)
                        if wake_check.get("detected"):
                            detected_wake_lang = wake_check.get("language") or detected_lang
                            w_word = wake_check.get("wake_word")
                            print(f"[Smartis Voice] >>> WAKE WORD MATCHED: '{w_word}'! Replying 'جانم'... <<<")
                            self._emit({
                                "type": "wake_detected",
                                "wake_word": w_word,
                                "language": detected_wake_lang,
                                "text": text,
                                "provider": provider,
                                "offline": is_offline,
                            })
                            # Stop wake listening loop and wait for Flutter command prompt
                            with self._lock:
                                self._mode = "idle"
                            break
                        else:
                            print(f"[Smartis Voice] Heard: '{text}' (no wake match; say 'اسمارتیز' or 'سعید')")
                            self._emit({
                                "type": "wake_miss",
                                "text": text,
                                "mode": "wake",
                            })
                        # Otherwise continue listening for wake word

                    elif current_mode == "command":
                        self._emit({
                            "type": "command_final",
                            "text": text,
                            "language": detected_lang,
                            "provider": provider,
                            "offline": is_offline,
                        })
                        # One command captured; finish command session
                        with self._lock:
                            self._mode = "idle"
                        break

        except Exception as exc:
            if not self._stop_requested.is_set():
                logger.error(f"Voice session worker crashed: {exc}")
                self._emit({"type": "voice_fatal", "error": str(exc)})
        finally:
            with self._lock:
                self._mode = "idle"

    def _transcribe_audio(self, audio: sr.AudioData, language: str, fast: bool = False) -> dict[str, Any]:
        """Convert AudioData to text via Google Web Speech API (online) with
        seamless fallback to local Whisper."""
        stt_result = None

        # 1. Online pass via Google recognize_google
        if self.internet.is_online() and self.recognizer is not None:
            # When waking, timeout quickly (2.0s) so Whisper can step in if Google hangs
            google_timeout = 2.0 if fast else GOOGLE_STT_TIMEOUT
            langs_to_try = [language]
            if fast:
                alt = "en" if language == "fa" else "fa"
                langs_to_try.append(alt)

            for lang_cand in langs_to_try:
                lang_tag = SMARTIS_GOOGLE_FA_LANGUAGE if lang_cand == "fa" else SMARTIS_GOOGLE_EN_LANGUAGE
                try:
                    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
                        future = executor.submit(
                            self.recognizer.recognize_google,
                            audio,
                            language=lang_tag,
                        )
                        text = future.result(timeout=google_timeout).strip()

                    if text:
                        print(f"[Smartis Voice] Google STT ({lang_tag}) -> '{text}'")
                        stt_result = {
                            "ok": True,
                            "text": text,
                            "language": lang_cand,
                            "provider": "google",
                            "offline": False,
                        }
                        if fast and detect_wake_word(text).get("detected"):
                            return stt_result
                        if not fast:
                            return stt_result
                except concurrent.futures.TimeoutError:
                    print(f"[Smartis Voice] Google STT ({lang_tag}) timed out after {google_timeout}s")
                except sr.UnknownValueError:
                    pass
                except Exception as exc:
                    print(f"[Smartis Voice] Google STT ({lang_tag}) notice: {exc}")

        # If Google found text and wake word matched, return it
        if stt_result and stt_result.get("ok"):
            if not fast or detect_wake_word(stt_result.get("text", "")).get("detected"):
                return stt_result

        # 2. Fallback to local Whisper
        # (Runs if Google is filtered/offline, returned UnknownValueError, or didn't detect wake word)
        if self.whisper.ready:
            print("[Smartis Voice] Running Whisper STT fallback...")
            whisper_result = self.whisper.transcribe_audio_data(
                audio,
                language_hint=None if fast else language,
                fast=fast,
            )
            if whisper_result.get("ok"):
                print(f"[Smartis Voice] Whisper STT -> '{whisper_result.get('text')}' (lang={whisper_result.get('language')})")
                return whisper_result
            else:
                print(f"[Smartis Voice] Whisper STT failed: {whisper_result.get('error')}")

        if stt_result and stt_result.get("ok"):
            return stt_result

        return {
            "ok": False,
            "error": "Could not understand audio.",
            "provider": "none",
        }
