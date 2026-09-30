from __future__ import annotations

import re

LEADING_SMARTIS = re.compile(
    r"^\s*(?:smart\s*is|smartis|smarties|smart\s+is|اسمارتیز|اسمارتیس|اسمارتس|اسمارتی|اسمارت)\s*[,،:؛\-]?\s*",
    re.IGNORECASE,
)


def normalize_command_text(text: str) -> str:
    value = str(text or "").strip()
    value = value.replace("\u200c", " ").replace("\u200d", " ")
    value = re.sub(r"\s+", " ", value)
    # The user's command is valid with or without the optional assistant name. We only strip
    # the optional assistant-name prefix when it appears at the beginning of the transcript.
    while True:
        cleaned = LEADING_SMARTIS.sub("", value, count=1).strip()
        if cleaned == value:
            break
        value = cleaned
    return value
