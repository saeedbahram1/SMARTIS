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

from config import OLLAMA_MODEL, OLLAMA_URL

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
        r = requests.post(
            f"{OLLAMA_URL}/api/chat",
            json={"model": OLLAMA_MODEL, "stream": False, "messages": [{"role": "user", "content": prompt}], "options": {"temperature": 0.15, "num_predict": 500}},
            timeout=12,
        )
        r.raise_for_status()
        text = str(r.json().get("message", {}).get("content", "")).strip()
        return text or None
    except Exception:
        return None


def research(query: str, language: str | None = None) -> dict[str, Any]:
    q = re.sub(r"\s+", " ", str(query or "")).strip()
    if not q:
        return {"ok": False, "error": "موضوع تحقیق مشخص نیست."}
    lang = "en" if language == "en" else "fa"
    wiki = _wikipedia(q, lang)
    if wiki:
        # Keep Wikipedia continuation available after a normal research answer.
        try:
            from agent import system_tools
            system_tools._set_pending(str(wiki.get("title") or q), str(wiki.get("language") or lang), str(wiki.get("text") or ""), str(wiki.get("url") or "") or None)
        except Exception:
            pass
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

    return {
        "ok": True,
        "query": q,
        "answer": answer,
        "sources": [{"title": s.get("title", ""), "url": s.get("url", ""), "source": s.get("source", "Web")} for s in sources[:5]],
        "wikipedia_used": bool(wiki),
        "speak": answer,
    }
