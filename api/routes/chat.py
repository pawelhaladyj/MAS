# api/routes/chat.py
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
import json

from agents.protocol.acl_messages import AclMessage

router = APIRouter()

class ChatIn(BaseModel):
    conversation_id: str = Field(..., min_length=1)
    text: str = Field(..., min_length=1)
    ontology: str = "ui"

@router.post("/chat")
async def chat(body: ChatIn):
    # Budujemy kanoniczne USER_MSG (bez realnej wysyłki – na tym kroku tylko echo)
    acl = AclMessage.build_request_user_msg(
        conversation_id=body.conversation_id,
        text=body.text,
        ontology=body.ontology,
        session_id=body.conversation_id,
    )
    # Zwracamy JSON ACL – ułatwia debug oraz dalsze testy e2e
    return {
        "status": "accepted",
        "acl": json.loads(acl.to_json()),
    }
