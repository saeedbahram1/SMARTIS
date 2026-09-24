from pathlib import Path
from typing import Optional
import threading
from config import MODEL_PATH, WHISPER_DEVICE, WHISPER_COMPUTE_TYPE
try:
    from faster_whisper import WhisperModel
except Exception:
    WhisperModel=None

class WhisperService:
    def __init__(self):
        self.model=None; self.lock=threading.Lock(); self.error: Optional[str]=None
    def load(self):
        if WhisperModel is None:
            self.error='faster-whisper is not installed.'; return
        if not Path(MODEL_PATH).exists():
            self.error=f'Whisper model not found: {MODEL_PATH}'; return
        try:
            self.model=WhisperModel(str(MODEL_PATH),device=WHISPER_DEVICE,compute_type=WHISPER_COMPUTE_TYPE)
            self.error=None
        except Exception as exc: self.error=f'Could not load Whisper model: {exc}'
    @property
    def ready(self): return self.model is not None
    def transcribe_file(self,audio_path,language_hint=None,fast=False):
        if not self.ready:
            return {'ok':False,'error':self.error or 'Whisper is not ready.','provider':'offline-whisper','offline':True}
        try:
            with self.lock:
                kwargs={
                    'audio':audio_path,'task':'transcribe','vad_filter':True,
                    'condition_on_previous_text':False,
                    # A short domain prompt nudges decoding toward assistant-style
                    # commands (app/website names, Persian function words) instead
                    # of drifting toward unrelated vocabulary on noisy audio.
                    'initial_prompt':'اسمارتیز، سعید، کروم، گوگل، باز کن، ببند، فایل، پوشه، جستجو کن، بفرست، Smartis, Saeed, Chrome, Google, open, close, search',
                }
                kwargs['language']=language_hint if language_hint in ('fa','en') else None
                if fast:
                    # Wake-word pass: still needs enough context to not clip the
                    # word, but stays cheap. A slightly larger beam catches short
                    # utterances that beam_size=1 previously missed outright.
                    kwargs.update(beam_size=2,best_of=2,patience=1,
                                   vad_parameters={'min_silence_duration_ms':200,'speech_pad_ms':160})
                else:
                    kwargs.update(beam_size=5,best_of=5,temperature=[0.0,0.2,0.4,0.6],
                                   vad_parameters={'min_silence_duration_ms':350,'speech_pad_ms':220})
                segments,info=self.model.transcribe(**kwargs)
                text=' '.join(s.text.strip() for s in segments).strip()
            return {'ok':True,'text':text,'language':getattr(info,'language',None),'language_probability':getattr(info,'language_probability',None),'offline':True,'provider':'offline-whisper'}
        except Exception as exc:
            return {'ok':False,'error':str(exc),'provider':'offline-whisper','offline':True}

    def transcribe_audio_data(self, audio_data, language_hint=None, fast=False):
        """Transcribe SpeechRecognition AudioData directly with Whisper, ensuring
        any temporary file used is cleanly deleted immediately."""
        import tempfile
        import os
        if not self.ready:
            return {'ok':False,'error':self.error or 'Whisper is not ready.','provider':'offline-whisper','offline':True}
        temp_path = None
        try:
            wav_bytes = audio_data.get_wav_data()
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
                f.write(wav_bytes)
                temp_path = f.name
            return self.transcribe_file(temp_path, language_hint=language_hint, fast=fast)
        except Exception as exc:
            return {'ok':False,'error':f'Whisper audio data transcription failed: {exc}','provider':'offline-whisper','offline':True}
        finally:
            if temp_path and os.path.exists(temp_path):
                try:
                    os.remove(temp_path)
                except OSError:
                    pass

