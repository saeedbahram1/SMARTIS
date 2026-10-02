from __future__ import annotations

import re
from typing import Any

from agent.command_normalizer import normalize_command_text
from agent.conversation import capabilities, creator_answer, greeting, introduction
from agent import system_tools

APP_ALIASES={
    "chrome":"chrome","google chrome":"chrome","کروم":"chrome","گوگل کروم":"chrome",
    "edge":"edge","microsoft edge":"edge","مایکروسافت اج":"edge","اج":"edge",
    "firefox":"firefox","فایرفاکس":"firefox","brave":"brave","بریو":"brave",
    "notepad":"notepad","notepad++":"notepad++","نوت پد":"notepad","نوت‌پد":"notepad",
    "calculator":"calculator","ماشین حساب":"calculator","explorer":"explorer","فایل اکسپلورر":"explorer",
    "vlc":"vlc","وی ال سی":"vlc","spotify":"spotify","اسپاتیفای":"spotify","potplayer":"potplayer","پات پلیر":"potplayer",
}
WEB_ALIASES={"گوگل":"https://www.google.com","google":"https://www.google.com","یوتیوب":"https://www.youtube.com","youtube":"https://www.youtube.com","جیمیل":"https://mail.google.com","gmail":"https://mail.google.com","چت جی پی تی":"https://chatgpt.com","chatgpt":"https://chatgpt.com"}
MEDIA_WORDS=("آهنگ","موزیک","موسیقی","فیلم","پلیر","پخش","مدیا","ویدیو","song","music","movie","player","media","track","video","vlc","spotify")


def _fa(text:str,language:str|None=None)->bool:
    # Prefer the actual script in the transcript over a noisy STT language hint.
    if re.search(r"[\u0600-\u06FF]", text): return True
    if re.search(r"[A-Za-z]", text): return False
    return language != "en"

def _reply(is_fa:bool,fa:str,en:str)->str: return fa if is_fa else en

def _num(text:str)->float|None:
    t=str(text).translate(str.maketrans("۰۱۲۳۴۵۶۷۸۹","0123456789")); m=re.search(r"(?<!\d)-?(\d+(?:\.\d+)?)",t)
    if m: return float(m.group(1))
    words=getattr(system_tools,"_NUMBER_WORDS",{})
    low=t.lower().strip()
    for phrase,value in sorted(words.items(), key=lambda kv:len(kv[0]), reverse=True):
        if re.search(rf"(?<![\w-]){re.escape(phrase)}(?![\w-])",low,re.I): return float(value)
    return None

def _plan(tool:str,args:dict[str,Any],is_fa:bool,fa:str,en:str)->dict[str,Any]:
    return {"ok":True,"plan":{"reply":_reply(is_fa,fa,en),"actions":[{"tool":tool,"args":args}],"needs_confirmation":False},"provider":"fast-path"}

def _multi(actions:list[dict[str,Any]],is_fa:bool,fa:str,en:str)->dict[str,Any]:
    return {"ok":True,"plan":{"reply":_reply(is_fa,fa,en),"actions":actions,"needs_confirmation":False},"provider":"fast-path"}

def _media(tool:str,is_fa:bool,fa:str,en:str)->dict[str,Any]: return _plan(tool,{},is_fa,fa,en)

def _extract_query(text:str)->str|None:
    m=re.search(r"(?:سرچ\s*کن|جستجو\s*کن|جست‌وجو\s*کن|search(?:\s+for)?|look\s+up|google\s+for)\s+(.+)",text,re.I)
    if not m:return None
    q=m.group(1).strip()
    q=re.sub(r"\s+(?:و|and)\s+(?:صفحه\s+)?(?:ویکی\s*پدیا|ویکیپدیا)(?:ش)?(?:\s+(?:را|رو))?(?:\s+باز(?:ش)?\s+کن)?\b.*$","",q,flags=re.I)
    q=re.sub(r"\s+(?:صفحه\s+)?(?:ویکی\s*پدیا|ویکیپدیا)(?:ش)?(?:\s+(?:را|رو))?(?:\s+باز(?:ش)?\s+کن)?\b.*$","",q,flags=re.I)
    q=re.sub(r"\s+(?:and\s+)?(?:open\s+)?(?:his|her|the)?\s*wikipedia(?:\s+page)?\b.*$","",q,flags=re.I)
    return q.strip(" ،,؟?!.:") or None

def _search_chain(text:str,is_fa:bool)->dict[str,Any]|None:
    q=_extract_query(text)
    if not q:return None
    wiki=bool(re.search(r"(?:ویکی\s*پدیا|ویکیپدیا|wikipedia)",text,re.I))
    actions=[{"tool":"open_chrome_url","args":{"url":"https://www.google.com/search?q="+quote_component(q)}}]
    if wiki:
        actions.append({"tool":"open_wikipedia_page","args":{"query":q,"language":"fa" if is_fa else "en"}})
        return _multi(actions,is_fa,f"گوگل را باز می‌کنم، فقط «{q}» را جست‌وجو می‌کنم و صفحه ویکی‌پدیا را هم باز می‌کنم.",f"I'll search only for {q} in Google and open its Wikipedia page.")
    return _plan("open_chrome_url",{"url":"https://www.google.com/search?q="+quote_component(q)},is_fa,f"فقط «{q}» را در گوگل جست‌وجو می‌کنم.",f"Searching Google for {q}.")

