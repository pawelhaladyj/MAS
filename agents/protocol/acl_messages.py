from __future__ import annotations
from enum import Enum
from typing import Any, Dict, Optional
from pydantic import BaseModel, Field, field_validator


class Performative(str, Enum):
    REQUEST = "REQUEST"
    INFORM = "INFORM"
    FAILURE = "FAILURE"
    REFUSE = "REFUSE"
    AGREE = "AGREE"
    CONFIRM = "CONFIRM"


class AclMessage(BaseModel):
    performative: Performative = Field(..., description="FIPA-ACL performative")
    conversation_id: str = Field(..., min_length=1, description="Conversation/session identifier")
    ontology: str = Field("default", min_length=1, description="Domain ontology tag")
    language: str = Field("json", min_length=1, description="Content language (default: json)")
    payload: Dict[str, Any] = Field(default_factory=dict, description="Message content")

    @field_validator("conversation_id")
    @classmethod
    def conv_id_no_whitespace(cls, v: str) -> str:
        if v.strip() != v or not v:
            raise ValueError("conversation_id must be non-empty and trimmed")
        return v

    # helpery budujące typowe wiadomości
    @classmethod
    def build_request(cls, conversation_id: str, payload: Dict[str, Any], *, ontology: str = "default") -> "AclMessage":
        return cls(performative=Performative.REQUEST, conversation_id=conversation_id, ontology=ontology, payload=payload)

    @classmethod
    def build_inform(cls, conversation_id: str, payload: Dict[str, Any], *, ontology: str = "default") -> "AclMessage":
        return cls(performative=Performative.INFORM, conversation_id=conversation_id, ontology=ontology, payload=payload)

    # (opcjonalnie) serializacja skrócona
    def to_json(self) -> str:
        return self.model_dump_json()

    @classmethod
    def from_json(cls, data: str) -> "AclMessage":
        return cls.model_validate_json(data)
