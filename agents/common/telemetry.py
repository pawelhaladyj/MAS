# agents/common/telemetry.py
from __future__ import annotations
import time
from typing import Any, Dict

from .kb import put_fact

def log_acl_event(conversation_id: str, direction: str, acl_dict: Dict[str, Any]) -> None:
    """
    Zapisz zdarzenie ACL jako wpis w KB.
    direction: "IN" lub "OUT".
    Slot jest unikalny (event_<DIR>_<time_ns>).
    """
    ts_ns = time.time_ns()
    slot = f"event_{direction}_{ts_ns}"
    put_fact(conversation_id, slot, {"direction": direction, "acl": acl_dict})
