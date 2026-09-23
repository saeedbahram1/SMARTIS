# Smartis — دستیار صوتی هوشمند (Smart Voice Assistant)

پروژه **Smartis** یک دستیار صوتی دسکتاپ مدرن و هیبریدی برای ویندوز است که با **Flutter Desktop** (رابط کاربری HUD با تم طلایی JARVIS) و **Python FastAPI Backend** ساخته شده است.

---

## معماری صوتی و پردازش گفتار

سیستم پردازش صوتی Smartis دارای ساختار بدون فایل موقت (Zero Disk Overhead) و کنترل مستقیم میکروفون توسط پایتون است:

```text
Windows Microphone
       ↓
Python Backend (PyAudio + SpeechRecognition)
       ↓
    [Online] ──> Google Web Speech (recognize_google)
    [Offline] ─> faster-whisper (Fallback محلی)
       ↓
Fast Path / Ollama Agent
       ↓
TTS (edge-tts / Windows SAPI) ──> پاسخ صوتی
```

### ۱. تبدیل گفتار به متن آنلاین (Online STT)
* پیاده‌سازی شده با: **`SpeechRecognition` + `PyAudio` + `recognize_google`**
* زبان پیش‌فرض فارسی: `fa-IR`
* زبان پیش‌فرض انگلیسی: `en-US`
* **توجه مهم:** این سرویس از موتور داخلی Google Web Speech استفاده می‌کند و **با Google Cloud Speech-to-Text یک سرویس یکسان نیست**. بنابراین به هیچ‌گونه Google Cloud API Key یا اعتبارسنجی ابری نیازی ندارد.
* در حالت آنلاین، هیچ فایل WAV موقتی روی دیسک ذخیره نمی‌شود و جریان بایت‌های صوتی در حافظه رم مستقیماً پردازش می‌گردد.

### ۲. تبدیل گفتار به متن آفلاین (Offline STT Fallback)
* پیاده‌سازی شده با: **`faster-whisper`** و مدل محلی `backend/models/whisper-small`
* چنانچه ارتباط اینترنت قطع باشد، یا متد گوگل با خطای شبکه/تایم‌اوت روبه‌رو شود، سیستم بلافاصله و بدون معطلی به Whisper سوییچ می‌کند تا کاربری سیستم هرگز مختل نشود.

### ۳. تشخیص کلمه بیدارباش (Wake Word)
* کنترل در پس‌زمینه با نشست صوتی یکپارچه در `backend/services/google_voice.py`.
* کلمات کلیدی مورد پشتیبانی:
  * **«اسمارتیز»**، **«اسمارتیس»**، **«اسمارتس»**، **«اسمارتی»**
  * **«Smartis»**، **«Smarties»**، **«Smart is»**
* مجهز به سیستم نرمال‌سازی نویسه‌های عربی/فارسی و تطبیق فازی با فاصله لون‌اشتاین (Levenshtein Distance).
* چرخه پایدار:
  `Wake Listening` → تشخیص کلمه → پاسخ صوتی **«جانم»** → `Command Listening` → تشخیص دستور با Google → اجرای دستور با Fast Path یا Agent → پاسخ صوتی TTS → بازگشت خودکار به `Wake Listening`.

### ۴. تبدیل متن به گفتار (TTS)
* **Online TTS:** سرویس مایکروسافت `edge-tts`
  * صدای فارسی: `fa-IR-DilaraNeural`
  * صدای انگلیسی: `en-US-GuyNeural`
* **Offline TTS:** موتور بومی ویندوز `pyttsx3` / Windows SAPI5 با راه‌اندازی استاندارد ترد COM (`pythoncom.CoInitialize`).

### ۵. مسیر میانبر سریع (Fast Path)
دستورات پرکاربرد زیر بدون اتلاف وقت و بدون معطلی برای LLM محلی بلافاصله اجرا می‌شوند:
* **کروم رو باز کن** / Google Chrome
* **اج رو باز کن** / Microsoft Edge
* **نوت‌پد رو باز کن** / Notepad
* **ماشین حساب رو باز کن** / Calculator
* **فایل اکسپلورر رو باز کن** / File Explorer
* **گوگل رو باز کن** / Google
* **یوتیوب رو باز کن** / YouTube
* **چت جی پی تی رو باز کن** / ChatGPT
* **کلود رو باز کن** / Claude

### ۶. ارتباط Flutter و Backend
* ارتباط صوتی از طریق کانال اختصاصی وب‌سوکت `ws://127.0.0.1:8765/voice` صورت می‌گیرد.
* فلاتر دیگر نیازی به ضبط فایل WAV روی دیسک ندارد و بسته‌های بلااستفاده صوتی حذف شده‌اند.
* رابط کاربری بدون قاب، شفاف، با قابلیت کشیدن با ماوس و مجهز به ویجت انیمیشنی `SmartisOrb` (طلایی `#FFD700`) بدون هیچ‌گونه خطای RenderFlex Overflow است.

---

## پیش‌نیازها و نصب

### ۱. تست و نصب خودکار صوت و وابستگی‌های پایتون
اسکریپت زیر را اجرا کنید:
```bat
INSTALL_GOOGLE_AUDIO.bat
```
این اسکریپت محیط مجازی پایتون (`.venv`) را آماده کرده، نیازمندی‌ها را نصب می‌کند و سلامت `SpeechRecognition`، `PyAudio`، میکروفون‌های فعال سیستم و `Google STT` را به صورت شفاف گزارش می‌دهد:
```text
SpeechRecognition: OK
PyAudio: OK
Microphone: OK (inputs found)
Google STT: READY
```

### ۲. نصب پکیج‌های فلاتر (اختیاری در صورت نیاز)
```cmd
cd frontend
flutter pub get
```

---

## نحوه اجرا

برای اجرای کامل سیستم، دو فایل بتچ تعبیه شده است:

1. اجرای بک‌اند پایتون:
```bat
run_backend.bat
```
2. اجرای فرانت‌اند فلاتر:
```bat
run_frontend.bat
```

در صورت بروز هرگونه مشکل در کش بیلد فلاتر ویندوز، می‌توانید فایل زیر را اجرا کنید:
```bat
REPAIR_WINDOWS.bat
```

---

## سناریوی تست و کاربری

1. دستیار Smartis را اجرا کنید. در پنل Live Log وضعیت `Microphone initialized` و `Listening for wake word` را مشاهده می‌کنید.
2. بگویید: **«اسمارتیز»**
3. Smartis با انیمیشن و صوت پاسخ می‌دهد: **«جانم»**
4. سپس بگویید: **«کروم رو باز کن»**
5. گوگل گفتار شما را با دقت بالا دریافت کرده، Fast Path مرورگر کروم را باز می‌کند، دستیار پاسخ صوتی می‌دهد و بلافاصله دوباره در وضعیت آماده‌باش کلمه کلیدی قرار می‌گیرد.
