from __future__ import annotations

"""Lightweight web research without an OpenAI/API dependency.

Pipeline: Wikipedia first -> Bing/DuckDuckGo search fallback -> page extraction ->
optional local Ollama synthesis. It never uses a remote LLM API.
"""

import html
import re
from html.parser import HTMLParser
from typing import Any
from urllib.parse import quote_plus, urljoin

import requests

from agent.llm import generate as llm_generate
from agent.ollama_model import ensure_ollama, resolve_model

UA = "Smartis/23 (Windows voice assistant; research)"
TIMEOUT = 5.0


class _TextParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []
        self.skip = 0

    def handle_starttag(self, tag, attrs):
        if tag.lower() in {"script", "style", "noscript", "svg", "nav", "footer", "header", "form"}:
            self.skip += 1

    def handle_endtag(self, tag):
        if tag.lower() in {"script", "style", "noscript", "svg", "nav", "footer", "header", "form"} and self.skip:
            self.skip -= 1

    def handle_data(self, data):
        if not self.skip:
            text = re.sub(r"\s+", " ", html.unescape(data)).strip()
            if text:
                self.parts.append(text)


def _clean_html(raw: str) -> str:
    p = _TextParser()
    try:
        p.feed(raw)
    except Exception:
        pass
    text = " ".join(p.parts)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _get(url: str, **kwargs):
    headers = {"User-Agent": UA, "Accept-Language": "fa,en;q=0.8"}
    headers.update(kwargs.pop("headers", {}) or {})
    return requests.get(url, headers=headers, timeout=TIMEOUT, allow_redirects=True, **kwargs)


def _wikipedia(query: str, language: str) -> dict[str, Any] | None:
    langs = ["fa", "en"] if language == "fa" else ["en", "fa"]
    for lang in langs:
        try:
            r = _get(
                f"https://{lang}.wikipedia.org/w/api.php",
                params={
                    "action": "query", "prop": "extracts|info", "exintro": 1,
                    "explaintext": 1, "inprop": "url", "redirects": 1,
                    "titles": query, "format": "json", "formatversion": 2,
                },
            )
            data = r.json()
            pages = data.get("query", {}).get("pages", [])
            if pages and not pages[0].get("missing"):
                page = pages[0]
                extract = re.sub(r"\s+", " ", str(page.get("extract") or "")).strip()
                if extract:
                    return {"title": page.get("title") or query, "url": page.get("fullurl") or f"https://{lang}.wikipedia.org/wiki/{quote_plus(str(page.get('title') or query)).replace('+','_')}", "text": extract[:9000], "source": "Wikipedia", "language": lang}
        except Exception:
            continue
    return None


def _search_bing(query: str) -> list[dict[str, str]]:
    try:
        raw = _get("https://www.bing.com/search", params={"q": query, "count": 6}).text
        # Bing's result anchors have class=b_algo; parse nearby text conservatively.
        hits = []
        for block in re.findall(r'<li[^>]+class=["\']b_algo["\'][\s\S]*?</li>', raw, re.I)[:8]:
            m = re.search(r'<h2[^>]*>\s*<a[^>]+href=["\']([^"\']+)["\'][^>]*>(.*?)</a>', block, re.I | re.S)
            if not m:
                continue
            title = re.sub(r"<[^>]+>", " ", html.unescape(m.group(2)))
            url = html.unescape(m.group(1))
            text = re.sub(r"<[^>]+>", " ", html.unescape(block))
            text = re.sub(r"\s+", " ", text).strip()
            hits.append({"title": title.strip(), "url": url, "snippet": text[:700]})
        return hits
    except Exception:
        return []


def _search_ddg(query: str) -> list[dict[str, str]]:
    try:
        raw = _get("https://html.duckduckgo.com/html/", params={"q": query}).text
        hits = []
        blocks = re.findall(r'<div[^>]+class=["\']result["\'][\s\S]*?</div>\s*</div>', raw, re.I)
        for block in blocks[:8]:
            m = re.search(r'class=["\']result__a["\'][^>]*href=["\']([^"\']+)["\'][^>]*>(.*?)</a>', block, re.I | re.S)
            if not m:
                continue
            title = re.sub(r"<[^>]+>", " ", html.unescape(m.group(2)))
            url = html.unescape(m.group(1))
            snippet_m = re.search(r'class=["\']result__snippet["\'][^>]*>(.*?)</', block, re.I | re.S)
            snippet = re.sub(r"<[^>]+>", " ", html.unescape(snippet_m.group(1))) if snippet_m else ""
            hits.append({"title": title.strip(), "url": url, "snippet": re.sub(r"\s+", " ", snippet).strip()[:700]})
        return hits
    except Exception:
        return []


def _search(query: str) -> list[dict[str, str]]:
    hits = _search_bing(query)
    if len(hits) < 3:
        hits += _search_ddg(query)
    seen = set()
    out = []
    for hit in hits:
        url = hit.get("url", "")
        if not url or url in seen:
            continue
        seen.add(url)
        out.append(hit)
    return out[:6]


def _fetch(url: str) -> str:
    if not url.startswith(("http://", "https://")):
        return ""
    try:
        r = _get(url)
        ctype = (r.headers.get("content-type") or "").lower()
        if "text/html" not in ctype:
            return ""
        return _clean_html(r.text)[:7000]
    except Exception:
        return ""


