# agents/common/metrics.py
from __future__ import annotations
from typing import Dict, Any
from collections import defaultdict
import time

from .kb import put_fact

# proste liczniki w procesie
_COUNTERS: Dict[str, int] = defaultdict(int)

def inc(key: str, n: int = 1) -> None:
    _COUNTERS[key] += n

def add_many(pairs: Dict[str, int]) -> None:
    for k, v in pairs.items():
        _COUNTERS[k] += int(v)

def snapshot(reset: bool = False) -> Dict[str, int]:
    data = dict(_COUNTERS)
    if reset:
        _COUNTERS.clear()
    return data

def export_to_kb(session_id: str = "system", slot_prefix: str = "metrics") -> str:
    """
    Zrzuca bieżące liczniki do KB w unikalny slot (slot_prefix_<ts_ns>).
    Zwraca nazwę użytego slotu.
    """
    ts_ns = time.time_ns()
    slot = f"{slot_prefix}_{ts_ns}"
    put_fact(session_id, slot, snapshot(reset=False))
    return slot
