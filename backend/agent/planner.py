from __future__ import annotations
import json,re
from typing import Any
import requests
from config import OLLAMA_URL,OLLAMA_MODEL,AGENT_TIMEOUT
SYSTEM_PROMPT=r'''
You are the planning brain of a Windows voice assistant called Smartis.
The user may speak Persian or English.
Convert natural language into a small sequence of tool calls.
Available tools:
- open_application(app): opens a desktop app the user just names casually (chrome, edge, notepad, calculator, explorer, or any other .exe name). Not tied to a fixed list — pass whatever app name the user said.
- open_website(url): opens a URL in the user's normal default browser. Fire-and-forget, nothing can be typed into it afterwards.
- open_folder(path)
- open_file(path)
- system_info()
- close_application(process) [requires confirmation]
- browser_open(url): opens a URL in a separate, automatable browser window that later steps CAN interact with.
- browser_type(text): types text into the most relevant field on the page opened by browser_open.
- browser_submit(): presses Enter to submit what was just typed.
- browser_read_response(): waits for the page's reply and returns/speaks it back. Always the LAST action when the user wants an answer read to them.
- browser_close(): closes the automation browser when the task is fully done.
Return ONLY valid JSON:
{"reply":"short human-facing reply in the user's language","actions":[{"tool":"tool_name","args":{"key":"value"}}],"needs_confirmation":false}
Rules:
1. Persian input => reply MUST be natural Persian.
2. English input => reply MUST be natural English.
3. Never answer a Persian user in English merely because a URL/tool name is English.
4. Never invent tools. If a request has no matching tool, say so in "reply" and return an empty actions list.
5. Never claim an action succeeded before execution.
6. Use confirmation for destructive or ambiguous operations.
7. No shell commands.
8. Google => https://www.google.com. ChatGPT => https://chatgpt.com. Claude => https://claude.ai.
9. Multi-step requests ("go to X, write Y, send it, read me the answer") MUST be broken into an ordered actions list using the browser_* tools chained together, e.g.:
   [{"tool":"browser_open","args":{"url":"https://claude.ai"}},
    {"tool":"browser_type","args":{"text":"..."}},
    {"tool":"browser_submit","args":{}},
    {"tool":"browser_read_response","args":{}}]
   Only use plain open_website when the user just wants something opened and nothing else.
10. If the user simply names an app conversationally (not from a fixed menu), still map it to open_application with that app name — don't refuse just because it isn't in a predefined list.
'''
def _json(text):
    try:
        x=json.loads(text); return x if isinstance(x,dict) else None
    except Exception: pass
    m=re.search(r'\{.*\}',text,re.S)
    if not m: return None
    try:
        x=json.loads(m.group(0)); return x if isinstance(x,dict) else None
    except Exception: return None
def plan_with_ollama(user_text,language=None):
    inst=''
    if language=='fa': inst='\nDETECTED LANGUAGE=Persian. reply MUST be Persian.'
    elif language=='en': inst='\nDETECTED LANGUAGE=English. reply MUST be English.'
    payload={'model':OLLAMA_MODEL,'stream':False,'format':'json','messages':[{'role':'system','content':SYSTEM_PROMPT+inst},{'role':'user','content':user_text}],'options':{'temperature':0.1}}
    try:
        r=requests.post(f'{OLLAMA_URL}/api/chat',json=payload,timeout=AGENT_TIMEOUT); r.raise_for_status()
        parsed=_json(r.json().get('message',{}).get('content',''))
        return {'ok':True,'plan':parsed,'provider':'ollama-local'} if parsed else {'ok':False,'error':'Invalid JSON','provider':'ollama-local'}
    except Exception as exc: return {'ok':False,'error':str(exc),'provider':'ollama-local'}
def fallback_plan(user_text):
    t=user_text.strip(); low=t.lower(); fa=any('\u0600'<=c<='\u06ff' for c in t)
    if 'گوگل' in low or 'google' in low:
        return {'ok':True,'plan':{'reply':'گوگل را باز می‌کنم.' if fa else 'Opening Google.','actions':[{'tool':'open_website','args':{'url':'https://www.google.com'}}],'needs_confirmation':False},'provider':'fallback'}
    if 'کروم' in low or 'chrome' in low:
        return {'ok':True,'plan':{'reply':'کروم را باز می‌کنم.' if fa else 'Opening Chrome.','actions':[{'tool':'open_application','args':{'app':'chrome'}}],'needs_confirmation':False},'provider':'fallback'}
    if 'کلود' in low or 'claude' in low:
        return {'ok':True,'plan':{'reply':'کلود را باز می‌کنم.' if fa else 'Opening Claude.','actions':[{'tool':'browser_open','args':{'url':'https://claude.ai'}}],'needs_confirmation':False},'provider':'fallback'}
    return {'ok':True,'plan':{'reply':'درک کردم، اما برای اجرای درست این درخواست به Agent محلی (Ollama) نیاز دارم؛ فعلاً فقط چند فرمان ساده بدون آن کار می‌کند.' if fa else 'I understood, but properly handling this needs the local Agent (Ollama); only a few simple commands work without it.','actions':[],'needs_confirmation':False},'provider':'fallback'}
