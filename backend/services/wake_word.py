import re
from config import WAKE_WORDS
FA_RE=re.compile(r'[\u0600-\u06FF]')

# Different keyboards/STT engines emit Arabic-script look-alikes instead of the
# Persian letters (ي vs ی, ك vs ک, ...). If we don't fold these together, a wake
# word can silently fail to match even though the text is "correct" to a human.
_CHAR_MAP=str.maketrans({
    'ي':'ی','ى':'ی','ئ':'ی',
    'ك':'ک',
    'ة':'ه',
    'ؤ':'و',
    'أ':'ا','إ':'ا','آ':'ا',
    '\u064a':'ی','\u0649':'ی',
})

def normalize(text):
    value=str(text or '').lower().translate(_CHAR_MAP).replace('‌',' ')
    value=re.sub(r'[^\w\u0600-\u06FF]+',' ',value,flags=re.UNICODE)
    return ' '.join(value.split())

def _levenshtein_leq(a,b,max_dist):
    """Cheap bounded edit-distance check (no extra dependency needed)."""
    if abs(len(a)-len(b))>max_dist: return False
    prev=list(range(len(b)+1))
    for i,ca in enumerate(a,1):
        cur=[i]+[0]*len(b)
        for j,cb in enumerate(b,1):
            cost=0 if ca==cb else 1
            cur[j]=min(prev[j]+1,cur[j-1]+1,prev[j-1]+cost)
        prev=cur
        if min(prev)>max_dist: return False
    return prev[-1]<=max_dist

def detect_wake_word(text):
    normalized=normalize(text); compact=normalized.replace(' ','')
    if not compact: return {'detected':False,'language':None,'wake_word':None}
    aliases=list(WAKE_WORDS)+[
        'اسمارتی','اسمارتیص','اسمارت','ای اسمارت','هی اسمارتیز','سلام اسمارتیز','الو اسمارتیز','بگو اسمارتیز',
        'smartis','smarties','smart is','hey smartis','hi smartis','smartiz','smartist','smartest','smartees','سمارتیز','اسمارتز'
    ]
    words=normalized.split()
    for alias in aliases:
        c=normalize(alias); cc=c.replace(' ','')
        if not cc: continue
        if c in normalized or cc in compact:
            return {'detected':True,'language':'fa' if FA_RE.search(c) else 'en','wake_word':alias}
        # Fuzzy fallback: tolerate 1-2 char STT mistakes on any single word/phrase
        # of similar length instead of requiring an exact substring match.
        max_dist=1 if len(cc)<=5 else 2
        for w in words:
            if _levenshtein_leq(w,cc,max_dist):
                return {'detected':True,'language':'fa' if FA_RE.search(c) else 'en','wake_word':alias}
    return {'detected':False,'language':None,'wake_word':None}
