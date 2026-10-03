from __future__ import annotations

"""Continuous Windows microphone capture for Smartis.

Smartis listens continuously for a spoken command, then pauses while the
command is processed and TTS is played.
"""

import math
import queue
import threading
import time
from collections import deque
from dataclasses import dataclass
from typing import Optional

import numpy as np

try:
    import sounddevice as sd
except Exception:  # pragma: no cover - environment dependent
    sd = None

from config import MICROPHONE_DEVICE
from services.sherpa_service import SherpaService


@dataclass
class _CommandState:
    started_at: float
    speech_started: bool = False
    last_voice_at: Optional[float] = None


class MicrophoneService:
    """Stable always-listening microphone with command segmentation."""

    TARGET_SAMPLE_RATE = 16000
    COMMAND_MAX_SECONDS = 12.0
    # Mirrors the fast endpointer style used by VoiceControl: finish a
    # command shortly after the user stops speaking instead of waiting >1s.
    COMMAND_SILENCE_SECONDS = 0.30
    COMMAND_MIN_SECONDS = 0.25
    MIN_SPEECH_BLOCKS = 3  # ~150 ms at the 50 ms audio callback rate
    AUTO_RESUME_PAUSED_SECONDS = 120.0
    LEVEL_MIN_DB = -60.0
    # Absolute lower bounds of the speech gate. The thresholds actually used at
    # runtime are derived from the measured ambient noise floor and clamped to
    # these values, so a quiet room keeps the historical sensitivity while a
    # noisy room (or Windows AGC pushing the floor up) still endpoints instead
    # of running every command into COMMAND_MAX_SECONDS.
    SPEECH_START_DB = -54.0
    SPEECH_CONTINUE_DB = -61.0
    SPEECH_START_PEAK_DB = -40.0
    SPEECH_CONTINUE_PEAK_DB = -49.0
    NOISE_START_MARGIN_DB = 7.0
    NOISE_CONTINUE_MARGIN_DB = 3.5
    NOISE_START_PEAK_MARGIN_DB = 12.0
    NOISE_CONTINUE_PEAK_MARGIN_DB = 8.0
    NOISE_FLOOR_MIN_DB = -95.0
    NOISE_FLOOR_MAX_DB = -35.0
    NOISE_SMOOTHING = 0.06
    NOISE_PEAK_SMOOTHING = 0.10
    NOISE_INITIAL_DB = -64.0
    NOISE_PEAK_INITIAL_DB = -52.0
    PRE_ROLL_BLOCKS = 5

    def __init__(self, stt: SherpaService) -> None:
        self.stt = stt
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._blocks: queue.Queue[np.ndarray] = queue.Queue(maxsize=160)
        self._subscribers: set[queue.Queue] = set()
        self._subscribers_lock = threading.Lock()
        self._state_lock = threading.Lock()
        self._state = "stopped"  # stopped | listening | paused | error
        self._last_error: Optional[str] = None
        self._device_name: Optional[str] = None
        self._native_sample_rate: Optional[int] = None
        self._command_buffer: list[np.ndarray] = []
        self._command_frames = 0
        self._speech_blocks = 0
        self._command: Optional[_CommandState] = None
        self._paused_since: Optional[float] = None
        self._last_level_emit = 0.0
        self._last_level = 0.0
        self._pre_roll: deque[np.ndarray] = deque(maxlen=self.PRE_ROLL_BLOCKS)
        self._noise_db = self.NOISE_INITIAL_DB
        self._noise_peak_db = self.NOISE_PEAK_INITIAL_DB

    def _speech_start_db(self) -> float:
        return max(self.SPEECH_START_DB, self._noise_db + self.NOISE_START_MARGIN_DB)

    def _speech_continue_db(self) -> float:
        return max(self.SPEECH_CONTINUE_DB, self._noise_db + self.NOISE_CONTINUE_MARGIN_DB)

    def _speech_start_peak_db(self) -> float:
        return max(
            self.SPEECH_START_PEAK_DB,
            self._noise_peak_db + self.NOISE_START_PEAK_MARGIN_DB,
        )

    def _speech_continue_peak_db(self) -> float:
        return max(
            self.SPEECH_CONTINUE_PEAK_DB,
            self._noise_peak_db + self.NOISE_CONTINUE_PEAK_MARGIN_DB,
        )

    def _update_noise_floor(self, db: float, peak_db: float) -> None:
        """Adapt the ambient estimate from blocks that are below the gate."""
        self._noise_db += self.NOISE_SMOOTHING * (db - self._noise_db)
        self._noise_peak_db += self.NOISE_PEAK_SMOOTHING * (peak_db - self._noise_peak_db)
        self._noise_db = min(max(self._noise_db, self.NOISE_FLOOR_MIN_DB), self.NOISE_FLOOR_MAX_DB)
        self._noise_peak_db = min(
            max(self._noise_peak_db, self.NOISE_FLOOR_MIN_DB), self.NOISE_FLOOR_MAX_DB
        )

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    @property
    def state(self) -> str:
        with self._state_lock:
            return self._state

    def status_dict(self) -> dict:
        return {
            "running": self.running,
            "state": self.state,
            "device": self._device_name,
            "sample_rate": self._native_sample_rate,
            "error": self._last_error,
            "always_listening": True,
            "noise_db": round(self._noise_db, 1),
            "gate_db": round(self._speech_start_db(), 1),
        }

    def subscribe(self) -> queue.Queue:
        q: queue.Queue = queue.Queue(maxsize=100)
        with self._subscribers_lock:
            self._subscribers.add(q)
        return q

    def unsubscribe(self, q: queue.Queue) -> None:
        with self._subscribers_lock:
            self._subscribers.discard(q)

    def _emit(self, event: dict) -> None:
        # Convert numpy scalars before an event ever reaches the WebSocket.
        event = self._json_safe(event)
        with self._subscribers_lock:
            subscribers = tuple(self._subscribers)
        for q in subscribers:
            try:
                q.put_nowait(event)
            except queue.Full:
                try:
                    q.get_nowait()
                except queue.Empty:
                    pass
                try:
                    q.put_nowait(event)
                except queue.Full:
                    pass

    @staticmethod
    def _json_safe(value):
        if isinstance(value, np.generic):
            return value.item()
        if isinstance(value, dict):
            return {str(k): MicrophoneService._json_safe(v) for k, v in value.items()}
        if isinstance(value, (list, tuple)):
            return [MicrophoneService._json_safe(v) for v in value]
        return value

    def start(self) -> None:
        if self.running:
            return
        while True:
            try:
                self._blocks.get_nowait()
            except queue.Empty:
                break
        self._command_buffer = []
        self._command_frames = 0
        self._speech_blocks = 0
        self._command = None
        self._paused_since = None
        self._pre_roll.clear()
        self._last_error = None
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._run,
            name="smartis-microphone",
            daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        thread = self._thread
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=2.5)
        self._thread = None
        self._set_state("stopped")

    def restart(self) -> None:
        self.stop()
        self.start()

    def stop_command(self) -> dict:
        self.pause_listening()
        return {"ok": True, "state": self.state}

    def pause_listening(self) -> dict:
        if not self.running:
            return {"ok": False, "error": "Microphone service is not running."}
        with self._state_lock:
            self._state = "paused"
            self._paused_since = time.monotonic()
            self._command = None
            self._command_buffer = []
            self._command_frames = 0
            self._speech_blocks = 0
            self._pre_roll.clear()
        self._emit({"type": "mic_state", "state": "paused"})
        return {"ok": True, "state": "paused"}

    def resume_listening(self) -> dict:
        if not self.running:
            return {"ok": False, "error": "Microphone service is not running."}
        with self._state_lock:
            self._state = "listening"
            self._paused_since = None
            self._command = None
            self._command_buffer = []
            self._command_frames = 0
            self._speech_blocks = 0
            self._pre_roll.clear()
        self._emit({"type": "mic_state", "state": "listening"})
        return {"ok": True, "state": "listening"}

    def _set_state(self, state: str) -> None:
        with self._state_lock:
            self._state = state
            if state != "paused":
                self._paused_since = None
            if state != "listening":
                self._command = None
        self._emit({"type": "mic_state", "state": state})

    def _run(self) -> None:
        if sd is None:
            self._last_error = "sounddevice is not installed."
            self._set_state("error")
            self._emit({"type": "mic_error", "error": self._last_error})
            return

        try:
            device = (
                sd.query_devices(MICROPHONE_DEVICE)
                if MICROPHONE_DEVICE
                else sd.query_devices(kind="input")
            )
            if not device or int(device.get("max_input_channels", 0)) < 1:
                raise RuntimeError("No Windows input microphone is available.")
            self._device_name = str(device.get("name") or "Default input device")
            native_rate = int(round(float(device.get("default_samplerate") or 48000)))
            if native_rate < 8000:
                native_rate = 48000
            self._native_sample_rate = native_rate

            def callback(indata, frames, time_info, status) -> None:
                del frames, time_info
                if status:
                    self._last_error = str(status)
                try:
                    block = np.asarray(indata[:, 0], dtype=np.int16).copy()
                    try:
                        self._blocks.put_nowait(block)
                    except queue.Full:
                        self._blocks.get_nowait()
                        self._blocks.put_nowait(block)
                except Exception as exc:
                    self._last_error = str(exc)

            self._set_state("listening")
            self._emit(
                {
                    "type": "mic_ready",
                    "device": self._device_name,
                    "sample_rate": self._native_sample_rate,
                    "direct_listening": True,
                }
            )

            with sd.InputStream(
                samplerate=native_rate,
                channels=1,
                dtype="int16",
                blocksize=max(400, int(native_rate * 0.05)),
                latency="low",
                callback=callback,
            ):
                while not self._stop_event.is_set():
                    try:
                        block = self._blocks.get(timeout=0.25)
                    except queue.Empty:
                        self._tick()
                        continue
                    if self.state == "paused":
                        # Drain audio captured while Smartis is executing/TTSing.
                        # Never replay this audio as a new command after resume.
                        self._tick()
                        continue
                    self._process_block(block)
                    self._tick()
        except Exception as exc:
            self._last_error = str(exc)
            self._set_state("error")
            self._emit({"type": "mic_error", "error": self._last_error})
        finally:
            if self._stop_event.is_set():
                self._set_state("stopped")

    def _tick(self) -> None:
        if self.state == "paused" and self._paused_since is not None:
            if time.monotonic() - self._paused_since >= self.AUTO_RESUME_PAUSED_SECONDS:
                self.resume_listening()

    def _process_block(self, block: np.ndarray) -> None:
        if block.size == 0:
            return
        # Measure once per block: the level meter and the endpointer need the
        # same RMS/peak numbers, and computing them twice costs ~20 ms of CPU
        # per second of audio for no benefit.
        samples = block.astype(np.float32) / 32768.0
        rms = float(np.sqrt(np.mean(np.square(samples))))
        db = 20.0 * math.log10(max(rms, 1e-9))
        peak = float(np.max(np.abs(samples)))
        peak_db = 20.0 * math.log10(max(peak, 1e-9))
        self._emit_level(db)
        if self.state == "listening":
            self._process_command_block(block, db, peak_db)

    def _emit_level(self, db: float) -> None:
        linear_level = max(0.0, min(1.0, (db - self.LEVEL_MIN_DB) / abs(self.LEVEL_MIN_DB)))
        # Compress quiet speech upward so the HUD follows a normal microphone
        # voice visibly instead of looking flat until the user gets loud.
        level = linear_level ** 0.62 if linear_level > 0 else 0.0
        now = time.monotonic()
        if now - self._last_level_emit >= 0.05 or abs(level - self._last_level) >= 0.04:
            self._last_level_emit = now
            self._last_level = level
            self._emit(
                {
                    "type": "mic_level",
                    "level": round(level, 3),
                    "db": round(db, 1),
                    "noise_db": round(self._noise_db, 1),
                    "gate_db": round(self._speech_start_db(), 1),
                }
            )

    def _process_command_block(self, block: np.ndarray, db: float, peak_db: float) -> None:
        now = time.monotonic()
        speech_now = db >= self._speech_start_db() or peak_db >= self._speech_start_peak_db()
        speech_continue = (
            db >= self._speech_continue_db() or peak_db >= self._speech_continue_peak_db()
        )
        if not speech_now:
            self._update_noise_floor(db, peak_db)

        if self._command is None:
            self._pre_roll.append(block)
            if not speech_now:
                return
            self._command = _CommandState(
                started_at=now,
                speech_started=True,
                last_voice_at=now,
            )
            self._command_buffer = list(self._pre_roll)
            self._command_frames = sum(len(chunk) for chunk in self._command_buffer)
            self._speech_blocks = 1
            self._pre_roll.clear()
            return

        command = self._command
        self._command_buffer.append(block)
        self._command_frames += len(block)

        if speech_now:
            self._speech_blocks += 1
            command.speech_started = True
            command.last_voice_at = now
        elif command.speech_started and speech_continue:
            command.last_voice_at = now

        elapsed = now - command.started_at
        if command.last_voice_at is not None:
            quiet_for = now - command.last_voice_at
            if (self._speech_blocks >= self.MIN_SPEECH_BLOCKS
                    and elapsed >= self.COMMAND_MIN_SECONDS
                    and quiet_for >= self.COMMAND_SILENCE_SECONDS):
                self._finish_command()
                return

        if elapsed >= self.COMMAND_MAX_SECONDS:
            self._finish_command()

    def _finish_command(self) -> None:
        command = self._command
        if command is None:
            return
        blocks = self._command_buffer
        self._command = None
        self._command_buffer = []
        self._command_frames = 0
        self._speech_blocks = 0
        self._pre_roll.clear()
        self.pause_listening()

        if not blocks:
            self._emit({"type": "command_result", "ok": False, "error": "empty_audio"})
            return

        raw = np.concatenate(blocks)
        samples = self._resample(raw, self._native_sample_rate or 48000)
        if not command.speech_started:
            self._emit(
                {
                    "type": "command_result",
                    "ok": False,
                    "text": "",
                    "language": None,
                    "offline": True,
                    "provider": "sherpa-onnx",
                    "error": "no_speech",
                }
            )
            return

        threading.Thread(
            target=self._decode_and_emit,
            args=(samples, time.monotonic()),
            name="smartis-stt-command",
            daemon=True,
        ).start()

    def _decode_and_emit(self, samples: np.ndarray, started_at: float) -> None:
        result = dict(
            self.stt.transcribe_samples(
                samples,
                self.TARGET_SAMPLE_RATE,
                language_hint=None,
            )
        )
        result["stt_elapsed_ms"] = round((time.monotonic() - started_at) * 1000)
        result["audio_seconds"] = round(samples.size / float(self.TARGET_SAMPLE_RATE), 2)
        result["type"] = "command_result"
        self._emit(result)

    @staticmethod
    def _resample(samples: np.ndarray, source_rate: int) -> np.ndarray:
        samples = np.asarray(samples, dtype=np.float32).reshape(-1) / 32768.0
        if samples.size == 0 or source_rate == MicrophoneService.TARGET_SAMPLE_RATE:
            return samples
        target_size = max(
            1,
            int(round(samples.size * MicrophoneService.TARGET_SAMPLE_RATE / source_rate)),
        )
        source_positions = np.linspace(0.0, 1.0, samples.size, endpoint=False)
        target_positions = np.linspace(0.0, 1.0, target_size, endpoint=False)
        return np.interp(target_positions, source_positions, samples).astype(np.float32)
