from __future__ import annotations
import asyncio,base64,os,platform,tempfile,threading
from pathlib import Path
try: import pyttsx3
except Exception: pyttsx3=None
try: import edge_tts
except Exception: edge_tts=None
try: import pythoncom
except Exception: pythoncom=None
from config import ONLINE_TTS_FA_VOICE,ONLINE_TTS_EN_VOICE,ONLINE_TTS_RATE,ONLINE_TTS_VOLUME,ONLINE_TTS_PITCH

_IS_WINDOWS = platform.system() == 'Windows'

class TTSService:
    def __init__(self,internet_monitor): self.internet_monitor=internet_monitor; self.lock=threading.Lock()
    def _voice(self,language): return ONLINE_TTS_FA_VOICE if language=='fa' else ONLINE_TTS_EN_VOICE
    async def _save(self,text,language,path):
        await edge_tts.Communicate(text,self._voice(language),rate=ONLINE_TTS_RATE,volume=ONLINE_TTS_VOLUME,pitch=ONLINE_TTS_PITCH).save(path)
    def _offline(self,text,language):
        if not pyttsx3: return {'ok':False,'error':'Offline TTS unavailable.','provider':'windows-sapi'}
        # pyttsx3's Windows SAPI5 driver talks to the voice engine over COM.
        # speak() normally runs inside a worker thread (asyncio.to_thread),
        # and COM requires each thread that uses it to explicitly initialize
        # its own apartment first — without this, pyttsx3.init() silently
        # fails (or raises) on that thread, which is why offline TTS could
        # produce no sound at all. CoInitialize/CoUninitialize fixes that.
        com_ready=False
        if _IS_WINDOWS and pythoncom:
            try:
                pythoncom.CoInitialize(); com_ready=True
            except Exception: com_ready=False
        try:
            with self.lock:
                engine=pyttsx3.init(); voices=engine.getProperty('voices') or []
                hints=('persian','farsi','فارسی','iran','iranian','1065','0x429') if language=='fa' else ('english','en-','microsoft david','microsoft zira','microsoft mark','409','0x409')
                selected=None
                for v in voices:
                    blob=' '.join([str(getattr(v,'id','')).lower(),str(getattr(v,'name','')).lower(),str(getattr(v,'languages','')).lower()])
                    if any(h in blob for h in hints): selected=v; break
                if selected: engine.setProperty('voice',selected.id)
                engine.setProperty('rate',175); engine.setProperty('volume',1.0); engine.say(text); engine.runAndWait(); engine.stop()
            return {'ok':True,'offline':True,'provider':'windows-sapi','voice_selected':getattr(selected,'name',None),'audio_base64':None}
        except Exception as exc: return {'ok':False,'error':str(exc),'provider':'windows-sapi'}
        finally:
            if com_ready:
                try: pythoncom.CoUninitialize()
                except Exception: pass
    def speak(self,text,language=None):
        text=str(text).strip()
        if not text: return {'ok':False,'error':'Text is empty.'}
        if edge_tts and self.internet_monitor.is_online():
            path=None
            try:
                with tempfile.NamedTemporaryFile(delete=False,suffix='.mp3') as f: path=f.name
                asyncio.run(self._save(text,language,path)); data=Path(path).read_bytes()
                if data: return {'ok':True,'offline':False,'provider':'edge-tts','voice':self._voice(language),'mime_type':'audio/mpeg','audio_base64':base64.b64encode(data).decode('ascii')}
            except Exception: pass
            finally:
                if path:
                    try: os.remove(path)
                    except OSError: pass
        return self._offline(text,language)
    def voices(self):
        if not pyttsx3: return []
        com_ready=False
        if _IS_WINDOWS and pythoncom:
            try:
                pythoncom.CoInitialize(); com_ready=True
            except Exception: com_ready=False
        try:
            e=pyttsx3.init(); out=[]
            for v in e.getProperty('voices') or []:
                out.append({'id':str(getattr(v,'id','')),'name':str(getattr(v,'name','')),'languages':[str(x) for x in (getattr(v,'languages',[]) or [])]})
            e.stop(); return out
        except Exception: return []
        finally:
            if com_ready:
                try: pythoncom.CoUninitialize()
                except Exception: pass
