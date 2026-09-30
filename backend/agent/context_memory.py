from __future__ import annotations

"""Small local conversation memory for Smartis.

This is intentionally in-process and bounded. It stores only recent turns and
lightweight referents so phrases such as «همون موضوع»، «اون رو باز کن» and
«درباره‌ش بیشتر بگو» can be resolved without a cloud service.
"""

from collections import deque
from dataclasses import dataclass
import re
import time
from typing import Any


@dataclass
class Turn:
    user: str
    reply: str = ""
    subject: str = ""
    action: str = ""
    timestamp: float = 0.0


class ConversationMemory:
    def __init__(self, max_turns: int = 12, ttl_seconds: int = 1800) -> None:
        self.turns: deque[Turn] = deque(maxlen=max_turns)
        self.ttl_seconds = ttl_seconds
        self.last_subject = ""
        self.last_action = ""
        self.last_path = ""
        self.last_media = ""
        self.last_url = ""
        self.last_language = "fa"

    def _fresh(self) -> bool:
        if not self.turns:
            return False
        return (time.time() - self.turns[-1].timestamp) <= self.ttl_seconds

    def _subject_from_text(self, text: str) -> str:
        t = re.sub(r"\s+", " ", text).strip()
        # Strong subject markers first.
        patterns = [
            r"(?:درباره(?:ی|ٔ)?|در مورد|راجع به|about|regarding|concerning)\s+(.+?)(?:\s+(?:تحقیق|بررسی|پیدا|بگو|توضیح|چی|چیه|کیه|کن|کنید|کنم)\b|[؟?!.]|$)",
            r"(?:تحقیق|بررسی|مطالعه|پژوهش)\s+(?:درباره|در مورد|راجع به|about|into)\s+(.+?)(?:[؟?!.]|$)",
            r"(?:آهنگ|موزیک|موسیقی|song|track)\s+(.+?)(?:\s+(?:را|رو)?\s*(?:پخش|play|بذار)|[؟?!.]|$)",
        ]
        for p in patterns:
            m = re.search(p, t, re.I)
            if m:
                value = m.group(1).strip(" ،,؟?!.:؛\"'")
                if len(value) >= 2:
                    return value
        return ""

    def remember(self, user: str, plan: dict[str, Any] | None = None, execution: dict[str, Any] | None = None, reply: str = "") -> None:
        user = str(user or "").strip()
        if not user:
            return
        now = time.time()
        subject = self._subject_from_text(user)
        action = ""
        if plan:
            actions = plan.get("actions") or []
            if actions and isinstance(actions[0], dict):
                action = str(actions[0].get("tool") or "")
                args = actions[0].get("args") or {}
                for key in ("query", "city", "path", "name", "url"):
                    value = str(args.get(key) or "").strip()
                    if value and not subject:
                        subject = value
                        break
                if action in {"play_media_search"}:
                    self.last_media = str(args.get("query") or "").strip()
                if action in {"open_file", "open_folder", "open_named", "create_file", "create_folder"}:
                    self.last_path = str(args.get("path") or args.get("name") or "").strip()
                if action in {"open_chrome_url", "open_website"}:
                    self.last_url = str(args.get("url") or "").strip()
        if subject:
            self.last_subject = subject
        if action:
            self.last_action = action
        self.last_language = "en" if re.search(r"[A-Za-z]", user) and not re.search(r"[\u0600-\u06FF]", user) else "fa"
        self.turns.append(Turn(user=user, reply=str(reply or ""), subject=subject, action=action, timestamp=now))

    def resolve_references(self, text: str) -> str:
        """Resolve obvious follow-up references using the latest local subject."""
        if not self._fresh():
            return text
        subject = self.last_subject or self.last_media or self.last_path
        if not subject:
            return text
        t = str(text).strip()
        if not t:
            return t

        # Natural continuation requests should inherit the last knowledge subject.
        if re.search(r"^(?:بیشتر(?:\s+بگو)?|باز هم بگو|ادامه(?:\s+بده)?|tell me more|read more|continue)(?:[؟?!.]*)$", t, re.I):
            if self.last_action in {"web_research", "wikipedia_answer", "wikipedia_lookup", "wikipedia_more"} and subject:
                return f"درباره {subject} بیشتر توضیح بده"

        # Persian forms: درباره‌ش / درباره اش / درباره اون موضوع / اون رو
        direct_forms = (
            "درباره‌ش", "درباره اش", "درباره‌اش", "درباره ش",
            "در موردش", "در مورد اش", "راجع بهش", "راجع به اش",
        )
        for form in direct_forms:
            if form in t:
                return t.replace(form, f"درباره {subject}", 1)

        if re.search(r"(?:درباره|در مورد|راجع به)\s+(?:اون|آن|همون|همان)(?:\s+موضوع)?", t, re.I):
            return re.sub(r"(?:درباره|در مورد|راجع به)\s+(?:اون|آن|همون|همان)(?:\s+موضوع)?", lambda m: f"{m.group(0).split()[0]} {subject}", t, count=1, flags=re.I)

        t2 = re.sub(r"(?:همون موضوع|همان موضوع|همون|همان|اون|آن|this topic|that topic|the same topic|the same|that|it|this)\s*(?:رو|را)?(?=\s|[؟?!.]|$)", subject, t, count=1, flags=re.I)
        return t2

    def context_text(self) -> str:
        if not self._fresh():
            return "No usable recent conversation context."
        lines = []
        if self.last_subject:
            lines.append(f"CURRENT_SUBJECT: {self.last_subject}")
        if self.last_media:
            lines.append(f"LAST_MEDIA: {self.last_media}")
        if self.last_path:
            lines.append(f"LAST_PATH: {self.last_path}")
        if self.last_url:
            lines.append(f"LAST_URL: {self.last_url}")
        for turn in list(self.turns)[-6:]:
            lines.append(f"USER: {turn.user}")
            if turn.reply:
                lines.append(f"SMARTIS: {turn.reply[:300]}")
        return "\n".join(lines)

    def reset(self) -> None:
        self.turns.clear()
        self.last_subject = self.last_action = self.last_path = self.last_media = self.last_url = ""


memory = ConversationMemory()
