from __future__ import annotations

"""Chat attachments: the user attaches a file (or a ZIP) in the chat and the
chat model must be able to READ it.

Flow
----
``POST /chat/upload`` (multipart)  -> ``store_upload()``
  * the raw file is saved under ``%TEMP%/smartis_uploads/<id>/``
  * a ZIP is extracted there too (zip-slip guarded, size/entry capped) so its
    FULL structure can be inspected
  * text/code files are read once (capped) and cached in the registry
  * the endpoint returns only PUBLIC stats (id, name, kind, size, counts)

``POST /chat`` with ``attachments: [id, ...]`` -> ``context_for()``
  * builds a compact Persian/English block: file header, full tree, and the
    most relevant text-file excerpts, ranked DETERMINISTICALLY so the block is
    byte-identical across follow-up questions (Ollama then reuses its KV prefix
    cache and skips the ~130 s re-prefill measured on the target machine);
    files explicitly named in the current message are appended at the very END
    as a tail, so a name mention never invalidates the shared prefix
  * the block goes into the conversation as part of the user turn, so the
    model answers about the file instead of guessing

Nothing here executes user files; ZIP extraction never writes outside its own
folder.
"""

import os
import re
import shutil
import tempfile
import threading
import time
import uuid
import zipfile
from pathlib import Path

from agent.logbus import logbus

_TTL_SECONDS = 2 * 3600.0
_MAX_ATTACHMENTS_PER_REQUEST = 4
_MAX_UPLOAD_BYTES = 100 * 1024 * 1024       # one uploaded file
_MAX_ZIP_ENTRIES = 300
_MAX_ZIP_UNCOMPRESSED = 60 * 1024 * 1024    # zip-bomb guard
_TEXT_EXT_EXCERPT_BYTES = 20_000            # read at most this much per text file
_MAX_CACHE_CHARS_PER_FILE = 20_000
_MAX_CONTEXT_CHARS = 2600                   # must fit the chat num_ctx budget
_MAX_TREE_LINES = 36
_MAX_FILES_WITH_CONTENT = 7
_PER_FILE_CHARS = 700

_CODE_EXT = {
    ".py", ".js", ".mjs", ".cjs", ".ts", ".tsx", ".jsx", ".dart", ".java", ".kt",
    ".c", ".h", ".cpp", ".hpp", ".cs", ".go", ".rs", ".rb", ".php", ".swift",
    ".html", ".htm", ".css", ".scss", ".sql", ".sh", ".bat", ".ps1", ".cmd",
    ".json", ".xml", ".yaml", ".yml", ".toml", ".ini", ".cfg", ".conf", ".env",
    ".md", ".txt", ".csv", ".tsv", ".log", ".rst", ".tex", ".gradle", ".dockerfile",
}
_IMAGE_EXT = {".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp", ".tif", ".tiff", ".ico", ".svg"}

_REGISTRY: dict[str, dict] = {}
_LOCK = threading.Lock()
_ROOT: Path | None = None
_SWEEP_AT = 0.0


def _root() -> Path:
    global _ROOT
    if _ROOT is None:
        _ROOT = Path(tempfile.gettempdir()) / "smartis_uploads"
        _ROOT.mkdir(parents=True, exist_ok=True)
        # Anything left from an earlier run is stale by definition.
        for child in _ROOT.iterdir():
            try:
                if child.is_dir():
                    shutil.rmtree(child, ignore_errors=True)
                else:
                    child.unlink(missing_ok=True)
            except OSError:
                pass
    return _ROOT


def _safe_base_name(name: str) -> str:
    base = Path(str(name or "").replace("\\", "/")).name
    base = re.sub(r"[^\w.\- ()\[\]]+", "_", base, flags=re.UNICODE).strip("._ ")
    return base[:80] or "file"