def _local_summarize(query: str, language: str, sources: list[dict[str, str]]) -> str | None:
    if not sources:
        return None
    lang_instruction = "پاسخ را طبیعی و دقیق به فارسی بده." if language == "fa" else "Answer naturally and accurately in English."
    source_text = "\n\n".join(
        f"SOURCE: {s.get('title','')}\nURL: {s.get('url','')}\nTEXT: {s.get('text') or s.get('snippet','')}"
        for s in sources
    )[:26000]
    prompt = f"""You are Smartis's local research synthesizer. {lang_instruction}
User question/topic: {query}
Use only the supplied source material. Combine consistent facts, distinguish uncertainty, and do not invent missing facts. Give a concise but useful answer (roughly 4-8 sentences), then a short 'منابع' list in Persian or 'Sources' list in English with source titles.\n\n{source_text}"""
    try:
        if not ensure_ollama().get("ok"):
            return None
        # Route through the single LLM gateway so this request uses the SAME
        # num_ctx / keep_alive / num_thread as chat. The old raw request omitted
        # num_ctx, which made Ollama restart the runner between research and chat.
        result = llm_generate(
            resolve_model(),
            [{"role": "user", "content": prompt}],
            num_predict=500,
            temperature=0.15,
            total_timeout=12.0,
            first_token_timeout=12.0,
            label="research",
        )
        return result.text.strip() or None
    except Exception:
        return None


def research(query: str, language: str | None = None) -> dict[str, Any]:
    q = re.sub(r"\s+", " ", str(query or "")).strip()
    if not q:
        return {"ok": False, "error": "موضوع تحقیق مشخص نیست."}
    lang = "en" if language == "en" else "fa"
    wiki = _wikipedia(q, lang)
    hits = _search(q)
    sources: list[dict[str, str]] = []
    if wiki:
        sources.append(wiki)
    for hit in hits:
        if len(sources) >= 5:
            break
        text = _fetch(hit["url"])
        if text:
            hit = dict(hit)
            hit["text"] = text
        sources.append(hit)
    if not sources:
        return {"ok": False, "error": f"برای «{q}» منبع قابل دسترسی پیدا نشد."}

    answer = _local_summarize(q, lang, sources)
    if not answer:
        if wiki:
            answer = wiki["text"][:1800]
        else:
            answer = sources[0].get("snippet") or sources[0].get("text", "")[:1800]

    # Same follow-up as a plain Wikipedia answer: when the gathered source text is
    # much longer than the summary, queue it so «ادامه بده» / "continue" keeps
    # reading (fast_path turns that reply into wikipedia_more, never chat).
    read_text = str((wiki or {}).get("text") or "").strip()
    if not read_text:
        read_text = " ".join(
            str(s.get("text") or s.get("snippet") or "").strip()
            for s in sources
            if (s.get("text") or s.get("snippet"))
        ).strip()
    ask = ""
    if len(read_text) > len(str(answer)) + 400:
        try:
            from agent import system_tools

            system_tools.set_reading_pending(q, read_text, lang, sources[0].get("url") if sources else None)
            ask = "می‌خوای کامل‌تر بخونم؟" if lang == "fa" else "Would you like me to read more?"
        except Exception:
            ask = ""

    return {
        "ok": True,
        "query": q,
        "answer": answer,
        "sources": [{"title": s.get("title", ""), "url": s.get("url", ""), "source": s.get("source", "Web")} for s in sources[:5]],
        "wikipedia_used": bool(wiki),
        "speak": (str(answer).strip() + (" " + ask if ask else "")).strip(),
    }


def search_open_read(query: str, language: str | None = None) -> dict[str, Any]:
    """«برو تو گوگل X رو جستجو کن، صفحهٔ اولش رو باز کن و بخون» as one command.

    Opens the Google results page and the first real hit in Chrome, reads the
    first page, and queues the text so «ادامه بده» keeps reading.
    """
    q = re.sub(r"\s+", " ", str(query or "")).strip()
    lang = "en" if language == "en" else "fa"
    if not q:
        return {"ok": False, "error": "موضوع جست‌وجو مشخص نیست." if lang == "fa" else "The search topic is missing."}
    try:
        from agent.tools import _open_in_chrome
    except Exception as exc:
        return {"ok": False, "error": str(exc)}

    _open_in_chrome(f"https://www.google.com/search?q={quote_plus(q)}")
    hits = _search(q)
    first = hits[0] if hits else None
    if first:
        _open_in_chrome(first["url"])
    else:
        wiki_probe = _wikipedia(q, lang)
        if wiki_probe:
            first = wiki_probe
            _open_in_chrome(wiki_probe["url"])

    body = ""
    title = q
    url = (first or {}).get("url")
    if first:
        title = str(first.get("title") or q).strip() or q
        body = _fetch(first.get("url", ""))
    if not body:
        wiki = _wikipedia(q, lang)
        if wiki:
            title, body, url = wiki["title"], wiki["text"], wiki["url"]
    if not body:
        snippet = str((first or {}).get("snippet") or "").strip()
        if snippet:
            body = snippet
    if not body:
        return {"ok": False, "error": f"صفحه‌ای دربارهٔ «{q}» باز شد ولی متنی برای خواندن نداشت." if lang == "fa" else f"I opened a page about {q} but there was no readable text."}

    try:
        from agent import system_tools

        system_tools.set_reading_pending(title, body, lang, url)
    except Exception:
        pass
    ask = "می‌خوای کامل‌تر بخونم؟" if lang == "fa" else "Would you like me to read more?"
    short = body[:1500].strip()
    prefix = f"«{title}» را باز کردم. " if lang == "fa" else f"I opened {title}. "
    spoken = f"{prefix}{short} {ask}"
    return {
        "ok": True,
        "query": q,
        "title": title,
        "url": url,
        "message": short,
        "speak": spoken,
        "has_more": len(body) > 1500,
    }
