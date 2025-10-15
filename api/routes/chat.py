# api/routes/chat.py
from fastapi import APIRouter, Request, HTTPException
from pydantic import BaseModel
import asyncio
import os

router = APIRouter()

class ChatIn(BaseModel):
    conversation_id: str
    text: str

@router.post("/chat")
async def chat(req: Request, body: ChatIn):
    bridge = getattr(req.app.state, "bridge", None)
    if not bridge:
        # Jeśli API_BRIDGE_ENABLED != 1, nie ma Bridge'a
        raise HTTPException(status_code=503, detail="Bridge disabled")

    session_id = body.conversation_id
    waiter = bridge.register_waiter(session_id)
    await bridge.send_user_msg(conversation_id=body.conversation_id, text=body.text, session_id=session_id)

    timeout_s = float(os.getenv("API_REPLY_TIMEOUT", "60"))
    try:
        payload = await asyncio.wait_for(waiter.get(), timeout=timeout_s)
        return {"reply": payload}
    except asyncio.TimeoutError:
        return {"reply": None}