def quote_component(value:str)->str:
    from urllib.parse import quote_plus
    return quote_plus(value)

def _is_player(text:str)->bool: return any(x in text.lower() for x in MEDIA_WORDS)

def _change(text:str)->tuple[bool,bool]:
    low=text.lower(); return bool(re.search(r"(?:زیاد|بالا|ببر|بیشتر|up|increase|louder|turn\s+up|raise|higher)",low)), bool(re.search(r"(?:کم|پایین|بیاور|کمتر|down|decrease|quieter|turn\s+down|lower)",low))

def _is_abs(text:str)->bool: return bool(re.search(r"(?:روی|رو|بذار|بگذار|تنظیم\s*کن|set|to|روی\s*مقدار|at)\s*[۰-۹0-9]+\s*(?:درصد|%|percent)?",text,re.I))

def _play_query(text:str)->str|None:
    value=re.sub(r"\s+", " ", text.strip())
    if not value:return None
    patterns=(
        # «آهنگ X رو پخش کن» / «X رو پخش کن» / «فلان آهنگ را پخش کن»
        r"^(?:لطفا|لطفاً|please)?\s*(?:آهنگ|موزیک|موسیقی|ترک|song|music|track)?\s*(.+?)\s+(?:را|رو)\s*(?:پخش|play)\s*(?:کن|کنش|please)?[؟?!.]*$",
        # «پخش کن X» / «play X»
        r"^(?:لطفا|لطفاً|please)?\s*(?:پخش|play)\s+(?:کن|کنش)?\s*(.+?)[؟?!.]*$",
        # «آهنگ X پخش کن» / «آهنگ X بذار»
        r"^(?:لطفا|لطفاً|please)?\s*(?:آهنگ|موزیک|موسیقی|ترک|song|music|track)\s+(.+?)\s+(?:بذار|بگذار|پخشش|پخش|play)(?:\s+کن)?[؟?!.]*$",
        # «X را بگذار پخش شود» / «X رو بذار»
        r"^(?:لطفا|لطفاً|please)?\s*(?:آهنگ|موزیک|موسیقی|ترک|song|music|track)\s+(.+?)\s+(?:را|رو)?\s*(?:بذار|بگذار|بپخش|play)(?:\s+(?:کن|ش|please))?[؟?!.]*$",
    )
    for pat in patterns:
        m=re.match(pat,value,re.I)
        if not m:continue
        q=m.group(1).strip(" ،,؟?!")
        q=re.sub(r"^(?:آهنگ|موزیک|موسیقی|ترک|song|music|track)\s+", "", q, flags=re.I).strip()
        q=re.sub(r"\s+(?:آهنگ|موزیک|موسیقی|ترک|song|music|track)$", "", q, flags=re.I).strip()
        q=re.sub(r"\s+(?:را|رو)$", "", q, flags=re.I).strip()
        # Remove a trailing command word accidentally captured by permissive forms.
        q=re.sub(r"\s+(?:پخش|play|کن|کنش)$", "", q, flags=re.I).strip()
        if q.lower() in {"بعد", "بعدش", "سپس", "and", "then", "after that", "کن", "play", "پخش"}:
            return None
        if q and len(q)>=2:return q
    return None


def _knowledge_query(text:str)->str|None:
    patterns=[
        r"^(?:در\s+مورد|درباره(?:ی)?|راجع\s+به)\s+(.+?)(?:\s+(?:برام|برای\s+من)?\s*(?:توضیح\s+(?:بده|ده)|بگو|اطلاعات\s+بده|چی\s+میدونی))(?:\s+(?:از\s+)?ویکی\s*پدیا)?[؟?!.]*$",
        r"^(?:فیلم|movie)\s+(.+?)(?:\s+(?:چیه|چیست|کیه|درباره\s*اش|درباره\s+آن|معرفی(?:ش)?\s+کن))?[؟?!.]*$",
        r"^(?:(.+?))\s+(?:کیه|کی\s+هست|چه\s+کسیه|چیه|چیست|درباره\s+چیه|درباره\s+چیست)(?:\s+(?:از\s+)?ویکی\s*پدیا)?[؟?!.]*$",
        r"^(?:who\s+is|what\s+is|what\s+are|tell\s+me\s+about|explain|who's)\s+(.+?)(?:\s+from\s+wikipedia)?[?!.]*$",
    ]
    for pat in patterns:
        m=re.match(pat,text,re.I)
        if m:
            q=m.group(1).strip(" ،,؟?!.:")
            q=re.sub(r"^(?:فیلم|movie)\s+", "", q, flags=re.I).strip()
            q=q.replace(" یک", " 1").replace(" اول", " 1")
            if q:return q
    return None