def _human_size(size: int) -> str:
    value = float(size)
    for unit in ("B", "KB", "MB", "GB"):
        if value < 1024 or unit == "GB":
            return f"{value:.0f}{unit}" if unit == "B" else f"{value:.1f}{unit}"
        value /= 1024
    return f"{value:.1f}GB"


def _is_text_name(name: str) -> bool:
    path = Path(name)
    if path.suffix.lower() in _CODE_EXT:
        return True
    return path.name.lower() in {"readme", "license", "makefile", "dockerfile", ".gitignore"}


def _read_text_excerpt(path: Path, limit: int = _TEXT_EXT_EXCERPT_BYTES) -> str | None:
    """Best-effort text read; None when the bytes look binary."""
    try:
        with path.open("rb") as handle:
            raw = handle.read(limit)
    except OSError:
        return None
    if not raw or b"\x00" in raw[:4096]:
        return None
    return raw.decode("utf-8", errors="replace")


def _extract_zip(archive: Path, target: Path) -> tuple[list[dict], int]:
    """Extract with zip-slip / bomb guards. Returns (files, skipped)."""
    files: list[dict] = []
    skipped = 0
    total = 0
    target_resolved = target.resolve()
    try:
        with zipfile.ZipFile(archive) as zf:
            for info in zf.infolist():
                if info.is_dir():
                    continue
                name = info.filename.replace("\\", "/")
                parts = [p for p in name.split("/") if p not in ("", ".")]
                if not parts or ".." in parts or re.match(r"^[A-Za-z]:", name):
                    skipped += 1
                    continue
                if info.flag_bits & 0x1:  # encrypted entry
                    skipped += 1
                    continue
                if len(files) >= _MAX_ZIP_ENTRIES or total + info.file_size > _MAX_ZIP_UNCOMPRESSED:
                    skipped += 1
                    continue
                rel = "/".join(parts)
                dest = (target_resolved / rel).resolve()
                if not dest.is_relative_to(target_resolved):
                    skipped += 1
                    continue
                dest.parent.mkdir(parents=True, exist_ok=True)
                with zf.open(info) as src, dest.open("wb") as out:
                    shutil.copyfileobj(src, out, length=65536)
                total += info.file_size
                files.append({"rel": rel, "size": int(info.file_size)})
    except zipfile.BadZipFile:
        return [], 0
    return files, skipped


def _kind_of(suffix: str, is_zip: bool) -> str:
    if is_zip:
        return "zip"
    low = suffix.lower()
    if low in _IMAGE_EXT:
        return "image"
    if low in _CODE_EXT:
        return "text"
    return "other"


_KIND_LABEL = {
    "fa": {"zip": "زیپ", "image": "تصویر", "text": "متنی", "other": "فایل"},
    "en": {"zip": "ZIP", "image": "image", "text": "text", "other": "file"},
}


def _sweep_locked(now: float) -> None:
    dead = [key for key, item in _REGISTRY.items() if now - float(item.get("created") or 0) > _TTL_SECONDS]
    for key in dead:
        item = _REGISTRY.pop(key, None)
        if item:
            shutil.rmtree(Path(item["dir"]), ignore_errors=True)


