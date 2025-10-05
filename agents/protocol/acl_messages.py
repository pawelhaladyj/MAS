from __future__ import annotations
from enum import Enum
from typing import Any, Dict, Optional
from pydantic import BaseModel, Field, field_validator
from datetime import datetime, timezone    # ⬅ NEW

class Performative(str, Enum):
    REQUEST = "REQUEST"
    INFORM = "INFORM"
    FAILURE = "FAILURE"
    REFUSE = "REFUSE"
    AGREE = "AGREE"
    CONFIRM = "CONFIRM"
    # (opcjonalnie w przyszłości: CANCEL)

class AclMessage(BaseModel):
    performative: Performative = Field(..., description="FIPA-ACL performative")
    conversation_id: str = Field(..., min_length=1, description="Conversation/session identifier")
    ontology: str = Field("default", min_length=1, description="Domain ontology tag")
    language: str = Field("json", min_length=1, description="Content language (default: json)")
    payload: Dict[str, Any] = Field(default_factory=dict, description="Message content")

    # ⬇⬇⬇ NEW meta
    schema_version: str = Field("1.0.0", description="ACL schema version")
    ts: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat(), description="UTC timestamp ISO8601")

    @field_validator("conversation_id")
    @classmethod
    def conv_id_no_whitespace(cls, v: str) -> str:
        if v.strip() != v or not v:
            raise ValueError("conversation_id must be non-empty and trimmed")
        return v

    # ⬇⬇⬇ NEW: lekka kontrola spójności performatywy ↔ typ payloadu (jeśli payload['type'] istnieje)
    @field_validator("payload")
    @classmethod
    def performative_payload_consistency(cls, payload: Dict[str, Any], info):
        perf = info.data.get("performative")
        ptype = payload.get("type")
        if ptype is None:
            return payload  # nic nie narzucamy, kompatybilnie

        if perf == Performative.REQUEST and ptype not in {"PING", "ASK", "METRICS_EXPORT"}:
            raise ValueError(f"REQUEST not allowed for payload.type={ptype}")
        if perf == Performative.INFORM and ptype not in {"ACK", "FACT", "OFFER", "CONFIRM"}:
            raise ValueError(f"INFORM not allowed for payload.type={ptype}")
        if perf == Performative.FAILURE and ptype != "ERROR":
            raise ValueError("FAILURE must carry payload.type=ERROR")
        return payload

    # helpery budujące typowe wiadomości (zostawiamy istniejące)
    @classmethod
    def build_request(cls, conversation_id: str, payload: Dict[str, Any], *, ontology: str = "default") -> "AclMessage":
        return cls(performative=Performative.REQUEST, conversation_id=conversation_id, ontology=ontology, payload=payload)

    @classmethod
    def build_inform(cls, conversation_id: str, payload: Dict[str, Any], *, ontology: str = "default") -> "AclMessage":
        return cls(performative=Performative.INFORM, conversation_id=conversation_id, ontology=ontology, payload=payload)

    # ⬇⬇⬇ NEW: fabryka błędów (FAILURE + ERROR)
    @classmethod
    def build_failure(cls, conversation_id: str, code: str, message: str, details: Optional[Dict[str, Any]] = None,
                      *, ontology: str = "default") -> "AclMessage":
        return cls(
            performative=Performative.FAILURE,
            conversation_id=conversation_id,
            ontology=ontology,
            payload={"type": "ERROR", "code": code, "message": message, "details": details or {}},
        )

    # (opcjonalnie) serializacja skrócona
    def to_json(self) -> str:
        return self.model_dump_json()

    @classmethod
    def from_json(cls, data: str) -> "AclMessage":
        return cls.model_validate_json(data)
    
    @classmethod
    def build_request_ask(cls, conversation_id: str, need: list[str], *, ontology: str = "default") -> "AclMessage":
        # minimalna walidacja listy (pełną zrobimy później)
        if not need or len({*need}) != len(need):
            raise ValueError("ASK.need must be non-empty and unique")
        return cls(
            performative=Performative.REQUEST,
            conversation_id=conversation_id,
            ontology=ontology,
            payload={"type": "ASK", "need": need},
        )

    @classmethod
    def build_inform_fact(cls, conversation_id: str, slot: str, value: Any, *, ontology: str = "default") -> "AclMessage":
        if not slot or not slot.strip():
            raise ValueError("FACT.slot must be non-empty")
        return cls(
            performative=Performative.INFORM,
            conversation_id=conversation_id,
            ontology=ontology,
            payload={"type": "FACT", "slot": slot, "value": value},
        )

    @classmethod
    def build_inform_ack(cls, conversation_id: str, echo: dict[str, Any], *, ontology: str = "default") -> "AclMessage":
        return cls(
            performative=Performative.INFORM,
            conversation_id=conversation_id,
            ontology=ontology,
            payload={"type": "ACK", "echo": echo or {}},
        )
        
    @classmethod
    def build_request_metrics_export(
        cls,
        conversation_id: str,
        *,
        ontology: str = "system",
    ) -> "AclMessage":
        return cls(
            performative=Performative.REQUEST,
            conversation_id=conversation_id,
            ontology=ontology,
            payload={"type": "METRICS_EXPORT"},
        )