def _research_query(text: str) -> str | None:
    """Extract the meaningful topic from natural research/investigation requests."""
    value = re.sub(r"\s+", " ", str(text or "").strip())
    if not value:
        return None

    # Conversational verbs/phrases that signal an information task.
    action = (
        r"(?:برو\s+)?(?:بریم\s+)?(?:تحقیق(?:ش)?|بررسی(?:ش)?|مطالعه(?:ش)?|پژوهش(?:ش)?)"
        r"\s*(?:رو|را|اش|ش)?\s*(?:کن|کنش|کنم|کنی|کنید|کنین|بکن|بکنش|بکنید|بخون|بخونش|بخونید)"
        r"|(?:اطلاعات(?:ش)?\s+)?(?:پیدا\s*کن|پیداش\s*کن|در\s*بیار|درش\s*بیار)"
        r"|(?:اطلاعات(?:ش)?\s+)?(?:بده|بگو)"
        r"|(?:research|investigate|look\s+up|look\s+into|find\s+out|check\s+out|read\s+about|study|explore|learn\s+about|check)(?:\s+it)?"
    )
    wrapper = r"(?:در\s+مورد|درباره(?:ی|ٔ)?|راجع\s*به|در\s+رابطه\s+با|about|regarding)"
    lead = r"(?:لطفاً|لطفا|خواهشاً|خواهشا|please|برای\s+من|برام|من\s+میخوام|میخوام|می‌خوام|میخواهم|می‌خواهم)"

    # Normalize leading conversational wrappers first. This lets all of these
    # forms share the same extraction logic:
    # «برای من درباره X تحقیق کن», «میخوام درباره X تحقیق کنی», «برو X رو بررسی کن».
    work = value
    work = re.sub(rf"^(?:{lead})\s+", "", work, flags=re.I).strip()
    work = re.sub(r"^(?:برو|بریم)\s+", "", work, flags=re.I).strip()

    hit: str | None = None

    # Wrapper + topic + action: «درباره X تحقیق کن».
    m = re.match(rf"^{wrapper}\s+(?P<topic>.+?)\s+(?:را|رو)?\s*(?:{action})(?:\s+(?:برام|برای\s+من|لطفاً|لطفا|please))?[؟?!.,]*$", work, re.I)
    if m:
        hit = m.group("topic").strip()

    # Topic + object marker + action: «X رو بررسی کن», «X رو برام پیدا کن».
    if not hit:
        m = re.match(rf"^(?P<topic>.+?)\s+(?:را|رو)\s*(?:(?:برام|برای\s+من)\s+)?(?:{action})[؟?!.,]*$", work, re.I)
        if m:
            hit = m.group("topic").strip()

    # Topic + action without «رو/را»: «X تحقیق کن» / «X find out».
    if not hit:
        m = re.match(rf"^(?P<topic>.+?)\s+(?:{action})[؟?!.,]*$", work, re.I)
        if m:
            hit = m.group("topic").strip()

    # Action first + optional wrapper: «تحقیق کن درباره X».
    if not hit:
        m = re.match(rf"^(?:{action})\s+(?:(?:{wrapper})\s+)?(?P<topic>.+?)[؟?!.,]*$", work, re.I)
        if m:
            hit = m.group("topic").strip()

    if not hit:
        return None

    hit = re.sub(rf"^(?:{lead})\s+", "", hit, flags=re.I).strip()
    hit = re.sub(r"^(?:برو|بریم)\s+", "", hit, flags=re.I).strip()
    hit = re.sub(rf"^{wrapper}\s+", "", hit, flags=re.I).strip()
    hit = re.sub(r"^(?:فیلم|movie)\s+", "", hit, flags=re.I).strip()
    hit = re.sub(r"\s+(?:را|رو|اش|ش)$", "", hit, flags=re.I).strip()
    hit = re.sub(r"\s+(?:میخوام|می‌خوام|میخواهم|می‌خواهم)$", "", hit, flags=re.I).strip()
    hit = hit.replace(" یک", " 1").replace(" اول", " 1")
    return hit.strip(" ،,؟?!.:؛\"'") or None


def _generic_web_query(text: str) -> str | None:
    low = text.lower().strip()
    patterns = [
        r"^(?:برو\s+)?(?:جستجو|جست‌وجو|سرچ)\s+(?:کن\s+)?(?:برای\s+)?(.+)$",
        r"^(?:برو\s+)?(?:پیدا\s+کن|پیداش\s+کن)\s+(.+)$",
        r"^(?:search|google|look up|find)\s+(?:for\s+)?(.+)$",
    ]
    for pat in patterns:
        m = re.match(pat, text, re.I)
        if m:
            q = m.group(1).strip(" ،,؟?!.")
            if q and len(q) >= 2: return q
    return None

def _news(text:str)->tuple[bool,str|None]:
    low=text.lower()
    if not any(x in low for x in ("خبر","اخبار","news","breaking")):return False,None
    m=re.search(r"(?:درباره|در\s+مورد|about|on)\s+(.+)$",text,re.I)
    topic=m.group(1).strip(" ،,؟?!. ") if m else None
    topic=re.sub(r"^(?:امروز|جدید|جدیدترین|today|latest|recent)\s+","",topic or "",flags=re.I).strip() or None
    return True,topic