def store_upload(filename: str, data: bytes, language: str | None = None) -> dict:
    """Save ONE uploaded file, inspect it, and register it for chat context."""
    if not data:
        return {"ok": False, "error": "فایل خالی است." if (language or "fa") != "en" else "The file is empty."}
    if len(data) > _MAX_UPLOAD_BYTES:
        limit = _human_size(_MAX_UPLOAD_BYTES)
        return {
            "ok": False,
            "error": f"حجم فایل بیشتر از {limit} است." if (language or "fa") != "en" else f"File is larger than {limit}.",
        }

    root = _root()
    key = f"{int(time.time() * 1000):x}{uuid.uuid4().hex[:6]}"
    folder = root / key
    folder.mkdir(parents=True, exist_ok=True)
    name = _safe_base_name(filename)
    raw_path = folder / name
    raw_path.write_bytes(data)

    is_zip = zipfile.is_zipfile(raw_path)
    kind = _kind_of(raw_path.suffix, is_zip)
    record: dict = {
        "id": key,
        "name": name,
        "dir": str(folder),
        "path": str(raw_path),
        "kind": kind,
        "size": len(data),
        "created": time.time(),
        "files": [],
        "folders": 0,
        "skipped": 0,
        "text": None,
    }

    if is_zip:
        extract_dir = folder / "extracted"
        extract_dir.mkdir(exist_ok=True)
        entries, skipped = _extract_zip(raw_path, extract_dir)
        record["files"] = entries
        record["skipped"] = skipped
        record["folders"] = len({
            "/".join(f["rel"].split("/")[:-1])
            for f in entries
            if "/" in f["rel"]
        })
        for item in entries:
            if item["size"] <= 2 * 1024 * 1024 and _is_text_name(item["rel"]):
                text = _read_text_excerpt(extract_dir / item["rel"])
                if text:
                    item["text"] = text[:_MAX_CACHE_CHARS_PER_FILE]
        logbus.emit(
            "ATTACH",
            f"Attached ZIP inspected: {len(entries)} file(s), {record['folders']} folder(s).",
            name,
        )
    elif kind == "text":
        text = _read_text_excerpt(raw_path)
        record["text"] = (text or "")[:_MAX_CACHE_CHARS_PER_FILE]
        record["files"] = [{"rel": name, "size": len(data), "text": record["text"]}]
        logbus.emit("ATTACH", "Attached text file inspected.", f"{name} ({_human_size(len(data))})")
    else:
        logbus.emit("ATTACH", f"Attached {kind} file registered.", f"{name} ({_human_size(len(data))})")

    with _LOCK:
        _sweep_locked(time.time())
        _REGISTRY[key] = record

    return {
        "ok": True,
        "id": key,
        "name": name,
        "kind": kind,
        "size": len(data),
        "size_label": _human_size(len(data)),
        "files": len(record["files"]),
        "folders": int(record["folders"]),
        "skipped": int(record["skipped"]),
        "chars": sum(len(str(f.get("text") or "")) for f in record["files"]) if is_zip else len(str(record["text"] or "")),
    }


def get_attachment(key: str) -> dict | None:
    with _LOCK:
        record = _REGISTRY.get(str(key))
        if record and time.time() - float(record.get("created") or 0) > _TTL_SECONDS:
            _REGISTRY.pop(str(key), None)
            shutil.rmtree(Path(record["dir"]), ignore_errors=True)
            return None
        return record


def _score_file(item: dict) -> float:
    """Rank excerpts by STATIC relevance only - never by the user's wording.

    The block rides on the system message and Ollama reuses the KV of the
    longest common token prefix between requests, so any turn-to-turn byte
    change costs a full re-prefill (~130 s measured). Questions that name a
    file still get that file's content via the volatile tail appended after
    the stable block (``_named_tail``).
    """
    rel = str(item.get("rel") or "")
    low_rel = rel.lower()
    score = 0.0
    base = low_rel.rsplit("/", 1)[-1]
    if base.startswith("readme") or "readme" in base:
        score += 30.0
    if re.match(r"(main|index|app|start|server|cli)\.", base):
        score += 20.0
    if Path(base).suffix.lower() in _CODE_EXT:
        score += 5.0
    if "/" in rel:
        score += 1.0
    score -= min(float(item.get("size") or 0) / 1_000_000.0, 20.0)
    return score


def _file_line(rel: str, size: int) -> str:
    return f"- {rel} ({_human_size(size)})"


