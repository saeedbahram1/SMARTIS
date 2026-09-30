from __future__ import annotations

"""Offline Persian/English speech recognition via sherpa-onnx."""

import threading
import re
from pathlib import Path
from typing import Optional

import numpy as np

from config import SHERPA_EN_DIR, SHERPA_FA_DIR, SHERPA_NUM_THREADS

try:
    import sherpa_onnx
except Exception:  # pragma: no cover - environment dependent
    sherpa_onnx = None

try:
    import soundfile as sf
except Exception:  # pragma: no cover - environment dependent
    sf = None


class SherpaService:
    TARGET_SAMPLE_RATE = 16000
    SILENCE_RMS_DB = -58.0
    SILENCE_PEAK_DB = -48.0

    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.fa_recognizer = None
        self.en_recognizer = None
        self.fa_error: Optional[str] = None
        self.en_error: Optional[str] = None
        self.status = "not_loaded"

    def load(self) -> None:
        if sherpa_onnx is None:
            self.fa_error = self.en_error = "sherpa-onnx is not installed."
            self.status = "error"
            return

        self.status = "loading"
        self.fa_error = None
        self.en_error = None

        fa_model = Path(SHERPA_FA_DIR) / "model.onnx"
        fa_tokens = Path(SHERPA_FA_DIR) / "tokens.txt"
        if fa_model.exists() and fa_tokens.exists():
            try:
                self.fa_recognizer = sherpa_onnx.OfflineRecognizer.from_nemo_ctc(
                    model=str(fa_model),
                    tokens=str(fa_tokens),
                    num_threads=SHERPA_NUM_THREADS,
                )
            except Exception as exc:  # pragma: no cover - model/runtime dependent
                self.fa_error = f"Could not load Persian model: {exc}"
        else:
            self.fa_error = (
                f"Persian model files not found in {SHERPA_FA_DIR}. "
                "Run SETUP_SHERPA_MODELS.bat first."
            )

        en_dir = Path(SHERPA_EN_DIR)
        en_tokens = en_dir / "tokens.txt"
        en_encoder = en_dir / "encoder-epoch-99-avg-1.onnx"
        en_decoder = en_dir / "decoder-epoch-99-avg-1.onnx"
        en_joiner = en_dir / "joiner-epoch-99-avg-1.onnx"
        if all(path.exists() for path in (en_tokens, en_encoder, en_decoder, en_joiner)):
            try:
                self.en_recognizer = sherpa_onnx.OfflineRecognizer.from_transducer(
                    tokens=str(en_tokens),
                    encoder=str(en_encoder),
                    decoder=str(en_decoder),
                    joiner=str(en_joiner),
                    num_threads=SHERPA_NUM_THREADS,
                )
            except Exception as exc:  # pragma: no cover - model/runtime dependent
                self.en_error = f"Could not load English model: {exc}"
        else:
            self.en_error = (
                f"English model files not found in {SHERPA_EN_DIR}. "
                "Run SETUP_SHERPA_MODELS.bat first."
            )

        self.status = "ready" if self.ready else "error"

    @property
    def ready(self) -> bool:
        return self.fa_recognizer is not None or self.en_recognizer is not None

    @staticmethod
    def _levels(samples: np.ndarray) -> dict:
        samples = np.asarray(samples, dtype=np.float32).reshape(-1)
        if samples.size == 0:
            return {"peak_db": None, "rms_db": None, "is_silent": True}

        peak = float(np.max(np.abs(samples)))
        rms = float(np.sqrt(np.mean(np.square(samples))))
        peak_db = 20.0 * np.log10(max(peak, 1e-9))
        rms_db = 20.0 * np.log10(max(rms, 1e-9))
        return {
            "peak_db": float(round(peak_db, 1)),
            "rms_db": float(round(rms_db, 1)),
            "is_silent": bool(
                rms_db < SherpaService.SILENCE_RMS_DB
                and peak_db < SherpaService.SILENCE_PEAK_DB
            ),
        }

    @staticmethod
    def _decode(recognizer, samples: np.ndarray, sample_rate: int) -> str:
        stream = recognizer.create_stream()
        stream.accept_waveform(sample_rate, samples)
        recognizer.decode_stream(stream)
        return (stream.result.text or "").strip()

    @staticmethod
    def _script_counts(text: str) -> tuple[int, int]:
        fa = sum(1 for ch in text if "\u0600" <= ch <= "\u06ff")
        en = sum(1 for ch in text if ("a" <= ch.lower() <= "z"))
        return fa, en

    @classmethod
    def _looks_persian(cls, text: str) -> bool:
        fa, en = cls._script_counts(text)
        if fa < 2:
            return False
        return fa >= en or fa >= 0.25 * max(1, len(text))

    @classmethod
    def _looks_english(cls, text: str) -> bool:
        fa, en = cls._script_counts(text)
        if en < 2:
            return False
        return en > fa or en >= 0.30 * max(1, len(text))

    @staticmethod
    def _trim_silence(samples: np.ndarray, sample_rate: int) -> np.ndarray:
        """Remove only long leading/trailing silence so CTC decode is faster."""
        values = np.asarray(samples, dtype=np.float32).reshape(-1)
        if values.size < max(1, int(sample_rate * 0.10)):
            return values
        frame = max(160, int(sample_rate * 0.02))
        threshold = 10 ** (-48.0 / 20.0)
        active: list[tuple[int, int]] = []
        for start in range(0, values.size, frame):
            chunk = values[start:start + frame]
            if chunk.size == 0:
                continue
            rms = float(np.sqrt(np.mean(np.square(chunk))))
            peak = float(np.max(np.abs(chunk)))
            if rms >= threshold or peak >= threshold * 1.8:
                active.append((start, min(values.size, start + frame)))
        if not active:
            return values
        pad = int(sample_rate * 0.06)
        left = max(0, active[0][0] - pad)
        right = min(values.size, active[-1][1] + pad)
        return values[left:right]

    @classmethod
    def is_usable_transcript(cls, text: str) -> bool:
        value = re.sub(r"[^\w\u0600-\u06FF]+", " ", str(text or "").strip(), flags=re.UNICODE).strip()
        if len(value) < 2:
            return False
        words = [w for w in value.split() if w]
        # Very short English one-word hypotheses are the most common cough/noise
        # false positives. Persian remains primary and known one-word commands
        # are allowed.
        fa, en = cls._script_counts(value)
        if en > fa and len(words) == 1 and len(value) < 5:
            return False
        if len(words) == 1 and value.lower() in {"uh","um","hmm","mm","the","a","i","oh","ah","er"}:
            return False
        return True

    def transcribe_samples(
        self,
        samples,
        sample_rate: int,
        language_hint: Optional[str] = None,
        fast: bool = False,
    ) -> dict:
        del fast  # retained for compatibility with older call sites
        samples = np.asarray(samples, dtype=np.float32).reshape(-1)
        if samples.size == 0:
            return {
                "ok": False,
                "text": "",
                "language": None,
                "offline": True,
                "provider": "sherpa-onnx",
                "error": "empty_audio",
                "levels": self._levels(samples),
            }

        levels = self._levels(samples)
        if levels["is_silent"]:
            return {
                "ok": False,
                "text": "",
                "language": None,
                "offline": True,
                "provider": "sherpa-onnx",
                "error": "silence",
                "levels": levels,
            }

        samples = self._trim_silence(samples, int(sample_rate))

        if language_hint == "fa" and self.fa_recognizer is not None:
            with self.lock:
                text = self._decode(self.fa_recognizer, samples, int(sample_rate))
            language = "fa" if text else None
        elif language_hint == "en" and self.en_recognizer is not None:
            with self.lock:
                text = self._decode(self.en_recognizer, samples, int(sample_rate))
            language = "en" if text else None
        else:
            # Persian is the primary language. Decode Persian first so normal
            # Persian commands pay for only one model. English is decoded only
            # when the Persian hypothesis is empty or clearly non-Persian.
            fa_text = ""
            en_text = ""
            if self.fa_recognizer is not None:
                with self.lock:
                    try:
                        fa_text = self._decode(self.fa_recognizer, samples, int(sample_rate))
                    except Exception:
                        fa_text = ""

            if fa_text and self._looks_persian(fa_text):
                language, text = "fa", fa_text
            else:
                if self.en_recognizer is not None:
                    with self.lock:
                        try:
                            en_text = self._decode(self.en_recognizer, samples, int(sample_rate))
                        except Exception:
                            en_text = ""
                if en_text and self._looks_english(en_text):
                    language, text = "en", en_text
                elif fa_text:
                    # Mixed-script Persian commands can contain brand names in
                    # Latin characters. Persian remains the preferred fallback.
                    language, text = "fa", fa_text
                elif en_text:
                    language, text = "en", en_text
                else:
                    language, text = None, ""

        if text and not self.is_usable_transcript(text):
            text, language = "", None
        return {
            "ok": bool(text),
            "text": text,
            "language": language,
            "offline": True,
            "provider": "sherpa-onnx",
            "error": None if text else "Empty result.",
            "levels": levels,
        }

    def transcribe_file(
        self,
        audio_path,
        language_hint: Optional[str] = None,
        fast: bool = False,
    ) -> dict:
        if sf is None:
            return {
                "ok": False,
                "error": "soundfile is not installed.",
                "provider": "sherpa-onnx",
                "offline": True,
            }
        try:
            data, sample_rate = sf.read(
                str(audio_path),
                dtype="float32",
                always_2d=False,
            )
        except Exception as exc:
            return {
                "ok": False,
                "error": str(exc),
                "provider": "sherpa-onnx",
                "offline": True,
            }
        if getattr(data, "ndim", 1) > 1:
            data = data.mean(axis=1).astype(np.float32)
        return self.transcribe_samples(data, int(sample_rate), language_hint, fast)

    def transcribe_partial(self, audio_path, language_hint: Optional[str] = None):
        return self.transcribe_file(audio_path, language_hint=language_hint, fast=True)

    def status_dict(self) -> dict:
        return {
            "internet": True,
            "online_stt_ready": False,
            "offline_stt_ready": self.ready,
            "fa_ready": self.fa_recognizer is not None,
            "en_ready": self.en_recognizer is not None,
            "sherpa_status": self.status,
        }
