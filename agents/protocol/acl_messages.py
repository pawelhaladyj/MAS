# agents/protocol/acl_messages.py
from __future__ import annotations
from enum import Enum
from typing import Any, Dict, Optional
from pydantic import BaseModel, Field, field_validator
from datetime import datetime, timezone
import json
import logging

logger = logging.getLogger(__name__)


class Performative(str, Enum):
    REQUEST = "REQUEST"
    INFORM = "INFORM"
    FAILURE = "FAILURE"
    REFUSE = "REFUSE"
    AGREE = "AGREE"
    CONFIRM = "CONFIRM"
    # (opcjonalnie w przyszłości: CANCEL)


# Jedno źródło prawdy dla dozwolonych zestawów performatywa ↔ typ payloadu
ALLOWED_PERFORMATIVES_BY_TYPE: Dict[str, set[Performative]] = {
    # system / ogólne
    "PING": {Performative.REQUEST},
    "ASK": {Performative.REQUEST},
    "METRICS_EXPORT": {Performative.REQUEST},
    "USER_MSG": {Performative.REQUEST},

    # fakty i odpowiedzi
    "FACT": {Performative.INFORM},
    "ACK": {Performative.INFORM},
    "OFFER": {Performative.INFORM},
    "CONFIRM": {Performative.INFORM},
    "PRESENTER_REPLY": {Performative.INFORM},

    # pogoda i registry (plug-and-play)
    "WEATHER_ADVICE": {Performative.REQUEST, Performative.INFORM},
    "CAPABILITY": {Performative.INFORM},

    # porażki
    "ERROR": {Performative.FAILURE},
}


