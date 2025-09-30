from typing import Literal, Any, List
from pydantic import BaseModel, Field

# Wspólna koperta zgodna z FIPA-ACL (okrojona do naszych potrzeb)
class Envelope(BaseModel):
    performative: Literal["REQUEST", "INFORM", "FAILURE"] = Field(...)
    conversation_id: str
    ontology: Literal["travel.mas"] = "travel.mas"
    language: Literal["json"] = "json"
    type: Literal["PING", "ACK", "ASK", "FACT"] = Field(...)

# Konkretne typy wiadomości
class MsgPing(Envelope):
    type: Literal["PING"] = "PING"
    session_id: str

class MsgAck(Envelope):
    type: Literal["ACK"] = "ACK"
    echo: Any

class MsgAsk(Envelope):
    type: Literal["ASK"] = "ASK"
    session_id: str
    need: List[str]

class MsgFact(Envelope):
    type: Literal["FACT"] = "FACT"
    session_id: str
    slot: str
    value: Any
    source: str = "user"
