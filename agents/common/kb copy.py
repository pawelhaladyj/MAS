from typing import Any, Dict, List
import time
from dataclasses import dataclass, field

@dataclass
class Fact:
    session_id: str
    slot: str
    value: Any
    source: str
    confidence: float = 1.0
    ts: float = field(default_factory=time.time)

class KB:
    def __init__(self):
        self._facts: List[Fact] = []

    def add(self, fact: Fact):
        self._facts.append(fact)

    def get_session(self, session_id: str) -> List[Fact]:
        return [f for f in self._facts if f.session_id == session_id]

kb = KB()