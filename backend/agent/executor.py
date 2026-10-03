from __future__ import annotations

import threading
import time
from typing import Any, Callable

from agent.tools import execute_tool
from config import CONFIRMATION_TTL_SECONDS, REQUIRE_CONFIRMATION_FOR

_PENDING_LOCK = threading.Lock()
_PENDING_CONFIRMATION: dict[str, Any] | None = None
_PENDING_AT: float = 0.0
_PENDING_TTL = CONFIRMATION_TTL_SECONDS


def validate_actions(actions: list[dict[str, Any]]) -> list[str]:
    errors = []
    for i, action in enumerate(actions):
        if not isinstance(action, dict):
            errors.append(f"Action {i} is not an object.")
            continue
        if not isinstance(action.get("tool"), str) or not action.get("tool"):
            errors.append(f"Action {i} has no tool.")
    return errors


# --------------------------------------------------------------------------
# Human description of a confirmation-gated action (used for the question the
# user is asked, so "yes" is always given for something specific).
# --------------------------------------------------------------------------
def describe_action(tool: str, args: dict[str, Any] | None, language: str | None = "fa") -> str:
    args = args or {}
    fa = language != "en"
    name = str(args.get("name") or args.get("path") or args.get("process") or "").strip()
    table = {
        "shutdown_windows": ("سیستم را خاموش کنم؟", "Shut down the computer?"),
        "restart_windows": ("سیستم را راه‌اندازی مجدد کنم؟", "Restart the computer?"),
        "sleep_windows": ("سیستم را به حالت خواب ببرم؟", "Put the computer to sleep?"),
        "delete_named": (f"«{name}» را پیدا و برای همیشه حذف کنم؟", f"Find and permanently delete “{name}”?"),
        "delete_file": (f"«{name}» را برای همیشه حذف کنم؟", f"Permanently delete “{name}”?"),
        "close_application": (f"برنامهٔ «{name}» را ببندم؟", f"Close the application “{name}”?"),
    }
    fa_text, en_text = table.get(tool, ("این کار را انجام بدهم؟", "Do you want me to do this?"))
    suffix_fa = " بگو «بله» یا «لغو»."
    suffix_en = " Say “yes” or “cancel”."
    return (fa_text + suffix_fa) if fa else (en_text + suffix_en)


def pending_confirmation() -> bool:
    global _PENDING_CONFIRMATION, _PENDING_AT
    with _PENDING_LOCK:
        if _PENDING_CONFIRMATION is not None and time.time() - _PENDING_AT > _PENDING_TTL:
            _PENDING_CONFIRMATION = None
            _PENDING_AT = 0.0
        return _PENDING_CONFIRMATION is not None


def pending_summary(language: str | None = "fa") -> dict[str, Any] | None:
    """Describe the waiting action (for the UI / logs). None when nothing waits."""
    if not pending_confirmation():
        return None
    with _PENDING_LOCK:
        plan = dict(_PENDING_CONFIRMATION or {})
        age = time.time() - _PENDING_AT
    actions = plan.get("actions") or []
    first = actions[0] if actions else {}
    tool = str(first.get("tool") or "")
    args = first.get("args") or {}
    return {
        "tool": tool,
        "args": args,
        "question": describe_action(tool, args, language),
        "remaining_actions": len(actions),
        "expires_in": max(0, int(_PENDING_TTL - age)),
    }


def clear_pending_confirmation() -> None:
    global _PENDING_CONFIRMATION, _PENDING_AT
    with _PENDING_LOCK:
        _PENDING_CONFIRMATION = None
        _PENDING_AT = 0.0


def execute_pending_confirmation() -> dict[str, Any]:
    global _PENDING_CONFIRMATION, _PENDING_AT
    with _PENDING_LOCK:
        plan = dict(_PENDING_CONFIRMATION) if _PENDING_CONFIRMATION else None
        _PENDING_CONFIRMATION = None
        _PENDING_AT = 0.0
    if not plan:
        return {"ok": False, "error": "No pending confirmation."}
    return execute_plan(plan, True)


def execute_plan(
    plan: dict[str, Any],
    confirmed: bool = False,
    on_action: Callable[[dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
    global _PENDING_CONFIRMATION, _PENDING_AT
    actions = plan.get("actions", [])
    if not isinstance(actions, list):
        return {"ok": False, "error": "Invalid actions list."}
    errors = validate_actions(actions)
    if errors:
        return {"ok": False, "error": "; ".join(errors)}
    results = []
    for index, action in enumerate(actions):
        tool = action["tool"]
        args = action.get("args", {}) or {}
        if tool in REQUIRE_CONFIRMATION_FOR and not confirmed:
            with _PENDING_LOCK:
                # Only the actions that have NOT run yet are stored. Storing the
                # whole plan made the already-executed prefix run a second time
                # after the user confirmed (e.g. "open Google, then shut down").
                _PENDING_CONFIRMATION = {**plan, "actions": [dict(item) for item in actions[index:]]}
                _PENDING_AT = time.time()
            return {"ok": True, "needs_confirmation": True, "tool": tool, "args": args, "results": results}
        if on_action is not None:
            # Runs right before the tool starts so the chat strip names the
            # action that is ACTUALLY in flight (sequential honesty). A broken
            # reporter must never break execution.
            try:
                on_action(action)
            except Exception:
                pass
        result = execute_tool(tool, args)
        results.append({"tool": tool, "result": result})
        if not result.get("ok"):
            return {"ok": False, "needs_confirmation": False, "results": results, "error": result.get("error", "Tool failed.")}
    return {"ok": True, "needs_confirmation": False, "results": results}