def _named_tail(readable: list[dict], chosen: set[str], user_text: str, used: int, fa: bool) -> list[str]:
    """Excerpts of files the user named in THIS message.

    Appended AFTER the stable block, so the shared KV prefix of earlier turns
    stays reusable - a name mention only forces a prefill of this small tail.
    """
    low = str(user_text or "").lower()
    if not low:
        return []
    lines: list[str] = []
    added = 0
    for item in readable:
        rel = str(item.get("rel") or "")
        base = rel.rsplit("/", 1)[-1].lower()
        if not base or rel in chosen or base not in low:
            continue
        if added >= 2 or used >= _MAX_CONTEXT_CHARS - 150:
            break
        text = str(item.get("text") or "")
        cut = text[:_PER_FILE_CHARS]
        if len(text) > _PER_FILE_CHARS:
            cut = cut.rstrip() + ("\n…(بریده شد)" if fa else "\n...(truncated)")
        lines += [f"--- {rel} ---", cut]
        used += len(cut) + len(rel) + 12
        added += 1
    return lines


def _zip_block_fa(record: dict, user_text: str) -> str:
    name = record["name"]
    files = list(record["files"])
    folders = int(record["folders"])
    skipped = int(record.get("skipped") or 0)
    head = (
        f"=== پیوست کاربر: {name} | زیپ | {_human_size(record['size'])} | "
        f"{len(files)} فایل، {folders} پوشه ==="
    )
    if skipped:
        head += f"\n({skipped} مورد مشکوک/بزرگ در زیپ نادیده گرفته شد.)"
    shown = files[:_MAX_TREE_LINES]
    tree_lines = [_file_line(f["rel"], f["size"]) for f in shown]
    if len(files) > len(shown):
        tree_lines.append(f"- ... و {len(files) - len(shown)} فایل دیگر")
    parts = [head, "ساختار کامل فایلها:", *tree_lines]

    budget = _MAX_CONTEXT_CHARS
    used = sum(len(p) + 1 for p in parts)
    readable = [f for f in files if f.get("text")]
    readable.sort(key=lambda f: (_score_file(f), -(f.get("size") or 0)), reverse=True)
    excerpt_lines: list[str] = []
    chosen: set[str] = set()
    taken = 0
    for item in readable:
        if taken >= _MAX_FILES_WITH_CONTENT or used >= budget - 120:
            break
        room = min(_PER_FILE_CHARS, budget - used - 60)
        if room < 120:
            break
        text = str(item.get("text") or "")
        cut = text[:room]
        if len(text) > room:
            cut = cut.rstrip() + "\n…(بریده شد)"
        excerpt_lines += [f"--- {item['rel']} ---", cut]
        chosen.add(str(item["rel"]))
        used += len(cut) + len(item["rel"]) + 12
        taken += 1
    if excerpt_lines:
        parts += ["محتوای مهمترین فایلهای متنی:", *excerpt_lines]
    else:
        parts.append("(فایل متنی قابل خواندنی داخل زیپ نیست.)")
    tail = _named_tail(readable, chosen, user_text, used, fa=True)
    if tail:
        parts += ["فایل‌هایی که کاربر در همین پیام نام برده:", *tail]
    return "\n".join(parts)


