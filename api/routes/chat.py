# api/routes/chat.py
from __future__ import annotations

import asyncio
from fastapi import APIRouter, Request
from pydantic import BaseModel
from agents.protocol.acl_messages import AclMessage

router = APIRouter()

class ChatIn(BaseModel):
    text: str
    conversation_id: str = "demo-1"
    session_id: str | None = None

@router.post("/chat")
async def chat(request: Request, payload: ChatIn):
    # 1) zbuduj USER_MSG ACL (do echo w odpowiedzi, jak wcześniej)
    acl = AclMessage.build_request_user_msg(
        conversation_id=payload.conversation_id,
        text=payload.text,
        ontology="ui",
        session_id=payload.session_id or payload.conversation_id,
    )

    # 2) wstaw do kolejki mostka (HTTP → Bridge)
    await request.app.state.bridge_inbox.put({
        "text": payload.text,
        "conversation_id": payload.conversation_id,
        "session_id": payload.session_id or payload.conversation_id,
    })

    # 3) spróbuj złapać PRESENTER_REPLY (Bridge → HTTP), krótki timeout
    reply = None
    try:
        reply_item = await asyncio.wait_for(
            request.app.state.bridge_outbox.get(), timeout=1.5
        )
        # (opcjonalnie) tu można filtrować po conversation_id, jeśli potrzeba
        reply = reply_item
    except asyncio.TimeoutError:
        pass

    return {
        "status": "accepted" if reply is None else "replied",
        "acl": acl.model_dump(),
        "reply": reply,  # None lub {"conversation_id": "...", "payload": {...}}
    }