class AclMessage(BaseModel):
    performative: Performative = Field(..., description="FIPA-ACL performative")
    conversation_id: str = Field(..., min_length=1, description="Conversation/session identifier")
    ontology: str = Field("default", min_length=1, description="Domain ontology tag")
    language: str = Field("json", min_length=1, description="Content language (default: json)")
    payload: Dict[str, Any] = Field(default_factory=dict, description="Message content")

    # meta
    schema_version: str = Field("1.0.0", description="ACL schema version")
    ts: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat(), description="UTC timestamp ISO8601")

    @field_validator("conversation_id")
    @classmethod
    def conv_id_no_whitespace(cls, v: str) -> str:
        if v.strip() != v or not v:
            raise ValueError("conversation_id must be non-empty and trimmed")
        return v

    @field_validator("payload")
    @classmethod
    def performative_payload_consistency(cls, payload: Dict[str, Any], info):
        perf: Performative = info.data.get("performative")
        ptype = payload.get("type")
        if ptype is None:
            # kompatybilnie: nie wymuszamy, gdy brak typu
            return payload

        # Specjalny przypadek: FAILURE musi nieść ERROR
        if perf == Performative.FAILURE:
            if ptype != "ERROR":
                raise ValueError("FAILURE must carry payload.type=ERROR")
            return payload

        allowed = ALLOWED_PERFORMATIVES_BY_TYPE.get(ptype, set())
        if perf not in allowed:
            raise ValueError(f"{perf} not allowed for payload.type={ptype}")
        return payload

    # ===== Helpery budujące typowe wiadomości =====

    @classmethod
    def build_request(cls, conversation_id: str, payload: Dict[str, Any], *, ontology: str = "default") -> "AclMessage":
        return cls(
            performative=Performative.REQUEST,
            conversation_id=conversation_id,
            ontology=ontology,
            payload=payload,
        )

    @classmethod
    def build_inform(cls, conversation_id: str, payload: Dict[str, Any], *, ontology: str = "default") -> "AclMessage":
        return cls(
            performative=Performative.INFORM,
            conversation_id=conversation_id,
            ontology=ontology,
            payload=payload,
        )

    @classmethod
    def build_failure(
        cls,
        conversation_id: str,
        code: str,
        message: str,
        details: Optional[Dict[str, Any]] = None,
        *,
        ontology: str = "default",
    ) -> "AclMessage":
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

    # ===== Integracja ze SPADE (wymuszenie XMPP thread == conversation_id) =====
    def to_spade_message(self, to: str):
        """Zbuduj SPADE Message z gwarancją: msg.thread == conversation_id."""
        from spade.message import Message  # lokalny import, by nie psuć importów tam, gdzie SPADE nie jest potrzebny

        msg = Message(to=to)
        # Metadane pomocnicze (nie zastępują body, ale ułatwiają debug)
        msg.set_metadata("performative", self.performative.value)
        msg.set_metadata("ontology", self.ontology)
        msg.set_metadata("language", self.language)
        msg.set_metadata("conversation_id", self.conversation_id)

        # KLUCZ: XMPP thread == conversation_id
        msg.thread = self.conversation_id

        # Treść: pełny JSON AclMessage
        msg.body = self.model_dump_json()
        return msg

    @classmethod
    def from_spade_message(cls, msg):
        """Odtwórz AclMessage ze SPADE Message, respektując thread jako conversation_id."""
        try:
            data = json.loads(getattr(msg, "body", "") or "{}")
        except Exception as e:
            raise ValueError(f"Invalid JSON body in SPADE Message: {e}")

        # Ustal conversation_id: najpierw z body, jeśli brak — z thread
        conv = data.get("conversation_id") or getattr(msg, "thread", None)
        if not conv:
            raise ValueError("Missing conversation_id (and XMPP thread)")

        # Ostrzeż, jeśli body i thread się rozjeżdżają
        thr = getattr(msg, "thread", None)
        if thr and thr != conv:
            logger.warning("Thread != conversation_id (thread=%s, conv=%s)", thr, conv)

        data["conversation_id"] = conv

        # Uzupełnij pola z metadanych SPADE (gdy nieobecne w body)
        meta = getattr(msg, "metadata", {}) or {}
        data.setdefault("ontology", meta.get("ontology", "default"))
        data.setdefault("language", meta.get("language", "json"))
        if "performative" not in data and meta.get("performative"):
            data["performative"] = meta["performative"]

        # Pydantic zrzutuje string -> Enum Performative
        return cls(**data)

    # ===== Dodatkowe fabryki używane w projekcie =====

    @classmethod
    def build_request_ask(cls, conversation_id: str, need: list[str], *, ontology: str = "default") -> "AclMessage":
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
    def build_request_metrics_export(cls, conversation_id: str, *, ontology: str = "system") -> "AclMessage":
        return cls(
            performative=Performative.REQUEST,
            conversation_id=conversation_id,
            ontology=ontology,
            payload={"type": "METRICS_EXPORT"},
        )

    @classmethod
    def build_request_user_msg(
        cls,
        conversation_id: str,
        text: str,
        *,
        ontology: str = "ui",
        session_id: Optional[str] = None,
    ) -> "AclMessage":
        payload = {"type": "USER_MSG", "text": text}
        if session_id:
            payload["session_id"] = session_id
        return cls(
            performative=Performative.REQUEST,
            conversation_id=conversation_id,
            ontology=ontology,
            payload=payload,
        )

    @classmethod
    def build_inform_presenter_reply(
        cls,
        conversation_id: str,
        text: str,
        *,
        ontology: str = "ui",
        session_id: Optional[str] = None,
    ) -> "AclMessage":
        payload = {"type": "PRESENTER_REPLY", "text": text}
        if session_id:
            payload["session_id"] = session_id
        return cls(
            performative=Performative.INFORM,
            conversation_id=conversation_id,
            ontology=ontology,
            payload=payload,
        )

    @classmethod
    def build_inform_capability(
        cls,
        conversation_id: str,
        provides: list[dict[str, Any]],
        *,
        ontology: str = "system",
    ) -> "AclMessage":
        """
        provides: np. [{"ontology": "weather", "types": ["WEATHER_ADVICE"]}]
        """
        payload = {"type": "CAPABILITY", "provides": provides}
        return cls(
            performative=Performative.INFORM,
            conversation_id=conversation_id,
            ontology=ontology,
            payload=payload,
        )
