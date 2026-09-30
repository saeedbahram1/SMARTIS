from __future__ import annotations

import threading
import time
from typing import Any

from agent.tools import execute_tool
from config import REQUIRE_CONFIRMATION_FOR

_PENDING_LOCK = threading.Lock()
_PENDING_CONFIRMATION: dict[str, Any] | None = None
_PENDING_AT: float = 0.0
_PENDING_TTL = 45.0


def validate_actions(actions: list[dict[str, Any]]) -> list[str]:
    errors=[]
    for i, action in enumerate(actions):
        if not isinstance(action, dict): errors.append(f"Action {i} is not an object."); continue
        if not isinstance(action.get("tool"), str) or not action.get("tool"): errors.append(f"Action {i} has no tool.")
    return errors


def pending_confirmation() -> bool:
    global _PENDING_CONFIRMATION, _PENDING_AT
    with _PENDING_LOCK:
        if _PENDING_CONFIRMATION is not None and time.time()-_PENDING_AT > _PENDING_TTL:
            _PENDING_CONFIRMATION=None; _PENDING_AT=0.0
        return _PENDING_CONFIRMATION is not None


def clear_pending_confirmation() -> None:
    global _PENDING_CONFIRMATION, _PENDING_AT
    with _PENDING_LOCK: _PENDING_CONFIRMATION=None; _PENDING_AT=0.0


def execute_pending_confirmation() -> dict[str, Any]:
    global _PENDING_CONFIRMATION, _PENDING_AT
    with _PENDING_LOCK:
        plan = dict(_PENDING_CONFIRMATION) if _PENDING_CONFIRMATION else None
        _PENDING_CONFIRMATION = None
        _PENDING_AT = 0.0
    if not plan:
        return {"ok": False, "error": "No pending confirmation."}
    return execute_plan(plan, True)


def execute_plan(plan: dict[str, Any], confirmed: bool = False) -> dict[str, Any]:
    global _PENDING_CONFIRMATION, _PENDING_AT
    actions=plan.get("actions",[])
    if not isinstance(actions,list): return {"ok":False,"error":"Invalid actions list."}
    errors=validate_actions(actions)
    if errors: return {"ok":False,"error":"; ".join(errors)}
    results=[]
    for action in actions:
        tool=action["tool"]; args=action.get("args",{}) or {}
        if tool in REQUIRE_CONFIRMATION_FOR and not confirmed:
            with _PENDING_LOCK:
                _PENDING_CONFIRMATION=dict(plan)
                _PENDING_AT=time.time()
            return {"ok":True,"needs_confirmation":True,"tool":tool,"args":args,"results":results}
        result=execute_tool(tool,args)
        results.append({"tool":tool,"result":result})
        if not result.get("ok"):
            return {"ok":False,"needs_confirmation":False,"results":results,"error":result.get("error","Tool failed.")}
    return {"ok":True,"needs_confirmation":False,"results":results}