def _weather(text:str)->tuple[bool,str|None,bool]:
    low=text.lower()
    if not any(x in low for x in ("هوا","آب و هوا","weather","forecast")):return False,None,False
    if any(x in low for x in ("اینجا","این جا","مکان من","my location","where i am","current location")): return True,None,True
    patterns=[r"(?:شهر|city)\s+(.+)$",r"(?:هوای|آب\s+و\s+هوای|آب\s+و\s+هوا(?:ی)?|weather\s+(?:in|for)?)\s+(.+)$"]
    for pat in patterns:
        m=re.search(pat,text,re.I)
        if m:
            city=m.group(1).strip(" ،,؟?!")
            city=re.sub(r"^(?:امروز|الان|current|today)\s+","",city,flags=re.I).strip()
            # Extract the city, not the remainder of the sentence.  Users
            # naturally say things like "هوای همدان رو بگو" or "هوای همدان
            # الان چطوره"; those suffixes must never become part of the city
            # query sent to the geocoder.
            city=re.sub(r"\s+(?:رو|را)\b.*$", "", city, flags=re.I).strip()
            city=re.sub(r"\s+(?:بگو|بهم بگو|به من بگو)$", "", city, flags=re.I).strip()
            city=re.sub(r"\s+(?:امروز|الان|فعلاً|فعلا|current|today|now)$", "", city, flags=re.I).strip()
            city=re.sub(r"\s+(?:چطوره|چطور(?:ه)?|چگونه(?:ه)?|چه(?:طور|جوری)(?:ه)?|خوبه|خوب(?:ه)?|how(?:'s| is) it|today|الان چطوره)$", "", city, flags=re.I).strip()
            city=re.sub(r"\s+(?:امروز|الان)\s+(?:چطوره|چطور(?:ه)?|خوبه|خوب(?:ه)?)$", "", city, flags=re.I).strip()
            city=re.sub(r"\s+(?:امروز|الان|current|today|now)$", "", city, flags=re.I).strip()
            return True,city or None,False
    return True,None,True

def _path_for_phrase(text:str)->str|None:
    low=text.lower()
    if "دسکتاپ" in low or "desktop" in low:return "desktop"
    if "دانلود" in low or "download" in low:return "downloads"
    if re.search(r"(?:درایو\s*سی|drive\s*c|c:)",low):return "C:/"
    return None

def _folder_name_for_create(text:str)->str|None:
    m=re.search(r"(?:به\s*اسم|با\s*اسم|به\s*نام|با\s*نام|اسم(?:ش)?\s*(?:را|رو)?\s*)\s*[\"']?(.+?)[\"']?$",text,re.I)
    return m.group(1).strip() if m else None

def _greeting(text:str)->bool:
    low=text.lower().strip()
    fa_hit=any(x in low for x in ("درود","سلام","خوبی","چطوری","چه خبر"))
    en_hit=bool(re.search(r"(?:^|\s)(?:hello|hi|hey)(?:$|\s|[!,?.])",low)) or any(x in low for x in ("how are you","what's up"))
    return (fa_hit or en_hit) and len(low)<80

def _affirm(text:str)->bool: return text.strip().lower() in {"بله","آره","اره","تایید","تأیید","تایید میکنم","تأیید می‌کنم","حتما","حتماً","باشه","ادامه بده","بخون","کاملش کن","بیشتر بگو","yes","yeah","yep","sure","okay","ok","confirm","confirmed","continue","read it","tell me more"}
def _negative(text:str)->bool: return text.strip().lower() in {"نه","نخیر","نمیخوام","نمی‌خوام","بیخیال","کافیه","بس است","no","nope","stop","enough"}


