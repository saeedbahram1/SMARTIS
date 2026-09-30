from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np

BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))

from agent.command_normalizer import normalize_command_text  # noqa: E402
from agent.fast_path import fast_plan  # noqa: E402
from agent.conversation import creator_answer, greeting, introduction  # noqa: E402
from agent.executor import clear_pending_confirmation, execute_plan, pending_confirmation  # noqa: E402
from agent import system_tools  # noqa: E402
from services.sherpa_service import SherpaService  # noqa: E402
from main import _json_payload, _affirmative_text, _negative_text  # noqa: E402


def action(text: str, language: str = "fa") -> dict:
    result = fast_plan(text, language)
    if not result or not result.get("ok"):
        raise AssertionError(f"No fast-path plan for: {text!r}")
    return result["plan"]["actions"][0]


def main() -> int:
    assert normalize_command_text("اسمارتیز گوگل رو باز کن") == "گوگل رو باز کن"
    assert normalize_command_text("Smartis play music") == "play music"

    encoded = _json_payload(
        {
            "numpy_bool": np.bool_(True),
            "numpy_float": np.float32(1.25),
            "numpy_array": np.array([np.int64(1), np.bool_(False)]),
        }
    )
    assert json.loads(encoded) == {
        "numpy_bool": True,
        "numpy_float": 1.25,
        "numpy_array": [1, False],
    }

    assert SherpaService._looks_persian("گوگل را باز کن")
    assert SherpaService._looks_english("open google")
    assert not SherpaService._looks_persian("open google")
    assert not SherpaService._looks_english("گوگل را باز کن")

    expected = {
        "اسمارتیز گوگل رو باز کن": "open_chrome_url",
        "گوگل رو باز کن": "open_chrome_url",
        "اسمارتیز بزن آهنگ بعدی": "media_next",
        "فیلم رو نگه دار": "media_play_pause",
        "پخش رو متوقف کن": "media_stop",
        "صدا 20 درصد": "system_volume_set",
        "صدا ده درصد": "system_volume_set",
        "صدا رو 20 درصد زیاد کن": "system_volume_change",
        "صدا رو قطع کن": "system_mute",
        "صدا رو وصل کن": "system_mute",
        "صدا رو باز کن": "system_mute",
        "صدای آهنگ 150 درصد": "player_volume_set",
        "صدای آهنگ رو ببر تا آخر": "player_volume_max",
        "آهنگ رو بی صدا کن": "player_mute",
        "آهنگ رو وصل کن": "player_mute",
        "آهنگ شایع ترک عصبانی رو پخش کن": "play_media_search",
        "هوای شهر همدان": "get_weather",
        "هوای کرج": "get_weather",
        "ساعت دقیق چنده": "get_time_date",
        "تاریخ امروز چنده": "get_time_date",
        "زبان سیستم رو بزار رو فارسی": "set_windows_language",
        "تنظیمات سیستم رو باز کن": "open_windows_settings",
        "سرچ سیستم رو باز کن سرچ کن کنترل پنل": "windows_system_search",
        "برو تو درایو سی پوشه Test رو پیدا کن و حذفش کن": "delete_named",
        "روی دسکتاپ یه فایل بساز": None,
        "روی دسکتاپ یه پوشه بساز": None,
    }
    for text, tool in expected.items():
        result = fast_plan(text, "fa")
        if tool is None:
            assert result and result["plan"]["actions"] == []
        else:
            assert action(text)["tool"] == tool, (text, action(text))

    combined = fast_plan("برو تو گوگل و آهنگ شایع ترک عصبانی رو پخش کن", "fa")
    assert combined and len(combined["plan"]["actions"]) == 2
    assert [a["tool"] for a in combined["plan"]["actions"]] == ["open_chrome_url", "play_media_search"]
    natural_combo = fast_plan("گوگل را باز کن و بعد آهنگ شایع ترک عصبانی را پخش کن", "fa")
    assert natural_combo and [a["tool"] for a in natural_combo["plan"]["actions"]] == ["open_chrome_url", "play_media_search"]

    chain = fast_plan("اسمارتیز گوگل رو باز کن سرچ کن تام هاردی و صفحه ویکی پدیاش رو باز کن", "fa")
    assert chain and [a["tool"] for a in chain["plan"]["actions"]] == ["open_chrome_url", "open_chrome_url", "open_wikipedia_page"]
    assert chain["plan"]["actions"][2]["args"]["query"] == "تام هاردی"
    assert chain["plan"]["actions"][1]["args"]["url"].startswith("https://www.google.com/search?q=")
    assert "%D8%AA%D8%A7%D9%85+%D9%87%D8%A7%D8%B1%D8%AF%DB%8C" in chain["plan"]["actions"][1]["args"]["url"]

    en_chain = fast_plan("open google search for Tom Hardy and open his Wikipedia page", "en")
    assert en_chain and [a["tool"] for a in en_chain["plan"]["actions"]] == ["open_chrome_url", "open_chrome_url", "open_wikipedia_page"]
    assert en_chain["plan"]["actions"][2]["args"]["query"] == "Tom Hardy"

    assert fast_plan("ایلان ماسک کیه", "fa")["plan"]["actions"][0]["tool"] == "web_research"
    assert fast_plan("در مورد زمین برام توضیح بده از ویکی پدیا", "fa")["plan"]["actions"][0]["tool"] == "web_research"
    assert fast_plan("آخرین اخبار", "fa")["plan"]["actions"][0]["tool"] == "get_news"
    assert fast_plan("سینوس 30 درجه", "fa")["plan"]["actions"][0]["tool"] == "calculate"
    assert fast_plan("دو به علاوه صد و بیست و پنج", "fa")["plan"]["actions"][0]["tool"] == "calculate"

    assert system_tools.calculate("سی درصد از پانصد", "fa")["result"] == "150"
    assert system_tools.calculate("ریشه دوم 81", "fa")["result"] == "9"
    assert system_tools.calculate("سینوس 30 درجه", "fa")["result"] == "0.5"

    intro1 = introduction("fa")
    intro2 = introduction("fa")
    assert intro1 and intro2
    assert "Smartis" in intro1
    assert "تیم سعید بهرامی" in creator_answer("fa")
    assert greeting("fa")

    assert fast_plan("گوگل رو باز کن بعد تام هاردی رو سرچ کن", "fa")["plan"]["actions"][1]["args"]["url"].startswith("https://www.google.com/search?q=")
    assert fast_plan("اول گوگل رو باز کن، بعد تام هاردی رو سرچ کن", "fa")["plan"]["actions"][1]["args"]["url"].startswith("https://www.google.com/search?q=")
    assert fast_plan("برو گوگل و تام هاردی رو سرچ کن", "fa")["plan"]["actions"][1]["args"]["url"].startswith("https://www.google.com/search?q=")
    assert fast_plan("آهنگ علی و رضا رو پخش کن", "fa")["plan"]["actions"][0]["args"]["query"] == "علی و رضا"

    # Confirmation must be queued, then natural Persian/English responses recognized.
    clear_pending_confirmation()
    pending_result = execute_plan({"reply": "confirm?", "actions": [{"tool": "shutdown_windows", "args": {}}]}, False)
    assert pending_result["needs_confirmation"] is True and pending_confirmation()
    assert _affirmative_text("تأیید") is True
    assert _affirmative_text("بله انجام بده") is True
    assert _affirmative_text("آره انجامش بده") is True
    assert _negative_text("نه لغو کن") is True
    assert _negative_text("بیخیال شو") is True
    clear_pending_confirmation()

    print("SMARTIS STAGE 26 SELF-TEST: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
