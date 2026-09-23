from __future__ import annotations

from typing import Any

from agent.tools import execute_tool
from config import REQUIRE_CONFIRMATION_FOR


def validate_actions(actions: list[dict[str, Any]]) -> list[str]:
    errors = []
    for i, action in enumerate(actions):
        if not isinstance(action, dict):
            errors.append(f"Action {i} is not an object.")
            continue
        tool = action.get("tool")
        if not isinstance(tool, str) or not tool:
            errors.append(f"Action {i} has no tool.")
    return errors


def execute_plan(plan: dict[str, Any], confirmed: bool = False) -> dict[str, Any]:
    actions = plan.get("actions", [])
    if not isinstance(actions, list):
        return {"ok": False, "error": "Invalid actions list."}

    errors = validate_actions(actions)
    if errors:
        return {"ok": False, "error": "; ".join(errors)}

    results = []

    for action in actions:
        tool = action["tool"]
        args = action.get("args", {}) or {}

        if tool in REQUIRE_CONFIRMATION_FOR and not confirmed:
            return {
                "ok": True,
                "needs_confirmation": True,
                "tool": tool,
                "args": args,
                "results": results,
            }

        result = execute_tool(tool, args)
        results.append({
            "tool": tool,
            "result": result,
        })

        if not result.get("ok"):
            return {
                "ok": False,
                "needs_confirmation": False,
                "results": results,
                "error": result.get("error", "Tool failed."),
            }

    return {
        "ok": True,
        "needs_confirmation": False,
        "results": results,
    }
