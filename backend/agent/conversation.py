from __future__ import annotations

import random
from datetime import datetime

CREATOR = "تیم سعید بهرامی"


def _fa(language: str | None) -> bool:
    return language != "en"


def introduction(language: str | None = None) -> str:
    if _fa(language):
        options = [
            "من Smartis هستم؛ دستیار صوتی ویندوزت. فارسی را در اولویت می‌فهمم و می‌توانم با وب، برنامه‌ها، رسانه و تنظیمات سیستم کار کنم.",
            "من Smartis هستم؛ یک دستیار صوتی فارسی‌محور برای ویندوز. فرمان بده، اجرا می‌کنم و نتیجه را هم برایت می‌گویم.",
            "Smartis هستم؛ دستیار صوتی تو برای کار با ویندوز، جست‌وجو، برنامه‌ها، مدیا و اطلاعات روز.",
            "من Smartis‌ام؛ برای این ساخته شده‌ام که با زبان طبیعی با ویندوز کار کنم، از جست‌وجو گرفته تا کنترل سیستم و رسانه.",
            "اسم من Smartis است. فارسی و انگلیسی را می‌فهمم و برای اجرای کارهای روزمره روی ویندوز در کنارت هستم.",
        ]
    else:
        options = [
            "I'm Smartis, your Windows voice assistant. I understand Persian first and can control apps, media, web tasks, and system actions.",
            "I'm Smartis, a Persian-first desktop assistant for Windows. Tell me what you need and I'll act first, then report the result.",
            "My name is Smartis. I can work with Windows, websites, media players, system controls, and everyday information.",
            "I'm Smartis, built to understand natural Persian and English commands and carry them out on your PC.",
            "Smartis here. I can handle web searches, apps, media, system controls, information, and everyday voice commands.",
        ]
    return random.choice(options)


def creator_answer(language: str | None = None) -> str:
    if _fa(language):
        return f"من توسط {CREATOR} ساخته شدم."
    return "I was created by Saeed Behrami's team."


def capabilities(language: str | None = None) -> str:
    if _fa(language):
        return "می‌توانم برنامه و سایت باز کنم، جست‌وجو کنم، اخبار و آب‌وهوا بخوانم، ریاضی حل کنم، رسانه و صدا را کنترل کنم، فایل و پوشه بسازم یا حذف کنم و تنظیمات ویندوز را مدیریت کنم."
    return "I can open apps and websites, search, read news and weather, solve math, control media and audio, manage files and folders, and open Windows settings."


def greeting(language: str | None = None) -> str:
    fa = _fa(language)
    hour = datetime.now().hour
    if fa:
        if 5 <= hour < 12:
            options = ["درود، صبح بخیر! من خوبم، شما خوبی؟ امروز چه خبر؟", "درود! صبح به خیر، من سرحالم. شما چطورید؟ امروز چه کارهایی داریم؟", "صبح بخیر! من آماده‌ام. شما خوبی؟ بگو امروز از کجا شروع کنیم."]
        elif 12 <= hour < 18:
            options = ["درود! من خوبم، شما خوبی؟ امروز تا اینجا چطور گذشته؟", "سلام! من سرحالم و گوش می‌دم. شما چطورید؟ چه خبر از امروز؟", "درود بر شما! من خوبم. امروز چه خبر؟ چه کاری داری برات انجام بدم؟"]
        else:
            options = ["درود! من خوبم، شما خوبی؟ امشب چه خبر؟", "سلام! من آماده‌ام. روزت چطور گذشت؟", "درود، من خوبم و در خدمتم. امشب چه کاری انجام بدیم؟"]
    else:
        options = ["Hello! I'm doing well. How are you? What's new today?", "Hi! I'm ready to help. How has your day been?", "Hello! I'm good. What's happening today, and what should we do next?"]
    return random.choice(options)