def fast_plan(text:str,language:str|None=None,include_conversation:bool=True,include_knowledge:bool=True)->dict[str,Any]|None:
    """Deterministic command engine.

    include_conversation=False -> greetings / identity questions are NOT handled here
    (the router sends them to the chat model). include_knowledge=False -> plain
    «X چیه؟» / "what is X" questions are NOT turned into web_research; only an
    explicit research/search request is.
    """
    value=normalize_command_text(text); low=value.lower().strip(); is_fa=_fa(value,language)
    if not value:return None

    if not include_conversation:
        pass
    elif _greeting(value): return {"ok":True,"plan":{"reply":greeting("fa" if is_fa else "en"),"actions":[],"needs_confirmation":False},"provider":"conversation"}
    if include_conversation and any(p in low for p in ("خودتو معرفی","خودت رو معرفی","تو کی هستی","معرفی کن خودتو","who are you","introduce yourself","what are you")):
        return {"ok":True,"plan":{"reply":introduction("fa" if is_fa else "en"),"actions":[],"needs_confirmation":False},"provider":"conversation"}
    if include_conversation and any(p in low for p in ("کی تو رو ساخته","کی تو را ساخته","چه کسی تو رو ساخته","سازندت کیه","سازنده تو کیه","who made you","who created you","who built you")):
        return {"ok":True,"plan":{"reply":creator_answer("fa" if is_fa else "en"),"actions":[],"needs_confirmation":False},"provider":"conversation"}
    if include_conversation and any(p in low for p in ("چه کارهایی بلدی","چه کارایی بلدی","قابلیت هات چیه","چه کار میکنی","what can you do")):
        return {"ok":True,"plan":{"reply":capabilities("fa" if is_fa else "en"),"actions":[],"needs_confirmation":False},"provider":"conversation"}

    if _affirm(value):
        if system_tools.wikipedia_more_available(): return _plan("wikipedia_more",{},is_fa,"ادامهٔ مطلب را می‌خوانم.","I'll continue reading the article.")
    if _negative(value) and system_tools.wikipedia_clear_pending(): return {"ok":True,"plan":{"reply":"باشه، منتظرم برای دستور بعدی." if is_fa else "Okay, I'm ready for your next command.","actions":[],"needs_confirmation":False},"provider":"conversation"}

    # Windows Search: accept many natural forms, including "باز کن توش بنویس X".
    if re.search(r"(?:سرچ|جست(?:جو|‌وجو)|search).{0,18}(?:ویندوز|سیستم|windows|system)", value, re.I):
        qm=re.search(r"(?:توش|داخلش|داخل|in it|there)\s*(?:بنویس|بنویسه|جستجو\s+کن|سرچ\s+کن|search|type)\s+(.+)$", value, re.I)
        if not qm:
            qm=re.search(r"(?:برای|for)\s+(.+)$", value, re.I)
        query=(qm.group(1).strip(" ،,؟?!.") if qm else "")
        return _plan("windows_system_search",{"query":query},is_fa,"جست‌وجوی ویندوز را باز می‌کنم." if not query else f"جست‌وجوی ویندوز را باز می‌کنم و «{query}» را جست‌وجو می‌کنم.","Opening Windows Search." if not query else f"Opening Windows Search and searching for {query}.")

    # Search/navigation chains first so only the requested topic is searched.
    chain=_search_chain(value,is_fa)
    if chain:return chain

    # Natural multi-action commands: split only on a clear coordinating
    # conjunction, then reuse the same semantic fast-path for each clause.
    # This keeps the engine from depending on one exact combined sentence.
    if re.search(r"(?:\s+(?:و|and|بعد|سپس|بعدش|و بعد|then|after that)\s+|،|;)", value, re.I):
        parts = [part.strip(" ،,؛;.") for part in re.split(r"\s+(?:و بعد|بعدش|بعد|سپس|و|and|then|after that)\s+|[،;]", value, flags=re.I) if part.strip()]
        if len(parts) >= 2 and len(parts) <= 4:
            actions = []
            replies = []
            for part in parts:
                child = fast_plan(part, language, include_conversation, include_knowledge)
                if not child or not child.get("ok"):
                    actions = []
                    break
                child_actions = child.get("plan", {}).get("actions") or []
                if len(child_actions) != 1:
                    actions = []
                    break
                actions.append(child_actions[0])
                reply = str(child.get("plan", {}).get("reply") or "").strip()
                if reply:
                    replies.append(reply)
            if len(actions) == len(parts) and len(actions) >= 2:
                return _multi(actions, is_fa, "، ".join(replies) or "دستورها را به‌ترتیب اجرا می‌کنم.", "I’ll execute the requested actions in order.")

    # Time/date.
    if re.search(r"(?:ساعت(?: دقیق)?|what time is it|current time|time now)",low): return _plan("get_time_date",{},is_fa,"ساعت دقیق سیستم را می‌گویم.","I'll give you the exact system time.")
    if re.search(r"(?:تاریخ(?: امروز)?|امروز چندمه|what(?:'s| is) the date|today's date|date today)",low): return _plan("get_time_date",{},is_fa,"تاریخ دقیق امروز را می‌گویم.","I'll give you today's exact date.")

    # Weather.
    weather,city,use_loc=_weather(value)
    if weather:return _plan("get_location_weather" if use_loc else "get_weather",({"language":"fa" if is_fa else "en"} if use_loc else {"city":city,"language":"fa" if is_fa else "en"}),is_fa,"وضعیت آب‌وهوا را می‌خوانم.","I'll get the weather.")

    # System language and settings/search.
    m=re.search(r"(?:زبان(?:\s+(?:سیستم|ویندوز))?|windows\s+language|system\s+language).{0,60}(فارسی|انگلیسی|english|persian|farsi|fa[-_]IR|en[-_]US)",value,re.I)
    if not m:
        m=re.search(r"(?:ویندوز|سیستم|windows).{0,25}(?:رو|را|را به|رو به|to)?\s*(?:به|on|in)?\s*(فارسی|انگلیسی|english|persian|farsi|fa[-_]IR|en[-_]US)",value,re.I)
    if m: return _plan("set_windows_language",{"language_name":m.group(1),"language":"fa" if is_fa else "en"},is_fa,"زبان ویندوز را بررسی و تنظیم می‌کنم.","I will check and set the Windows language.")

    if any(x in low for x in ("تنظیمات سیستم","تنظیمات ویندوز","windows settings","system settings","settings")): return _plan("open_windows_settings",{},is_fa,"تنظیمات ویندوز را باز می‌کنم.","Opening Windows Settings.")

    # Files and folders.
    base=_path_for_phrase(value)
    if re.search(r"(?:فایل|file)\s+(?:بساز|ایجاد\s*کن|create|make)",low):
        m=re.search(r"(?:به\s*اسم|با\s*اسم|به\s*نام|با\s*نام|اسم(?:ش)?\s*(?:را|رو)?\s*)\s*[\"']?(.+?)[\"']?$",value,re.I)
        if m:
            name=m.group(1).strip(); base=base or "desktop"
            return _plan("create_file",{"path":str(PathSafeJoin(base,name))},is_fa,"فایل ساخته شد.","The file has been created.")
        system_tools.set_pending_file(base or "desktop")
        return {"ok":True,"plan":{"reply":"اسم فایل رو چی بزارم؟","actions":[],"needs_confirmation":False},"provider":"conversation"}
    if re.search(r"(?:پوشه|folder)\s+(?:بساز|ایجاد\s*کن|create|make)",low):
        name=_folder_name_for_create(value)
        if name:
            base=base or "desktop"; return _plan("create_folder",{"path":str(PathSafeJoin(base,name))},is_fa,"پوشه ساخته شد.","The folder has been created.")
        system_tools.set_pending_folder(base or "desktop")
        return {"ok":True,"plan":{"reply":"اسم پوشه رو چی بزارم؟","actions":[],"needs_confirmation":False},"provider":"conversation"}
    if re.search(r"(?:حذف|پاک|delete|remove)",low) and re.search(r"(?:پوشه|فایل|folder|file)",low):
        m=re.search(r"(?:پوشه|فایل|folder|file)\s+(?:با\s+اسم|به\s+اسم|به\s+نام|named|called)?\s*[\"']?(.+?)[\"']?\s*(?:را|رو)?\s*(?:پیدا\s+کن|پیدا کن و|پیدا\s+ش)?\s*(?:و\s*)?(?:حذفش\s+کن|حذف\s+کن|پاک\s+کن|حذف|پاک|delete|remove)",value,re.I)
        if not m:
            m=re.search(r"(?:پوشه|فایل|folder|file)\s+([A-Za-z0-9_\-آ-ی\s.]+?)\s*(?:را|رو)?\s*(?:حذفش|حذف|پاک|delete|remove)",value,re.I)
        if m:
            name=m.group(1).strip(" \"'،,")
            name=re.sub(r"(?:را|رو)\s+(?:پیدا\s+کن|پیدا کن و)$","",name,flags=re.I).strip()
            return _plan("delete_named",{"name":name,"root":base},is_fa,"پیدایش می‌کنم و حذفش می‌کنم.","I'll find it and delete it.")

    # Media.
    if re.search(r"(?:آهنگ|ترک|موزیک|song|track)\s+(?:بعدی|next)",low): return _media("media_next",is_fa,"رفتم آهنگ بعدی.","Going to the next track.")
    if re.search(r"(?:آهنگ|ترک|موزیک|song|track)\s+(?:قبلی|previous)",low): return _media("media_previous",is_fa,"رفتم آهنگ قبلی.","Going to the previous track.")
    if any(x in low for x in ("قطع پخش","متوقف پخش","پخش رو متوقف","پخش را متوقف","stop playback","stop the music","stop the movie")): return _media("media_stop",is_fa,"پخش را متوقف کردم.","Stopping playback.")
    if any(x in low for x in ("نگه دار","مکث","pause","pause playback","پخش رو نگه")): return _media("media_play_pause",is_fa,"پخش را روی مکث گذاشتم.","Pausing playback.")
    if any(x in low for x in ("ادامه پخش","resume","continue playback","ادامه بده")) and _is_player(low): return _media("media_play_pause",is_fa,"پخش را ادامه دادم.","Resuming playback.")

    player=_is_player(low); inc,dec=_change(low); n=_num(value)
    if player and any(x in low for x in ("بی صدا","بی‌صدا","قطع صدا","mute")):
        return _plan("player_mute",{"enabled":True},is_fa,"صدای پخش‌کننده را قطع کردم.","Muted the active player.")
    if player and any(x in low for x in ("وصل صدا","صدا رو وصل","صدا را وصل","آهنگ رو وصل","آهنگ را وصل","وصل کن","unmute","از حالت بی صدا دربیار")):
        return _plan("player_mute",{"enabled":False},is_fa,"صدای پخش‌کننده را وصل کردم.","Unmuted the active player.")
    if player and any(x in low for x in ("صدای آهنگ","صدای موزیک","صدای فیلم","صدای پلیر","player volume","music volume","movie volume")):
        if any(x in low for x in ("قطع صدا","بی صدا","بی‌صدا","mute")): return _plan("player_mute",{"enabled":True},is_fa,"صدای پخش‌کننده را قطع کردم.","Muted the active player.")
        if any(x in low for x in ("وصل صدا","صدا رو وصل","صدا را وصل","آهنگ رو وصل","آهنگ را وصل","وصل کن","unmute","از حالت بی صدا دربیار")): return _plan("player_mute",{"enabled":False},is_fa,"صدای پخش‌کننده را وصل کردم.","Unmuted the active player.")
        if any(x in low for x in ("تا آخر","تا اخر","maximum","max","full")): return _plan("player_volume_max",{},is_fa,"صدای پخش‌کننده را تا بیشترین مقدار قابل پشتیبانی می‌برم.","I'll set the player to its maximum supported volume.")
        if n is not None and not inc and not dec and ("%" in value or "درصد" in low or _is_abs(value)): return _plan("player_volume_set",{"percent":n},is_fa,f"صدای پخش‌کننده را روی {n:.0f} درصد می‌گذارم.",f"Setting player volume to {n:.0f}%.")
        if n is not None and inc:return _plan("player_volume_change",{"delta":abs(n)},is_fa,f"صدای پخش‌کننده را {abs(n):.0f} درصد زیاد می‌کنم.",f"Increasing player volume by {abs(n):.0f}%.")
        if n is not None and dec:return _plan("player_volume_change",{"delta":-abs(n)},is_fa,f"صدای پخش‌کننده را {abs(n):.0f} درصد کم می‌کنم.",f"Decreasing player volume by {abs(n):.0f}%.")

    # System audio — plain "صدا 10 درصد" is absolute.
    if not player and any(x in low for x in ("صدا","volume","بلندی صدا","میزان صدا")):
        if any(x in low for x in ("قطع صدا","صدا رو قطع","صدا را قطع","بی صدا","بی‌صدا","mute","سایلنت")): return _plan("system_mute",{"enabled":True},is_fa,"صدای سیستم را قطع کردم.","Muted system audio.")
        if any(x in low for x in ("وصل صدا","صدا رو وصل","صدا را وصل","آهنگ رو وصل","آهنگ را وصل","وصل کن","unmute","از حالت بی صدا دربیار")): return _plan("system_mute",{"enabled":False},is_fa,"صدای سیستم را وصل کردم.","Unmuted system audio.")
        if any(x in low for x in ("تا آخر","maximum","max","full")): return _plan("system_volume_set",{"percent":100},is_fa,"صدای سیستم را روی 100 درصد گذاشتم.","Set system volume to 100%.")
        if n is not None and not inc and not dec and ("%" in value or "درصد" in low or _is_abs(value) or re.fullmatch(r"صدا\s*[۰-۹0-9]+",low)): return _plan("system_volume_set",{"percent":n},is_fa,f"صدای سیستم روی {n:.0f} درصد تنظیم شد.",f"Setting system volume to {n:.0f}%.")
        if n is not None and inc:return _plan("system_volume_change",{"delta":abs(n)},is_fa,f"صدای سیستم را {abs(n):.0f} درصد زیاد می‌کنم.",f"Increasing system volume by {abs(n):.0f}%.")
        if n is not None and dec:return _plan("system_volume_change",{"delta":-abs(n)},is_fa,f"صدای سیستم را {abs(n):.0f} درصد کم می‌کنم.",f"Decreasing system volume by {abs(n):.0f}%.")

    # Power. Only SHORT imperative sentences count; "how do I restart my router?"
    # or "I could not sleep" are conversation, not a power command.
    power_ok = (not re.search(r"[?؟]|چطور|چگونه|چجوری|چرا|\bhow\b|\bwhy\b|\bwhat\b", low)) and len(low.split()) <= 8 and not re.search(r"لغو|\bcancel\b|\babort\b",low)
    if power_ok:
        for pattern,tool,fa_reply,en_reply in [
            (r"(?:خاموش\s*کن|خاموش\s*شو|خاموشش\s*کن|\bshut\s*down\b|\bshutdown\b|\bturn\s+off\b.*\b(?:pc|computer|system)\b)","shutdown_windows","سیستم را خاموش کنم؟ تأیید می‌کنی؟","Should I shut down the system? Please confirm."),
            (r"(?:ری\s*استارت|راه‌?اندازی\s*مجدد|\brestart\b|\breboot\b)","restart_windows","سیستم را راه‌اندازی مجدد کنم؟ تأیید می‌کنی؟","Should I restart the system? Please confirm."),
            (r"(?:حالت\s*خواب|برو\s*تو\s*خواب|\bgo\s+to\s+sleep\b|\bsleep\s+(?:mode|now)\b|^(?:please\s+)?sleep$|put\b.*\bto\s+sleep\b)","sleep_windows","سیستم را به حالت خواب ببرم؟ تأیید می‌کنی؟","Should I put the system to sleep? Please confirm.")]:
            if re.search(pattern,low): return _plan(tool,{},is_fa,fa_reply,en_reply)
    if any(p in low for p in ("لغو خاموش","cancel shutdown","لغو ری استارت")):return _plan("cancel_shutdown",{},is_fa,"عملیات خاموش یا ری‌استارت لغو شد.","Cancelled the pending power action.")

    # Math, knowledge, news, media search.
    math_expr=_simple_math(value)
    if math_expr:return _plan("calculate",{"expression":math_expr,"language":"fa" if is_fa else "en"},is_fa,"حسابش می‌کنم.","I'll calculate it.")
    research=_research_query(value)
    if research:return _plan("web_research",{"query":research,"language":"fa" if is_fa else "en"},is_fa,f"دربارهٔ «{research}» در ویکی‌پدیا و وب تحقیق می‌کنم.",f"I'll research {research} across Wikipedia and the web.")
    knowledge=_knowledge_query(value) if include_knowledge else None
    if knowledge:return _plan("web_research",{"query":knowledge,"language":"fa" if is_fa else "en"},is_fa,"موضوع را در ویکی‌پدیا و منابع وب بررسی می‌کنم.","I'll research it across Wikipedia and the web.")
    wants_news,topic=_news(value)
    if wants_news:return _plan("get_news",{"topic":topic,"language":"fa" if is_fa else "en"},is_fa,"خبرهای جدید را از منابع معتبر می‌خوانم.","I'll read recent news from reputable sources.")
    query=_play_query(value)
    if query:
        return _plan("play_media_search",{"query":query},is_fa,f"«{query}» را مستقیم در VLC پخش می‌کنم.",f"I'll play {query} directly in VLC.")

    generic_search=_generic_web_query(value)
    if generic_search and not re.search(r"(?:فایل|پوشه|folder|file)", low):
        return _plan("open_chrome_url",{"url":"https://www.google.com/search?q="+quote_component(generic_search)},is_fa,f"«{generic_search}» را در گوگل جست‌وجو می‌کنم.",f"Searching Google for {generic_search}.")

    # Named file/folder opening.
    if re.search(r"(?:پوشه|folder)", low) and re.search(r"(?:باز\s*(?:کن|ش کن)|open|launch)", low):
        m=re.search(r"(?:پوشه|folder)\s+(?:با\s+اسم|به\s+اسم|به\s+نام|named|called)?\s*[\"']?(.+?)[\"']?\s*(?:را|رو)?\s*(?:باز\s*(?:کن|ش کن)|open|launch)", value, re.I)
        if m:
            name=m.group(1).strip(" \"'،,")
            alias={"دسکتاپ":"desktop","desktop":"desktop","دانلود":"downloads","دانلودها":"downloads","downloads":"downloads","اسناد":"documents","documents":"documents"}.get(name.lower())
            if alias:
                return _plan("open_folder",{"path":alias},is_fa,"پوشه را باز می‌کنم.","Opening the folder.")
            return _plan("open_named",{"name":name,"kind":"folder"},is_fa,"پوشه را پیدا می‌کنم و باز می‌کنم.","I'll find and open the folder.")
    if re.search(r"(?:فایل|file)", low) and re.search(r"(?:باز\s*(?:کن|ش کن)|open|launch)", low):
        m=re.search(r"(?:فایل|file)\s+(?:با\s+اسم|به\s+اسم|به\s+نام|named|called)?\s*[\"']?(.+?)[\"']?\s*(?:را|رو)?\s*(?:باز\s*(?:کن|ش کن)|open|launch)", value, re.I)
        if m:
            name=m.group(1).strip(" \"'،,")
            return _plan("open_named",{"name":name,"kind":"file"},is_fa,"فایل را پیدا می‌کنم و باز می‌کنم.","I'll find and open the file.")

    # Navigation/open commands.
    open_words=("باز کن","بازش کن","اجرا کن","راه‌اندازی کن","راه اندازی کن","بیار","open","launch","start","go to","برو تو","برو به","وارد شو","برو داخل")
    def _word(x:str)->bool: return bool(re.search(rf"(?<![\w]){re.escape(x)}(?![\w])",low))
    # Close an application (confirmation-gated by the executor).
    close_m=re.match(r"^(?:لطفا\s+|please\s+)?(?:(?:close|quit|kill|exit)\s+(.+?)|(.+?)\s+(?:را|رو)?\s*(?:ببند|ببندش|ببندید|ببند\s+لطفا))\s*[.!]*$",value,re.I)
    if close_m:
        target=(close_m.group(1) or close_m.group(2) or "").strip(" \"'،,").lower()
        app=APP_ALIASES.get(target)
        if app:
            return _plan("close_application",{"process":app},is_fa,f"{target} را ببندم؟","Closing the application requires confirmation.")
    if any(_word(x) for x in open_words):
        for alias,app in sorted(APP_ALIASES.items(),key=lambda kv:-len(kv[0])):
            if _word(alias):return _plan("open_application",{"app":app},is_fa,f"{alias} را باز می‌کنم.",f"Opening {alias}.")
        for alias,url in sorted(WEB_ALIASES.items(),key=lambda kv:-len(kv[0])):
            if _word(alias):return _plan("open_chrome_url",{"url":url},is_fa,f"{alias} را در Chrome باز می‌کنم.",f"Opening {alias} in Chrome.")

    # If the previous turn asked for a file name, consume the next otherwise-unknown utterance.
    if system_tools.has_pending_file() and not _negative(value) and not low.startswith(("لغو","cancel")):
        pending=system_tools.take_pending_file()
        return _plan("create_file",{"path":str(PathSafeJoin(pending["base"],value.strip('" ')))},is_fa,"فایل ساخته شد.","The file has been created.")

    # If the previous turn asked for a folder name, consume the next otherwise-unknown utterance.
    if system_tools.has_pending_folder() and not _negative(value) and not low.startswith(("لغو","cancel")):
        pending=system_tools.take_pending_folder()
        return _plan("create_folder",{"path":str(PathSafeJoin(pending["base"],value.strip('" ')))},is_fa,"پوشه ساخته شد.","The folder has been created.")

    return None


