from __future__ import annotations

"""Stateful browser automation for the agent.

`open_website` (in tools.py) just calls webbrowser.open() — that hands the URL
to whatever the user's default browser is, and Python has no further control
over that window. It's fine for "باز کن" (just open this), but it can never
support "برو به سایت X، این متن رو بنویس، بفرست، جوابشو برام بخون" (go to X,
type this, send it, read me the answer), because there is nothing left to
drive afterwards.

These tools instead drive a single, reused Selenium Chrome session, so a plan
can chain: browser_open -> browser_type -> browser_submit -> browser_read_response,
all against the same live page.
"""

import threading
import time
from typing import Any, Optional

_lock = threading.Lock()
_driver = None  # lazily-created, reused across calls until browser_close


def _get_driver():
    global _driver
    with _lock:
        if _driver is not None:
            try:
                _ = _driver.title  # cheap liveness check
                return _driver
            except Exception:
                _driver = None
        try:
            from selenium import webdriver
            from selenium.webdriver.chrome.options import Options
        except Exception as exc:
            raise RuntimeError(
                "Selenium is not installed. Run: pip install selenium webdriver-manager"
            ) from exc

        options = Options()
        options.add_argument("--start-maximized")
        options.add_argument("--disable-notifications")
        options.add_experimental_option("excludeSwitches", ["enable-automation"])
        options.add_experimental_option("useAutomationExtension", False)

        try:
            # Prefer Selenium Manager (bundled with recent Selenium): no extra
            # setup needed, it fetches the right chromedriver automatically.
            _driver = webdriver.Chrome(options=options)
        except Exception:
            # Fall back to webdriver-manager for older environments.
            from selenium.webdriver.chrome.service import Service
            from webdriver_manager.chrome import ChromeDriverManager
            _driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=options)
        return _driver


def _visible_text_length(driver) -> int:
    try:
        return len(driver.execute_script("return document.body ? document.body.innerText : ''") or "")
    except Exception:
        return 0


_FIELD_JS = r"""
function isVisible(el){
  const r = el.getBoundingClientRect();
  const s = window.getComputedStyle(el);
  return r.width > 4 && r.height > 4 && s.visibility !== 'hidden' && s.display !== 'none';
}
function score(el){
  let sc = 0;
  const tag = el.tagName.toLowerCase();
  if (tag === 'textarea') sc += 5;
  if (el.getAttribute('contenteditable') === 'true') sc += 5;
  if (tag === 'input') {
    const t = (el.getAttribute('type') || 'text').toLowerCase();
    if (['text','search','email','url',''].includes(t)) sc += 3; else return -1;
  }
  const ph = (el.getAttribute('placeholder') || '').toLowerCase();
  const aria = (el.getAttribute('aria-label') || '').toLowerCase();
  const blob = ph + ' ' + aria;
  if (/message|prompt|ask|search|type|بنویس|پیام|سوال|جستجو/.test(blob)) sc += 4;
  const r = el.getBoundingClientRect();
  sc += Math.max(0, 200 - Math.abs(r.top + r.height/2 - window.innerHeight*0.7)) / 100;
  return sc;
}
let best = null, bestScore = -1;
const active = document.activeElement;
if (active && (active.tagName === 'TEXTAREA' || active.tagName === 'INPUT' || active.getAttribute('contenteditable') === 'true')) {
  best = active; bestScore = 999;
}
const candidates = document.querySelectorAll('textarea, input, [contenteditable="true"]');
for (const el of candidates) {
  if (!isVisible(el) || el.disabled) continue;
  const sc = score(el);
  if (sc > bestScore) { bestScore = sc; best = el; }
}
if (!best) return false;
best.scrollIntoView({block:'center'});
best.focus();
window.__smartis_target = best;
return true;
"""


def browser_open(url: str) -> dict[str, Any]:
    if not url:
        return {"ok": False, "error": "URL is empty."}
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    try:
        driver = _get_driver()
        driver.get(url)
        time.sleep(1.2)  # let the page settle before anything else touches it
        return {"ok": True, "message": f"Opened {url}.", "url": url}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def browser_type(text: str) -> dict[str, Any]:
    text = str(text or "")
    if not text.strip():
        return {"ok": False, "error": "Text is empty."}
    try:
        driver = _get_driver()
        found = driver.execute_script(_FIELD_JS)
        if not found:
            return {"ok": False, "error": "No usable text field found on the page."}
        from selenium.webdriver.common.by import By  # noqa: F401 (kept for clarity/extension)
        el = driver.execute_script("return window.__smartis_target")
        el.send_keys(text)
        return {"ok": True, "message": "Text entered."}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def browser_submit() -> dict[str, Any]:
    try:
        driver = _get_driver()
        driver.execute_script("window.__smartis_before_len = document.body ? document.body.innerText.length : 0;")
        el = driver.execute_script("return window.__smartis_target")
        from selenium.webdriver.common.keys import Keys
        if el is not None:
            el.send_keys(Keys.RETURN)
        else:
            driver.switch_to.active_element.send_keys(Keys.RETURN)
        return {"ok": True, "message": "Submitted."}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def browser_read_response(max_wait_seconds: float = 20.0) -> dict[str, Any]:
    """Wait for new content to appear after a submit, then return it.

    Heuristic: poll the page's visible text length until it stops growing for
    ~1.2s (streaming responses keep growing), then diff against the length
    captured right before submit to isolate the newly-added text.
    """
    try:
        driver = _get_driver()
        before_len = driver.execute_script("return window.__smartis_before_len || 0")
        start = time.time()
        last_len = _visible_text_length(driver)
        stable_since = time.time()
        while time.time() - start < max_wait_seconds:
            time.sleep(0.5)
            cur_len = _visible_text_length(driver)
            if cur_len != last_len:
                last_len = cur_len
                stable_since = time.time()
            elif time.time() - stable_since > 1.2 and cur_len > before_len:
                break

        full_text = driver.execute_script("return document.body ? document.body.innerText : ''") or ""
        new_text = full_text[before_len:].strip()
        # Trim to something reasonable to speak aloud / show in the transcript.
        snippet = new_text[:1200].strip() or full_text[-1200:].strip()
        if not snippet:
            return {"ok": False, "error": "No new content appeared on the page."}
        return {"ok": True, "message": "Read response.", "response_text": snippet, "speak": snippet}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def browser_close() -> dict[str, Any]:
    global _driver
    with _lock:
        if _driver is not None:
            try:
                _driver.quit()
            except Exception:
                pass
            _driver = None
    return {"ok": True, "message": "Browser closed."}