def _zip_block_en(record: dict, user_text: str) -> str:
    name = record["name"]
    files = list(record["files"])
    folders = int(record["folders"])
    skipped = int(record.get("skipped") or 0)
    head = (
        f"=== User attachment: {name} | ZIP | {_human_size(record['size'])} | "
        f"{len(files)} files, {folders} folders ==="
    )
    if skipped:
        head += f"\n({skipped} suspicious/oversized entr(ies) were skipped.)"
    shown = files[:_MAX_TREE_LINES]
    tree_lines = [_file_line(f["rel"], f["size"]) for f in shown]
    if len(files) > len(shown):
        tree_lines.append(f"- ... and {len(files) - len(shown)} more files")
    parts = [head, "Full file tree:", *tree_lines]
    budget = _MAX_CONTEXT_CHARS
    used = sum(len(p) + 1 for p in parts)
    readable = [f for f in files if f.get("text")]
    readable.sort(key=lambda f: (_score_file(f), -(f.get("size") or 0)), reverse=True)
    excerpt_lines: list[str] = []
    chosen: set[str] = set()
    taken = 0
    for item in readable:
        if taken >= _MAX_FILES_WITH_CONTENT or used >= budget - 120:
            break
        room = min(_PER_FILE_CHARS, budget - used - 60)
        if room < 120:
            break
        text = str(item.get("text") or "")
        cut = text[:room]
        if len(text) > room:
            cut = cut.rstrip() + "\n...(truncated)"
        excerpt_lines += [f"--- {item['rel']} ---", cut]
        chosen.add(str(item["rel"]))
        used += len(cut) + len(item["rel"]) + 12
        taken += 1
    if excerpt_lines:
        parts += ["Key text-file contents:", *excerpt_lines]
    else:
        parts.append("(No readable text file inside this ZIP.)")
    tail = _named_tail(readable, chosen, user_text, used, fa=False)
    if tail:
        parts += ["Files the user named in this message:", *tail]
    return "\n".join(parts)


def _single_block(record: dict, lang: str) -> str:
    fa = lang != "en"
    kind = record["kind"]
    label = _KIND_LABEL["fa" if fa else "en"].get(kind, kind)
    head = (
        f"=== پیوست کاربر: {record['name']} | {label} | {_human_size(record['size'])} ==="
        if fa else
        f"=== User attachment: {record['name']} | {label} | {_human_size(record['size'])} ==="
    )
    if kind == "text":
        text = str(record.get("text") or "")
        room = _MAX_CONTEXT_CHARS - len(head) - 40
        cut = text[:room]
        if len(text) > room:
            cut = cut.rstrip() + ("\n…(بریده شد)" if fa else "\n...(truncated)")
        return f"{head}\n{cut}" if cut else head
    if kind == "image":
        note = (
            "این یک تصویر است؛ محتوای داخلی تصویر قابل خواندن نیست و فقط نام و حجم آن را می‌بینی. "
            "اگر کاربر دربارهٔ جزئیات تصویر پرسید صادقانه بگو فقط مشخصات فایل را می‌بینی."
            if fa else
            "This is an image; its inner pixels are not readable here - only name and size are known. "
            "If the user asks about image details, say you can only see the file metadata."
        )
        return f"{head}\n{note}"
    note = (
        "فایل دودویی/ناشناخته است؛ محتوایش قابل خواندن نیست و فقط مشخصات آن در دسترس است."
        if fa else
        "Binary/unknown file; its content is not readable here - only metadata is available."
    )
    return f"{head}\n{note}"


def context_for(ids, lang: str | None, user_text: str = "") -> str:
    """Compact context block for the given attachment ids (unknown ids ignored)."""
    if not ids:
        return ""
    blocks: list[str] = []
    for key in list(ids)[:_MAX_ATTACHMENTS_PER_REQUEST]:
        record = get_attachment(str(key))
        if not record:
            logbus.emit("ATTACH", "Attachment id is unknown or expired; ignored.", str(key))
            continue
        if record["kind"] == "zip":
            blocks.append(_zip_block_fa(record, user_text) if lang != "en" else _zip_block_en(record, user_text))
        else:
            blocks.append(_single_block(record, "fa" if lang != "en" else "en"))
    if not blocks:
        return ""
    if len(blocks) > 1:
        joined = "\n\n".join(blocks)
    else:
        joined = blocks[0]
    if lang != "en":
        intro = "پیوست‌های کاربر (بر اساس همین محتوا پاسخ بده و چیزی از خودت اضافه نکن):\n"
    else:
        intro = "User attachments (answer based on this content; do not invent):\n"
    block = intro + joined
    if len(block) > _MAX_CONTEXT_CHARS:
        block = block[: _MAX_CONTEXT_CHARS - 2].rstrip() + "\n…"
    return block