def _simple_math(text:str)->str|None:
    # Recognize natural arithmetic requests before the general knowledge route.
    # A keyword alone ("what is", "جواب", "درصد") is NOT enough: "what is a CPU?"
    # must reach the chat model, so a real number / number word is required.
    t=text.lower().translate(str.maketrans("۰۱۲۳۴۵۶۷۸۹","0123456789"))
    has_digit=bool(re.search(r"\d",t))
    has_word=bool(re.search(r"(?<![\w])(?:یک|دو|سه|چهار|پنج|شش|هفت|هشت|نه|ده|بیست|سی|چهل|پنجاه|شصت|هفتاد|هشتاد|نود|صد|one|two|three|four|five|six|seven|eight|nine|ten|twenty|thirty|forty|fifty|hundred)(?![\w])",t))
    if (has_digit or has_word) and re.search(r"(?:حساب|محاسبه|چند\s*می(?:شه|شود)|به\s*علاوه|بعلاوه|منهای|منها|ضرب|ضربدر|تقسیم|درصد|ریشه|جذر|سینوس|کسینوس|تانژانت|calculate|compute|solve|what is|plus|minus|times|divided by|percent|square root|sine|cosine|tangent)",t):
        return t
    if re.search(r"[0-9]+(?:\s*[+\-*/%^]\s*[0-9() .]+)+",t): return t
    if re.search(r"(?:یک|دو|سه|چهار|پنج|شش|هفت|هشت|نه|ده|بیست|سی|صد)\s+(?:به\s*علاوه|بعلاوه|منهای|منها|ضربدر|تقسیم)",t): return t
    return None

def PathSafeJoin(base:str,name:str)->str:
    from pathlib import Path
    b=Path(base); clean=Path(str(name).strip().replace("/"," ").replace("\\"," "))
    return str(b / clean.name)
